"""ipc.py — a single Sedut instance; a second instance / the native host sends links here.

Protocol: one JSON line per connection over a Unix socket
    {"action": "add", "url": "...", "referer": "...", "title": "..."}
Reply: {"ok": true}
No Qt imports here so the native host stays light and fast.
"""
from __future__ import annotations

import json
import os
import socket


def socket_path() -> str:
    if os.environ.get("SEDUT_SOCKET"):
        return os.environ["SEDUT_SOCKET"]
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.path.isdir(base):
        base = "/tmp"
    return os.path.join(base, f"sedut-{os.getuid()}.sock")


def send(payload: dict, timeout: float = 3.0) -> dict | None:
    """Send to the running instance. None = no instance running."""
    path = socket_path()
    if not os.path.exists(path):
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(json.dumps(payload).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        return json.loads(data or b'{"ok": true}')
    except (OSError, ValueError):
        return None
