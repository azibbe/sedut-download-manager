"""engine.py — jalankan muat turun guna aria2c (fail terus) atau yt-dlp (video).

Jeda = hentikan proses. Sambung = jalankan semula; aria2c (-c, fail .aria2)
dan yt-dlp (fail .part) sambung dari tempat ia berhenti.
"""
from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict

from PySide6.QtCore import QObject, QProcess, Signal

# status
QUEUED, RUNNING, PAUSED, DONE, FAILED = "Menunggu", "Memuat turun", "Dijeda", "Siap", "Gagal"


@dataclass
class Download:
    url: str
    kind: str                     # 'file' | 'media'
    folder: str
    filename: str                 # tanpa sambungan untuk 'media'
    fmt: str | None = None
    sort: str | None = None
    audio_only: bool = False
    cookies_browser: str | None = None
    size: int | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = QUEUED
    done_bytes: int = 0
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    error: str = ""
    final_path: str = ""
    added: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Download":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ------------------------------------------------------------- bina arahan
def build_command(d: Download, connections: int = 8) -> list[str]:
    if d.kind == "file":
        return [
            shutil.which("aria2c") or "aria2c",
            "-c", f"-x{connections}", f"-s{connections}", "-k1M",
            "--file-allocation=none", "--auto-file-renaming=false", "--allow-overwrite=false",
            "--summary-interval=1", "--console-log-level=warn", "--show-console-readout=true",
            "--enable-color=false", "--max-tries=5", "--retry-wait=3",
            "-d", d.folder, "-o", d.filename, d.url,
        ]
    cmd = [
        shutil.which("yt-dlp") or "yt-dlp",
        "--newline", "--no-playlist", "--no-colors", "--continue", "--no-mtime",
        "-N", str(connections),       # muat turun serpihan HLS/DASH serentak
        "--progress-template",
        "download:SEDUT|%(progress.status)s|%(progress.downloaded_bytes)s|"
        "%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|"
        "%(progress._speed_str)s|%(progress._eta_str)s|%(progress.fragment_index)s|%(progress.fragment_count)s",
        "--print", "after_move:SEDUTFILE|%(filepath)s",
        "-o", os.path.join(d.folder, d.filename + ".%(ext)s"),
    ]
    if d.audio_only:
        cmd += ["-f", d.fmt or "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        cmd += ["-f", d.fmt or "bv*+ba/b", "--merge-output-format", "mp4"]
        if d.sort:
            cmd += ["-S", d.sort]
    if d.cookies_browser:
        cmd += ["--cookies-from-browser", d.cookies_browser]
    cmd.append(d.url)
    return cmd


# ------------------------------------------------------------- parse progress
# [#2089b0 1.2MiB/10MiB(12%) CN:8 DL:2.3MiB ETA:4s]
ARIA_RE = re.compile(r"\[#\w+\s+([\d.]+\w*B)/([\d.]+\w*B)\((\d+)%\).*?(?:DL:([\d.]+\w*B))?(?:\s+ETA:(\w+))?\]")
UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}


def _bytes(s: str) -> int:
    m = re.match(r"([\d.]+)(\w+)", s)
    return int(float(m.group(1)) * UNITS.get(m.group(2), 1)) if m else 0


def parse_aria2(line: str) -> dict | None:
    m = ARIA_RE.search(line)
    if not m:
        return None
    return {"done": _bytes(m.group(1)), "total": _bytes(m.group(2)), "percent": float(m.group(3)),
            "speed": (m.group(4) or "").replace("iB", "B") + "/s" if m.group(4) else "",
            "eta": m.group(5) or ""}


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_ytdlp(line: str) -> dict | None:
    if not line.startswith("SEDUT|"):
        return None
    p = line.split("|")
    if len(p) < 10:
        return None
    done = _num(p[2]) or 0
    total = _num(p[3]) or _num(p[4])
    fi, fc = _num(p[8]), _num(p[9])
    if total:
        pct = done / total * 100
    elif fi and fc:
        pct = fi / fc * 100
    else:
        pct = 0.0
    speed = p[6].strip() if p[6].strip() not in ("NA", "Unknown", "") else ""
    eta = p[7].strip() if p[7].strip() not in ("NA", "Unknown", "") else ""
    return {"done": int(done), "total": int(total) if total else None, "percent": min(pct, 100.0),
            "speed": speed, "eta": eta, "finished": p[1] == "finished"}


# ------------------------------------------------------------- runner
class Runner(QObject):
    """Satu QProcess untuk satu muat turun."""
    progress = Signal(str)          # id
    finished = Signal(str)          # id

    def __init__(self, d: Download, parent=None):
        super().__init__(parent)
        self.d = d
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self._buf = ""
        self._tail: list[str] = []
        self._stopping = False
        self._parts = 0             # yt-dlp: video+audio = 2 bahagian

    def start(self):
        os.makedirs(self.d.folder, exist_ok=True)
        cmd = build_command(self.d)
        self.d.status, self.d.error, self.d.speed = RUNNING, "", ""
        self.proc.start(cmd[0], cmd[1:])

    def stop(self):
        self._stopping = True
        if self.proc.state() != QProcess.NotRunning:
            self.proc.terminate()
            if not self.proc.waitForFinished(3000):
                self.proc.kill()

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput()).decode(errors="replace").replace("\r", "\n")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            self._handle(line)

    def _handle(self, line: str):
        d = self.d
        if d.kind == "file":
            info = parse_aria2(line)
        else:
            if line.startswith("SEDUTFILE|"):
                d.final_path = line.split("|", 1)[1]
                return
            info = parse_ytdlp(line)
            if info and info.get("finished"):
                self._parts += 1
        if info:
            d.done_bytes = info["done"]
            if info.get("total"):
                d.size = info["total"]
            d.percent = info["percent"]
            d.speed, d.eta = info["speed"], info["eta"]
            self.progress.emit(d.id)
        else:
            self._tail = (self._tail + [line])[-8:]
            if d.kind == "media" and ("[Merger]" in line or "[ExtractAudio]" in line):
                d.speed, d.eta = "", "menggabung…" if "[Merger]" in line else "tukar MP3…"
                self.progress.emit(d.id)

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self.d.status = FAILED
            self.d.error = "Gagal mula proses (aria2c/yt-dlp dipasang?)"
            self.finished.emit(self.d.id)

    def _done(self, code, _status):
        d = self.d
        d.speed, d.eta = "", ""
        if self._stopping:
            d.status = PAUSED
        elif code == 0:
            d.status, d.percent = DONE, 100.0
            if not d.final_path:
                d.final_path = os.path.join(d.folder, d.filename)
            if os.path.exists(d.final_path):
                d.size = d.done_bytes = os.path.getsize(d.final_path)
        else:
            d.status = FAILED
            errs = [l for l in self._tail if "error" in l.lower() or "ERROR" in l] or self._tail
            d.error = (errs[-1] if errs else f"kod keluar {code}").replace("ERROR: ", "")[:300]
        self.finished.emit(d.id)
