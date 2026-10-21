#!/usr/bin/python3
"""Sedut — download manager ringkas untuk CachyOS / KDE Plasma."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from sedut_app.ui import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sedut")
    app.setDesktopFileName("sedut")
    w = MainWindow()
    if len(sys.argv) > 1:          # sedut <url> — terus kesan
        w.url.setText(sys.argv[1])
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
