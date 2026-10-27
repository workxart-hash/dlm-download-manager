"""Pure unit tests for segmentation logic (no network)."""

from __future__ import annotations

import pytest

from dlm.segmentation import (
    MAX_SEGMENTS,
    MIN_SPLIT_BYTES,
    clamp_segments,
    plan_segments,
    split_point,
)


# -- clamp ------------------------------------------------------------------

def test_clamp_caps_at_max():
    assert clamp_segments(1000, total=10**9) == MAX_SEGMENTS


def test_clamp_minimum_one():
    assert clamp_segments(0, total=10**9) == 1
    assert clamp_segments(-5, total=10**9) == 1


def test_clamp_never_exceeds_total_bytes():
    # Can't have more segments than bytes.
    assert clamp_segments(8, total=3) == 3
    assert clamp_segments(8, total=0) == 1


# -- plan -------------------------------------------------------------------

def test_plan_covers_entire_file_contiguously():
    total = 1_000_003
    segs = plan_segments(total, 8)
    assert segs[0][0] == 0
    assert segs[-1][1] == total - 1
    # contiguous, no gaps or overlaps
    for (s0, e0), (s1, _e1) in zip(segs, segs[1:]):
        assert s1 == e0 + 1
    # covers exactly `total` bytes
    assert sum(e - s + 1 for s, e in segs) == total


def test_plan_segments_are_balanced():
    segs = plan_segments(1_000_003, 8)
    sizes = [e - s + 1 for s, e in segs]
    assert max(sizes) - min(sizes) <= 1


def test_plan_single_segment():
    assert plan_segments(500, 1) == [(0, 499)]


def test_plan_respects_requested_count():
    assert len(plan_segments(10_000, 5)) == 5


# -- dynamic split ----------------------------------------------------------

def test_split_returns_midpoint_of_remaining():
    # segment [0, 999], nothing downloaded -> split into [0,499],[500,999]
    mid = split_point(0, 999, downloaded=0, min_split=2)
    assert mid == 499


def test_split_accounts_for_already_downloaded():
    # [0, 999], 400 already done -> remaining [400,999] (600 bytes),
    # split at 400 + 300 - 1 = 699
    mid = split_point(0, 999, downloaded=400, min_split=2)
    assert mid == 699


def test_split_halves_are_non_empty_and_contiguous():
    start, end, downloaded = 100, 200, 10
    mid = split_point(start, end, downloaded, min_split=2)
    # victim keeps [start, mid], new segment is [mid+1, end]
    assert start + downloaded <= mid < end  # victim still has work, new is non-empty


def test_split_declines_when_remaining_too_small():
    # remaining is below the minimum worth splitting
    assert split_point(0, 1000, downloaded=0, min_split=MIN_SPLIT_BYTES) is None
    # remaining of exactly 1 byte can never be split in two
    assert split_point(0, 10, downloaded=10, min_split=2) is None
