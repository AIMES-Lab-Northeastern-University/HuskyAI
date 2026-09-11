"""Unit tests for the group room manager (no DB, no WebSocket, no Redis).

These exercise the memory backend, which is what runs when REDIS_URL is unset.
Cross-worker behaviour on the Redis backend is covered by
`tests/test_group_room_redis.py` (skipped unless REDIS_URL points at a live
server) and by the two-process check in `tests/multiworker/`.
"""

import asyncio

from group_room import GroupRoom, MemoryBackend, RoomManager


class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[str] = []
        self.fail = fail

    async def send_text(self, text: str):
        if self.fail:
            raise RuntimeError("dead socket")
        self.sent.append(text)


def _room(gsid: str = "gs1") -> GroupRoom:
    return GroupRoom(gsid, MemoryBackend())


def test_broadcast_reaches_all_and_drops_dead():
    async def go():
        room = _room()
        a, b, dead = FakeWS(), FakeWS(), FakeWS(fail=True)
        await room.add(a, "u1", "A")
        await room.add(b, "u2", "B")
        await room.add(dead, "u3", "C")
        await room.broadcast({"type": "x"})
        assert len(a.sent) == 1 and len(b.sent) == 1
        assert room.local_count() == 2  # errored socket pruned
        # ...and it is gone from presence too, not just from the local map.
        assert {m["user_id"] for m in await room.members_snapshot()} == {"u1", "u2"}
        await room.shutdown()

    asyncio.run(go())


def test_broadcast_exclude_skips_one():
    async def go():
        room = _room("gs")
        a, b = FakeWS(), FakeWS()
        await room.add(a, "u1", "A")
        await room.add(b, "u2", "B")
        await room.broadcast({"type": "x"}, exclude=a)
        assert a.sent == [] and len(b.sent) == 1
        await room.shutdown()

    asyncio.run(go())


def test_members_snapshot_dedups_multiple_tabs():
    async def go():
        room = _room("gs")
        a, b = FakeWS(), FakeWS()
        await room.add(a, "u1", "Alice")
        await room.add(b, "u1", "Alice")  # same user, second tab
        assert await room.members_snapshot() == [{"user_id": "u1", "name": "Alice"}]
        await room.shutdown()

    asyncio.run(go())


def test_remove_clears_presence():
    async def go():
        room = _room("gs")
        a = FakeWS()
        await room.add(a, "u1", "Alice")
        assert len(await room.members_snapshot()) == 1
        await room.remove(a)
        assert await room.members_snapshot() == []
        await room.shutdown()

    asyncio.run(go())


def test_turn_lock_is_exclusive_and_reusable():
    async def go():
        room = _room("gs")
        first = await room.try_acquire_turn()
        assert first is not None
        assert await room.try_acquire_turn() is None  # held -> second sender busy
        await room.release_turn(first)
        second = await room.try_acquire_turn()
        assert second is not None  # released -> next turn can run
        await room.release_turn(second)
        await room.shutdown()

    asyncio.run(go())


def test_turn_lock_is_scoped_per_session():
    """One session's turn must never block another's."""

    async def go():
        backend = MemoryBackend()
        a = GroupRoom("session-a", backend)
        b = GroupRoom("session-b", backend)
        held = await a.try_acquire_turn()
        assert held is not None
        other = await b.try_acquire_turn()
        assert other is not None  # unrelated session is unaffected
        await a.release_turn(held)
        await b.release_turn(other)

    asyncio.run(go())


def test_manager_get_is_stable_and_drop_if_empty():
    async def go():
        mgr = RoomManager()
        mgr.configure(redis_url="")  # force the memory backend
        r1 = await mgr.get("s")
        assert await mgr.get("s") is r1  # same instance while live
        await mgr.drop_if_empty("s")  # no local sockets -> removed
        assert await mgr.get("s") is not r1  # fresh instance after drop
        # A room this worker still owns sockets in is never dropped.
        r3 = await mgr.get("s")
        await r3.add(FakeWS(), "u", "U")
        await mgr.drop_if_empty("s")
        assert await mgr.get("s") is r3
        await mgr.close()

    asyncio.run(go())


def test_manager_defaults_to_memory_without_redis_url():
    mgr = RoomManager()
    mgr.configure(redis_url="")
    assert mgr.backend_name == "memory"
