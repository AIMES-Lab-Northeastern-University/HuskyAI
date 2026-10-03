"""Cross-worker behaviour against a real Redis server.

Skipped unless REDIS_URL points at a reachable server. Two RedisFanout /
RoomManager instances, each with its own client, stand in for two Uvicorn
workers; what these add over test_multiworker_safety.py is the real client's
wire behaviour: pub/sub delivery, a killed subscription coming back, key
TTLs, lease renewal, and a command timeout against a server that stalls.
"""

import asyncio
import json
import os
import uuid

import pytest

import coordination
import group_room
from group_room import GroupRoom, RedisFanout, RedisUnavailable, RoomManager

REDIS_URL = os.getenv("REDIS_URL", "").strip()


def _redis_up() -> bool:
    if not REDIS_URL:
        return False

    async def go():
        from redis.asyncio import Redis
        r = Redis.from_url(REDIS_URL, socket_connect_timeout=1)
        try:
            await r.ping()
            return True
        except Exception:
            return False
        finally:
            await r.aclose()

    return asyncio.run(go())


pytestmark = pytest.mark.skipif(not _redis_up(), reason="REDIS_URL not set or Redis unreachable")


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


async def _eventually(cond, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


def test_the_team_turn_is_exclusive_across_workers_and_expires():
    async def go():
        gsid = uuid.uuid4().hex
        a, b = RedisFanout(REDIS_URL), RedisFanout(REDIS_URL)
        try:
            ra, rb = GroupRoom(gsid, a), GroupRoom(gsid, b)
            ta = await ra.acquire_group_turn()
            tb = await rb.acquire_group_turn()
            ttl = await a._redis.ttl(f"husky:room:{gsid}:turn")
            await ra.release_group_turn(ta)
            tb2 = await rb.acquire_group_turn()
            await rb.release_group_turn(tb2)
            return ta, tb, ttl, tb2
        finally:
            await a.close(); await b.close()

    ta, tb, ttl, tb2 = asyncio.run(go())
    assert ta and tb is None and tb2
    assert 0 < ttl <= group_room.TURN_LOCK_TTL_SEC, "a dead worker's turn lock expires"


def test_a_broadcast_on_one_worker_reaches_a_socket_on_another():
    async def go():
        gsid = uuid.uuid4().hex
        wa, wb = RoomManager(), RoomManager()
        wa.configure(url=REDIS_URL); wb.configure(url=REDIS_URL)
        try:
            ra, rb = await wa.get(gsid), await wb.get(gsid)
            sock_a, sock_b = FakeWS(), FakeWS()
            await ra.add(sock_a, "ua", "A"); await rb.add(sock_b, "ub", "B")
            await ra.broadcast({"type": "hello"})
            ok = await _eventually(lambda: sock_b.sent)
            members = await ra.members_snapshot()
            await ra.remove(sock_a); await rb.remove(sock_b)
            return ok, sock_a.sent, sock_b.sent, members
        finally:
            await wa.close(); await wb.close()

    ok, sent_a, sent_b, members = asyncio.run(go())
    assert ok and sent_b == [{"type": "hello"}]
    assert sent_a == [{"type": "hello"}], "delivered locally once, not echoed back"
    assert {m["user_id"] for m in members} == {"ua", "ub"}


def test_a_killed_subscription_comes_back(monkeypatch):
    monkeypatch.setattr(group_room, "RESUBSCRIBE_BACKOFF_SEC", (0.05,))

    async def go():
        from redis.asyncio import Redis

        gsid = uuid.uuid4().hex
        wa, wb = RoomManager(), RoomManager()
        wa.configure(url=REDIS_URL); wb.configure(url=REDIS_URL)
        admin = Redis.from_url(REDIS_URL)
        try:
            ra, rb = await wa.get(gsid), await wb.get(gsid)
            sock_b = FakeWS()
            await rb.add(sock_b, "ub", "B")
            # Drop every pub/sub connection, as a Redis restart or a network
            # blip would.
            await admin.execute_command("CLIENT", "KILL", "TYPE", "pubsub")
            channel = f"husky:room:{gsid}:events"

            async def resubscribed():
                return (await admin.pubsub_numsub(channel))[0][1] >= 2

            for _ in range(100):
                if await resubscribed():
                    break
                await asyncio.sleep(0.05)
            await ra.broadcast({"type": "after_the_kill"})
            ok = await _eventually(lambda: sock_b.sent)
            await rb.remove(sock_b)
            return ok, sock_b.sent
        finally:
            await admin.aclose()
            await wa.close(); await wb.close()

    ok, sent = asyncio.run(go())
    assert ok and sent == [{"type": "after_the_kill"}]


def test_a_stalled_redis_is_an_error_not_a_hang(monkeypatch):
    """CLIENT PAUSE makes the server sit on every command, the way a Redis
    under a network partition does. The lock call must give up on its own."""
    monkeypatch.setattr(group_room, "REDIS_TIMEOUT_SEC", 0.5)

    async def go():
        from redis.asyncio import Redis

        fanout = RedisFanout(REDIS_URL)
        admin = Redis.from_url(REDIS_URL)
        try:
            await fanout.ping()                  # connect before the pause
            await admin.execute_command("CLIENT", "PAUSE", "1500", "ALL")
            t0 = asyncio.get_running_loop().time()
            with pytest.raises(RedisUnavailable):
                await fanout.try_acquire_turn(uuid.uuid4().hex)
            return asyncio.get_running_loop().time() - t0
        finally:
            await asyncio.sleep(1.6)             # let the pause end before cleanup
            await admin.aclose()
            await fanout.close()

    assert asyncio.run(go()) < 1.4


def test_a_lease_outlives_its_ttl_while_held_and_lapses_when_abandoned(monkeypatch):
    monkeypatch.setattr(coordination, "LEASE_TTL_SEC", 1)
    monkeypatch.setattr(coordination, "LEASE_RENEW_SEC", 0.3)
    coordination.configure(None)

    async def go():
        name = f"test:{uuid.uuid4().hex}"
        held = await coordination.acquire(name)
        assert held.shared
        await asyncio.sleep(2.0)                          # twice the TTL
        still_held = await coordination.is_held(name)
        rival = await coordination.acquire(name)
        await held.release()
        released = await coordination.is_held(name)

        abandoned = await coordination.acquire(name)
        abandoned._renewer.cancel()                       # its worker died
        await asyncio.sleep(1.5)
        lapsed = await coordination.is_held(name)
        await coordination.close()
        return still_held, rival, released, lapsed

    still_held, rival, released, lapsed = asyncio.run(go())
    assert still_held is True and rival is None
    assert released is False
    assert lapsed is False, "a dead holder's lease frees itself"
