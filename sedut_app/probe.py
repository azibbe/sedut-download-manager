"""probe.py — kesan apa yang ada di sebalik satu URL.

Tiada kod GUI di sini supaya boleh diuji terus dari terminal:
    /usr/bin/python3 -m sedut_app.probe <url>
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0 Safari/537.36")

STREAM_MIME = ("mpegurl", "dash+xml")


@dataclass
class Choice:
    """Satu pilihan kualiti yang dipapar dalam combo box."""
    label: str
    fmt: str | None = None          # nilai -f yt-dlp
    sort: str | None = None         # nilai -S yt-dlp
    audio_only: bool = False
    size: int | None = None         # anggaran bait


@dataclass
class ProbeResult:
    kind: str                       # 'file' | 'media' | 'none'
    url: str
    title: str = ""
    filename: str = ""
    size: int | None = None
    mime: str = ""
    resumable: bool = False
    extractor: str = ""
    duration: float | None = None
    choices: list[Choice] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------- utiliti
def human_size(n: int | float | None) -> str:
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def safe_filename(name: str, limit: int = 180) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip().strip(".")
    return (name or "fail")[:limit]


def _filename_from_cd(cd: str) -> str:
    # RFC 5987: filename*=UTF-8''nama%20fail.zip
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd, re.I)
    if m:
        return urllib.parse.unquote(m.group(1).strip('" '))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    return m.group(1).strip() if m else ""


def looks_like_url(text: str) -> bool:
    return bool(re.match(r"^(https?|ftp)://\S+$", text.strip(), re.I))


# ---------------------------------------------------------------- fail terus
def probe_direct(url: str, timeout: float = 15, referer: str | None = None,
                 user_agent: str | None = None) -> ProbeResult | None:
    """Minta bait pertama sahaja (Range: bytes=0-0). Pulangkan None kalau HTML/stream."""
    headers = {"User-Agent": user_agent or UA, "Range": "bytes=0-0"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            final = r.geturl()
            h = r.headers
            mime = (h.get("Content-Type") or "").split(";")[0].strip().lower()
            if mime.startswith("text/html") or any(s in mime for s in STREAM_MIME):
                return None
            size = None
            cr = h.get("Content-Range") or ""
            m = re.search(r"/(\d+)\s*$", cr)
            if m:
                size = int(m.group(1))
            elif r.status == 200 and h.get("Content-Length"):
                size = int(h["Content-Length"])
            name = _filename_from_cd(h.get("Content-Disposition") or "")
            if not name:
                name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(final).path)) or "fail"
            if final.lower().split("?")[0].endswith((".m3u8", ".mpd")):
                return None
            return ProbeResult(kind="file", url=final, title=name, filename=safe_filename(name),
                               size=size, mime=mime, resumable=(r.status == 206))
    except Exception as e:  # rangkaian/HTTP gagal — biar yt-dlp cuba pula
        return ProbeResult(kind="none", url=url, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- video (yt-dlp)
def _fmt_size(f: dict) -> int:
    return int(f.get("filesize") or f.get("filesize_approx") or 0)


def _pref_video(cand: list[dict]) -> dict:
    """Tiru pilihan yt-dlp dgn -S res,fps,vcodec:h264 — h264 dulu, kalau tiada ambil tbr tertinggi."""
    video_only = [f for f in cand if f.get("acodec") in (None, "none")] or cand
    h264 = [f for f in video_only if str(f.get("vcodec") or "").startswith(("avc1", "h264"))]
    return max(h264 or video_only, key=lambda f: (f.get("fps") or 0, f.get("tbr") or 0))


def _res_label(f: dict) -> str:
    # video letterbox 3840x1634 -> YouTube labelkan "2160p"; guna label itu, bukan tinggi mentah
    m = re.search(r"(\d{3,4}p)", str(f.get("format_note") or ""))
    return m.group(1) if m else f"{f['height']}p"


def build_choices(info: dict) -> list[Choice]:
    formats = info.get("formats") or [info]
    # HLS generik selalunya vcodec=None tapi ada height — tetap dikira video
    videos = [f for f in formats if f.get("vcodec") != "none" and f.get("height")]
    audios = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    m4a = [a for a in audios if a.get("ext") == "m4a"]
    best_audio = max((_fmt_size(a) for a in (m4a or audios)), default=0)

    choices: list[Choice] = []
    heights = sorted({f["height"] for f in videos}, reverse=True)
    for i, h in enumerate(heights):
        vbest = _pref_video([f for f in videos if f["height"] == h])
        has_audio = vbest.get("acodec") not in (None, "none")
        size = _fmt_size(vbest) + (0 if has_audio else best_audio)
        label = _res_label(vbest) + (" (terbaik)" if i == 0 else "")
        fps = vbest.get("fps")
        if fps and fps > 30:
            label += f" {int(fps)}fps"
        # PENTING: jangan letak acodec dalam -S — ia buat format gabungan 360p (id 18)
        # menang atas video-only resolusi tinggi. Audio dipilih berasingan (ba[ext=m4a]).
        choices.append(Choice(
            label=label,
            fmt=f"bv*[height<={h}]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b",
            sort="res,fps,vcodec:h264", size=size or None))
    if not choices:
        choices.append(Choice(label="Terbaik", fmt="bv*+ba/b", size=_fmt_size(info) or None))
    if audios or videos:
        choices.append(Choice(label="Audio sahaja (MP3)", fmt="ba/b", audio_only=True,
                              size=best_audio or None))
    return choices


def probe_media(url: str, cookies_browser: str | None = None, timeout: float = 90,
                referer: str | None = None, user_agent: str | None = None) -> ProbeResult:
    cmd = ["yt-dlp", "-J", "--no-playlist", "--no-warnings", url]
    if referer:
        cmd[1:1] = ["--referer", referer]
    if user_agent:
        cmd[1:1] = ["--user-agent", user_agent]
    if cookies_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_browser]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return ProbeResult(kind="none", url=url, error="yt-dlp tidak dipasang")
    except subprocess.TimeoutExpired:
        return ProbeResult(kind="none", url=url, error="yt-dlp tamat masa")
    if p.returncode != 0 or not p.stdout.strip():
        err = (p.stderr.strip().splitlines() or ["tiada video dikesan"])[-1]
        return ProbeResult(kind="none", url=url, error=err.replace("ERROR: ", ""))
    info = json.loads(p.stdout)
    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            return ProbeResult(kind="none", url=url, error="Playlist kosong")
        info = entries[0]
    title = info.get("title") or "video"
    return ProbeResult(kind="media", url=url, title=title, filename=safe_filename(title),
                       extractor=info.get("extractor_key") or info.get("extractor") or "",
                       duration=info.get("duration"), choices=build_choices(info))


def probe(url: str, cookies_browser: str | None = None, referer: str | None = None,
          user_agent: str | None = None) -> ProbeResult:
    url = url.strip()
    direct = probe_direct(url, referer=referer, user_agent=user_agent)
    if direct and direct.kind == "file":
        return direct
    media = probe_media(url, cookies_browser, referer=referer, user_agent=user_agent)
    if media.kind == "media":
        return media
    # dua-dua gagal: laporkan ralat yang paling berguna
    if direct and direct.error and "HTTPError" in direct.error:
        media.error = f"{direct.error} | {media.error}"
    return media


if __name__ == "__main__":
    r = probe(sys.argv[1])
    print(r.kind, r.title, human_size(r.size), r.error)
    for c in r.choices:
        print("  -", c.label, human_size(c.size), c.fmt)
