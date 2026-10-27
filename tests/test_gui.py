"""Headless smoke test for the GUI: drive the real stack offscreen through to
a completed, byte-verified download. Skipped if PySide6 is unavailable."""

from __future__ import annotations

import hashlib
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dlm.gui.app import MainWindow  # noqa: E402

PAYLOAD = bytes((i * 53 + 1) % 256 for i in range(500_000))


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump_until(app, predicate, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_gui_downloads_through_queue(qapp, server, tmp_path):
    url = server.configure(PAYLOAD)
    win = MainWindow()
    dest = tmp_path / "out.bin"
    tid = win.add_download(url, dest=dest, segments=4)

    done = _pump_until(qapp, lambda: win.tasks[tid].status == "done")
    assert done, f"status stuck at {win.tasks[tid].status!r}"
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)
    # progress fields were populated from snapshots
    assert win.tasks[tid].total == len(PAYLOAD)
    assert win.tasks[tid].downloaded == len(PAYLOAD)


def test_gui_queue_respects_max_concurrent(qapp, server, tmp_path):
    url = server.configure(PAYLOAD)
    win = MainWindow()
    win.concurrency.setValue(1)

    ids = [win.add_download(url, dest=tmp_path / f"out{i}.bin", segments=2)
           for i in range(3)]

    # With a limit of 1, at most one task runs at any instant.
    from dlm.queue import TaskStatus
    max_seen = [0]

    def check():
        running = sum(1 for t in ids
                      if win.queue.status(t) is TaskStatus.RUNNING)
        max_seen[0] = max(max_seen[0], running)
        return all(win.tasks[t].status == "done" for t in ids)

    assert _pump_until(qapp, check, timeout=40), "not all downloads finished"
    assert max_seen[0] == 1
    for i, t in enumerate(ids):
        assert _sha((tmp_path / f"out{i}.bin").read_bytes()) == _sha(PAYLOAD)
