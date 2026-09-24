"""Cross-worker rooms: presence, fan-out, echo suppression and the coach lock.

There is no Redis server in this environment, so these drive RedisFanout with an
injected fake that implements the handful of commands the module uses, and share
one fake "server" between two fanout instances — which is what two Uvicorn
workers are. That covers the logic this module owns (key naming, envelope
shape, origin suppression, lock semantics, presence merging and eviction) and
deliberately does NOT claim to cover the real client's wire behaviour.

`test_an_unreachable_redis_fails_loudly_at_startup` is the one case that uses
the real client, against a port nothing is listening on.
"""

import asyncio
import json
import time

import pytest

from group_room import (COACH_LOCK_TTL_SEC, MEMBER_TTL_SEC, GroupRoom, RedisFanout,
                        RedisUnavailable, RoomManager)


# ---------------------------------------------------------------------------
# A fake Redis, shared between fanouts so two instances see one dataset.
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self, store=None):
        s = store if store is not None else {}
        self.z = s.setdefault("z", {})          # key -> {member: score}
        self.h = s.setdefault("h", {})          # key -> {field: value}
        self.kv = s.setdefault("kv", {})        # key -> value
        self.channels = s.setdefault("ch", {})  # channel -> [subscriber queues]
        self.published = s.setdefault("pub", [])
        self.closed = False

    # -- plumbing ---------------------------------------------------------

    async def ping(self):
        return True

    async def close(self):
        self.closed = True

    def pipeline(self, transaction=True):
        outer = self

        class _Pipe:
            def __init__(self):
                self.ops = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def zadd(self, key, mapping):
                self.ops.append(("zadd", key, mapping))

            def hset(self, key, field, value):
                self.ops.append(("hset", key, field, value))

            def expire(self, key, ttl):
                self.ops.append(("expire", key, ttl))

            def zrem(self, key, member):
                self.ops.append(("zrem", key, member))

            def hdel(self, key, field):
                self.ops.append(("hdel", key, field))

            async def execute(self):
                for op in self.ops:
                    if op[0] == "zadd":
                        outer.z.setdefault(op[1], {}).update(op[2])
                    elif op[0] == "hset":
                        outer.h.setdefault(op[1], {})[op[2]] = op[3]
                    elif op[0] == "zrem":
                        outer.z.get(op[1], {}).pop(op[2], None)
                    elif op[0] == "hdel":
                        outer.h.get(op[1], {}).pop(op[2], None)
                self.ops = []

        return _Pipe()

    # -- sorted sets / hashes ---------------------------------------------

    async def zremrangebyscore(self, key, lo, hi):
        members = self.z.get(key, {})
        for m in [m for m, score in members.items() if score <= float(hi)]:
            members.pop(m, None)

    async def zrange(self, key, start, end):
        return sorted(self.z.get(key, {}), key=lambda m: self.z[key][m])

    async def hmget(self, key, fields):
        h = self.h.get(key, {})
        return [h.get(f) for f in fields]

    async def zrem(self, key, *members):
        for m in members:
            self.z.get(key, {}).pop(m, None)

    # -- strings / scripts -------------------------------------------------

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def eval(self, script, numkeys, key, arg):
        # Only the compare-and-delete release script is used.
        if self.kv.get(key) == arg:
            self.kv.pop(key, None)
            return 1
        return 0

    # -- pub/sub -----------------------------------------------------------

    async def publish(self, channel, data):
        self.published.append((channel, data))
        for q in self.channels.get(channel, []):
            await q.put({"type": "message", "channel": channel, "data": data})

    def pubsub(self, ignore_subscribe_messages=False):
        outer = self

        class _PubSub:
            def __init__(self):
                self.queue = asyncio.Queue()
                self.channel = None

            async def subscribe(self, channel):
                self.channel = channel
                outer.channels.setdefault(channel, []).append(self.queue)

            async def listen(self):
                while True:
                    yield await self.queue.get()

            async def unsubscribe(self):
                subs = outer.channels.get(self.channel, [])
                if self.queue in subs:
                    subs.remove(self.queue)

            async def close(self):
                return None

        return _PubSub()


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


def two_workers():
    """Two fanouts over one dataset — the shape of two Uvicorn workers."""
    store = {}
    return RedisFanout("redis://fake", client=FakeRedis(store)), \
        RedisFanout("redis://fake", client=FakeRedis(store))


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


def test_presence_spans_workers():
    """The team_min gate counts members. If presence were per-worker, a team
    split across two would never reach the gate and could not start."""
    async def run():
        a, b = two_workers()
        await a.register("gs1", "sock-a", "user-a", "Ana")
        await b.register("gs1", "sock-b", "user-b", "Ben")

        seen_from_a = await a.members("gs1")
        seen_from_b = await b.members("gs1")
        return seen_from_a, seen_from_b

    from_a, from_b = asyncio.run(run())
    assert {m["user_id"] for m in from_a} == {"user-a", "user-b"}
    assert {m["user_id"] for m in from_b} == {"user-a", "user-b"}


