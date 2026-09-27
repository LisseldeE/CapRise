"""
剪贴板网络
局域网 UDP 发现与 TCP 中转（星型拓扑）
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import concurrent.futures
import json
import socket
import struct
import threading
import time

from PySide6.QtCore import QObject, Signal


# --- Ports (CapRise-specific; separate from LANSyncBox to allow co-existence)
DISCOVERY_PORT_START = 9548
DISCOVERY_PORT_END = 9557            # inclusive (10 ports, allows multi-instance)
TCP_PORT_DEFAULT = 9547
TCP_PORT_RANGE = 11                  # try 9547..9557
DISCOVERY_TIMEOUT = 3.0              # seconds
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB sanity cap
RECV_CHUNK = 65536


# ---------------------------------------------------------------------------
# Framing helpers
# ---------------------------------------------------------------------------

def pack_message(msg: dict) -> bytes:
    payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(payload)) + payload


class MessageReader:
    """Accumulates bytes from a TCP stream and yields complete JSON messages."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes):
        self._buf.extend(data)
        out = []
        while len(self._buf) >= 4:
            (length,) = struct.unpack(">I", self._buf[:4])
            if length > MAX_MESSAGE_SIZE:
                raise ValueError("message too large")
            if len(self._buf) < 4 + length:
                break
            payload = bytes(self._buf[4:4 + length])
            del self._buf[:4 + length]
            out.append(json.loads(payload.decode("utf-8")))
        return out


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _safe_emit(signal, *args):
    """Emit a Qt signal, swallowing RuntimeError if the QObject was deleted."""
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Host-side per-client connection
# ---------------------------------------------------------------------------

