"""
Sliding-window rate limit for auth endpoints (per client IP).
Disabled or relaxed when HUSKY_TESTING=1 (pytest). Override max with AUTH_RATE_TEST_MAX in tests.

Counters live in Redis when REDIS_URL is set, so several Uvicorn workers share one
budget. Without it they fall back to per-process counters, which means the
effective limit is multiplied by the number of workers -- fine on one worker,
wrong on several. See `_RedisSlidingWindow`.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections import defaultdict
from time import monotonic

from fastapi import HTTPException, Request

log = logging.getLogger("rate_limit")


class SlidingWindowLimiter:
    """Per-process sliding window. Used directly on a single worker, and as the
    fallback when Redis is configured but unreachable."""

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


# ---------------------------------------------------------------------------
# Shared (Redis) sliding window
# ---------------------------------------------------------------------------

# One sorted set per key: member = a unique id for the request, score = its
# timestamp. A hit evicts anything older than the window, counts what is left,
# and appends itself only if that count is under the cap.
#
# The evict/count/append trio MUST be atomic. Done as three round trips, two
# concurrent requests could both read "count = max - 1" and both be allowed. Lua
# runs inside Redis as a single indivisible step, which closes that window.
_HIT_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local maxn   = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) >= maxn then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window))
return 1
"""


class _RedisSlidingWindow:
    """Cross-worker sliding window backed by Redis."""

    def __init__(self, url: str, window_sec: float, namespace: str) -> None:
        from redis.asyncio import Redis  # imported here so redis stays optional

        self._redis = Redis.from_url(url, decode_responses=True)
        self._script = self._redis.register_script(_HIT_LUA)
        self.window_sec = window_sec
        self._ns = namespace

    async def hit(self, key: str, max_events: int) -> bool:
        """True if allowed. Raises on any Redis problem so the caller can fall
        back -- it must never swallow an error and silently allow everything."""
        allowed = await self._script(
            keys=[f"huskyai:rl:{self._ns}:{key}"],
            args=[time.time(), self.window_sec, max_events, uuid.uuid4().hex],
        )
        return bool(int(allowed))

    async def clear(self) -> None:
        """Test helper: drop every key in this namespace."""
        pattern = f"huskyai:rl:{self._ns}:*"
        async for k in self._redis.scan_iter(match=pattern, count=500):
            await self._redis.delete(k)

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:
            pass


# Lazily built per namespace, so importing this module never opens a connection.
_shared: dict[str, _RedisSlidingWindow] = {}


def _shared_window(namespace: str, window_sec: float) -> _RedisSlidingWindow | None:
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    existing = _shared.get(namespace)
    if existing is None:
        try:
            existing = _RedisSlidingWindow(url, window_sec, namespace)
        except Exception as e:
            log.error("Rate limit: could not build Redis window (%s: %s)", type(e).__name__, e)
            return None
        _shared[namespace] = existing
    return existing


async def _allowed(namespace: str, local: SlidingWindowLimiter, key: str, max_events: int) -> bool:
    """Charge one request against the shared budget, falling back to the local one.

    Deliberately fails *back*, not open or closed. Failing closed would turn a
    Redis blip into "nobody can log in", which is worse than the abuse it guards
    against; failing open would drop the guard entirely. The per-process limiter
    is exactly the pre-Redis behaviour, so a fallback is never worse than the
    status quo -- it only loses the cross-worker sharing.
    """
    if max_events <= 0:
        return True
    shared = _shared_window(namespace, local.window_sec)
    if shared is not None:
        try:
            return await shared.hit(key, max_events)
        except Exception as e:
            log.error(
                "Rate limit: Redis unavailable (%s: %s) -- falling back to this "
                "worker's local counter. The limit is now per-worker, so the "
                "effective cap is multiplied by the worker count.",
                type(e).__name__, e,
            )
    return local.hit(key, max_events)


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

_auth_limiter = SlidingWindowLimiter(60.0)


def _effective_auth_max() -> int:
    if os.getenv("HUSKY_TESTING") == "1":
        return int(os.getenv("AUTH_RATE_TEST_MAX", "1000000"))
    return int(os.getenv("AUTH_RATE_MAX", "60"))


async def clear_auth_rate_buckets() -> None:
    """Test helper: reset counters between cases (local and shared).

    Builds the shared window rather than only clearing an already-built one:
    in a fresh process nothing has gone through _allowed() yet, so the lazy
    instance does not exist and the Redis clear would silently no-op -- leaving
    a previous run's entries alive inside the window and making the suite
    order- and timing-dependent.
    """
    _auth_limiter.clear()
    shared = _shared_window("auth", _auth_limiter.window_sec)
    if shared is not None:
        try:
            await shared.clear()
        except Exception as e:
            log.warning("could not clear shared auth rate buckets: %s", e)


async def check_auth_rate_limit(request: Request) -> None:
    mx = _effective_auth_max()
    if mx <= 0:
        return
    if not await _allowed("auth", _auth_limiter, _client_ip(request), mx):
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


async def clear_reset_rate_buckets() -> None:
    """Test helper: reset counters between cases (local and shared).
    See clear_auth_rate_buckets for why this builds the window."""
    _reset_limiter.clear()
    shared = _shared_window("reset", _reset_limiter.window_sec)
    if shared is not None:
        try:
            await shared.clear()
        except Exception as e:
            log.warning("could not clear shared reset rate buckets: %s", e)


async def check_reset_rate_limit(request: Request, email: str | None = None, *, scope: str = "req") -> None:
    """Rate-limit a password-reset request.

    Called from inside the handler rather than as a dependency, because the email
    lives in the request body and both keys must be charged on the same request.
    `scope` namespaces the buckets so that redeeming a link and requesting one
    draw on separate budgets — fumbling a reset form must not block asking for a
    fresh email.
    """
    ip = _client_ip(request)

    checks: list[tuple[str, int]] = [(f"{scope}:ip:{ip}", _reset_max_per_ip())]
    if email:
        checks.append((f"{scope}:email:{email.strip().lower()}", _reset_max_per_email()))

    for key, mx in checks:
        if mx <= 0:
            continue
        if not await _allowed("reset", _reset_limiter, key, mx):
            raise HTTPException(
                status_code=429,
                detail="Too many reset requests. Try again later.",
            )


async def close_rate_limit_clients() -> None:
    """Release Redis connections at shutdown."""
    for w in list(_shared.values()):
        await w.close()
    _shared.clear()