def test_one_student_with_two_tabs_counts_once():
    async def run():
        a, b = two_workers()
        await a.register("gs1", "sock-1", "user-a", "Ana")
        await b.register("gs1", "sock-2", "user-a", "Ana")
        return await a.members("gs1")

    members = asyncio.run(run())
    assert members == [{"user_id": "user-a", "name": "Ana"}]


def test_a_crashed_worker_s_members_age_out():
    """A worker that dies stops heartbeating. Its members must not linger as
    ghosts that keep satisfying the team_min gate."""
    async def run():
        a, _ = two_workers()
        await a.register("gs1", "sock-stale", "user-gone", "Ghost")
        # Backdate the heartbeat past the TTL, as a dead worker's entry would be.
        a._redis.z["husky:room:gs1:members"]["sock-stale"] = time.time() - (MEMBER_TTL_SEC + 5)
        await a.register("gs1", "sock-live", "user-here", "Live")
        return await a.members("gs1")

    members = asyncio.run(run())
    assert [m["user_id"] for m in members] == ["user-here"]


def test_unregister_removes_presence():
    async def run():
        a, b = two_workers()
        await a.register("gs1", "sock-a", "user-a", "Ana")
        await a.unregister("gs1", "sock-a")
        return await b.members("gs1")

    assert asyncio.run(run()) == []


# ---------------------------------------------------------------------------
# Fan-out
# ---------------------------------------------------------------------------


def test_a_broadcast_reaches_a_socket_on_another_worker():
    """The blocking requirement for multi-worker: a write by one teammate must
    appear for a teammate the load balancer put on a different worker."""
    async def run():
        a, b = two_workers()
        remote_ws = FakeWS()
        room_b = GroupRoom("gs1", fanout=b)
        await room_b.add(remote_ws, "user-b", "Ben")
        await b.subscribe("gs1", room_b.deliver_local)

        room_a = GroupRoom("gs1", fanout=a)
        local_ws = FakeWS()
        await room_a.add(local_ws, "user-a", "Ana")
        await room_a.broadcast({"type": "artifact_updated", "section_key": "s1"})

        await asyncio.sleep(0.05)   # let the listener drain
        await b.unsubscribe("gs1")
        return local_ws.sent, remote_ws.sent

    local, remote = asyncio.run(run())
    assert local == [{"type": "artifact_updated", "section_key": "s1"}]
    assert remote == [{"type": "artifact_updated", "section_key": "s1"}], \
        "a teammate on another worker saw nothing"


def test_a_worker_does_not_redeliver_its_own_broadcast():
    """Every payload is delivered locally AND published. Without origin
    suppression the publisher would deliver its own echo a second time, and
    every teammate would see doubled writes and doubled chat."""
    async def run():
        a, _ = two_workers()
        room_a = GroupRoom("gs1", fanout=a)
        ws = FakeWS()
        await room_a.add(ws, "user-a", "Ana")
        await a.subscribe("gs1", room_a.deliver_local)

        await room_a.broadcast({"type": "team_chat", "content": "hi"})
        await asyncio.sleep(0.05)
        await a.unsubscribe("gs1")
        return ws.sent

    assert asyncio.run(run()) == [{"type": "team_chat", "content": "hi"}]


def test_the_published_envelope_carries_the_origin_and_the_payload():
    async def run():
        a, _ = two_workers()
        await a.publish("gs1", {"type": "presence", "members": []})
        return a._redis.published, a.origin

    published, origin = asyncio.run(run())
    channel, raw = published[0]
    envelope = json.loads(raw)
    assert channel == "husky:room:gs1:events", "keys must be namespaced per session"
    assert envelope["origin"] == origin
    assert envelope["payload"] == {"type": "presence", "members": []}


def test_private_coach_output_is_never_published():
    """send_to_user is local by design: mirroring a private stream would put one
    student's coaching on the wire for every worker."""
    async def run():
        a, _ = two_workers()
        room = GroupRoom("gs1", fanout=a)
        ws = FakeWS()
        await room.add(ws, "user-a", "Ana")
        await room.send_to_user("user-a", {"type": "stream", "content": "private"})
        return ws.sent, a._redis.published

    sent, published = asyncio.run(run())
    assert sent == [{"type": "stream", "content": "private"}]
    assert published == [], "private coach output must not cross the bus"


# ---------------------------------------------------------------------------
# The per-student coach lock
# ---------------------------------------------------------------------------


