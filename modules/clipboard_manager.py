"""Clipboard feature coordinator.

Ties together discovery, network (host/client), the system-clipboard
monitor, the SQLite history, and the floating panel. Owns the lifecycle:
enable/disable, room config, host-vs-join auto-selection, and state
persistence (enabled / expanded / room / panel position) across restarts.

Role selection (per PRD): after a room code is entered, scan the LAN via UDP.
If a host for that room responds -> join as a TCP client. Otherwise -> become
the host (start a TCP server + UDP discovery responder).
"""
import socket
import uuid

from PySide6.QtCore import QObject, Signal, QTimer

from modules.keystroke import send_ctrl_v

from modules.config import Config
from modules.i18n import I18n
from modules.clipboard_history import ClipboardHistory
from modules.clipboard_monitor import ClipboardMonitor
from modules.clipboard_network import (
    RoomDiscovery, RoomResponder, ClipboardHost, ClipboardClient,
    SubnetTCPProbe, _get_local_ip
)
from modules.clipboard_panel import ClipboardPanel
from modules.room_config import RoomConfigDialog


class ClipboardManager(QObject):
    """Coordinates the LAN clipboard feature end-to-end."""

    def __init__(self, capsule):
        super().__init__()
        self.capsule = capsule

        self._history = ClipboardHistory()
        self._monitor = ClipboardMonitor(self)
        self._panel = ClipboardPanel()

        # Network components (created on enable)
        self._discovery = None
        self._tcp_probe = None
        self._responder = None
        self._host = None
        self._client = None
        self._role = None  # "host" | "client" | None

        self._peer_id = uuid.uuid4().hex[:12]
        self._peer_name = (socket.gethostname() or "CapRise")[:24]
        self._room_code = ""
        self._enabled = False
        # expanded = panel card visible. Independent of _enabled so the user can
        # have the feature running (network on) with the card collapsed.
        self._expanded = False
        self._connecting = False
        self._peer_count = 0
        self._status = ""
        # Host-conflict scan (reliable fallback when competitor detection fails)
        self._conflict_discovery = None
        self._conflict_tcp_probe = None
        self._scanning_for_conflict = False
        # Initial discovery coordination: UDP discovery + TCP probe run in
        # parallel; the first to find a matching host wins, and if both come
        # back empty we become host. _connect_resolved guards against late
        # callbacks acting after a decision (or after _stop_network).
        self._connect_resolved = False
        self._connect_pending = 0
        # Last text emitted by the local monitor — collapses burst writes (some
        # apps set the clipboard text/html/inline several times in a row).
        self._last_local_text = None

        # --- Wire panel ---
        self._panel.copy_requested.connect(self._on_panel_copy)
        self._panel.delete_requested.connect(self._on_panel_delete)
        self._panel.clear_requested.connect(self._on_panel_clear)
        self._panel.collapse_requested.connect(self.hide_card)

        # --- Wire monitor ---
        self._monitor.copied.connect(self._on_local_copy)

        # --- Family hide coordination ---
        # Both capsule and panel emit this when focus leaves the family; the
        # manager hides whichever is still visible.
        self.capsule.hide_family_requested.connect(self._hide_family)
        self._panel.hide_family_requested.connect(self._hide_family)

        self._refresh_panel()
        self._restore_from_config()

    # ------------------------------------------------------------------ state

    def is_enabled(self) -> bool:
        return self._enabled

    def is_expanded(self) -> bool:
        return self._expanded

    def is_panel_visible(self) -> bool:
        """True if the panel card is currently on screen (mid-animation or
        fully shown). Used by CapRise.toggle_capsule to decide whether the
        family as a whole is visible — capsule OR panel counts."""
        return self._panel.isVisible()

    def _restore_from_config(self):
        cfg = Config()
        room = cfg.get("clipboard_room", "") or ""
        # Migrate the legacy "clipboard_room_code" key (an earlier schema
        # name) if the current key is empty. Either way, drop the legacy
        # key so config.json stops carrying both fields.
        if not room:
            legacy = cfg.get("clipboard_room_code", "") or ""
            if self._is_valid_room(legacy):
                room = legacy
                cfg.set("clipboard_room", room)
        # Always remove the legacy key (even if empty/None) so it's gone.
        if "clipboard_room_code" in cfg._config:
            del cfg._config["clipboard_room_code"]
            cfg.save()

        # Always remember the stored room, regardless of whether the feature
        # is currently enabled. Otherwise, after a restart with the feature
        # disabled, _room_code stays empty and the next enable click would
        # wrongly re-open the room dialog instead of reusing the saved room.
        self._room_code = room if self._is_valid_room(room) else ""

        enabled = bool(cfg.get("clipboard_enabled", False))
        expanded = bool(cfg.get("clipboard_expanded", False))
        # The panel is no longer draggable and always positions next to the
        # cursor on show, so the persisted clipboard_pos is obsolete. Drop
        # it from existing configs to avoid carrying dead state.
        if "clipboard_pos" in cfg._config:
            del cfg._config["clipboard_pos"]
            cfg.save()

        if enabled and self._is_valid_room(room):
            # Set _expanded BEFORE _enable() — _enable() calls _save_state(),
            # which would otherwise persist the init-default False and
            # clobber the user's stored preference.
            self._expanded = bool(expanded)
            self._enable(room)  # network + monitor on, no UI
            # DON'T auto-pop the card on startup. Restarting with a floating
            # panel and no capsule felt broken — and the panel couldn't
            # detect focus loss without the capsule running. Instead, the
            # panel surfaces together with the capsule when the user presses
            # Ctrl+`, gated by _expanded.
        self._update_button_tooltip()
        self._refresh_status_text()

    def _save_state(self):
        cfg = Config()
        cfg.set("clipboard_enabled", self._enabled)
        cfg.set("clipboard_expanded", self._expanded)
        if self._room_code:
            cfg.set("clipboard_room", self._room_code)

    # ------------------------------------------------------------------ button

    def on_button_left(self):
        """Left-click cycle (revised two-state model):
            A. disabled (any panel state) -> enable + expand panel
            B. enabled + expanded         -> disable (stop sync, hide panel)
            C. enabled + collapsed         -> expand panel (back to B)

        State C is only reached via the panel's collapse ("-") button, NOT
        via left-click on the capsule button. So a left-click on an enabled
        family is unambiguous:
          - panel expanded (B) -> turn the whole feature off
          - panel collapsed (C) -> re-expand

        First-time setup (no room configured): left-click opens the room
        config dialog (right-click also does this) — there's nothing to
        enable yet."""
        if not self._enabled:
            # A -> B: enable + expand. Needs a room.
            if not self._is_valid_room(self._room_code):
                self._open_room_config(initial=self._room_code)
                return
            self._enable(self._room_code)
            self.show_card()
            return
        # Enabled: branch on _expanded (the logical panel-preference flag,
        # NOT panel.isVisible() — that stays True during the 300ms collapse
        # animation and would misclassify a fast double-click).
        if self._expanded:
            # B -> A: turn the feature off, hide panel, stop sync.
            self.disable()
        else:
            # C -> B: re-expand the panel (the feature stays enabled).
            self.show_card()

    def on_button_right(self):
        """Right-click: change (or set) the room code. The only path that
        opens the room-config dialog."""
        self._open_room_config(initial=self._room_code)

    def _open_room_config(self, initial=""):
        dialog = RoomConfigDialog(initial_code=initial)
        if dialog.exec() == RoomConfigDialog.Accepted:
            code = dialog.get_room_code()
            if self._is_valid_room(code):
                self._enable(code)
                # If the capsule is visible, surface the card as feedback.
                if self.capsule.isVisible():
                    self.show_card()

    # ------------------------------------------------------------------ enable

    def _enable(self, room_code):
        """Turn the feature on (network + monitor + active button) without
        touching the panel. Safe to call repeatedly; re-points to a new room."""
        self._stop_network()
        self._room_code = room_code
        Config().set("clipboard_room", room_code)
        self._panel.set_room(room_code)
        was_enabled = self._enabled
        self._enabled = True
        self.capsule.set_clipboard_active(True)
        if not was_enabled:
            self._monitor.enable()
        self._save_state()
        self._start_connection(room_code)
        self._update_button_tooltip()

    def disable(self):
        if not self._enabled:
            return
        self._enabled = False
        self._expanded = False
        self._stop_network()
        self._monitor.disable()
        self._panel.set_room("")
        self.capsule.set_clipboard_active(False)
        if self._panel.isVisible():
            self._panel.hide_panel()
        self._save_state()
        self._set_status(I18n.tr("clipboard_status_disconnected"))
        self._update_button_tooltip()

    # ------------------------------------------------------------------ network

    def _start_connection(self, room_code):
        """Discover an existing host for the room and join it, or become the
        host if none is found. Runs TWO discovery mechanisms in parallel and
        takes the first hit:

          * UDP broadcast discovery (RoomDiscovery) — fast when broadcast
            delivery works;
          * TCP subnet probe (SubnetTCPProbe) — reliable directed-connection
            scan that finds hosts UDP misses (Windows UDP broadcast is
            unreliable; this is the path that actually resolves on real Wi-Fi
            LANs where the user observed both devices becoming hosts).

        If either finds a matching host, we become a client. If both come
        back empty, we become the host ourselves.
        """
        self._connecting = True
        self._connect_resolved = False
        self._connect_pending = 2
        self._set_status(I18n.tr("clipboard_status_scanning"))

        self._discovery = RoomDiscovery(self)
        self._discovery.discovery_finished.connect(self._on_initial_discovery_part)
        self._discovery.error.connect(self._on_initial_part_error)
        self._discovery.discover(room_code)

        self._tcp_probe = SubnetTCPProbe(self)
        self._tcp_probe.probe_finished.connect(self._on_initial_discovery_part)
        self._tcp_probe.error.connect(self._on_initial_part_error)
        self._tcp_probe.probe(room_code, timeout=5.0)

    @staticmethod
    def _match_room(rooms, room_code):
        for ip, rc, port in rooms:
            if rc == room_code:
                return (ip, port)
        return None

    def _on_initial_discovery_part(self, rooms):
        if not self._enabled or self._connect_resolved:
            return
        match = self._match_room(rooms, self._room_code)
        if match:
            self._connect_resolved = True
            self._connecting = False
            self._cancel_initial_discovery()
            self._become_client(match[0], match[1])
            return
        # No match from this mechanism — wait for the other, or become host
        # if both are done.
        self._connect_pending -= 1
        if self._connect_pending <= 0:
            self._connect_resolved = True
            self._connecting = False
            self._become_host()

    def _on_initial_part_error(self, msg):
        if not self._enabled or self._connect_resolved:
            return
        self._connect_pending -= 1
        if self._connect_pending <= 0:
            # Both mechanisms failed/empty — become host (the conflict scan
            # will reconcile if another host is actually out there).
            self._connect_resolved = True
            self._connecting = False
            self._become_host()

    def _cancel_initial_discovery(self):
        if self._discovery:
            self._discovery.stop()
            self._discovery = None
        if self._tcp_probe:
            self._tcp_probe.stop()
            self._tcp_probe = None

    # ------------------------------------------------------------------ host conflict resolution

    def _schedule_host_conflict_scan(self):
        """Schedule a periodic host-conflict scan. After becoming a host,
        we periodically re-scan the LAN to check for other hosts running
        the same room. If another host is found, the IP tiebreaker
        determines who keeps the host role and who steps down.

        This is the reliable fallback for the simultaneous-startup race
        condition: if both devices start at the same time, both scan
        during the same 3s window (no responder running yet), both
        become hosts. The conflict scan 2s later finds the other host
        and resolves via IP tiebreaker.

        The scan itself uses repeated broadcasts (every 500ms during the
        3s window) so even on lossy Windows UDP, at least one of the
        6 broadcasts should get through."""
        QTimer.singleShot(2000, self._do_host_conflict_scan)

    def _do_host_conflict_scan(self):
        if self._scanning_for_conflict or self._role != "host" or not self._enabled:
            return
        self._scanning_for_conflict = True
        self._conflict_rooms = []
        self._conflict_pending = 2  # UDP discovery + TCP probe

        # UDP discovery (finds hosts whose responder receives broadcast).
        self._conflict_discovery = RoomDiscovery(self)
        self._conflict_discovery.discovery_finished.connect(
            self._on_conflict_scan_part
        )
        self._conflict_discovery.error.connect(self._on_conflict_scan_part_error)
        # NOTE: discover() emits `error` synchronously on start failure
        # (same-thread AutoConnection = Direct), which already drives
        # _on_conflict_scan_part_error — no extra bookkeeping needed here.
        if not self._conflict_discovery.discover(self._room_code, timeout=3.0):
            self._conflict_discovery = None

        # TCP subnet probe (reliable — finds hosts UDP misses; this is the
        # path that resolves the both-become-hosts case on real Wi-Fi LANs).
        self._conflict_tcp_probe = SubnetTCPProbe(self)
        self._conflict_tcp_probe.probe_finished.connect(self._on_conflict_scan_part)
        self._conflict_tcp_probe.error.connect(self._on_conflict_scan_part_error)
        if not self._conflict_tcp_probe.probe(self._room_code, timeout=5.0):
            self._conflict_tcp_probe = None

    def _on_conflict_scan_part(self, rooms):
        # Collect results from each mechanism; evaluate once both are done.
        self._conflict_rooms.extend(rooms)
        self._conflict_pending -= 1
        if self._conflict_pending > 0:
            return
        self._evaluate_conflict_scan()

    def _on_conflict_scan_part_error(self, msg):
        self._conflict_pending -= 1
        if self._conflict_pending > 0:
            return
        self._evaluate_conflict_scan()

    def _evaluate_conflict_scan(self):
        self._scanning_for_conflict = False
        self._conflict_discovery = None
        self._conflict_tcp_probe = None
        if not self._enabled or self._role != "host":
            return
        local_ip = _get_local_ip()
        for ip, rc, port in self._conflict_rooms:
            if rc == self._room_code and ip != local_ip and ip != "127.0.0.1":
                # Another host found for the same room. Use IP tiebreaker.
                all_ips = sorted([local_ip, ip])
                if local_ip != all_ips[0]:
                    # We have the higher IP — step down and join the other host.
                    self._resolve_host_conflict(ip, port)
                # If we have the lower IP, we keep being the host.
                # The other device's conflict scan will detect us and step down.
                return
        # No conflict found, schedule next scan.
        self._schedule_host_conflict_scan()

    def _resolve_host_conflict(self, other_host_ip, other_host_port):
        """Step down as host and join the other host as a client."""
        # Stop the conflict scan first to avoid re-entrance.
        self._scanning_for_conflict = False
        if self._conflict_discovery:
            self._conflict_discovery.stop()
            self._conflict_discovery = None
        if self._conflict_tcp_probe:
            self._conflict_tcp_probe.stop()
            self._conflict_tcp_probe = None
        # Stop host and responder, then join the other host.
        if self._responder:
            self._responder.stop()
            self._responder = None
        if self._host:
            self._host.stop()
            self._host = None
        self._role = None
        if self._enabled:
            self._become_client(other_host_ip, other_host_port)

    def _become_host(self):
        self._host = ClipboardHost(self)
        self._host.clipboard_received.connect(self._on_remote_clipboard)
        self._host.peer_count_changed.connect(self._on_peer_count)
        self._host.error.connect(self._on_network_error)
        if not self._host.start():
            self._set_status(I18n.tr("clipboard_status_failed"))
            return
        # Expose the room code so the host can answer SubnetTCPProbe "probe"
        # messages (probe_resp carries the room for verification by the prober).
        self._host.room_code = self._room_code
        self._responder = RoomResponder(self)
        self._responder.start(self._room_code, self._host.port)
        self._role = "host"
        self._refresh_status_text()
        # Start periodic conflict scan to detect other hosts (fallback when
        # competitor detection during initial discovery fails).
        self._schedule_host_conflict_scan()

    def _become_client(self, host_ip, port):
        self._client = ClipboardClient(self)
        # Connect to bound methods (not lambdas) so Qt auto-queues the
        # cross-thread call onto the main thread — network threads must not
        # touch QClipboard / widgets directly.
        self._client.clipboard_received.connect(self._on_client_clipboard)
        self._client.peer_count_changed.connect(self._on_peer_count)
        self._client.connected.connect(self._on_client_connected)
        self._client.disconnected.connect(self._on_client_disconnected)
        self._client.reconnecting.connect(self._on_client_reconnecting)
        self._client.retries_exhausted.connect(self._on_client_retries_exhausted)
        self._client.error.connect(self._on_network_error)
        self._client.connect_to_host(
            host_ip, port, self._room_code, self._peer_id, self._peer_name
        )
        self._role = "client"
        self._set_status(I18n.tr("clipboard_status_connecting"))

    # ----- cross-thread slots (run on main thread via Qt auto-queue) -----

    def _on_client_clipboard(self, text):
        self._on_remote_clipboard(text, "")

    def _on_client_connected(self):
        self._set_status(I18n.tr("clipboard_status_joined"))

    def _on_client_reconnecting(self):
        # Emitted by the client between retry attempts (initial connect
        # failure or a dropped connection). Show "connecting..." rather
        # than "disconnected" — we're still trying, not terminal.
        if not self._enabled:
            return
        self._set_status(I18n.tr("clipboard_status_connecting"))

    def _on_client_disconnected(self):
        if not self._enabled:
            return
        self._set_status(I18n.tr("clipboard_status_disconnected"))

    def _on_client_retries_exhausted(self):
        """The client gave up after MAX_RETRIES attempts to reach the host.
        Self-heal: tear down the dead client and re-run discovery. If the
        other host has come back, we re-join it; if not, we become host so
        the LAN has a host again instead of stranding both devices.

        This closes the 'manager stuck as client with no connection' hole:
        when the host we stepped down to join is unreachable for the full
        retry budget (~92s default), we don't strand the user in
        'disconnected' — we re-evaluate and may promote ourselves.
        """
        if not self._enabled:
            return
        # Drop the dead client and re-discover. _start_connection also
        # re-arms the conflict scan if we end up becoming host.
        self._stop_network()
        self._enabled = True  # _stop_network doesn't touch _enabled, but be explicit
        self._connecting = True
        self._set_status(I18n.tr("clipboard_status_scanning"))
        self._start_connection(self._room_code)

    def _on_network_error(self, msg):
        self._set_status(I18n.tr("clipboard_status_failed"))

    def _on_peer_count(self, count):
        self._peer_count = count
        self._refresh_status_text()

    def _stop_network(self):
        # Mark initial-discovery resolved so any late callback from a still-
        # running UDP/TCP discovery is ignored instead of becoming host/client.
        self._connect_resolved = True
        self._connect_pending = 0
        self._scanning_for_conflict = False
        if self._conflict_discovery:
            self._conflict_discovery.stop()
            self._conflict_discovery = None
        if self._conflict_tcp_probe:
            self._conflict_tcp_probe.stop()
            self._conflict_tcp_probe = None
        if self._discovery:
            self._discovery.stop()
            self._discovery = None
        if self._tcp_probe:
            self._tcp_probe.stop()
            self._tcp_probe = None
        if self._responder:
            self._responder.stop()
            self._responder = None
        if self._host:
            self._host.stop()
            self._host = None
        if self._client:
            self._client.disconnect()
            self._client = None
        self._role = None
        self._peer_count = 0

    # ------------------------------------------------------------------ clipboard flows

    def _on_local_copy(self, text):
        """User copied locally -> store + broadcast to peers.
        Dedupes burst writes (some apps fire dataChanged several times for the
        same text: text/html/inline variants) so history + network aren't
        hammered with duplicates."""
        if not text or text == self._last_local_text:
            return
        self._last_local_text = text
        self._history.add(text, source="local", origin_peer=self._peer_id)
        self._refresh_panel()
        self._broadcast(text)

    def _on_remote_clipboard(self, text, origin_peer=""):
        """Received text from a peer -> write to local clipboard (echo-guarded)
        and add to history. Echo guard prevents re-broadcasting it."""
        self._monitor.set_clipboard(text)
        self._history.add(text, source="remote", origin_peer=origin_peer)
        self._refresh_panel()

    def _on_panel_copy(self, content):
        """User clicked a history item -> paste it at the user's caret,
        then collapse the family.

        Sequence:
          1. Write the content to the system clipboard (echo-guarded so
             this doesn't re-broadcast to peers — peers already have it,
             or will receive it via _broadcast below).
          2. Bump it to the top of history + broadcast to peers.
          3. After 50ms (let QClipboard settle), synthesize Ctrl+V via
             SendInput. The panel never steals focus (WS_EX_NOACTIVATE),
             so the foreground window is still the user's original input
             field — the paste lands at their caret.
          4. After another 100ms (SendInput is synchronous, but the target
             app needs a tick to process the keystroke), collapse the
             family. This avoids the panel obscuring whatever just got
             pasted, and matches the "click → paste → done" expectation.

        Timings are tuned for Windows: SendInput returns after the OS has
        queued the events, but the receiving app processes them on its own
        message pump — a short grace period prevents the panel's hide
        animation from racing the paste."""
        self._monitor.set_clipboard(content)
        self._history.add(content, source="local", origin_peer=self._peer_id)
        self._refresh_panel()
        self._broadcast(content)
        # Step 3: synthesize the paste.
        QTimer.singleShot(50, send_ctrl_v)
        # Step 4: collapse the family. hide_family() is animation-aware
        # (reversible show/hide) and does NOT touch _expanded, so the
        # next Ctrl+` surfaces the family with the panel still open per
        # the user's preference.
        QTimer.singleShot(150, self.hide_family)

    def _on_panel_delete(self, item_id):
        self._history.delete(item_id)
        self._refresh_panel()

    def _on_panel_clear(self):
        self._history.clear()
        self._refresh_panel()

    def _broadcast(self, text):
        if not self._enabled or not text:
            return
        if self._role == "host" and self._host:
            self._host.broadcast_clipboard(text, origin_peer_id=self._peer_id)
        elif self._role == "client" and self._client and self._client.is_connected:
            self._client.send_clipboard(text)

    # ------------------------------------------------------------------ panel / status

    def show_card(self):
        if not self._enabled:
            return
        self._refresh_panel()
        self._panel.show_panel()
        self._expanded = True
        self._save_state()

    def hide_card(self):
        """Collapse just the panel (B -> C). Feature stays enabled."""
        if self._panel.isVisible():
            self._panel.hide_panel()
        self._expanded = False
        self._save_state()

    def hide_family(self):
        """Hide the whole family (capsule + panel). Animation-aware: doesn't
        gate on _can_hide / _animating — the show/hide methods themselves
        handle reversal cleanly. Does NOT change _expanded — that is a user
        preference and is only flipped by an explicit collapse (hide_card)
        or expand (show_card). Keeping it stable means the next Ctrl+`
        surfaces the family exactly as the user last had it."""
        if self.capsule.isVisible():
            self.capsule.hide_capsule()
        if self._panel.isVisible():
            self._panel.hide_panel()

    def hide_family_immediately(self):
        """Hide the whole family instantly — no animation. Used when entering
        screenshot/annotation overlays: any lingering panel would be captured
        into the screenshot, so we want it gone the same frame. Like
        hide_family(), this does NOT touch _expanded or save_state — the
        user's panel preference is preserved, and the family will resurface
        (with or without the panel per _expanded) on the next Ctrl+`."""
        self.capsule.hide_immediately()
        # _panel may be visible OR mid-animation; hide_immediately() handles
        # both. Guard against the panel never having been shown (no HWND yet).
        if self._panel.isVisible() or self._panel._animating:
            self._panel.hide_immediately()

    def _hide_family(self):
        # Called when focus leaves the family (capsule or panel detected it).
        self.hide_family()

    def _refresh_panel(self):
        self._panel.set_items(self._history.get_all())

    def _set_status(self, text):
        self._status = text
        self._panel.set_status(text)

    def _refresh_status_text(self):
        if not self._enabled:
            self._set_status(I18n.tr("clipboard_status_disconnected"))
            return
        if self._connecting:
            self._set_status(I18n.tr("clipboard_status_scanning"))
            return
        total = self._peer_count + 1
        if self._role == "host":
            self._set_status(f"{I18n.tr('clipboard_status_hosting')} · {total}")
        elif self._role == "client":
            self._set_status(f"{I18n.tr('clipboard_status_joined')} · {total}")
        else:
            self._set_status(I18n.tr("clipboard_status_disconnected"))

    def _update_button_tooltip(self):
        if self._enabled and self._room_code:
            tip = f"{I18n.tr('clipboard')} · {self._room_code}"
        else:
            tip = I18n.tr("clipboard_no_room")
        self.capsule.btn_clipboard.setToolTip(tip)

    @staticmethod
    def _is_valid_room(code):
        return isinstance(code, str) and len(code) == 6 and code.isdigit()

    # ------------------------------------------------------------------ shutdown

    def shutdown(self):
        """Persist state and tear down. Does NOT reset enabled/expanded
        (so they survive restart) — per the hard constraint."""
        self._save_state()
        self._stop_network()
        if self._panel.isVisible():
            self._panel.hide_panel()
        self._monitor.disable()
        self._history.close()
