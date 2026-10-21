#!/usr/bin/python3
"""Sedut — download manager ringkas untuk CachyOS / KDE Plasma."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from sedut_app import ipc  # noqa: E402
from sedut_app.ui import MainWindow  # noqa: E402


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    # Sedut dah terbuka? Hantar link (atau minta naikkan tetingkap) dan keluar.
    if ipc.send({"action": "add", "url": url} if url else {"action": "show"}) is not None:
        return
    app = QApplication(sys.argv)
    app.setApplicationName("Sedut")
    app.setDesktopFileName("sedut")
    w = MainWindow()
    w.start_ipc()
    if url:                        # sedut <url> — terus kesan
        w.url.setText(url)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
