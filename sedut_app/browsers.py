"""browsers.py — find browsers whose cookies yt-dlp can read (--cookies-from-browser)."""
from __future__ import annotations

import os
from pathlib import Path

_HOME = Path.home()
_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or _HOME / ".config")

# (yt-dlp name, label, profile folders yt-dlp looks in on Linux)
BROWSERS: list[tuple[str, str, list[Path]]] = [
    ("firefox", "Firefox", [
        _CONFIG / "mozilla/firefox",                               # Firefox 147+ (XDG)
        _HOME / ".mozilla/firefox",                                # older Firefox
        _HOME / ".var/app/org.mozilla.firefox/config/mozilla/firefox",  # Flatpak
        _HOME / ".var/app/org.mozilla.firefox/.mozilla/firefox",
        _HOME / "snap/firefox/common/.mozilla/firefox",            # Snap
    ]),
    ("chrome", "Chrome", [_CONFIG / "google-chrome"]),
    ("chromium", "Chromium", [_CONFIG / "chromium"]),
    ("brave", "Brave", [_CONFIG / "BraveSoftware/Brave-Browser"]),
    ("edge", "Edge", [_CONFIG / "microsoft-edge"]),
    ("vivaldi", "Vivaldi", [_CONFIG / "vivaldi"]),
    ("opera", "Opera", [_CONFIG / "opera"]),
]

LABELS = {key: label for key, label, _ in BROWSERS}


def installed() -> list[tuple[str, str]]:
    """(key, label) for every browser that has a profile folder on this machine."""
    return [(key, label) for key, label, dirs in BROWSERS if any(d.is_dir() for d in dirs)]


if __name__ == "__main__":
    for key, label in installed():
        print(f"{key:10} {label}")
