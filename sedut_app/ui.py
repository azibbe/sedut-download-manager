"""ui.py — Sedut main window (PySide6)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtNetwork import QLocalServer
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QToolBar, QVBoxLayout, QWidget,
)

from . import ipc
from .engine import DONE, FAILED, PAUSED, QUEUED, RUNNING, Download, Runner
from .probe import ProbeResult, human_size, looks_like_url, probe, safe_filename

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sedut"
STORE = DATA_DIR / "downloads.json"
SETTINGS = DATA_DIR / "settings.json"
BASE_DIR = Path.home() / "Downloads" / "Sedut"
MAX_ACTIVE = 3

CATEGORIES = {
    "Video": {"mp4", "mkv", "webm", "mov", "avi", "m4v", "flv", "ts", "3gp"},
    "Music": {"mp3", "m4a", "flac", "wav", "ogg", "opus", "aac"},
    "Documents": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "epub"},
    "Programs": {"deb", "rpm", "appimage", "exe", "msi", "pkg", "zst", "iso", "img", "run", "sh"},
    "Archives": {"zip", "rar", "7z", "tar", "gz", "xz", "bz2", "tgz"},
    "Images": {"jpg", "jpeg", "png", "gif", "webp", "svg"},
}


def category_dir(filename: str, kind: str, audio_only: bool = False) -> str:
    if kind == "media":
        return str(BASE_DIR / ("Music" if audio_only else "Video"))
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return str(BASE_DIR / cat)
    return str(BASE_DIR / "Other")


def notify(title: str, body: str):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Sedut", "-i", "folder-download", title, body])


# ------------------------------------------------------------- detection (thread)
class _ProbeSignals(QObject):
    done = Signal(object)


class ProbeTask(QRunnable):
    def __init__(self, url: str, cookies: str | None, referer: str | None = None, user_agent: str | None = None):
        super().__init__()
        self.url, self.cookies, self.referer, self.ua = url, cookies, referer, user_agent
        self.signals = _ProbeSignals()

    def run(self):
        try:
            r = probe(self.url, self.cookies, referer=self.referer, user_agent=self.ua)
        except Exception as e:  # never let the thread die silently
            r = ProbeResult(kind="none", url=self.url, error=str(e))
        self.signals.done.emit(r)


# ------------------------------------------------------------- detection result dialog
GENERIC = {"index", "master", "playlist", "video", "videoplayback", "chunklist", "manifest",
           "prog_index", "media", "stream", "file", "download", "fail", "main"}


def _better_name(r: ProbeResult, page_title: str | None) -> str | None:
    """Links from the extension are often index.m3u8 / videoplayback — use the page title instead."""
    if not page_title:
        return None
    stem, dot, ext = r.filename.rpartition(".") if r.kind == "file" else (r.filename, "", "")
    if not dot:
        stem, ext = r.filename, ""
    if stem.strip().lower() in GENERIC or stem.lower().startswith(("index", "master")):
        name = safe_filename(page_title)
        return f"{name}.{ext}" if ext else name
    return None



class DetectDialog(QDialog):
    def __init__(self, r: ProbeResult, cookies: str | None, parent=None, hint: dict | None = None):
        super().__init__(parent)
        self.r, self.cookies, self.hint = r, cookies, hint or {}
        better = _better_name(r, self.hint.get("title"))
        if better:
            r.filename = better
        self.setWindowTitle("Detected — Sedut")
        self.setMinimumWidth(560)
        form = QFormLayout()

        kind = "Video / media" + (f" ({r.extractor})" if r.extractor else "") if r.kind == "media" else (r.mime or "file")
        form.addRow("Type:", QLabel(kind))
        title = QLabel(r.title); title.setWordWrap(True)
        form.addRow("Title:", title)
        if r.duration:
            m, s = divmod(int(r.duration), 60)
            form.addRow("Duration:", QLabel(f"{m}:{s:02d}"))

        self.quality = None
        self.size_lbl = QLabel(human_size(r.size) + ("" if r.kind == "media" or r.resumable else "  (server does not support resume)"))
        if r.kind == "media":
            self.quality = QComboBox()
            for c in r.choices:
                self.quality.addItem(c.label + (f"  ~{human_size(c.size)}" if c.size else ""), c)
            self.quality.currentIndexChanged.connect(self._quality_changed)
            form.addRow("Quality:", self.quality)
        form.addRow("Size:", self.size_lbl)

        self.name = QLineEdit(r.filename)
        form.addRow("File name:", self.name)

        folder_row = QHBoxLayout()
        self.folder = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1); folder_row.addWidget(browse)
        form.addRow("Save to:", folder_row)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Download", QDialogButtonBox.AcceptRole)
        ok.setDefault(True)
        buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form); lay.addWidget(buttons)
        self._quality_changed()

    def _choice(self):
        return self.quality.currentData() if self.quality else None

    def _quality_changed(self, *_):
        c = self._choice()
        if c is not None:
            self.size_lbl.setText(f"~{human_size(c.size)}" if c.size else "unknown (determined during download)")
        self.folder.setText(category_dir(self.name.text(), self.r.kind, bool(c and c.audio_only)))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def download(self) -> Download:
        c = self._choice()
        return Download(
            url=self.r.url, kind=self.r.kind, folder=self.folder.text().strip(),
            filename=safe_filename(self.name.text()), fmt=c.fmt if c else None,
            sort=c.sort if c else None, audio_only=bool(c and c.audio_only),
            cookies_browser=self.cookies if self.r.kind == "media" else None,
            size=(c.size if c else self.r.size),
            referer=self.hint.get("referer") or None,
            user_agent=self.hint.get("userAgent") or None,
        )


# ------------------------------------------------------------- main window
COLS = ["Name", "Size", "Progress", "Speed", "Time left", "Status"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sedut — Download Manager")
        self.setWindowIcon(QIcon.fromTheme("folder-download"))
        self.resize(980, 520)
        self.downloads: dict[str, Download] = {}
        self.runners: dict[str, Runner] = {}
        self.rows: dict[str, int] = {}
        self.pool = QThreadPool.globalInstance()
        self._probing = False
        self._dialog_open = False
        self._hint: dict = {}
        self._ext_queue: list[dict] = []

        # --- URL bar
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste a link here (Ctrl+V) — Sedut detects it automatically")
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.detect)
        self.url.textChanged.connect(lambda _: self._debounce.start())
        self._debounce = QTimer(self, singleShot=True, interval=500, timeout=self._auto_detect)
        self._last_probed = ""
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.clicked.connect(self.detect)
        self.cookies = QCheckBox("Use Chrome cookies")
        self.cookies.setToolTip("For YouTube/Facebook/Vimeo when they ask you to sign in or prove you're not a bot.\n"
                                "yt-dlp reads the cookies from your Google Chrome profile.")
        top = QHBoxLayout()
        top.addWidget(self.url, 1); top.addWidget(self.detect_btn); top.addWidget(self.cookies)

        # --- table
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in enumerate([0, 90, 160, 100, 90, 110]):
            if i:
                self.table.setColumnWidth(i, w)
        self.table.doubleClicked.connect(lambda *_: self.open_file())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemSelectionChanged.connect(self._update_actions)

        central = QWidget(); lay = QVBoxLayout(central)
        lay.addLayout(top); lay.addWidget(self.table)
        self.setCentralWidget(central)

        # --- toolbar
        tb = QToolBar("Actions"); tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.a_resume = QAction(QIcon.fromTheme("media-playback-start"), "Resume", self, triggered=self.resume)
        self.a_pause = QAction(QIcon.fromTheme("media-playback-pause"), "Pause", self, triggered=self.pause)
        self.a_remove = QAction(QIcon.fromTheme("edit-delete"), "Remove", self, triggered=self.remove)
        self.a_remove.setShortcut(QKeySequence.Delete)
        self.a_open = QAction(QIcon.fromTheme("document-open"), "Open file", self, triggered=self.open_file)
        self.a_folder = QAction(QIcon.fromTheme("folder-open"), "Open folder", self, triggered=self.open_folder)
        self.a_retry = QAction(QIcon.fromTheme("view-refresh"), "Retry", self, triggered=self.resume)
        for a in (self.a_resume, self.a_pause, self.a_remove, self.a_open, self.a_folder):
            tb.addAction(a)

        self._save_timer = QTimer(self, singleShot=True, interval=1500, timeout=self.save)
        self._load()
        self._update_actions()
        self.statusBar().showMessage("Ready. Paste a link to start.")
        self._st = QTimer(self, interval=1000, timeout=self._status); self._st.start()

    # ---------------------------------------------------- detect
    def _auto_detect(self):
        t = self.url.text().strip()
        if looks_like_url(t) and t != self._last_probed:
            self.detect()

    def detect(self):
        t = self.url.text().strip()
        if not looks_like_url(t):
            self.statusBar().showMessage("That is not a valid http/https/ftp link.", 4000)
            return
        if self._probing:
            return
        self._probing, self._last_probed = True, t
        self.detect_btn.setEnabled(False); self.detect_btn.setText("Detecting…")
        self.statusBar().showMessage(f"Detecting {t} …")
        hint = self._hint if self._hint.get("url") == t else {}
        self._hint = hint
        task = ProbeTask(t, "chrome" if self.cookies.isChecked() else None,
                         referer=hint.get("referer") or None, user_agent=hint.get("userAgent") or None)
        task.signals.done.connect(self._probed)
        self.pool.start(task)

    def _probed(self, r: ProbeResult):
        self._probing = False
        self.detect_btn.setEnabled(True); self.detect_btn.setText("Detect")
        self._dialog_open = True
        try:
            self._show_result(r)
        finally:
            self._dialog_open = False
            self._hint = {}
            QTimer.singleShot(0, self._next_external)

    def _show_result(self, r: ProbeResult):
        if r.kind == "none":
            self.statusBar().showMessage("No file or video detected.", 5000)
            msg = r.error or "No file or video was detected at this link."
            if any(k in msg.lower() for k in ("sign in", "log", "cookies", "bot", "forbidden", "403")) and not self.cookies.isChecked():
                msg += "\n\nTry ticking 'Use Chrome cookies' and detect again."
            QMessageBox.warning(self, "Not detected", msg[:1200])
            return
        self.statusBar().showMessage(f"Detected: {r.title}", 4000)
        dlg = DetectDialog(r, "chrome" if self.cookies.isChecked() else None, self, hint=self._hint)
        if dlg.exec() == QDialog.Accepted:
            self.add(dlg.download())
            self.url.clear(); self._last_probed = ""

    # ---------------------------------------------------- receive links from outside
    def start_ipc(self) -> bool:
        """Listen on a Unix socket so the Chrome extension / a second instance can send links."""
        path = ipc.socket_path()
        QLocalServer.removeServer(path)          # stale socket left by an earlier crash
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        ok = self.server.listen(path)
        self.server.newConnection.connect(self._ipc_conn)
        return ok

    def _ipc_conn(self):
        while self.server.hasPendingConnections():
            c = self.server.nextPendingConnection()
            c.setProperty("buf", b"")
            c.readyRead.connect(lambda c=c: self._ipc_read(c))
            c.disconnected.connect(c.deleteLater)
            if c.bytesAvailable():        # data arrived before readyRead was connected
                self._ipc_read(c)

    def _ipc_read(self, c):
        buf = bytes(c.property("buf") or b"") + bytes(c.readAll())
        c.setProperty("buf", buf)
        if b"\n" not in buf:
            return
        try:
            payload = json.loads(buf.split(b"\n", 1)[0])
        except ValueError:
            c.write(b'{"ok": false, "error": "Invalid JSON"}\n'); c.flush(); c.disconnectFromServer()
            return
        c.write(b'{"ok": true}\n'); c.flush(); c.disconnectFromServer()
        if payload.get("action") == "add" and looks_like_url(payload.get("url", "")):
            self.add_external(payload)
        elif payload.get("action") == "show":
            self.showNormal(); self.raise_(); self.activateWindow()

    def add_external(self, payload: dict):
        self._ext_queue.append(payload)
        self.showNormal(); self.raise_(); self.activateWindow()
        n = len(self._ext_queue)
        self.statusBar().showMessage(f"Link received from Chrome ({n} in queue)", 4000)
        self._next_external()

    def _next_external(self):
        if self._probing or self._dialog_open or not self._ext_queue:
            return
        p = self._ext_queue.pop(0)
        self._hint = p
        self._debounce.stop()
        self.url.blockSignals(True); self.url.setText(p["url"]); self.url.blockSignals(False)
        self._last_probed = ""
        self.detect()

    # ---------------------------------------------------- list
    def add(self, d: Download, start: bool = True):
        self.downloads[d.id] = d
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.rows[d.id] = row
        for c in range(len(COLS)):
            it = QTableWidgetItem("")
            it.setData(Qt.UserRole, d.id)
            self.table.setItem(row, c, it)
        bar = QProgressBar(); bar.setRange(0, 1000); bar.setTextVisible(True)
        self.table.setCellWidget(row, 2, bar)
        self._render(d.id)
        if start and d.status == QUEUED:
            self._schedule()
        self._save_timer.start()

    def _render(self, did: str):
        d, row = self.downloads[did], self.rows[did]
        name = d.filename if d.kind == "file" else (os.path.basename(d.final_path) if d.final_path else d.filename + (" [MP3]" if d.audio_only else " [video]"))
        if d.picked and not d.final_path:
            name += f"  ·  format {d.picked}"
        self.table.item(row, 0).setText(name)
        self.table.item(row, 0).setToolTip(f"{d.url}\n{d.folder}" + (f"\n\nError: {d.error}" if d.error else ""))
        self.table.item(row, 1).setText(human_size(d.size))
        bar: QProgressBar = self.table.cellWidget(row, 2)
        bar.setValue(int(d.percent * 10)); bar.setFormat(f"{d.percent:.1f}%")
        self.table.item(row, 3).setText(d.speed)
        self.table.item(row, 4).setText(d.eta)
        st = self.table.item(row, 5)
        st.setText(d.status)
        st.setToolTip(d.error)

    def _schedule(self):
        active = sum(1 for d in self.downloads.values() if d.status == RUNNING)
        for d in sorted(self.downloads.values(), key=lambda x: x.added):
            if active >= MAX_ACTIVE:
                break
            if d.status == QUEUED and d.id not in self.runners:
                r = Runner(d, self)
                r.progress.connect(self._render)
                r.finished.connect(self._finished)
                self.runners[d.id] = r
                r.start()
                active += 1
                self._render(d.id)
        self._update_actions()

    def _finished(self, did: str):
        self.runners.pop(did, None)
        d = self.downloads.get(did)
        if d:
            self._render(did)
            if d.status == DONE:
                notify("Download complete", os.path.basename(d.final_path) or d.filename)
            elif d.status == FAILED:
                notify("Download failed", f"{d.filename}\n{d.error[:150]}")
        self._save_timer.start()
        self._schedule()

    # ---------------------------------------------------- actions
    def _selected(self) -> list[Download]:
        ids = {self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectionModel().selectedRows()}
        return [self.downloads[i] for i in ids if i in self.downloads]

    def _update_actions(self):
        sel = self._selected()
        self.a_resume.setEnabled(any(d.status in (PAUSED, FAILED) for d in sel))
        self.a_pause.setEnabled(any(d.status in (RUNNING, QUEUED) for d in sel))
        self.a_remove.setEnabled(bool(sel))
        self.a_open.setEnabled(any(d.status == DONE for d in sel))
        self.a_folder.setEnabled(bool(sel))

    def resume(self):
        for d in self._selected():
            if d.status in (PAUSED, FAILED):
                d.status, d.error = QUEUED, ""
                self._render(d.id)
        self._schedule()

    def pause(self):
        for d in self._selected():
            if d.id in self.runners:
                self.runners[d.id].stop()
            elif d.status == QUEUED:
                d.status = PAUSED
                self._render(d.id)
        self._update_actions(); self._save_timer.start()

    def remove(self):
        sel = self._selected()
        if not sel:
            return
        box = QMessageBox(QMessageBox.Question, "Remove", f"Remove {len(sel)} item(s) from the list?", parent=self)
        only = box.addButton("Remove from list", QMessageBox.AcceptRole)
        also = box.addButton("Remove + delete files", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in (only, also):
            return
        for d in sel:
            if d.id in self.runners:
                self.runners[d.id].stop()
                self.runners.pop(d.id, None)
            if box.clickedButton() is also:
                self._delete_files(d)
            self.downloads.pop(d.id, None)
        self._rebuild()
        self._schedule(); self.save()

    def _delete_files(self, d: Download):
        paths = [d.final_path] if d.final_path else []
        if d.kind == "file":
            p = os.path.join(d.folder, d.filename)
            paths += [p, p + ".aria2"]
        else:
            stem = os.path.join(d.folder, d.filename)
            folder = Path(d.folder)
            if folder.exists():
                paths += [str(f) for f in folder.glob(glob_escape(d.filename) + ".*")]
        for p in set(paths):
            try:
                if p and os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass

    def _rebuild(self):
        self.table.setRowCount(0); self.rows.clear()
        items = sorted(self.downloads.values(), key=lambda x: x.added)
        self.downloads = {}
        for d in items:
            self.add(d, start=False)

    def open_file(self):
        for d in self._selected():
            if d.status == DONE:
                path = d.final_path or os.path.join(d.folder, d.filename)
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
                return

    def open_folder(self):
        for d in self._selected():
            QDesktopServices.openUrl(QUrl.fromLocalFile(d.folder))
            return

    def _menu(self, pos):
        self._update_actions()
        m = QMenu(self)
        for a in (self.a_resume, self.a_pause, self.a_open, self.a_folder):
            m.addAction(a)
        copy = m.addAction("Copy link")
        m.addSeparator(); m.addAction(self.a_remove)
        if m.exec(self.table.viewport().mapToGlobal(pos)) is copy:
            sel = self._selected()
            if sel:
                QApplication.clipboard().setText(sel[0].url)

    def _status(self):
        running = [d for d in self.downloads.values() if d.status == RUNNING]
        if running:
            self.statusBar().showMessage(f"{len(running)} downloading · "
                                         f"{sum(1 for d in self.downloads.values() if d.status == QUEUED)} queued")
        self._update_actions()

    # ---------------------------------------------------- save / load
    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps([d.to_dict() for d in self.downloads.values()], indent=1, ensure_ascii=False))
        tmp.replace(STORE)

    def _load(self):
        if not STORE.exists():
            return
        try:
            data = json.loads(STORE.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for raw in data:
            d = Download.from_dict(raw)
            if d.status in (RUNNING, QUEUED):
                d.status, d.speed, d.eta = PAUSED, "", ""   # never auto-start after reopening
            self.add(d, start=False)

    def closeEvent(self, e):
        running = [r for r in self.runners.values()]
        if running:
            ans = QMessageBox.question(self, "Quit", f"{len(running)} download(s) still running. Pause and quit?\n"
                                                     "(You can resume them when you open Sedut again.)")
            if ans != QMessageBox.Yes:
                e.ignore(); return
            for r in running:
                r.stop()
        self.save()
        e.accept()


def glob_escape(s: str) -> str:
    import glob
    return glob.escape(s)
