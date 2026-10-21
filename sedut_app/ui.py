"""ui.py — tetingkap utama Sedut (PySide6)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QToolBar, QVBoxLayout, QWidget,
)

from .engine import DONE, FAILED, PAUSED, QUEUED, RUNNING, Download, Runner
from .probe import ProbeResult, human_size, looks_like_url, probe, safe_filename

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sedut"
STORE = DATA_DIR / "downloads.json"
SETTINGS = DATA_DIR / "settings.json"
BASE_DIR = Path.home() / "Downloads" / "Sedut"
MAX_ACTIVE = 3

CATEGORIES = {
    "Video": {"mp4", "mkv", "webm", "mov", "avi", "m4v", "flv", "ts", "3gp"},
    "Muzik": {"mp3", "m4a", "flac", "wav", "ogg", "opus", "aac"},
    "Dokumen": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "epub"},
    "Program": {"deb", "rpm", "appimage", "exe", "msi", "pkg", "zst", "iso", "img", "run", "sh"},
    "Mampatan": {"zip", "rar", "7z", "tar", "gz", "xz", "bz2", "tgz"},
    "Gambar": {"jpg", "jpeg", "png", "gif", "webp", "svg"},
}


def category_dir(filename: str, kind: str, audio_only: bool = False) -> str:
    if kind == "media":
        return str(BASE_DIR / ("Muzik" if audio_only else "Video"))
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return str(BASE_DIR / cat)
    return str(BASE_DIR / "Lain")


def notify(title: str, body: str):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Sedut", "-i", "folder-download", title, body])


# ------------------------------------------------------------- kesan (thread)
class _ProbeSignals(QObject):
    done = Signal(object)


class ProbeTask(QRunnable):
    def __init__(self, url: str, cookies: str | None):
        super().__init__()
        self.url, self.cookies = url, cookies
        self.signals = _ProbeSignals()

    def run(self):
        try:
            r = probe(self.url, self.cookies)
        except Exception as e:  # jangan biar thread mati senyap
            r = ProbeResult(kind="none", url=self.url, error=str(e))
        self.signals.done.emit(r)


# ------------------------------------------------------------- dialog hasil kesan
class DetectDialog(QDialog):
    def __init__(self, r: ProbeResult, cookies: str | None, parent=None):
        super().__init__(parent)
        self.r, self.cookies = r, cookies
        self.setWindowTitle("Dikesan — Sedut")
        self.setMinimumWidth(560)
        form = QFormLayout()

        kind = "Video / media" + (f" ({r.extractor})" if r.extractor else "") if r.kind == "media" else (r.mime or "fail")
        form.addRow("Jenis:", QLabel(kind))
        title = QLabel(r.title); title.setWordWrap(True)
        form.addRow("Tajuk:", title)
        if r.duration:
            m, s = divmod(int(r.duration), 60)
            form.addRow("Tempoh:", QLabel(f"{m}:{s:02d}"))

        self.quality = None
        self.size_lbl = QLabel(human_size(r.size) + ("" if r.kind == "media" or r.resumable else "  (pelayan tak sokong sambung)"))
        if r.kind == "media":
            self.quality = QComboBox()
            for c in r.choices:
                self.quality.addItem(c.label + (f"  ~{human_size(c.size)}" if c.size else ""), c)
            self.quality.currentIndexChanged.connect(self._quality_changed)
            form.addRow("Kualiti:", self.quality)
        form.addRow("Saiz:", self.size_lbl)

        self.name = QLineEdit(r.filename)
        form.addRow("Nama fail:", self.name)

        folder_row = QHBoxLayout()
        self.folder = QLineEdit()
        browse = QPushButton("Pilih…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1); folder_row.addWidget(browse)
        form.addRow("Simpan ke:", folder_row)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Muat turun", QDialogButtonBox.AcceptRole)
        ok.setDefault(True)
        buttons.addButton("Batal", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form); lay.addWidget(buttons)
        self._quality_changed()

    def _choice(self):
        return self.quality.currentData() if self.quality else None

    def _quality_changed(self, *_):
        c = self._choice()
        if c is not None:
            self.size_lbl.setText(f"~{human_size(c.size)}" if c.size else "tidak diketahui (dikira semasa muat turun)")
        self.folder.setText(category_dir(self.name.text(), self.r.kind, bool(c and c.audio_only)))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Pilih folder", self.folder.text())
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
        )


# ------------------------------------------------------------- tetingkap utama
COLS = ["Nama", "Saiz", "Kemajuan", "Kelajuan", "Baki masa", "Status"]


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

        # --- bar URL
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste link di sini (Ctrl+V) — Sedut akan kesan sendiri")
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.detect)
        self.url.textChanged.connect(lambda _: self._debounce.start())
        self._debounce = QTimer(self, singleShot=True, interval=500, timeout=self._auto_detect)
        self._last_probed = ""
        self.detect_btn = QPushButton("Kesan")
        self.detect_btn.clicked.connect(self.detect)
        self.cookies = QCheckBox("Guna cookies Chrome")
        self.cookies.setToolTip("Untuk YouTube/Facebook/Vimeo yang minta log masuk atau semakan 'bukan bot'.\n"
                                "yt-dlp baca cookies dari profil Google Chrome anda.")
        top = QHBoxLayout()
        top.addWidget(self.url, 1); top.addWidget(self.detect_btn); top.addWidget(self.cookies)

        # --- jadual
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
        tb = QToolBar("Tindakan"); tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.a_resume = QAction(QIcon.fromTheme("media-playback-start"), "Sambung", self, triggered=self.resume)
        self.a_pause = QAction(QIcon.fromTheme("media-playback-pause"), "Jeda", self, triggered=self.pause)
        self.a_remove = QAction(QIcon.fromTheme("edit-delete"), "Buang", self, triggered=self.remove)
        self.a_remove.setShortcut(QKeySequence.Delete)
        self.a_open = QAction(QIcon.fromTheme("document-open"), "Buka fail", self, triggered=self.open_file)
        self.a_folder = QAction(QIcon.fromTheme("folder-open"), "Buka folder", self, triggered=self.open_folder)
        self.a_retry = QAction(QIcon.fromTheme("view-refresh"), "Cuba semula", self, triggered=self.resume)
        for a in (self.a_resume, self.a_pause, self.a_remove, self.a_open, self.a_folder):
            tb.addAction(a)

        self._save_timer = QTimer(self, singleShot=True, interval=1500, timeout=self.save)
        self._load()
        self._update_actions()
        self.statusBar().showMessage("Sedia. Paste link untuk mula.")
        self._st = QTimer(self, interval=1000, timeout=self._status); self._st.start()

    # ---------------------------------------------------- kesan
    def _auto_detect(self):
        t = self.url.text().strip()
        if looks_like_url(t) and t != self._last_probed:
            self.detect()

    def detect(self):
        t = self.url.text().strip()
        if not looks_like_url(t):
            self.statusBar().showMessage("Itu bukan link http/https/ftp yang sah.", 4000)
            return
        if self._probing:
            return
        self._probing, self._last_probed = True, t
        self.detect_btn.setEnabled(False); self.detect_btn.setText("Mengesan…")
        self.statusBar().showMessage(f"Mengesan {t} …")
        task = ProbeTask(t, "chrome" if self.cookies.isChecked() else None)
        task.signals.done.connect(self._probed)
        self.pool.start(task)

    def _probed(self, r: ProbeResult):
        self._probing = False
        self.detect_btn.setEnabled(True); self.detect_btn.setText("Kesan")
        if r.kind == "none":
            self.statusBar().showMessage("Tiada fail/video dikesan.", 5000)
            msg = r.error or "Tiada fail atau video dikesan pada link ini."
            if any(k in msg.lower() for k in ("sign in", "log", "cookies", "bot", "forbidden", "403")) and not self.cookies.isChecked():
                msg += "\n\nCuba tanda 'Guna cookies Chrome' dan kesan semula."
            QMessageBox.warning(self, "Tidak dikesan", msg[:1200])
            return
        self.statusBar().showMessage(f"Dikesan: {r.title}", 4000)
        dlg = DetectDialog(r, "chrome" if self.cookies.isChecked() else None, self)
        if dlg.exec() == QDialog.Accepted:
            self.add(dlg.download())
            self.url.clear(); self._last_probed = ""

    # ---------------------------------------------------- senarai
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
        self.table.item(row, 0).setText(name)
        self.table.item(row, 0).setToolTip(f"{d.url}\n{d.folder}" + (f"\n\nRalat: {d.error}" if d.error else ""))
        self.table.item(row, 1).setText(human_size(d.size))
        bar: QProgressBar = self.table.cellWidget(row, 2)
        bar.setValue(int(d.percent * 10)); bar.setFormat(f"{d.percent:.1f}%")
        self.table.item(row, 3).setText(d.speed)
        self.table.item(row, 4).setText(d.eta)
        st = self.table.item(row, 5)
        st.setText(d.status if d.status != FAILED else f"Gagal")
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
                notify("Muat turun siap", os.path.basename(d.final_path) or d.filename)
            elif d.status == FAILED:
                notify("Muat turun gagal", f"{d.filename}\n{d.error[:150]}")
        self._save_timer.start()
        self._schedule()

    # ---------------------------------------------------- tindakan
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
        box = QMessageBox(QMessageBox.Question, "Buang", f"Buang {len(sel)} item dari senarai?", parent=self)
        only = box.addButton("Buang dari senarai", QMessageBox.AcceptRole)
        also = box.addButton("Buang + padam fail", QMessageBox.DestructiveRole)
        box.addButton("Batal", QMessageBox.RejectRole)
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
        copy = m.addAction("Salin link")
        m.addSeparator(); m.addAction(self.a_remove)
        if m.exec(self.table.viewport().mapToGlobal(pos)) is copy:
            sel = self._selected()
            if sel:
                QApplication.clipboard().setText(sel[0].url)

    def _status(self):
        running = [d for d in self.downloads.values() if d.status == RUNNING]
        if running:
            self.statusBar().showMessage(f"{len(running)} sedang dimuat turun · "
                                         f"{sum(1 for d in self.downloads.values() if d.status == QUEUED)} menunggu")
        self._update_actions()

    # ---------------------------------------------------- simpan / muat
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
                d.status, d.speed, d.eta = PAUSED, "", ""   # jangan auto-mula selepas buka semula
            self.add(d, start=False)

    def closeEvent(self, e):
        running = [r for r in self.runners.values()]
        if running:
            ans = QMessageBox.question(self, "Keluar", f"{len(running)} muat turun masih berjalan. Jeda dan keluar?\n"
                                                       "(Boleh disambung bila buka Sedut semula.)")
            if ans != QMessageBox.Yes:
                e.ignore(); return
            for r in running:
                r.stop()
        self.save()
        e.accept()


def glob_escape(s: str) -> str:
    import glob
    return glob.escape(s)
