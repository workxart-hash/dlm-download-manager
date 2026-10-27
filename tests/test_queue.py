"""Pure unit tests for the download queue concurrency policy (no Qt)."""

from __future__ import annotations

from dlm.queue import DownloadQueue, TaskStatus


def test_pump_starts_up_to_max_concurrent():
    q = DownloadQueue(max_concurrent=2)
    for t in ["a", "b", "c", "d"]:
        q.add(t)
    started = q.pump()
    assert started == ["a", "b"]          # FIFO
    assert set(q.running()) == {"a", "b"}
    assert q.pump() == []                  # no free slots


def test_finishing_a_task_frees_a_slot():
    q = DownloadQueue(max_concurrent=1)
    q.add("a")
    q.add("b")
    assert q.pump() == ["a"]
    q.on_finished("a")
    assert q.status("a") is TaskStatus.DONE
    assert q.pump() == ["b"]


def test_pause_frees_slot_and_resume_requeues():
    q = DownloadQueue(max_concurrent=1)
    q.add("a")
    q.add("b")
    q.pump()                               # a running
    q.on_paused("a")
    assert q.status("a") is TaskStatus.PAUSED
    assert q.pump() == ["b"]               # paused task freed the slot
    q.resume("a")                          # a is eligible again (queued)
    assert q.status("a") is TaskStatus.QUEUED
    q.on_finished("b")
    assert q.pump() == ["a"]               # a runs once a slot opens


def test_cancel_removes_from_running_and_queue():
    q = DownloadQueue(max_concurrent=1)
    q.add("a")
    q.add("b")
    q.pump()
    q.cancel("a")
    assert q.status("a") is TaskStatus.CANCELLED
    assert q.pump() == ["b"]
    q.cancel("b")  # cancel while running
    assert q.status("b") is TaskStatus.CANCELLED
    assert q.pump() == []


def test_raising_max_concurrent_starts_more():
    q = DownloadQueue(max_concurrent=1)
    for t in ["a", "b", "c"]:
        q.add(t)
    assert q.pump() == ["a"]
    q.set_max_concurrent(3)
    assert q.pump() == ["b", "c"]


def test_failed_task_frees_slot():
    q = DownloadQueue(max_concurrent=1)
    q.add("a")
    q.add("b")
    q.pump()
    q.on_failed("a")
    assert q.status("a") is TaskStatus.FAILED
    assert q.pump() == ["b"]
