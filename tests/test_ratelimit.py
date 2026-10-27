"""Pure unit tests for the shared speed limiter (no real sleeping)."""

from __future__ import annotations

from dlm.ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_unlimited_never_waits():
    rl = RateLimiter(None)
    assert rl.reserve(10_000, now=0.0) == 0.0
    assert rl.reserve(10_000, now=0.0) == 0.0


def test_within_initial_burst_no_wait():
    # starts with one second of credit (= rate)
    rl = RateLimiter(1000)
    assert rl.reserve(500, now=0.0) == 0.0
    assert rl.reserve(500, now=0.0) == 0.0


def test_exceeding_rate_waits_proportionally():
    rl = RateLimiter(1000)
    rl.reserve(1000, now=0.0)          # drains the bucket
    wait = rl.reserve(1000, now=0.0)   # need a full second more
    assert abs(wait - 1.0) < 1e-9


def test_refill_over_time():
    rl = RateLimiter(1000)
    rl.reserve(1000, now=0.0)          # empty
    # half a second later, 500 bytes have refilled
    assert rl.reserve(500, now=0.5) == 0.0
    # nothing left again
    assert abs(rl.reserve(500, now=0.5) - 0.5) < 1e-9


def test_set_rate_to_unlimited_stops_throttling():
    rl = RateLimiter(1000)
    rl.reserve(1000, now=0.0)
    rl.set_rate(None)
    assert rl.reserve(10_000, now=0.0) == 0.0


def test_throttle_sleeps_by_reserved_amount():
    slept = []
    clock = FakeClock()
    rl = RateLimiter(1000, monotonic=clock, sleep=slept.append)
    rl.throttle(1000)  # within burst -> no sleep
    assert slept == []
    rl.throttle(1000)  # bucket now empty -> must wait ~1s
    assert len(slept) == 1 and abs(slept[0] - 1.0) < 1e-6
