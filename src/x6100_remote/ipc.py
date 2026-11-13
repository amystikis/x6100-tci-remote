"""Tiny local control channel so an OS-level hotkey can drive the running app.

    x6100-tci-remote --ptt toggle      # or: on | off

The command is sent over a per-user local socket (a Unix socket on Linux, not reachable from the network) to the
already running window, which applies exactly the same guards as its own PTT button: transmit controls must be
enabled, the radio connected, and the auto-unkey timer still runs. Only the commands in :data:`COMMANDS` exist.
"""
from __future__ import annotations

import getpass
import os
from typing import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

COMMANDS = ("ptt on", "ptt off", "ptt toggle", "ping")


def default_name() -> str:
    override = os.environ.get("X6100_TCI_REMOTE_IPC")          # lets tests (or two profiles) use another channel
    if override:
        return override
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return "x6100-tci-remote-" + user


def send_command(cmd: str, name: str | None = None, timeout_ms: int = 2500) -> tuple[bool, str]:
    """Send one command to the running app. Returns (reached_the_app, reply_text)."""
    if cmd not in COMMANDS:
        return False, "unknown command %r" % cmd
    sock = QLocalSocket()
    sock.connectToServer(name or default_name())
    if not sock.waitForConnected(timeout_ms):
        return False, "x6100-tci-remote is not running (or its window has not started yet)"
    sock.write((cmd + "\n").encode())
    sock.waitForBytesWritten(timeout_ms)
    if not sock.waitForReadyRead(timeout_ms):
        return False, "no answer from x6100-tci-remote"
    reply = bytes(sock.readAll()).decode(errors="replace").strip()
    sock.disconnectFromServer()
    return True, reply


class CommandServer(QObject):
    """Listens for commands and answers each with one line. ``handler(cmd) -> reply`` runs in the GUI thread."""

    def __init__(self, handler: Callable[[str], str], name: str | None = None) -> None:
        super().__init__()
        self.handler = handler
        self.name = name or default_name()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # this user only
        self.server.newConnection.connect(self._on_connection)

    def start(self) -> bool:
        """False if another instance already owns the name."""
        ok, _ = send_command("ping", self.name, 400)
        if ok:
            return False
        QLocalServer.removeServer(self.name)                                   # stale socket of a crashed run
        return self.server.listen(self.name)

    def _on_connection(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(sock.deleteLater)

    def _on_ready(self, sock: QLocalSocket) -> None:
        if not sock.canReadLine():
            return
        cmd = bytes(sock.readLine()).decode(errors="replace").strip()
        if cmd not in COMMANDS:
            reply = "error: unknown command"
        elif cmd == "ping":
            reply = "pong"
        else:
            try:
                reply = self.handler(cmd)
            except Exception as e:                                             # never crash the GUI on a bad call
                reply = "error: %s" % e
        sock.write((reply + "\n").encode())
        sock.flush()
        sock.disconnectFromServer()

    def stop(self) -> None:
        self.server.close()
