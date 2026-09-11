"""Per-section artifact locks.

Memory-backend tests run always. The cross-worker tests (two RoomManagers, one
Redis, standing in for two Uvicorn workers) skip unless REDIS_URL is reachable.
"""

import asyncio
import os
import uuid

import pytest

from group_room import GroupRoom, MemoryBackend, RoomManager

REDIS_URL = os.getenv("REDIS_URL", "").strip()


class FakeWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send_text(self, text: str):
        self.sent.append(text)


def _gsid() -> str:
    return f"artifact-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Memory backend
# ---------------------------------------------------------------------------

def test_one_holder_at_a_time_and_denial_names_the_holder():
    async def go():
        room = GroupRoom(_gsid(), MemoryBackend())
        alice, bob = FakeWS(), FakeWS()
        await room.add(alice, "u-alice", "Alice")
        await room.add(bob, "u-bob", "Bob")

        got, rec = await room.acquire_section(alice, "design", "u-alice", "Alice")
        assert got is True and rec["holder_user_id"] == "u-alice"

        got2, holder = await room.acquire_section(bob, "design", "u-bob", "Bob")
        assert got2 is False
        # Bob must learn WHO holds it, not just that he failed.
        assert holder["holder_user_id"] == "u-alice"
        assert holder["holder_name"] == "Alice"
        await room.shutdown()

    asyncio.run(go())


def test_different_sections_do_not_block_each_other():
    async def go():
        room = GroupRoom(_gsid(), MemoryBackend())
        alice, bob = FakeWS(), FakeWS()
        await room.add(alice, "u-alice", "Alice")
        await room.add(bob, "u-bob", "Bob")

        assert (await room.acquire_section(alice, "design", "u-alice", "Alice"))[0] is True
        # A different subproblem is a different key -> no contention at all.
        assert (await room.acquire_section(bob, "testing", "u-bob", "Bob"))[0] is True
        assert len(await room.section_locks()) == 2
        await room.shutdown()

    asyncio.run(go())


def test_release_frees_it_for_a_teammate():
    async def go():
        room = GroupRoom(_gsid(), MemoryBackend())
        alice, bob = FakeWS(), FakeWS()
        await room.add(alice, "u-alice", "Alice")
        await room.add(bob, "u-bob", "Bob")

        await room.acquire_section(alice, "design", "u-alice", "Alice")
        assert await room.release_section(alice, "design") is True
        assert (await room.acquire_section(bob, "design", "u-bob", "Bob"))[0] is True
        await room.shutdown()

    asyncio.run(go())


def test_a_non_holder_cannot_release_someone_elses_lock():
    async def go():
        room = GroupRoom(_gsid(), MemoryBackend())
        alice, bob = FakeWS(), FakeWS()
        await room.add(alice, "u-alice", "Alice")
        await room.add(bob, "u-bob", "Bob")

        await room.acquire_section(alice, "design", "u-alice", "Alice")
        assert await room.release_section(bob, "design") is False
        # ...and Alice still holds it.
        holder = (await room.section_locks())[0]
        assert holder["holder_user_id"] == "u-alice"
        await room.shutdown()

    asyncio.run(go())


def test_disconnect_releases_every_section_that_socket_held():
    async def go():
        room = GroupRoom(_gsid(), MemoryBackend())
        alice, bob = FakeWS(), FakeWS()
        alice_sid = await room.add(alice, "u-alice", "Alice")
        await room.add(bob, "u-bob", "Bob")

        await room.acquire_section(alice, "design", "u-alice", "Alice")
        await room.acquire_section(alice, "testing", "u-alice", "Alice")

        freed = await room.release_sections_for_socket(alice_sid)
        assert sorted(freed) == ["design", "testing"]
        assert await room.section_locks() == []
        # Bob can take over immediately.
        assert (await room.acquire_section(bob, "design", "u-bob", "Bob"))[0] is True
        await room.shutdown()

    asyncio.run(go())


def test_holds_section_tracks_ownership():
    async def go():
        room = GroupRoom(_gsid(), MemoryBackend())
        alice, bob = FakeWS(), FakeWS()
        await room.add(alice, "u-alice", "Alice")
        await room.add(bob, "u-bob", "Bob")
        await room.acquire_section(alice, "design", "u-alice", "Alice")
        assert room.holds_section(alice, "design") is True
        assert room.holds_section(bob, "design") is False
        await room.shutdown()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# Redis backend -- two managers stand in for two workers
# ---------------------------------------------------------------------------

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


redis_only = pytest.mark.skipif(
    not _redis_up(), reason="REDIS_URL not set or Redis unreachable"
)


