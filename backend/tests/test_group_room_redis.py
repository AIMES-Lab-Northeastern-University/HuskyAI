"""Redis-backend tests for the group room manager.

Skipped unless REDIS_URL points at a reachable server, so CI without Redis still
passes. These cover the parts the memory backend cannot exercise: two *separate*
RoomManager instances (standing in for two Uvicorn workers) sharing one Redis.
"""

import asyncio
import os
import uuid

import pytest

from group_room import RoomManager, RedisUnavailable

REDIS_URL = os.getenv("REDIS_URL", "").strip()


def _redis_up() -> bool:
    if not REDIS_URL:
        return False

    async def go():
        mgr = RoomManager()
        mgr.configure(redis_url=REDIS_URL)
        try:
            await mgr.startup_check()
            return True
        except Exception:
            return False
        finally:
            await mgr.close()

    return asyncio.run(go())


pytestmark = pytest.mark.skipif(
    not _redis_up(), reason="REDIS_URL not set or Redis unreachable"
)


class FakeWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send_text(self, text: str):
        self.sent.append(text)


def _gsid() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _worker() -> RoomManager:
    mgr = RoomManager()
    mgr.configure(redis_url=REDIS_URL)
    return mgr


def test_presence_is_shared_across_workers():
    """Two managers (= two workers) each see the other's members."""

    async def go():
        gsid = _gsid()
        a, b = await _worker(), await _worker()
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            await ra.add(FakeWS(), "u1", "Alice")
            await rb.add(FakeWS(), "u2", "Bob")
            # Each worker owns exactly one socket...
            assert ra.local_count() == 1 and rb.local_count() == 1
            # ...but presence is the union across both.
            for room in (ra, rb):
                names = {m["user_id"] for m in await room.members_snapshot()}
                assert names == {"u1", "u2"}
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


def test_broadcast_crosses_workers():
    async def go():
        gsid = _gsid()
        a, b = await _worker(), await _worker()
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            wa, wb = FakeWS(), FakeWS()
            await ra.add(wa, "u1", "Alice")
            await rb.add(wb, "u2", "Bob")

            await ra.broadcast({"type": "hello"})
            await asyncio.sleep(0.4)  # let pub/sub deliver

            assert len(wa.sent) == 1  # delivered locally by the publisher
            assert len(wb.sent) == 1  # delivered on the other worker via Redis
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


def test_broadcast_exclude_is_honoured_across_workers():
    async def go():
        gsid = _gsid()
        a, b = await _worker(), await _worker()
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            wa, wb = FakeWS(), FakeWS()
            await ra.add(wa, "u1", "Alice")
            await rb.add(wb, "u2", "Bob")

            await ra.broadcast({"type": "hello"}, exclude=wa)
            await asyncio.sleep(0.4)

            assert wa.sent == []       # excluded sender stays silent
            assert len(wb.sent) == 1   # everyone else still receives it
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


def test_turn_lock_is_exclusive_across_workers():
    """The core safety property: two workers cannot both start a turn."""

    async def go():
        gsid = _gsid()
        a, b = await _worker(), await _worker()
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            first = await ra.try_acquire_turn()
            assert first is not None
            assert await rb.try_acquire_turn() is None  # blocked on the other worker
            await ra.release_turn(first)
            second = await rb.try_acquire_turn()
            assert second is not None  # freed for the other worker
            await rb.release_turn(second)
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


def test_turn_lock_is_scoped_per_session_across_workers():
    """Session A's held lock must not block session B on another worker."""

    async def go():
        gsid_a, gsid_b = _gsid(), _gsid()
        a, b = await _worker(), await _worker()
        try:
            held = await (await a.get(gsid_a)).try_acquire_turn()
            assert held is not None
            other = await (await b.get(gsid_b)).try_acquire_turn()
            assert other is not None  # different session -> different key
            await (await a.get(gsid_a)).release_turn(held)
            await (await b.get(gsid_b)).release_turn(other)
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


def test_unreachable_redis_raises_rather_than_degrading():
    """A configured-but-down Redis must fail loudly, never fall back to memory."""

    async def go():
        mgr = RoomManager()
        mgr.configure(redis_url="redis://127.0.0.1:6399/0")  # nothing listening
        with pytest.raises(RedisUnavailable):
            await mgr.startup_check()
        room = await mgr.get(_gsid())
        with pytest.raises(Exception):
            await room.add(FakeWS(), "u1", "Alice")
        assert mgr.backend_name == "redis"  # did not silently switch backends
        await mgr.close()

    asyncio.run(go())
