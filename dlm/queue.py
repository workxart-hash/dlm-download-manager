"""Download queue concurrency policy.

Pure state machine, independent of Qt: it decides which queued downloads may
start given a concurrency limit. The GUI calls :meth:`pump` after any state
change and actually starts whatever ids it returns.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Dict, Hashable, List


class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadQueue:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max(1, max_concurrent)
        self._order: List[Hashable] = []
        self._status: Dict[Hashable, TaskStatus] = {}
        self._lock = threading.Lock()

    def add(self, task_id: Hashable) -> None:
        with self._lock:
            if task_id not in self._status:
                self._order.append(task_id)
            self._status[task_id] = TaskStatus.QUEUED

    def pump(self) -> List[Hashable]:
        """Promote QUEUED tasks to RUNNING up to the concurrency limit, FIFO."""
        started: List[Hashable] = []
        with self._lock:
            running = sum(1 for s in self._status.values() if s is TaskStatus.RUNNING)
            for tid in self._order:
                if running >= self.max_concurrent:
                    break
                if self._status.get(tid) is TaskStatus.QUEUED:
                    self._status[tid] = TaskStatus.RUNNING
                    started.append(tid)
                    running += 1
        return started

    def on_finished(self, task_id: Hashable) -> None:
        self._set(task_id, TaskStatus.DONE)

    def on_failed(self, task_id: Hashable) -> None:
        self._set(task_id, TaskStatus.FAILED)

    def on_paused(self, task_id: Hashable) -> None:
        self._set(task_id, TaskStatus.PAUSED)

    def resume(self, task_id: Hashable) -> None:
        self._set(task_id, TaskStatus.QUEUED)

    def cancel(self, task_id: Hashable) -> None:
        self._set(task_id, TaskStatus.CANCELLED)

    def set_max_concurrent(self, n: int) -> None:
        with self._lock:
            self.max_concurrent = max(1, n)

    def running(self) -> List[Hashable]:
        with self._lock:
            return [t for t in self._order if self._status.get(t) is TaskStatus.RUNNING]

    def status(self, task_id: Hashable) -> TaskStatus:
        with self._lock:
            return self._status[task_id]

    def _set(self, task_id: Hashable, status: TaskStatus) -> None:
        with self._lock:
            self._status[task_id] = status