def test_one_student_cannot_run_two_coach_turns_across_workers():
    async def run():
        a, b = two_workers()
        room_a, room_b = GroupRoom("gs1", fanout=a), GroupRoom("gs1", fanout=b)

        first = await room_a.acquire_user_turn("user-a")
        second = await room_b.acquire_user_turn("user-a")
        # Releasing the first frees it for the next turn.
        await room_a.release_user_turn("user-a", first)
        third = await room_b.acquire_user_turn("user-a")
        return first, second, third

    first, second, third = asyncio.run(run())
    assert first is not None
    assert second is None, "a second tab on another worker started a parallel turn"
    assert third is not None


def test_a_teammate_s_turn_is_not_blocked():
    """Private coaches run concurrently — serialising them defeats the design."""
    async def run():
        a, b = two_workers()
        room_a, room_b = GroupRoom("gs1", fanout=a), GroupRoom("gs1", fanout=b)
        mine = await room_a.acquire_user_turn("user-a")
        theirs = await room_b.acquire_user_turn("user-b")
        return mine, theirs

    mine, theirs = asyncio.run(run())
    assert mine is not None and theirs is not None


def test_only_the_holder_can_release_the_lock():
    """Compare-and-delete: a turn that overran its TTL and lost the lock must
    not free the next holder's claim on its way out."""
    async def run():
        a, _ = two_workers()
        held = await a.try_acquire_user("gs1", "user-a")
        await a.release_user("gs1", "user-a", "a-different-nonce")
        # Still held by the real owner.
        blocked = await a.try_acquire_user("gs1", "user-a")
        await a.release_user("gs1", "user-a", held)
        free = await a.try_acquire_user("gs1", "user-a")
        return blocked, free

    blocked, free = asyncio.run(run())
    assert blocked is None
    assert free is not None


def test_the_lock_key_carries_a_ttl_so_a_dead_worker_frees_it():
    """Without a TTL a worker dying mid-turn would wedge that student out of
    their own coach for the rest of the session."""
    assert COACH_LOCK_TTL_SEC >= 60


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_without_redis_url_the_manager_stays_in_process(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    mgr = RoomManager()
    mgr.configure()
    assert mgr.backend_name == "in-process"
    # And startup_check is a no-op rather than an error.
    asyncio.run(mgr.startup_check())


def test_in_process_rooms_still_report_local_presence():
    async def run():
        mgr = RoomManager()
        mgr.configure(url="")
        room = await mgr.get("gs1")
        await room.add(FakeWS(), "user-a", "Ana")
        await room.add(FakeWS(), "user-b", "Ben")
        return await room.members_snapshot()

    members = asyncio.run(run())
    assert {m["user_id"] for m in members} == {"user-a", "user-b"}


def test_an_unreachable_redis_fails_loudly_at_startup():
    """The one test that uses the real client. A configured-but-unreachable
    Redis must raise at boot, not degrade to per-worker rooms that look fine
    until two teammates cannot see each other."""
    pytest.importorskip("redis")
    mgr = RoomManager()
    # Port 1 on loopback: nothing listens there.
    mgr.configure(url="redis://127.0.0.1:1/0")
    assert mgr.backend_name == "redis"
    with pytest.raises(RedisUnavailable):
        asyncio.run(mgr.startup_check())
    asyncio.run(mgr.close())


def test_presence_is_refreshed_while_a_socket_stays_connected():
    """A student reading a teammate's section for a minute must not vanish from
    the roster. Presence entries expire, so something has to refresh them."""
    import group_room

    async def run():
        a, _ = two_workers()
        room = GroupRoom("gs-hb", fanout=a)
        ws = FakeWS()
        # Heartbeat immediately rather than after 15s of real time.
        original = group_room.HEARTBEAT_SEC
        group_room.HEARTBEAT_SEC = 0.01
        try:
            await room.add(ws, "user-a", "Ana")
            zkey = "husky:room:gs-hb:members"
            sock = next(iter(a._redis.z[zkey]))
            # Age the entry as if the session had been quiet.
            a._redis.z[zkey][sock] = time.time() - (MEMBER_TTL_SEC - 1)
            stale = a._redis.z[zkey][sock]
            await asyncio.sleep(0.05)
            refreshed = a._redis.z[zkey][sock]
            still_there = await a.members("gs-hb")
        finally:
            group_room.HEARTBEAT_SEC = original
            await room.remove(ws)
        return stale, refreshed, still_there

    stale, refreshed, still_there = asyncio.run(run())
    assert refreshed > stale, "the heartbeat did not refresh the presence entry"
    assert [m["user_id"] for m in still_there] == ["user-a"]


def test_the_heartbeat_stops_when_the_last_socket_leaves():
    """A room nobody is in must not keep a task alive for the life of the worker."""
    async def run():
        a, _ = two_workers()
        room = GroupRoom("gs-hb2", fanout=a)
        ws = FakeWS()
        await room.add(ws, "user-a", "Ana")
        running = room._heartbeat_task is not None
        await room.remove(ws)
        return running, room._heartbeat_task

    running, after = asyncio.run(run())
    assert running is True
    assert after is None
