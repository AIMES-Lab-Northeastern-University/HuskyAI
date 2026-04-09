"""
Sliding-window rate limit for auth endpoints (per client IP).
Disabled or relaxed when HUSKY_TESTING=1 (pytest). Override max with AUTH_RATE_TEST_MAX in tests.
"""

from __future__ import annotations

import os
from collections import defaultdict
from time import monotonic

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self, window_sec: float) -> None:
        self.window_sec = window_sec
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def hit(self, key: str, max_events: int) -> bool:
        """Return True if request is allowed, False if over limit."""
        if max_events <= 0:
            return True
        now = monotonic()
        bucket = self._buckets[key]
        bucket[:] = [t for t in bucket if now - t < self.window_sec]
        if len(bucket) >= max_events:
            return False
        bucket.append(now)
        return True

    def clear(self) -> None:
        self._buckets.clear()


_auth_limiter = SlidingWindowLimiter(60.0)


def _effective_auth_max() -> int:
    if os.getenv("HUSKY_TESTING") == "1":
        return int(os.getenv("AUTH_RATE_TEST_MAX", "1000000"))
    return int(os.getenv("AUTH_RATE_MAX", "60"))


def clear_auth_rate_buckets() -> None:
    """Test helper: reset counters between cases."""
    _auth_limiter.clear()


def check_auth_rate_limit(request: Request) -> None:
    mx = _effective_auth_max()
    if mx <= 0:
        return
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        key = forwarded
    elif request.client:
        key = request.client.host
    else:
        key = "unknown"
    if not _auth_limiter.hit(key, mx):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again later.",
        )
