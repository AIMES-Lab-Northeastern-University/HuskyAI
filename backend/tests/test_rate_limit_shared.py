"""Cross-worker rate limiting.

Skipped unless REDIS_URL points at a reachable server. Two independent
_RedisSlidingWindow instances stand in for two Uvicorn workers: the point is that
one shared budget is charged, not one budget each.
"""

import asyncio
import os
import uuid

import pytest

from rate_limit import SlidingWindowLimiter, _RedisSlidingWindow

REDIS_URL = os.getenv("REDIS_URL", "").strip()


def _redis_up() -> bool:
    if not REDIS_URL:
        return False

    async def go():
        w = _RedisSlidingWindow(REDIS_URL, 60.0, "probe")
        try:
            await w.hit(uuid.uuid4().hex, 1)
            return True
        except Exception:
            return False
        finally:
            await w.close()

    return asyncio.run(go())


pytestmark = pytest.mark.skipif(
    not _redis_up(), reason="REDIS_URL not set or Redis unreachable"
)


def test_two_workers_share_one_budget():
    """The bug this fixes: N workers used to allow N x the configured limit."""

    async def go():
        key = uuid.uuid4().hex
        a = _RedisSlidingWindow(REDIS_URL, 60.0, "test")
        b = _RedisSlidingWindow(REDIS_URL, 60.0, "test")
        try:
            # Budget of 3, spent alternately across the two "workers".
            assert await a.hit(key, 3) is True   # 1
            assert await b.hit(key, 3) is True   # 2
            assert await a.hit(key, 3) is True   # 3
            # Budget exhausted -- and crucially, exhausted for BOTH workers.
            assert await b.hit(key, 3) is False
            assert await a.hit(key, 3) is False
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


def test_per_process_limiters_do_not_share_budget():
    """Control: the old behaviour, showing what the Redis version fixes."""
    a = SlidingWindowLimiter(60.0)
    b = SlidingWindowLimiter(60.0)
    assert a.hit("k", 2) is True
    assert a.hit("k", 2) is True
    assert a.hit("k", 2) is False      # worker A is out of budget...
    assert b.hit("k", 2) is True       # ...but worker B still has its own
    assert b.hit("k", 2) is True
    # Two workers, cap of 2 -> 4 requests got through. That is the bug.


def test_keys_are_independent():
    """One IP/email hitting its cap must not affect anyone else."""

    async def go():
        w = _RedisSlidingWindow(REDIS_URL, 60.0, "test")
        try:
            k1, k2 = uuid.uuid4().hex, uuid.uuid4().hex
            assert await w.hit(k1, 1) is True
            assert await w.hit(k1, 1) is False   # k1 exhausted
            assert await w.hit(k2, 1) is True    # k2 untouched
        finally:
            await w.close()

    asyncio.run(go())


def test_concurrent_hits_cannot_exceed_the_cap():
    """The atomicity guarantee: 50 simultaneous requests against a cap of 5 must
    allow exactly 5. A non-atomic check-then-add would let extras slip through."""

    async def go():
        key = uuid.uuid4().hex
        workers = [_RedisSlidingWindow(REDIS_URL, 60.0, "test") for _ in range(5)]
        try:
            results = await asyncio.gather(
                *(workers[i % 5].hit(key, 5) for i in range(50))
            )
            assert sum(results) == 5, f"expected exactly 5 allowed, got {sum(results)}"
        finally:
            for w in workers:
                await w.close()

    asyncio.run(go())


def test_window_expiry_frees_budget():
    """A short window must release budget once it rolls past."""

    async def go():
        key = uuid.uuid4().hex
        w = _RedisSlidingWindow(REDIS_URL, 1.0, "test")
        try:
            assert await w.hit(key, 1) is True
            assert await w.hit(key, 1) is False
            await asyncio.sleep(1.2)
            assert await w.hit(key, 1) is True   # window rolled over
        finally:
            await w.close()

    asyncio.run(go())
