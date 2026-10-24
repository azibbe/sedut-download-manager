# Sedut — Download Manager

A small, no-nonsense download manager for Linux desktops (built on CachyOS / KDE Plasma), written in Python + PySide6.
Paste a link, Sedut figures out what it is, and downloads it — direct files through **aria2c**, video/streams through **yt-dlp**.

> *Sedut* is Malay for "to suck in / slurp".

## Features

- **Paste and go** — paste a URL in the top bar; Sedut auto-detects it after 0.5 s (or press Enter / *Detect*).
- **Smart detection**
  - Direct files: a `Range: bytes=0-0` probe reads size, filename (`Content-Disposition`, RFC 5987) and whether the server supports resume.
  - Anything else (YouTube, Facebook, Vimeo, generic HLS `.m3u8` / DASH `.mpd`, …) is handed to `yt-dlp -J`.
- **Quality picker** for video — one entry per resolution (2160p, 1440p, 1080p … with fps), estimated size, plus *Audio only (MP3)*. H.264 preferred; video + audio merged to MP4 with ffmpeg.
- **Fast downloads** — aria2c with 8 connections per file; yt-dlp fetches HLS/DASH fragments 8 at a time.
- **Pause / resume** — survives app restarts (aria2c `.aria2` control files, yt-dlp `.part` files).
- **Queue** — up to 3 downloads run at once, the rest wait.
- **Auto-sorted folders** — `~/Downloads/Sedut/{Video,Music,Documents,Programs,Archives,Images,Other}`.
- **Browser cookies** — for sites that require login or a "not a bot" check, pick your browser in the *Sign-in* box (Firefox, Chrome, Chromium, Brave, Edge, Vivaldi, Opera — only the ones installed are listed). yt-dlp then reads that browser's cookies (`--cookies-from-browser`). Firefox works from the regular, Flatpak and Snap installs; the choice is remembered.
- **Single instance** — running `sedut <url>` while Sedut is open sends the link to the existing window (Unix socket).
- **Browser integration (optional)** — the bundled Video Grabber extension sends links (with Referer, User-Agent and page title) straight into Sedut through a native messaging host.
- Desktop notifications on finish/failure (`notify-send`), download list persisted between sessions.

## Requirements

- Linux with a Qt-capable desktop (developed on KDE Plasma, Wayland)
- Python 3.10+ with PySide6
- `aria2c`, `yt-dlp`, `ffmpeg`
- optional: `notify-send` (libnotify) for notifications

Arch / CachyOS:

```bash
sudo pacman -S --needed pyside6 yt-dlp aria2 ffmpeg
```

Debian / Ubuntu (package names may vary; a recent `yt-dlp` from pipx is recommended):

```bash
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtnetwork aria2 ffmpeg
pipx install yt-dlp
```

## Install

```bash
git clone https://github.com/azibbe/sedut-download-manager.git
cd sedut-download-manager
./install.sh
```

`install.sh` runs without sudo and:

1. checks the dependencies above,
2. symlinks `sedut.py` to `~/.local/bin/sedut`,
3. creates `~/.local/share/applications/sedut.desktop` (shows up in the app menu),
4. registers the native messaging host `com.sedut.host` for Google Chrome, Chromium and Brave.

The install points at the cloned folder, so keep it where it is (or re-run `install.sh` after moving it).

## Usage

```bash
sedut              # open the window
sedut <url>        # open (or reuse the running window) and detect <url>
```

1. Paste a link into the top bar.
2. In the *Detected* dialog, choose quality, file name and folder.
3. Click *Download*.

Toolbar / right-click menu: *Resume* (also retries failed items), *Pause*, *Remove* (from the list, optionally deleting the files), *Open file*, *Open folder*, *Copy link*. Double-click a finished item to open it.

Test detection from a terminal without the GUI:

```bash
python3 -m sedut_app.probe <url>
```

## Browser extension: Video Grabber (optional)

The [`extension/`](extension/) folder contains **Video Grabber**, a Chrome / Chromium / Brave extension (Manifest V3) that works on its own *and* as Sedut's browser companion.

