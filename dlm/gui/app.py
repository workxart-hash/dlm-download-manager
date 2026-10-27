"""Main window: download list, per-segment detail, queue, speed limit."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QMainWindow, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..engine import Downloader
from ..queue import DownloadQueue
from ..ratelimit import RateLimiter
from ..state import default_state_path
from .worker import DownloadWorker

COLS = ["Name", "Size", "Progress", "Speed", "ETA", "Status"]


def human(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024


@dataclass
class Task:
    tid: int
    url: str
    dest: Path
    segments: int
    name: str
    status: str = "queued"
    total: int = 0
    downloaded: int = 0
    segs: List[tuple] = field(default_factory=list)
    speed: float = 0.0
    worker: Optional[DownloadWorker] = None
    _last_t: float = 0.0
    _last_bytes: int = 0


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("dlm — download manager")
        self.resize(900, 560)

        self.rl = RateLimiter(None)                  # shared global speed limit
        self.queue = DownloadQueue(max_concurrent=3)
        self.tasks: Dict[int, Task] = {}
        self._next_id = 0

        self._build_ui()

    # -- UI ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # toolbar
        bar = QHBoxLayout()
        add_btn = QPushButton("Add URL…")
        add_btn.clicked.connect(self._add_dialog)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self._pause_selected)
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.clicked.connect(self._resume_selected)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_selected)
        for b in (add_btn, self.pause_btn, self.resume_btn, self.cancel_btn):
            bar.addWidget(b)
        bar.addStretch(1)

        bar.addWidget(QLabel("Max concurrent:"))
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 32)
        self.concurrency.setValue(3)
        self.concurrency.valueChanged.connect(self._on_concurrency)
        bar.addWidget(self.concurrency)

        bar.addWidget(QLabel("Limit (KB/s, 0=∞):"))
        self.limit = QSpinBox()
        self.limit.setRange(0, 1_000_000)
        self.limit.setValue(0)
        self.limit.valueChanged.connect(self._on_limit)
        bar.addWidget(self.limit)
        root.addLayout(bar)

        # table
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._rebuild_segments)
        root.addWidget(self.table, 3)

        # per-segment detail
        self.seg_box = QGroupBox("Segments")
        box_layout = QVBoxLayout(self.seg_box)
        self.seg_area = QScrollArea()
        self.seg_area.setWidgetResizable(True)
        self.seg_host = QWidget()
        self.seg_layout = QVBoxLayout(self.seg_host)
        self.seg_layout.addStretch(1)
        self.seg_area.setWidget(self.seg_host)
        box_layout.addWidget(self.seg_area)
        self.seg_bars: List[QProgressBar] = []
        root.addWidget(self.seg_box, 2)

    # -- public API (also used by tests) ------------------------------------

    def add_download(self, url: str, dest=None, segments: int = 8) -> int:
        if dest is None:
            dest = Path.cwd() / Downloader._name_from_url(url)
        tid = self._next_id
        self._next_id += 1
        dest = Path(dest)
        self.tasks[tid] = Task(tid=tid, url=url, dest=dest, segments=segments,
                               name=dest.name)
        self._append_row(tid)
        self.queue.add(tid)
        self._pump()
        return tid

    # -- queue driving -------------------------------------------------------

    def _pump(self):
        for tid in self.queue.pump():
            self._start(tid)

    def _start(self, tid: int):
        task = self.tasks[tid]
        sp = default_state_path(task.dest)
        if sp.exists():
            d = Downloader.from_state_file(str(sp), rate_limiter=self.rl)
        else:
            d = Downloader(task.url, dest=str(task.dest),
                           segments=task.segments, rate_limiter=self.rl)
        w = DownloadWorker(d)
        w.progress.connect(lambda snap, t=tid: self._on_progress(t, snap))
        w.finished_ok.connect(lambda p, t=tid: self._on_finished(t, p))
        w.failed.connect(lambda m, t=tid: self._on_failed(t, m))
        w.paused.connect(lambda t=tid: self._on_paused(t))
        w.cancelled.connect(lambda t=tid: self._on_cancelled(t))
        task.worker = w
        task.status = "running"
        task._last_t = 0.0
        task._last_bytes = 0
        self._refresh_row(tid)
        w.start()

    # -- signal handlers (GUI thread) ---------------------------------------

    def _on_progress(self, tid: int, snap):
        task = self.tasks.get(tid)
        if not task:
            return
        now = time.monotonic()
        if task._last_t:
            dt = now - task._last_t
            if dt > 0:
                task.speed = (snap.downloaded - task._last_bytes) / dt
        task._last_t = now
        task._last_bytes = snap.downloaded
        task.total = snap.total
        task.downloaded = snap.downloaded
        task.segs = snap.segments
        self._refresh_row(tid)
        if self._selected_tid() == tid:
            self._update_segments(task)

    def _on_finished(self, tid, path):
        self.tasks[tid].status = "done"
        self.tasks[tid].speed = 0.0
        self.queue.on_finished(tid)
        self._refresh_row(tid)
        self._pump()

    def _on_failed(self, tid, msg):
        self.tasks[tid].status = f"failed: {msg[:40]}"
        self.tasks[tid].speed = 0.0
        self.queue.on_failed(tid)
        self._refresh_row(tid)
        self._pump()

    def _on_paused(self, tid):
        self.tasks[tid].status = "paused"
        self.tasks[tid].speed = 0.0
        self.queue.on_paused(tid)
        self._refresh_row(tid)
        self._pump()

    def _on_cancelled(self, tid):
        self.tasks[tid].status = "cancelled"
        self.tasks[tid].speed = 0.0
        self.queue.cancel(tid)
        self._refresh_row(tid)
        self._pump()

    # -- toolbar actions -----------------------------------------------------

    def _add_dialog(self):
        url, ok = QInputDialog.getText(self, "Add download", "URL:")
        if not ok or not url.strip():
            return
        url = url.strip()
        suggested = Downloader._name_from_url(url)
        dest, ok = QFileDialog.getSaveFileName(self, "Save as", suggested)
        if not ok or not dest:
            return
        self.add_download(url, dest)

    def _pause_selected(self):
        tid = self._selected_tid()
        if tid is None:
            return
        task = self.tasks[tid]
        if task.status == "running" and task.worker:
            task.worker.pause()

    def _resume_selected(self):
        tid = self._selected_tid()
        if tid is None:
            return
        task = self.tasks[tid]
        if task.status in ("paused",) or task.status.startswith("failed"):
            self.queue.resume(tid)
            task.status = "queued"
            self._refresh_row(tid)
            self._pump()

    def _cancel_selected(self):
        tid = self._selected_tid()
        if tid is None:
            return
        task = self.tasks[tid]
        if task.status == "running" and task.worker:
            task.worker.cancel()
        elif task.status in ("queued", "paused"):
            self.queue.cancel(tid)
            task.status = "cancelled"
            self._refresh_row(tid)
            self._pump()

    def _on_concurrency(self, n):
        self.queue.set_max_concurrent(n)
        self._pump()

    def _on_limit(self, kbps):
        self.rl.set_rate(kbps * 1024 if kbps > 0 else None)

    # -- table / segment rendering ------------------------------------------

    def _append_row(self, tid):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for c in range(len(COLS)):
            self.table.setItem(row, c, QTableWidgetItem(""))
        self.table.item(row, 0).setData(Qt.UserRole, tid)
        self._refresh_row(tid)

    def _row_of(self, tid):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == tid:
                return row
        return None

    def _selected_tid(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _refresh_row(self, tid):
        row = self._row_of(tid)
        if row is None:
            return
        t = self.tasks[tid]
        pct = (t.downloaded / t.total * 100) if t.total else 0.0
        eta = ((t.total - t.downloaded) / t.speed) if (t.total and t.speed > 0) else 0.0
        vals = [
            t.name,
            human(t.total) if t.total else "?",
            f"{pct:.1f}%",
            f"{human(t.speed)}/s" if t.speed > 0 else "—",
            f"{eta:.0f}s" if eta > 0 else "—",
            t.status,
        ]
        for c, v in enumerate(vals):
            self.table.item(row, c).setText(v)

    def _rebuild_segments(self):
        tid = self._selected_tid()
        if tid is None:
            return
        self._update_segments(self.tasks[tid], force=True)

    def _update_segments(self, task: Task, force: bool = False):
        if force or len(self.seg_bars) != len(task.segs):
            # rebuild bars (segment count can grow with dynamic segmentation)
            while self.seg_layout.count() > 1:  # keep the trailing stretch
                item = self.seg_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.seg_bars = []
            for _ in task.segs:
                bar = QProgressBar()
                bar.setRange(0, 100)
                self.seg_bars.insert(len(self.seg_bars), bar)
                self.seg_layout.insertWidget(self.seg_layout.count() - 1, bar)
        for bar, (_start, size, done) in zip(self.seg_bars, task.segs):
            bar.setValue(int(done / size * 100) if size else 100)


def run(argv=None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", ""))
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
