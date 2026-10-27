"""Pure unit tests for resume-state persistence (no network)."""

from __future__ import annotations

from pathlib import Path

from dlm.state import DownloadState, default_state_path, is_resumable


def _state(**over):
    base = dict(
        url="http://host/f.bin",
        dest="C:/tmp/f.bin",
        total=1000,
        etag='"v1"',
        accept_ranges=True,
        segments=[(0, 499), (500, 999)],
        sha256=None,
    )
    base.update(over)
    return DownloadState(**base)


def test_round_trip_save_load(tmp_path):
    state = _state()
    path = tmp_path / "f.bin.dlm.json"
    state.save(path)
    loaded = DownloadState.load(path)
    assert loaded == state


def test_segments_survive_as_tuples(tmp_path):
    path = tmp_path / "s.json"
    _state().save(path)
    loaded = DownloadState.load(path)
    assert loaded.segments == [(0, 499), (500, 999)]


def test_default_state_path_sits_next_to_dest():
    p = default_state_path("C:/downloads/movie.mkv")
    assert p == Path("C:/downloads/movie.mkv.dlm.json")


def test_is_resumable_true_when_total_and_etag_match():
    assert is_resumable(_state(), remote_total=1000, remote_etag='"v1"') is True


def test_is_resumable_false_on_total_mismatch():
    assert is_resumable(_state(), remote_total=2000, remote_etag='"v1"') is False


def test_is_resumable_false_on_etag_mismatch():
    assert is_resumable(_state(), remote_total=1000, remote_etag='"v2"') is False


def test_is_resumable_true_when_etag_absent_both_sides():
    # Servers without ETag: fall back to size match only.
    assert is_resumable(_state(etag=None), remote_total=1000, remote_etag=None) is True
