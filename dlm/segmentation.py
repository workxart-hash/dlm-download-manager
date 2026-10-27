"""Pure segmentation logic: planning a download into byte ranges and deciding
how to split the slowest segment for dynamic segmentation.

Kept free of any I/O so it can be unit-tested in isolation.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

Segment = Tuple[int, int]  # (start, end), both inclusive

MAX_SEGMENTS = 32
MIN_SPLIT_BYTES = 1 << 20  # 1 MiB: don't bother splitting less than this


def clamp_segments(requested: int, total: int) -> int:
    """Clamp a requested segment count to [1, MAX_SEGMENTS] and never exceed the
    number of bytes available."""
    if total <= 0:
        return 1
    return max(1, min(requested, MAX_SEGMENTS, total))


def plan_segments(total: int, segments: int) -> List[Segment]:
    """Split ``total`` bytes into contiguous, near-equal inclusive ranges."""
    n = clamp_segments(segments, total)
    base, rem = divmod(total, n)
    segs: List[Segment] = []
    start = 0
    for i in range(n):
        size = base + (1 if i < rem else 0)  # spread the remainder over the first few
        end = start + size - 1
        segs.append((start, end))
        start = end + 1
    return segs


def split_point(
    start: int, end: int, downloaded: int, min_split: int = MIN_SPLIT_BYTES
) -> Optional[int]:
    """Where to cut a segment's *remaining* work in half for dynamic segmentation.

    Returns ``mid`` such that the original segment becomes ``[start, mid]`` and a
    new segment covers ``[mid + 1, end]``. Returns ``None`` when the remaining
    work is too small to be worth splitting.
    """
    offset = start + downloaded  # next byte still needed
    remaining = end - offset + 1
    if remaining < max(2, min_split):
        return None
    half = remaining // 2
    mid = offset + half - 1
    if mid < offset or mid >= end:
        return None
    return mid