class _ClientConn:
    """A connected joiner on the host side."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.peer_id = None
        self.peer_name = ""
        self.send_lock = threading.Lock()
        self.reader = MessageReader()
        self.alive = True

    def send(self, msg) -> bool:
        with self.send_lock:
            if not self.alive:
                return False
            try:
                self.sock.sendall(pack_message(msg))
                return True
            except Exception:
                self.alive = False
                return False


# ---------------------------------------------------------------------------
# UDP discovery (joiner side) + responder (host side)
# ---------------------------------------------------------------------------

class RoomDiscovery(QObject):
    """Joiner-side UDP discovery. Broadcasts a request and collects responses.

    Uses a random ephemeral port with SO_REUSEADDR — exactly matching the
    LANSyncBox model.  This avoids any port conflict with RoomResponder
    (which binds to the discovery port range) on the same machine.

    Key reliability feature: sends discovery_request broadcasts repeatedly
    (every 500ms) during the entire timeout window, not just a single
    burst.  On Windows, a single UDP broadcast burst is frequently lost,
    so repeating gives multiple chances for delivery.  This is essential
    for the conflict-scan scenario where both devices must detect each
    other."""

    room_found = Signal(str, str, int)   # ip, room_code, tcp_port
    discovery_finished = Signal(list)    # [(ip, room_code, tcp_port), ...]
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = None
        self._running = False
        self._found = {}
        self._lock = threading.Lock()
        self._room_code = ""           # set during discover()
        self._timeout = DISCOVERY_TIMEOUT

    def discover(self, room_code: str, timeout: float = DISCOVERY_TIMEOUT) -> bool:
        try:
            self._found.clear()
            self._room_code = room_code
            self._timeout = timeout

            # Random port + SO_REUSEADDR — matches LANSyncBox.  No conflict
            # with RoomResponder (which uses the discovery port range).
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", 0))
            self._sock.settimeout(0.5)
            self._running = True

            threading.Thread(target=self._recv_loop, daemon=True).start()
            threading.Thread(target=self._broadcast_loop, daemon=True).start()

            timer = threading.Timer(timeout, self._finish)
            timer.daemon = True
            timer.start()
            return True
        except Exception as e:
            _safe_emit(self.error, f"discovery start failed: {e}")
            return False

    def _broadcast_loop(self):
        """Send discovery_request broadcasts every 500ms during the entire
        discovery window.  A single burst is often lost on Windows; repeating
        gives multiple chances for the responder on the other device to
        receive it and reply."""
        msg = json.dumps(
            {"type": "discovery_request", "room_code": self._room_code}
        ).encode("utf-8")
        local_ip = _get_local_ip()
        interval = 0.5
        elapsed = 0.0
        while self._running and elapsed < self._timeout:
            for port in range(DISCOVERY_PORT_START, DISCOVERY_PORT_END + 1):
                try:
                    self._sock.sendto(msg, ("<broadcast>", port))
                except OSError:
                    pass
                try:
                    self._sock.sendto(msg, ("127.0.0.1", port))
                except OSError:
                    pass
                if local_ip != "127.0.0.1":
                    try:
                        self._sock.sendto(msg, (local_ip, port))
                    except OSError:
                        pass
            time.sleep(interval)
            elapsed += interval

    def _recv_loop(self):
        """Receive loop: listens for discovery_response messages from
        existing hosts on the LAN."""
        while self._running:
            try:
                data, addr = self._sock.recvfrom(2048)
                resp = json.loads(data.decode("utf-8"))
                if resp.get("type") == "discovery_response":
                    ip = addr[0]
                    rc = resp.get("room_code", "")
                    port = resp.get("port", TCP_PORT_DEFAULT)
                    with self._lock:
                        self._found[ip] = (ip, rc, port)
                    _safe_emit(self.room_found, ip, rc, port)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                continue

    def _finish(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        with self._lock:
            rooms = list(self._found.values())
        _safe_emit(self.discovery_finished, rooms)

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


class RoomResponder(QObject):
    """Host-side UDP responder. Replies to discovery requests matching room."""

    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = None
        self._running = False
        self._room_code = ""
        self._tcp_port = TCP_PORT_DEFAULT
        self._discovery_port = None

    @property
    def discovery_port(self):
        return self._discovery_port

    def start(self, room_code: str, tcp_port: int) -> bool:
        self._room_code = room_code
        self._tcp_port = tcp_port
        for port in range(DISCOVERY_PORT_START, DISCOVERY_PORT_END + 1):
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.bind(("0.0.0.0", port))
                self._sock.settimeout(1.0)
                self._running = True
                self._discovery_port = port
                threading.Thread(target=self._loop, daemon=True).start()
                return True
            except OSError:
                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                self._sock = None
                continue
            except Exception as e:
                _safe_emit(self.error, f"responder start failed: {e}")
                return False
        _safe_emit(self.error, "all discovery ports occupied")
        return False

    def _loop(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(2048)
                req = json.loads(data.decode("utf-8"))
                if req.get("type") != "discovery_request":
                    continue
                target = req.get("room_code", "")
                # Empty room_code = scan-all request; respond anyway.
                if target and target != self._room_code:
                    continue
                resp = json.dumps({
                    "type": "discovery_response",
                    "room_code": self._room_code,
                    "port": self._tcp_port,
                }).encode("utf-8")
                self._sock.sendto(resp, addr)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                continue

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None


# ---------------------------------------------------------------------------
# Reliable TCP subnet probe (fallback / primary discovery)
# ---------------------------------------------------------------------------

class SubnetTCPProbe(QObject):
    """Reliable host discovery via directed TCP probing of the local /24 subnet.

    UDP broadcast discovery (RoomDiscovery) is unreliable on Windows — the
    project's own lesson notes packet loss, delivery issues, and firewall
    blocks on broadcast. A directed TCP connect, by contrast, is reliably
    delivered (it is not a broadcast) and only requires:

      * OUTBOUND TCP from the prober (allowed by default, even for new apps),
      * the host's TCP server to be reachable inbound — which is covered by the
        same firewall prompt that the host's listen socket triggers on first
        run.

    So when UDP discovery finds nothing (broadcast dropped, or the host
    device's firewall blocks inbound UDP to the responder port), this probe
    still finds the host as long as its TCP server is reachable — the common
    case once the user has allowed the firewall prompt.

    Mechanism: derive the local /24 base from _get_local_ip(), then for each
    candidate IP x port in the host TCP range, open a short-lived TCP
    connection, send a "probe" message, read a "probe_resp", and verify the
    room code. Probing runs concurrently in a thread pool; the overall call is
    bounded by `timeout`. Found hosts are emitted via host_found and collected
    in probe_finished.

    Limitation: assumes a /24 subnet (covers the vast majority of home / small
    /24 LANs). On larger subnets, hosts outside the local /24 are not probed
    by this mechanism; UDP discovery (run alongside) covers the broadcast
    domain.
    """

    host_found = Signal(str, str, int)   # ip, room_code, tcp_port
    probe_finished = Signal(list)        # [(ip, room_code, tcp_port), ...]
    error = Signal(str)

    # Probe tuning. connect_timeout is per-IP:port; unused IPs on a /24 fail
    # by timeout (slow path), live hosts reply in a few ms. With ~150 workers
    # the whole /24 x port-range scan completes in well under `timeout`.
    CONNECT_TIMEOUT = 0.35
    READ_TIMEOUT = 1.0
    MAX_WORKERS = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    def probe(self, room_code: str, timeout: float = 6.0) -> bool:
        """Start probing the local /24 subnet. Non-blocking: runs in a daemon
        thread and emits probe_finished when done (or on timeout)."""
        try:
            self._running = True
            threading.Thread(
                target=self._probe_worker,
                args=(room_code, timeout),
                daemon=True,
            ).start()
            return True
        except Exception as e:
            self._running = False
            _safe_emit(self.error, f"probe start failed: {e}")
            return False

    def _probe_worker(self, room_code: str, timeout: float):
        results = []
        lock = threading.Lock()
        local_ip = _get_local_ip()
        parts = local_ip.split(".")
        # No usable LAN IP (e.g. offline) — nothing to probe.
        if len(parts) != 4 or local_ip == "127.0.0.1":
            self._running = False
            _safe_emit(self.probe_finished, [])
            return
        subnet_base = ".".join(parts[:3])  # a.b.c — /24 assumption
        # Candidate IPs: a.b.c.1 .. a.b.c.254, excluding ourselves.
        ips = [f"{subnet_base}.{i}" for i in range(1, 255)
               if f"{subnet_base}.{i}" != local_ip]
        ports = list(range(TCP_PORT_DEFAULT, TCP_PORT_DEFAULT + TCP_PORT_RANGE))

        ex = concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS)
        try:
            futs = [ex.submit(self._probe_one, ip, p, room_code, results, lock)
                    for ip in ips for p in ports]
            # Bound the whole scan; proceed with whatever was found so far.
            concurrent.futures.wait(futs, timeout=timeout)
        except Exception as e:
            _safe_emit(self.error, f"probe worker failed: {e}")
        finally:
            # Stop accepting results past this point (late-finishing probes
            # would emit host_found after probe_finished, confusing callers).
            self._running = False
            ex.shutdown(wait=False, cancel_futures=True)

        with lock:
            out = list(results)
        _safe_emit(self.probe_finished, out)

    def _probe_one(self, ip, port, room_code, results, lock):
        if not self._running:
            return
        try:
            sock = socket.create_connection((ip, port), timeout=self.CONNECT_TIMEOUT)
        except OSError:
            return  # unused IP / no service / refused — expected, skip
        try:
            sock.settimeout(self.READ_TIMEOUT)
            sock.sendall(pack_message({"type": "probe", "room_code": room_code}))
            reader = MessageReader()
            deadline = time.time() + self.READ_TIMEOUT
            while self._running and time.time() < deadline:
                try:
                    data = sock.recv(RECV_CHUNK)
                except socket.timeout:
                    break
                if not data:
                    break
                msgs = reader.feed(data)
                for m in msgs:
                    if (m.get("type") == "probe_resp"
                            and m.get("room_code") == room_code):
                        rc = m.get("room_code", "")
                        tcp_port = m.get("tcp_port") or port
                        with lock:
                            results.append((ip, rc, tcp_port))
                        _safe_emit(self.host_found, ip, rc, tcp_port)
                        return
                if msgs:
                    break  # got a non-matching message; stop reading
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def stop(self):
        self._running = False


# ---------------------------------------------------------------------------
# TCP host (server + relay)
# ---------------------------------------------------------------------------

class ClipboardHost(QObject):
    """Host: accepts TCP joiners, relays clipboard updates between them,
    and emits received updates to the local manager (host is also a peer)."""

    clipboard_received = Signal(str, str)   # text, origin_peer_id
    peer_count_changed = Signal(int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listen_sock = None
        self._running = False
        self._clients = {}                   # peer_id -> _ClientConn
        self._clients_lock = threading.Lock()
        self._tcp_port = None
        # Room code is set by the manager after start(); used to answer
        # SubnetTCPProbe "probe" messages so a prober can verify the room
        # without registering as a peer.
        self.room_code = ""

    @property
    def port(self):
        return self._tcp_port

    def start(self, preferred_port: int = TCP_PORT_DEFAULT) -> bool:
        for port in range(preferred_port, preferred_port + TCP_PORT_RANGE):
            try:
                self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._listen_sock.bind(("0.0.0.0", port))
                self._listen_sock.listen(16)
                self._tcp_port = port
                self._running = True
                threading.Thread(target=self._accept_loop, daemon=True).start()
                return True
            except OSError:
                if self._listen_sock:
                    try:
                        self._listen_sock.close()
                    except Exception:
                        pass
                self._listen_sock = None
                continue
        _safe_emit(self.error, "no free TCP port")
        return False

    def _accept_loop(self):
        while self._running:
            try:
                sock, addr = self._listen_sock.accept()
            except OSError:
                break
            conn = _ClientConn(sock, addr)
            threading.Thread(
                target=self._handle_client, args=(conn,), daemon=True
            ).start()

    def _handle_client(self, conn):
        try:
            conn.sock.settimeout(None)
            while self._running and conn.alive:
                try:
                    data = conn.sock.recv(RECV_CHUNK)
                except OSError:
                    break
                if not data:
                    break
                try:
                    msgs = conn.reader.feed(data)
                except Exception:
                    break  # malformed frame — drop connection
                for msg in msgs:
                    self._on_message(conn, msg)
        except Exception:
            pass
        finally:
            self._remove_client(conn)

    def _on_message(self, conn, msg):
        t = msg.get("type")
        if t == "hello":
            conn.peer_id = msg.get("peer_id") or f"peer-{id(conn)}"
            conn.peer_name = msg.get("peer_name", "peer")
            with self._clients_lock:
                old = self._clients.get(conn.peer_id)
                self._clients[conn.peer_id] = conn
            if old is not None and old is not conn:
                old.alive = False
                try:
                    old.sock.close()
                except Exception:
                    pass
            conn.send({"type": "welcome", "peer_id": conn.peer_id})
            self._broadcast_peer_count()
        elif t == "clipboard":
            text = msg.get("text", "")
            origin = msg.get("origin_peer_id", conn.peer_id)
            # Relay to every other client (star relay). Originator excluded
            # so it never receives its own update back (no echo loop).
            self._relay(msg, except_peer=conn.peer_id)
            _safe_emit(self.clipboard_received, text, origin)
        elif t == "probe":
            # Lightweight discovery probe from a SubnetTCPProbe. Reply with
            # our room + TCP port so the prober can verify the room match.
            # Do NOT register the prober as a peer — it closes immediately
            # after receiving this response.
            conn.send({"type": "probe_resp",
                       "room_code": self.room_code,
                       "tcp_port": self._tcp_port})
        elif t == "bye":
            self._remove_client(conn)

    def _relay(self, msg, except_peer):
        with self._clients_lock:
            targets = [c for pid, c in self._clients.items() if pid != except_peer]
        for c in targets:
            c.send(msg)

    def _broadcast_peer_count(self):
        with self._clients_lock:
            count = len(self._clients)
        self._relay({"type": "peer_update", "peer_count": count}, except_peer=None)
        _safe_emit(self.peer_count_changed, count)

    def _remove_client(self, conn):
        removed = False
        with self._clients_lock:
            if conn.peer_id and self._clients.get(conn.peer_id) is conn:
                self._clients.pop(conn.peer_id, None)
                removed = True
        conn.alive = False
        try:
            conn.sock.close()
        except Exception:
            pass
        if removed:
            self._broadcast_peer_count()

    def broadcast_clipboard(self, text: str, origin_peer_id: str = "host"):
        """Send a local clipboard update to every connected joiner."""
        msg = {"type": "clipboard", "text": text, "origin_peer_id": origin_peer_id}
        self._relay(msg, except_peer=None)

    def peer_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    def stop(self):
        self._running = False
        if self._listen_sock:
            try:
                self._listen_sock.close()
            except Exception:
                pass
            self._listen_sock = None
        with self._clients_lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            c.alive = False
            try:
                c.sock.close()
            except Exception:
                pass
        _safe_emit(self.peer_count_changed, 0)


# ---------------------------------------------------------------------------
# TCP client (joiner)
# ---------------------------------------------------------------------------

class ClipboardClient(QObject):
    """Joiner: connects to the host, sends local updates, receives relays.

    The connect loop is resilient: on connection failure or a dropped
    connection it retries with exponential backoff (1s -> 2s -> 4s -> ...
    capped at 8s) up to MAX_RETRIES times. This matters when the manager
    steps down from host to client after a conflict scan (the other host
    may need a moment to finish coming up), and for transient Wi-Fi /
    firewall hiccups. `reconnecting` is emitted between attempts so the UI
    can show "connecting..." instead of "disconnected" while retrying.
    """

    clipboard_received = Signal(str)
    peer_count_changed = Signal(int)
    connected = Signal()
    disconnected = Signal()
    reconnecting = Signal()  # retrying after failure/drop — not terminal
    retries_exhausted = Signal()  # gave up after MAX_RETRIES attempts — caller decides recovery
    error = Signal(str)

    # Retry tuning. Total worst-case backoff across MAX_RETRIES attempts
    # is ~2 minutes, which comfortably covers a peer finishing host startup
    # or a brief network blip. A successful welcome resets the counter so
    # a connection that lived for a while still gets a full retry budget
    # when it later drops.
    MAX_RETRIES = 8
    INITIAL_BACKOFF = 1.0
    MAX_BACKOFF = 8.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = None
        self._reader = MessageReader()
        self._running = False
        self._peer_id = ""
        self._send_lock = threading.Lock()
        self._host = None
        self._port = None
        # Set True on welcome receipt, reset at the start of each attempt
        # and after the connection ends. Drives the "were we ever connected
        # on this attempt?" decision in _connect_loop.
        self._welcomed = False

    @property
    def is_connected(self):
        return self._welcomed and self._sock is not None

    def connect_to_host(self, host: str, port: int, room_code: str,
                        peer_id: str, peer_name: str):
        self._peer_id = peer_id
        self._host = host
        self._port = port
        self._running = True
        threading.Thread(
            target=self._connect_loop,
            args=(host, port, room_code, peer_id, peer_name),
            daemon=True,
        ).start()

    def _connect_loop(self, host, port, room_code, peer_id, peer_name):
        attempt = 0
        while self._running:
            self._welcomed = False
            # Fresh reader per attempt — buffered partial frames from a
            # previous connection must not bleed into the new one.
            self._reader = MessageReader()
            try:
                self._sock = socket.create_connection((host, port), timeout=5)
                self._sock.settimeout(None)
                self._send({"type": "hello", "room_code": room_code,
                            "peer_id": peer_id, "peer_name": peer_name})
                # `connected` is emitted on welcome receipt (see _on_message),
                # so the host has registered us by the time it fires.
                while self._running:
                    try:
                        data = self._sock.recv(RECV_CHUNK)
                    except OSError:
                        break
                    if not data:
                        break
                    try:
                        msgs = self._reader.feed(data)
                    except Exception:
                        break
                    for msg in msgs:
                        self._on_message(msg)
            except Exception:
                # Silent: the retry path below handles all failure modes
                # (initial connect failure, dropped mid-stream, etc.).
                # Surfacing every retry as `error` would flip the UI to
                # "failed" even though we're still trying.
                pass
            finally:
                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                    self._sock = None

            if not self._running:
                return  # clean shutdown via disconnect()

            # Signal semantics:
            #   - While retrying (including right after a real connection
            #     dropped), emit ONLY `reconnecting` so the UI shows
            #     "connecting..." — NOT `disconnected`, which is reserved
            #     for the terminal "we gave up" state below.
            #   - On the terminal state (retries exhausted), emit
            #     `retries_exhausted` then `disconnected` so the manager
            #     can self-heal (re-discover / become host).
            if self._welcomed:
                attempt = 0  # reset backoff after a real connection

            attempt += 1
            if attempt > self.MAX_RETRIES:
                # Exhausted retries without ever connecting (or without
                # reconnecting after a drop). Emit retries_exhausted so the
                # manager can re-discover (the other host may have crashed
                # — re-running discovery will either find a new host or
                # promote us to host). Then emit disconnected as the
                # terminal UI state until recovery kicks in.
                _safe_emit(self.retries_exhausted)
                _safe_emit(self.disconnected)
                return

            _safe_emit(self.reconnecting)
            backoff = min(
                self.INITIAL_BACKOFF * (2 ** (attempt - 1)),
                self.MAX_BACKOFF,
            )
            # Sleep in small chunks so disconnect() is responsive.
            slept = 0.0
            while self._running and slept < backoff:
                time.sleep(0.1)
                slept += 0.1

    def _on_message(self, msg):
        t = msg.get("type")
        if t == "clipboard":
            _safe_emit(self.clipboard_received, msg.get("text", ""))
        elif t == "welcome":
            pid = msg.get("peer_id")
            if pid:
                self._peer_id = pid
            # Emitted here (not at hello-send) so the host has confirmed
            # registration before listeners act on "connected".
            self._welcomed = True
            _safe_emit(self.connected)
        elif t == "peer_update":
            _safe_emit(self.peer_count_changed, msg.get("peer_count", 0))

    def send_clipboard(self, text: str):
        self._send({"type": "clipboard", "text": text,
                    "origin_peer_id": self._peer_id})

    def _send(self, msg):
        with self._send_lock:
            if self._sock is None:
                return
            try:
                self._sock.sendall(pack_message(msg))
            except Exception:
                pass

    def disconnect(self):
        self._running = False
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
