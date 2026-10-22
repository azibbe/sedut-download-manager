#!/usr/bin/python3
"""Sedut — a simple download manager for CachyOS / KDE Plasma."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from sedut_app import ipc  # noqa: E402
from sedut_app.ui import MainWindow  # noqa: E402


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    # Sedut already open? Send it the link (or ask it to raise its window) and exit.
    if ipc.send({"action": "add", "url": url} if url else {"action": "show"}) is not None:
        return
    app = QApplication(sys.argv)
    app.setApplicationName("Sedut")
    app.setDesktopFileName("sedut")
    w = MainWindow()
    w.start_ipc()
    if url:                        # sedut <url> — detect right away
        w.url.setText(url)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
