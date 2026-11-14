"""Application entry point."""
from __future__ import annotations

import argparse
import asyncio
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="x6100-tci-remote",
                                 description="Desktop remote controller for the Xiegu X6100 and X6200 (TCI)")
    ap.add_argument("address", nargs="?", help="radio address, e.g. 192.168.0.150 or 192.168.0.150:50001")
    ap.add_argument("--demo", action="store_true", help="run against a built-in fake radio (no hardware)")
    ap.add_argument("--ptt", choices=["on", "off", "toggle"],
                    help="tell the already running app to key/unkey the radio (use it from an OS keyboard shortcut)")
    args = ap.parse_args(argv)

    if args.ptt:                                   # remote-control mode: no window, just talk to the running app
        from PySide6.QtCore import QCoreApplication
        from .ipc import send_command
        QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        reached, reply = send_command("ptt " + args.ptt)
        print(reply, file=sys.stdout if reached and reply.startswith("ok") else sys.stderr)
        return 0 if reached and reply.startswith("ok") else 1

    from PySide6.QtWidgets import QApplication
    from .gui.main_window import MainWindow
    from .gui.worker import TciWorker

    app = QApplication(sys.argv[:1])
    app.setApplicationName("X6100 TCI Remote")
    worker = TciWorker()
    win = MainWindow(worker)
    win.show()
    if not win.start_command_server():
        print("note: another x6100-tci-remote is already running; --ptt will control that one", file=sys.stderr)
    if args.demo:
        from .fakeradio import serve_fake, serve_fake_panel

        async def start():
            radio, server = await serve_fake(0)
            _, pserver = await serve_fake_panel(radio, 0)
            return server, pserver

        server, pserver = asyncio.run_coroutine_threadsafe(start(), worker.loop).result(timeout=5)
        port = server.sockets[0].getsockname()[1]
        win.addr.setEditText("127.0.0.1:%d" % port)
        win.connect_to("ws://127.0.0.1:%d/" % port, "ws://127.0.0.1:%d/" % pserver.sockets[0].getsockname()[1])
    elif args.address:
        win.addr.setEditText(args.address)
        win.toggle_connection()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
