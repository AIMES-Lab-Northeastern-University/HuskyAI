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


# Password reset is far more sensitive than login: each request can send mail to a
# real inbox, so it gets its own much tighter hourly budget, counted per email
# address as well as per IP. Keyed separately from _auth_limiter so a burst of
# resets cannot exhaust the login budget or vice versa.
_reset_limiter = SlidingWindowLimiter(3600.0)


def _testing() -> bool:
    return os.getenv("HUSKY_TESTING") == "1"


def _reset_max_per_email() -> int:
    if _testing():
        return int(os.getenv("RESET_RATE_TEST_MAX", "1000000"))
    return int(os.getenv("RESET_RATE_MAX_PER_HOUR", "5"))


def _reset_max_per_ip() -> int:
    """Deliberately much looser than the per-email budget.

    Students share NAT egress on a university network, so a whole section can
    appear as one IP. A tight per-IP cap would let the first few users lock
    everyone else out of password resets, which is worse than the abuse it
    prevents — the per-email cap is what actually protects an individual inbox.
    """
    if _testing():
        return int(os.getenv("RESET_RATE_TEST_MAX", "1000000"))
    return int(os.getenv("RESET_RATE_MAX_PER_IP_PER_HOUR", "40"))


def clear_reset_rate_buckets() -> None:
    """Test helper: reset counters between cases."""
    _reset_limiter.clear()


def check_reset_rate_limit(request: Request, email: str | None = None, *, scope: str = "req") -> None:
    """Rate-limit a password-reset request.

    Called from inside the handler rather than as a dependency, because the email
    lives in the request body and both keys must be charged on the same request.
    `scope` namespaces the buckets so that redeeming a link and requesting one
    draw on separate budgets — fumbling a reset form must not block asking for a
    fresh email.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else "unknown")

    checks: list[tuple[str, int]] = [(f"{scope}:ip:{ip}", _reset_max_per_ip())]
    if email:
        checks.append((f"{scope}:email:{email.strip().lower()}", _reset_max_per_email()))

    for key, mx in checks:
        if mx <= 0:
            continue
        if not _reset_limiter.hit(key, mx):
            raise HTTPException(
                status_code=429,
                detail="Too many reset requests. Try again later.",
            )
