"""Single-instance guard + IPC "poke".

CapRise is a tray + global-hotkey desktop tool. Running more than one
instance causes duplicate tray icons, failed global-hotkey registration,
and conflicting clipboard / LAN-sync listeners. The first instance owns a
QLocalServer on a fixed name; a later launch probes that socket:
  - if a live instance is listening -> we must yield: ask it to show the
    capsule, then exit quietly;
  - otherwise we take over, clearing any stale socket name left by a crash
    (the OS releases the underlying handle when a process dies, so a
    rerun can always re-bind).
"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_SERVER_NAME = "LisseldeE.CapRise.ipc"

_CONNECT_TIMEOUT_MS = 300


def _is_live(name):
    """True if another process currently owns and listens on `name`."""
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
        probe.disconnectFromServer()
        return True
    return False


def poke_existing_instance():
    """Ask a running instance to surface its capsule. Returns True when an
    instance was listening (message delivered), False otherwise."""
    sock = QLocalSocket()
    sock.connectToServer(_SERVER_NAME)
    if not sock.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False
    sock.write(b"show\n")
    sock.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
    sock.disconnectFromServer()
    return True


class SingleInstance(QObject):
    """Owns the single-instance role while the app runs.

    `is_first_instance` decides, once at startup, whether this process gets
    to keep running. When it is the first instance it listens on the fixed
    socket and re-emits `activated` whenever another launch asks it to show
    the capsule.
    """

    activated = Signal()  # a second launch requested the capsule

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None

    @property
    def is_first_instance(self):
        if self._own_server():
            return True
        return False

    def _own_server(self):
        if _is_live(_SERVER_NAME):
            # A healthy instance already owns the socket: we are the second.
            return False
        # No live owner: clear a left-over name from an abnormal exit and
        # take over. skip removing when a live owner exists so we never
        # yank a running instance's pipe out from under it.
        QLocalServer.removeServer(_SERVER_NAME)
        self._server = QLocalServer(self)
        if self._server.listen(_SERVER_NAME):
            self._server.newConnection.connect(self._on_connection)
            return True
        return False

    def _on_connection(self):
        conn = self._server.nextPendingConnection()
        if conn is None:
            return

        def _handle():
            if conn.readAll().strip().lower() == b"show":
                self.activated.emit()

        conn.readyRead.connect(_handle)