@redis_only
def test_section_lock_is_exclusive_across_workers():
    """The whole reason this is Redis-backed: worker B must see worker A's lock."""

    async def go():
        gsid = _gsid()
        a, b = RoomManager(), RoomManager()
        a.configure(redis_url=REDIS_URL)
        b.configure(redis_url=REDIS_URL)
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            alice, bob = FakeWS(), FakeWS()
            await ra.add(alice, "u-alice", "Alice")
            await rb.add(bob, "u-bob", "Bob")

            got, _ = await ra.acquire_section(alice, "design", "u-alice", "Alice")
            assert got is True
            got2, holder = await rb.acquire_section(bob, "design", "u-bob", "Bob")
            assert got2 is False, "worker B acquired a section worker A already holds"
            assert holder["holder_name"] == "Alice"
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


@redis_only
def test_simultaneous_acquire_yields_exactly_one_winner():
    """20 concurrent attempts across 4 'workers' -> exactly one holder."""

    async def go():
        gsid = _gsid()
        mgrs = [RoomManager() for _ in range(4)]
        for m in mgrs:
            m.configure(redis_url=REDIS_URL)
        try:
            rooms_ = [await m.get(gsid) for m in mgrs]
            socks = []
            for i, r in enumerate(rooms_):
                ws = FakeWS()
                await r.add(ws, f"u{i}", f"User{i}")
                socks.append((r, ws, f"u{i}", f"User{i}"))

            results = await asyncio.gather(*[
                socks[i % 4][0].acquire_section(
                    socks[i % 4][1], "design", socks[i % 4][2], socks[i % 4][3]
                )
                for i in range(20)
            ])
            winners = [r for r in results if r[0] is True]
            assert len(winners) == 1, f"expected exactly 1 winner, got {len(winners)}"
            # Everyone else was told who actually has it.
            losers = [r[1] for r in results if r[0] is False]
            assert all(h.get("holder_user_id") for h in losers)
        finally:
            for m in mgrs:
                await m.close()

    asyncio.run(go())


@redis_only
def test_disconnect_on_one_worker_frees_it_for_the_other():
    async def go():
        gsid = _gsid()
        a, b = RoomManager(), RoomManager()
        a.configure(redis_url=REDIS_URL)
        b.configure(redis_url=REDIS_URL)
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            alice, bob = FakeWS(), FakeWS()
            alice_sid = await ra.add(alice, "u-alice", "Alice")
            await rb.add(bob, "u-bob", "Bob")

            await ra.acquire_section(alice, "design", "u-alice", "Alice")
            assert (await rb.acquire_section(bob, "design", "u-bob", "Bob"))[0] is False

            await ra.release_sections_for_socket(alice_sid)  # Alice drops
            assert (await rb.acquire_section(bob, "design", "u-bob", "Bob"))[0] is True
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


@redis_only
def test_sections_are_independent_across_workers():
    async def go():
        gsid = _gsid()
        a, b = RoomManager(), RoomManager()
        a.configure(redis_url=REDIS_URL)
        b.configure(redis_url=REDIS_URL)
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            alice, bob = FakeWS(), FakeWS()
            await ra.add(alice, "u-alice", "Alice")
            await rb.add(bob, "u-bob", "Bob")
            assert (await ra.acquire_section(alice, "design", "u-alice", "Alice"))[0] is True
            assert (await rb.acquire_section(bob, "testing", "u-bob", "Bob"))[0] is True
            assert len(await ra.section_locks()) == 2
        finally:
            await a.close()
            await b.close()

    asyncio.run(go())


@redis_only
def test_lock_expires_without_renewal():
    """The TTL backstop: if nothing renews, the lock lapses on its own."""

    async def go():
        import group_room

        gsid = _gsid()
        original = group_room.SECTION_LOCK_TTL_SEC
        group_room.SECTION_LOCK_TTL_SEC = 1  # shrink so the test is quick
        a, b = RoomManager(), RoomManager()
        a.configure(redis_url=REDIS_URL)
        b.configure(redis_url=REDIS_URL)
        try:
            ra, rb = await a.get(gsid), await b.get(gsid)
            alice, bob = FakeWS(), FakeWS()
            await ra.add(alice, "u-alice", "Alice")
            await rb.add(bob, "u-bob", "Bob")
            assert (await ra.acquire_section(alice, "design", "u-alice", "Alice"))[0] is True
            assert (await rb.acquire_section(bob, "design", "u-bob", "Bob"))[0] is False
            await asyncio.sleep(1.4)  # no renewal -> lapses
            assert (await rb.acquire_section(bob, "design", "u-bob", "Bob"))[0] is True
        finally:
            group_room.SECTION_LOCK_TTL_SEC = original
            await a.close()
            await b.close()

    asyncio.run(go())
