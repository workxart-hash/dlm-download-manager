"""Multi-segment download engine with resume, retry, fallback and dynamic
segmentation.

Concurrency model
-----------------
Each segment is a mutable ``_Seg`` (start, end, downloaded) in a shared table
guarded by one lock. One worker thread is started per initial segment. A worker
downloads its segment to completion, then calls :meth:`_acquire_more`: if
dynamic segmentation is enabled and the table isn't at the cap, it finds the
in-progress segment with the most remaining bytes, splits its *remaining* range
in two (shrinking the victim's ``end``), and takes the second half. Writes are
capped to the live ``end`` so a shrunk victim never writes into the new
segment's range — no overlap, no gaps.

Resume is implicit: a segment's progress is the size of its part file
(``<dest>.dlmpart_<start>``). A JSON sidecar records the current segment table
and server metadata so a fresh process can continue, and so stale partial data
is discarded if the remote file changed.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .ratelimit import RateLimiter
from .segmentation import MAX_SEGMENTS, MIN_SPLIT_BYTES, plan_segments, split_point
from .state import DownloadState, default_state_path, is_resumable


class DownloadError(Exception):
    """Raised when a download cannot be completed."""


class Paused(Exception):
    """Raised by download() when pause() was requested; state is preserved."""


class Cancelled(Exception):
    """Raised by download() when cancel() was requested; scratch is removed."""


class _Retryable(Exception):
    """Internal: a mid-stream failure worth retrying."""


@dataclass
class Snapshot:
    total: int
    downloaded: int
    segments: list  # list of (start, size, downloaded)


@dataclass
class RemoteFile:
    size: int
    accept_ranges: bool
    etag: Optional[str] = None
    filename: Optional[str] = None


@dataclass
class _Seg:
    start: int
    end: int           # inclusive; shrinks when this segment is split
    downloaded: int    # live byte count; guarded by the engine lock
    active: bool = False


class Downloader:
    def __init__(
        self,
        url: str,
        dest: Optional[os.PathLike | str] = None,
        *,
        segments: int = 8,
        max_retries: int = 5,
        retry_backoff: float = 0.5,
        chunk_size: int = 64 * 1024,
        timeout: float = 30.0,
        dynamic: bool = True,
        min_split: int = MIN_SPLIT_BYTES,
        expected_sha256: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None,
        session: Optional[requests.Session] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ):
        self.url = url
        self.segments = max(1, segments)
        self.max_retries = max(0, max_retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.dynamic = dynamic
        self.min_split = min_split
        self.expected_sha256 = expected_sha256.lower() if expected_sha256 else None
        self.on_progress = on_progress
        self._rate = rate_limiter or RateLimiter(None)

        self.dest = Path(dest) if dest is not None else Path(self._name_from_url(url))

        self._session = session or self._build_session()
        self._owns_session = session is None

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pause_requested = threading.Event()
        self._cancel_requested = threading.Event()
        self._segs: List[_Seg] = []
        self._errors: List[BaseException] = []
        self._total = 0
        self._total_done = 0
        self._accept_ranges = False
        self._remote: Optional[RemoteFile] = None
        self._resume: Optional[DownloadState] = None

        self.splits = 0  # how many dynamic splits occurred (observable for tests)

    # -- construction / resume ----------------------------------------------

    @classmethod
    def from_state_file(cls, state_path, **overrides) -> "Downloader":
        st = DownloadState.load(state_path)
        d = cls(st.url, dest=st.dest, segments=len(st.segments),
                expected_sha256=st.sha256, **overrides)
        d._resume = st
        return d

    # -- control -------------------------------------------------------------

    def pause(self) -> None:
        """Cooperatively stop all workers, keeping partial data for resume."""
        self._pause_requested.set()
        self._stop.set()

    def cancel(self) -> None:
        """Cooperatively stop all workers and discard partial data."""
        self._cancel_requested.set()
        self._stop.set()

    def snapshot(self) -> Snapshot:
        with self._lock:
            segs = [(s.start, s.end - s.start + 1, s.downloaded)
                    for s in sorted(self._segs, key=lambda x: x.start)]
            return Snapshot(total=self._total, downloaded=self._total_done, segments=segs)

    # -- public API ----------------------------------------------------------

    def probe(self) -> RemoteFile:
        r = self._session.head(self.url, timeout=self.timeout, allow_redirects=True)
        r.raise_for_status()
        return RemoteFile(
            size=int(r.headers.get("Content-Length", 0)),
            accept_ranges=r.headers.get("Accept-Ranges", "").lower() == "bytes",
            etag=r.headers.get("ETag"),
            filename=self._name_from_url(r.url),
        )

    def download(self) -> str:
        remote = self.probe()
        self._remote = remote
        self._accept_ranges = remote.accept_ranges
        self._total = remote.size
        self.dest.parent.mkdir(parents=True, exist_ok=True)

        spec = None
        if self._resume is not None and is_resumable(self._resume, remote.size, remote.etag):
            spec = list(self._resume.segments)
        if spec is None:
            self._discard_scratch()
            n = self.segments if remote.accept_ranges else 1
            spec = plan_segments(remote.size, n) if remote.size else [(0, -1)]

        self._segs = [_Seg(s, e, self._part_size(s)) for (s, e) in spec]
        with self._lock:
            self._total_done = sum(s.downloaded for s in self._segs)
        self._persist_state()

        # One worker per initial segment; workers self-schedule further splits.
        threads = []
        for seg in list(self._segs):
            t = threading.Thread(target=self._worker, args=(seg,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        if self._cancel_requested.is_set():
            self._discard_scratch()
            raise Cancelled("download cancelled")
        if self._pause_requested.is_set():
            self._persist_state()  # progress lives in the part files
            raise Paused("download paused")
        if self._errors:
            raise DownloadError(str(self._errors[0])) from self._errors[0]

        self._merge(remote.size)
        self._verify_checksum()
        self._cleanup()
        return str(self.dest)

    # -- workers -------------------------------------------------------------

    def _worker(self, seg: _Seg) -> None:
        try:
            while seg is not None and not self._stop.is_set():
                with self._lock:
                    seg.active = True
                self._run_segment(seg)
                with self._lock:
                    seg.active = False
                seg = self._acquire_more()
        except BaseException as e:  # noqa: BLE001 - surfaced via download()
            with self._lock:
                self._errors.append(e)
            self._stop.set()

    def _run_segment(self, seg: _Seg) -> None:
        attempts = 0
        while not self._stop.is_set():
            with self._lock:
                start, end, downloaded = seg.start, seg.end, seg.downloaded
            if downloaded >= end - start + 1:
                return

            if not self._accept_ranges and downloaded:
                # No range support => can't resume a stream; start it over.
                with self._lock:
                    self._total_done -= seg.downloaded
                    seg.downloaded = 0
                open(self._part_path(seg.start), "wb").close()
                downloaded = 0

            headers = {}
            if self._accept_ranges:
                headers["Range"] = f"bytes={start + downloaded}-{end}"

            try:
                self._stream(seg, headers, downloaded)
                with self._lock:
                    done = seg.downloaded >= seg.end - seg.start + 1
                if done:
                    return
                raise _Retryable("stream ended before the segment was complete")
            except (requests.RequestException, OSError, _Retryable) as e:
                attempts += 1
                if attempts > self.max_retries:
                    raise DownloadError(
                        f"segment @{seg.start} failed after {attempts} attempt(s): {e}"
                    ) from e
                if self.retry_backoff:
                    time.sleep(self.retry_backoff * (2 ** (attempts - 1)))

    def _stream(self, seg: _Seg, headers, downloaded) -> None:
        ranged = "Range" in headers
        # Ask for identity so the body bytes are the file bytes (range offsets
        # stay meaningful and no decoding sits between us and the socket).
        req_headers = {**headers, "Accept-Encoding": "identity"}
        with self._session.get(
            self.url, headers=req_headers, stream=True, timeout=self.timeout
        ) as r:
            if ranged and r.status_code == 200 and (seg.start + downloaded) > 0:
                raise DownloadError("server ignored Range request (got 200)")
            r.raise_for_status()

            raw = r.raw
            # We track completion ourselves via byte counts, so we don't want
            # urllib3 to raise (and discard the buffer) on a short read; a short
            # read just means "resume from here".
            try:
                raw.enforce_content_length = False
            except Exception:
                pass

            mode = "ab" if downloaded else "wb"
            with open(self._part_path(seg.start), mode) as f:
                while not self._stop.is_set():
                    try:
                        chunk = raw.read(self.chunk_size, decode_content=True)
                    except Exception as e:  # connection dropped mid-read
                        raise _Retryable(str(e)) from e
                    if not chunk:
                        return  # EOF; caller checks whether the segment is complete
                    # Cap-to-end, write, and bookkeeping must be atomic w.r.t. a
                    # concurrent split: otherwise a split could shrink `end`
                    # between the cap check and the write, letting this segment
                    # write past its new end and overlap the new segment.
                    with self._lock:
                        allowed = seg.end - (seg.start + seg.downloaded) + 1
                        if allowed <= 0:
                            return  # our range was shrunk by a split; stop here
                        if len(chunk) > allowed:
                            chunk = chunk[:allowed]
                        f.write(chunk)
                        seg.downloaded += len(chunk)
                        self._total_done += len(chunk)
                        done_total = self._total_done
                        reached_end = seg.start + seg.downloaded - 1 >= seg.end
                    if self.on_progress:
                        self.on_progress(done_total, self._total)
                    # Throttle outside the lock so other segments keep flowing
                    # while this one waits for its share of the rate budget.
                    self._rate.throttle(len(chunk))
                    if reached_end:
                        return

    def _acquire_more(self) -> Optional[_Seg]:
        if not (self.dynamic and self._accept_ranges):
            return None
        with self._lock:
            if len(self._segs) >= MAX_SEGMENTS:
                return None
            victim = None
            best_remaining = -1
            for s in self._segs:
                if not s.active:
                    continue
                remaining = s.end - (s.start + s.downloaded) + 1
                if remaining > best_remaining:
                    best_remaining, victim = remaining, s
            if victim is None:
                return None
            mid = split_point(victim.start, victim.end, victim.downloaded, self.min_split)
            if mid is None:
                return None
            new = _Seg(start=mid + 1, end=victim.end, downloaded=0, active=True)
            victim.end = mid  # victim's worker will stop once it reaches mid
            self._segs.append(new)
            self.splits += 1
            self._persist_state_locked()
            return new

    # -- finalisation --------------------------------------------------------

    def _merge(self, total: int) -> None:
        segs = sorted(self._segs, key=lambda s: s.start)
        tmp = self.dest.with_name(self.dest.name + ".merging")
        with open(tmp, "wb") as out:
            for s in segs:
                with open(self._part_path(s.start), "rb") as f:
                    while True:
                        block = f.read(1 << 20)
                        if not block:
                            break
                        out.write(block)
        size = tmp.stat().st_size
        if total and size != total:
            tmp.unlink(missing_ok=True)
            raise DownloadError(f"size mismatch: got {size}, expected {total}")
        os.replace(tmp, self.dest)

    def _verify_checksum(self) -> None:
        if not self.expected_sha256:
            return
        h = hashlib.sha256()
        with open(self.dest, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        actual = h.hexdigest()
        if actual != self.expected_sha256:
            raise DownloadError(
                f"SHA-256 mismatch: got {actual}, expected {self.expected_sha256}"
            )

    def _cleanup(self) -> None:
        for p in self.dest.parent.glob(self.dest.name + ".dlmpart_*"):
            p.unlink(missing_ok=True)
        default_state_path(self.dest).unlink(missing_ok=True)

    # -- state / helpers -----------------------------------------------------

    def _persist_state(self) -> None:
        with self._lock:
            self._persist_state_locked()

    def _persist_state_locked(self) -> None:
        remote = self._remote
        state = DownloadState(
            url=self.url,
            dest=str(self.dest),
            total=remote.size if remote else self._total,
            etag=remote.etag if remote else None,
            accept_ranges=self._accept_ranges,
            segments=[(s.start, s.end) for s in sorted(self._segs, key=lambda x: x.start)],
            sha256=self.expected_sha256,
        )
        state.save(default_state_path(self.dest))

    def _discard_scratch(self) -> None:
        for p in self.dest.parent.glob(self.dest.name + ".dlmpart_*"):
            p.unlink(missing_ok=True)
        default_state_path(self.dest).unlink(missing_ok=True)

    def _part_path(self, start: int) -> Path:
        return self.dest.with_name(f"{self.dest.name}.dlmpart_{start}")

    def _part_size(self, start: int) -> int:
        p = self._part_path(start)
        return p.stat().st_size if p.exists() else 0

    @staticmethod
    def _name_from_url(url: str) -> str:
        return os.path.basename(unquote(urlparse(url).path)) or "download.bin"

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        retry = Retry(
            total=self.max_retries,
            connect=self.max_retries,
            read=0,  # mid-stream reads are retried by our own loop
            status=self.max_retries,
            backoff_factor=self.retry_backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        return s

    def __del__(self):
        if getattr(self, "_owns_session", False):
            try:
                self._session.close()
            except Exception:
                pass
