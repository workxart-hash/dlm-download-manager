"""Integration tests for engine control: pause, resume, cancel, rate limit,
and the per-segment snapshot used by the GUI."""

from __future__ import annotations

import hashlib
import threading
import time

import pytest

from dlm.engine import Cancelled, DownloadError, Downloader, Paused
from dlm.ratelimit import RateLimiter
from dlm.state import default_state_path

PAYLOAD = bytes((i * 97 + 11) % 256 for i in range(1_500_000))  # ~1.5 MB


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Runner:
    def __init__(self, d: Downloader):
        self.d = d
        self.exc = None
        self.path = None
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            self.path = self.d.download()
        except BaseException as e:  # noqa: BLE001 - captured for assertions
            self.exc = e

    def start(self):
        self.t.start()

    def join(self, timeout=15):
        self.t.join(timeout)
        assert not self.t.is_alive(), "download thread did not stop"


def _wait_until_running(d: Downloader, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = d.snapshot()
        if s.total and 0 < s.downloaded < s.total * 0.7:
            return
        time.sleep(0.01)
    raise AssertionError("download never reached a pausable mid-point")


def test_pause_preserves_state_then_resume_completes(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    d = Downloader(url, dest=dest, segments=4, retry_backoff=0, dynamic=False,
                   rate_limiter=RateLimiter(300_000))
    r = _Runner(d)
    r.start()
    _wait_until_running(d)
    d.pause()
    r.join()

    assert isinstance(r.exc, Paused)
    assert default_state_path(dest).exists()
    assert 0 < d.snapshot().downloaded < len(PAYLOAD)

    # Resume (unlimited) via the state file and finish the job.
    Downloader.from_state_file(default_state_path(dest), retry_backoff=0).download()
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)


def test_cancel_stops_and_cleans_up(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    d = Downloader(url, dest=dest, segments=4, retry_backoff=0, dynamic=False,
                   rate_limiter=RateLimiter(300_000))
    r = _Runner(d)
    r.start()
    _wait_until_running(d)
    d.cancel()
    r.join()

    assert isinstance(r.exc, Cancelled)
    assert not dest.exists()
    assert not default_state_path(dest).exists()
    assert list(tmp_path.glob("out.bin.dlmpart_*")) == []


def test_rate_limit_slows_download(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    # 1.5 MB at 500 KB/s with a 1 s burst => ~2 s. Assert a generous lower bound.
    start = time.monotonic()
    Downloader(url, dest=dest, segments=4, retry_backoff=0, dynamic=False,
               rate_limiter=RateLimiter(500_000)).download()
    elapsed = time.monotonic() - start
    assert elapsed >= 1.2
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)


def test_snapshot_reports_all_segments(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    d = Downloader(url, dest=dest, segments=4, retry_backoff=0, dynamic=False)
    d.download()
    snap = d.snapshot()
    assert len(snap.segments) == 4
    assert sum(size for _start, size, _done in snap.segments) == len(PAYLOAD)
    assert snap.downloaded == len(PAYLOAD)
    assert all(done == size for _start, size, done in snap.segments)
