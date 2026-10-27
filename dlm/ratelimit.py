"""A shared, thread-safe speed limiter (token bucket).

One limiter is shared by every segment thread of a download so the cap applies
to the aggregate throughput, not per connection. The rate can be changed while
downloading (GUI slider). ``reserve`` is the pure decision (how long to wait for
``n`` bytes given the clock); ``throttle`` applies it by sleeping.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class RateLimiter:
    def __init__(
        self,
        rate_bps: Optional[float] = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self.set_rate(rate_bps)

    def set_rate(self, rate_bps: Optional[float]) -> None:
        with self._lock:
            self.rate = float(rate_bps) if rate_bps else None
            # Start with one second of credit so small downloads aren't penalised.
            self._allowance = self.rate if self.rate else 0.0
            self._last = self._monotonic()

    def reserve(self, n: int, now: Optional[float] = None) -> float:
        """Return the number of seconds to wait before sending ``n`` bytes."""
        with self._lock:
            if not self.rate:
                return 0.0
            if now is None:
                now = self._monotonic()
            elapsed = max(0.0, now - self._last)  # never let the clock run backwards
            self._last = now
            # Refill (capped at one second of credit), then take our bytes. The
            # allowance may go negative: that debt makes concurrent callers wait
            # progressively longer, so overlapping sleeps stay additive and the
            # aggregate throughput actually honours the rate.
            self._allowance = min(self.rate, self._allowance + elapsed * self.rate) - n
            if self._allowance >= 0:
                return 0.0
            return -self._allowance / self.rate

    def throttle(self, n: int) -> None:
        wait = self.reserve(n)
        if wait > 0:
            self._sleep(wait)
