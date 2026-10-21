#!/usr/bin/python3
"""Native messaging host untuk extension Chrome "Video Grabber".

Chrome jalankan skrip ini, hantar satu mesej (4 bait panjang + JSON), dan
tunggu jawapan. Kita terus hantar link ke Sedut yang sedang berjalan; kalau
Sedut belum dibuka, kita buka dulu kemudian hantar.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from sedut_app import ipc  # noqa: E402

LOG = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "sedut", "host.log")


def log(msg: str):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(time.strftime("%F %T ") + msg + "\n")
    except OSError:
        pass


def read_msg():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    n = struct.unpack("<I", raw)[0]
    if n > 1024 * 1024:
        return None
    return json.loads(sys.stdin.buffer.read(n))


def write_msg(obj):
    data = json.dumps(obj).encode()
    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
    sys.stdout.buffer.flush()


def launch_sedut():
    cmd = os.environ.get("SEDUT_CMD")
    if cmd:
        argv = cmd.split()
    else:
        exe = shutil.which("sedut") or os.path.expanduser("~/.local/bin/sedut")
        argv = [exe if os.path.exists(exe) else os.path.join(os.path.dirname(os.path.realpath(__file__)), "sedut.py")]
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    msg = read_msg()
    if not msg:
        return
    if msg.get("action") == "ping":
        write_msg({"ok": True, "running": ipc.send({"action": "ping"}) is not None})
        return
    if msg.get("action") != "add" or not msg.get("url"):
        write_msg({"ok": False, "error": "Mesej tidak sah"})
        return
    payload = {k: msg.get(k, "") for k in ("action", "url", "referer", "title", "kind", "userAgent")}

    r = ipc.send(payload)
    how = "running"
    if r is None:
        how = "launched"
        launch_sedut()
        for _ in range(60):          # tunggu Sedut sedia (≤ 15 s)
            time.sleep(0.25)
            r = ipc.send(payload)
            if r is not None:
                break
    if r is None:
        log(f"GAGAL hantar {payload['url']}")
        write_msg({"ok": False, "error": "Sedut tidak dapat dibuka"})
    else:
        log(f"{how}: {payload['url']}")
        write_msg({"ok": bool(r.get("ok", True)), "how": how, "error": r.get("error")})


if __name__ == "__main__":
    main()
