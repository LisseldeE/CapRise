"""
单实例
单实例守卫与进程间“唤起”通讯
Copyright (c) 2026 Lisselde_E <Lisselde.E@outlook.com>.
Licensed under the MIT License.
"""
import os
import time

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_CONNECT_TIMEOUT_MS = 300
# 数据写进管道的等待上限（秒）。
_WRITE_TIMEOUT = 1.0


def _server_name():
    """按账号隔离的 socket 名：Windows 命名管道是机器级的，不隔离会让另一个
    用户启动时被当成第二实例。"""
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "default"
    # 管道名要当文件名用，域账号的 DOMAIN\user 反斜杠必须折掉。
    user = "".join(c if c.isalnum() or c in "._-" else "_" for c in user)
    return f"LisseldeE.CapRise.{user}.ipc"


def _is_live(name):
    """`name` 上是否已有活着的拥有者。"""
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
        probe.disconnectFromServer()
        return True
    return False


def poke_existing_instance():
    """唤起已有实例；返回消息是否真的写进管道（没写出去就会随进程退出丢掉）。"""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False
    sock.write(b"show\n")
    sock.flush()
    # 转事件循环等队列排空：waitForBytesWritten 会超时留数据。
    deadline = time.monotonic() + _WRITE_TIMEOUT
    while sock.bytesToWrite() > 0 and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        sock.waitForBytesWritten(50)
    if sock.bytesToWrite() > 0:
        return False
    sock.disconnectFromServer()
    return True


class SingleInstance(QObject):
    """单实例守卫：抢到 socket 的进程是唯一实例，被别的启动唤起时发出 activated。"""

    activated = Signal()  # 第二次启动请求显示胶囊

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self._receiver = None
        self._pending = False

    @property
    def is_first_instance(self):
        return self._own_server()

    def connect_activation(self, slot):
        """注册唤起回调；界面就绪前收到的请求在这里补发。"""
        self._receiver = slot
        self.activated.connect(slot)
        if self._pending:
            self._pending = False
            slot()

    def take_over(self):
        """poke 发现没人应答时，接管实例角色。"""
        return self._own_server()

    def _own_server(self):
        if self._server is not None and self._server.isListening():
            return True
        if _is_live(_server_name()):
            # 已有活的拥有者，我们是第二实例。
            return False
        # 只在没有活的拥有者时才清残留名，否则会拽掉运行中实例的管道。
        QLocalServer.removeServer(_server_name())
        self._server = QLocalServer(self)
        if self._server.listen(_server_name()):
            self._server.newConnection.connect(self._on_connection)
            return True
        return False

    def _on_connection(self):
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda c=conn: self._on_request(c))
        # 消息可能早于 readyRead 到达，信号不补发，自己再查一次缓冲区。
        if conn.bytesAvailable() > 0:
            self._on_request(conn)

    def _on_request(self, conn):
        # QByteArray 没有 strip()，必须转 bytes，否则异常被槽吞掉、唤起
        # 静默失效。
        if bytes(conn.readAll()).strip().lower() != b"show":
            return
        if self._receiver is None:
            # 界面还没就绪，先记下等 connect_activation 补发。
            self._pending = True
        else:
            self.activated.emit()