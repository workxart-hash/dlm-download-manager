"""Qt worker: runs one download on a background thread and reports via signals.

The engine itself spins its own segment threads; this ``QThread`` just drives
one ``Downloader.download()`` call and translates its outcome and progress into
Qt signals delivered (queued) to the GUI thread.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal

from ..engine import Cancelled, DownloadError, Downloader, Paused


class DownloadWorker(QThread):
    progress = Signal(object)    # engine.Snapshot
    finished_ok = Signal(str)    # output path
    failed = Signal(str)         # error message
    paused = Signal()
    cancelled = Signal()

    def __init__(self, downloader: Downloader, poll_ms: int = 200, parent=None):
        super().__init__(parent)
        self.d = downloader
        self._interval = poll_ms / 1000.0
        self._lock = threading.Lock()
        self._last_emit = 0.0
        self.d.on_progress = self._on_progress

    def _on_progress(self, done: int, total: int) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_emit < self._interval and done < total:
                return
            self._last_emit = now
        self.progress.emit(self.d.snapshot())

    def run(self) -> None:
        try:
            path = self.d.download()
        except Paused:
            self.progress.emit(self.d.snapshot())
            self.paused.emit()
            return
        except Cancelled:
            self.cancelled.emit()
            return
        except DownloadError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:  # noqa: BLE001 - surface anything else to the UI
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.progress.emit(self.d.snapshot())
        self.finished_ok.emit(path)

    # Called from the GUI thread.
    def pause(self) -> None:
        self.d.pause()

    def cancel(self) -> None:
        self.d.cancel()
