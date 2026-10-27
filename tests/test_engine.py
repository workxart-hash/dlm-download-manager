"""Integration tests for the download engine against a real local server.

Every test that downloads compares the SHA-256 of the result to the source.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from dlm.engine import Downloader, DownloadError
from dlm.state import DownloadState, default_state_path

PAYLOAD = bytes((i * 131 + 7) % 256 for i in range(400_000))  # ~400 KB deterministic


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_leftovers(tmp_path, dest_name="out.bin"):
    return [p.name for p in tmp_path.iterdir() if p.name != dest_name]


# -- probe ------------------------------------------------------------------

def test_probe_reports_size_and_range_support(server, tmp_path):
    url = server.configure(PAYLOAD, accept_ranges=True)
    info = Downloader(url, dest=tmp_path / "out.bin").probe()
    assert info.size == len(PAYLOAD)
    assert info.accept_ranges is True


def test_probe_detects_missing_range_support(server, tmp_path):
    url = server.configure(PAYLOAD, accept_ranges=False)
    info = Downloader(url, dest=tmp_path / "out.bin").probe()
    assert info.accept_ranges is False


# -- basic downloads --------------------------------------------------------

def test_single_segment_download_matches(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    path = Downloader(url, dest=dest, segments=1, retry_backoff=0).download()
    assert os.path.getsize(path) == len(PAYLOAD)
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)


def test_multi_segment_download_matches_and_cleans_up(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    Downloader(url, dest=dest, segments=8, retry_backoff=0, dynamic=False).download()
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)
    assert _no_leftovers(tmp_path) == []  # parts + state file removed on success


def test_falls_back_to_single_stream_without_range_support(server, tmp_path):
    url = server.configure(PAYLOAD, accept_ranges=False)
    dest = tmp_path / "out.bin"
    Downloader(url, dest=dest, segments=8, retry_backoff=0).download()
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)


# -- retry / resume ---------------------------------------------------------

def test_retries_and_resumes_after_dropped_connection(server, tmp_path):
    url = server.configure(PAYLOAD, fail_once=True)
    dest = tmp_path / "out.bin"
    Downloader(url, dest=dest, segments=4, max_retries=3,
               retry_backoff=0, dynamic=False).download()
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)


def test_gives_up_after_max_retries(server, tmp_path):
    url = server.configure(PAYLOAD, fail_once=True)
    dest = tmp_path / "out.bin"
    with pytest.raises(DownloadError):
        Downloader(url, dest=dest, segments=4, max_retries=0,
                   retry_backoff=0, dynamic=False).download()


def test_resume_across_runs_reuses_partial_data(server, tmp_path):
    dest = tmp_path / "out.bin"

    # First run is forced to fail mid-stream, leaving partial parts + state file.
    url = server.configure(PAYLOAD, fail_once=True)
    with pytest.raises(DownloadError):
        Downloader(url, dest=dest, segments=4, max_retries=0,
                   retry_backoff=0, dynamic=False).download()

    assert default_state_path(dest).exists()
    assert any(".dlmpart_" in p.name for p in tmp_path.iterdir())

    # Second run via the resume path: continue, don't refetch everything.
    url = server.configure(PAYLOAD, fail_once=False)
    Downloader.from_state_file(default_state_path(dest), retry_backoff=0).download()

    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)
    assert server.bytes_served < len(PAYLOAD)


# -- dynamic segmentation ---------------------------------------------------

def test_dynamic_segmentation_splits_and_file_is_correct(server, tmp_path):
    # Delay every non-first range so segment 0 finishes early and steals work.
    url = server.configure(PAYLOAD, delay=0.25)
    dest = tmp_path / "out.bin"
    d = Downloader(url, dest=dest, segments=4, retry_backoff=0,
                   dynamic=True, min_split=4096, chunk_size=16384)
    d.download()
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)
    assert d.splits >= 1  # at least one segment was dynamically split


# -- checksum verification --------------------------------------------------

def test_sha256_verification_passes(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    Downloader(url, dest=dest, segments=4, retry_backoff=0,
               expected_sha256=_sha(PAYLOAD)).download()
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)


def test_sha256_mismatch_raises(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    with pytest.raises(DownloadError):
        Downloader(url, dest=dest, segments=4, retry_backoff=0,
                   expected_sha256="deadbeef").download()


# -- progress ---------------------------------------------------------------

def test_progress_callback_reaches_total(server, tmp_path):
    url = server.configure(PAYLOAD)
    seen = []
    Downloader(
        url, dest=tmp_path / "out.bin", segments=4, retry_backoff=0, dynamic=False,
        on_progress=lambda done, total: seen.append((done, total)),
    ).download()
    assert seen
    assert seen[-1][0] == len(PAYLOAD)
    assert seen[-1][1] == len(PAYLOAD)