On its own it:

- detects videos on any page from network traffic (`video/*`, HLS `.m3u8`, DASH `.mpd`) and the DOM (`<video>`, `<source>`, `og:video`, links) — the red badge shows how many were found in the tab;
- downloads MP4 / WebM / MOV directly, and HLS by fetching + joining the segments in the browser (quality picker, AES-128 decryption).

With Sedut installed it adds:

- a **Sedut** button per detected video and a **Page → Sedut** button (sends the page URL so yt-dlp can handle YouTube, Facebook, TikTok…);
- right-click menu items: *Download with Sedut* (link), *Download this media with Sedut* (video/audio), *Send this page to Sedut* (page).

Links are sent with the page's Referer, User-Agent and title, so Sedut names files after the page instead of `index.m3u8`.

Install it:

1. Open `chrome://extensions` and turn on **Developer mode**.
2. **Load unpacked** → select the `extension/` folder of this repo.
3. Run `./install.sh` (if you haven't) so the browser can reach Sedut.

The extension ID is fixed at `mjdkcacdjpnnidoahofhfhgajkomcmmc` by the public `key` in `extension/manifest.json`, which is exactly the ID `install.sh` allows. If you remove that key or load a fork with a different key, update `EXT_ID` in `install.sh` and re-run it.

Limits: DRM-protected video (Netflix, Disney+, Widevine/FairPlay) is not supported, by design. YouTube and other MSE players split video into small ranges, so use the *Page → Sedut* button for those. See [`extension/README.md`](extension/README.md) for details.

### Native messaging protocol

`sedut_host.py` is a [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) host (`com.sedut.host`). The extension sends one JSON message:

```json
{"action": "add", "url": "...", "referer": "...", "title": "...", "kind": "...", "userAgent": "..."}
```

The host forwards it to the running Sedut (launching it first if needed, waiting up to 15 s) and replies `{"ok": true, "how": "running" | "launched"}`. `{"action": "ping"}` reports whether Sedut is running. Host log: `~/.local/state/sedut/host.log`.

## Files & paths

| What | Where |
|---|---|
| Downloads | `~/Downloads/Sedut/<category>/` |
| Download list | `~/.local/share/sedut/downloads.json` |
| Settings (cookie browser) | `~/.local/share/sedut/settings.json` |
| IPC socket | `$XDG_RUNTIME_DIR/sedut-<uid>.sock` (override with `SEDUT_SOCKET`) |
| Native host manifest | `~/.config/<browser>/NativeMessagingHosts/com.sedut.host.json` |
| Command the host uses to launch Sedut | `SEDUT_CMD` env var (default: `sedut` on `PATH`) |

## Project layout

```
sedut.py            entry point (single-instance check, starts the GUI)
sedut_host.py       Chrome native messaging host (no Qt import, starts fast)
install.sh          per-user install: launcher, .desktop file, native host
sedut_app/
  probe.py          URL detection: direct-file probe + yt-dlp metadata, quality choices
  engine.py         Download model, aria2c / yt-dlp command builder, progress parsing (QProcess)
  browsers.py       finds installed browsers for the cookie picker
  ui.py             main window, detect dialog, queue, persistence, IPC server
  ipc.py            Unix-socket client used by the 2nd instance and the native host
extension/          Video Grabber browser extension (MV3)
```

## Uninstall

```bash
rm ~/.local/bin/sedut ~/.local/share/applications/sedut.desktop
rm -f ~/.config/{google-chrome,chromium,BraveSoftware/Brave-Browser}/NativeMessagingHosts/com.sedut.host.json
rm -r ~/.local/share/sedut ~/.local/state/sedut   # download history and log
```

## Notes

- Only download content you have the right to download. Respect each site's terms of service.
- Site support is whatever your installed `yt-dlp` supports — keep it updated when a site stops working.

## License

[MIT](LICENSE) © 2026 azibbe — covers both the Sedut app and the `extension/` folder.
Sedut calls `aria2c`, `yt-dlp` and `ffmpeg` as external programs; they keep their own licenses.
