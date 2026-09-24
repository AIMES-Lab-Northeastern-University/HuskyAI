"""Room manager for live group-challenge chats and collaborative coach sessions.

Two modes, chosen by environment:

  in-process  (default, REDIS_URL unset)
      Rooms live in this process's memory, so every member of a team must be
      served by the same Uvicorn worker. Correct ONLY on a single worker.

  redis       (REDIS_URL set)
      Presence, fan-out and the per-student coach-turn lock move to Redis, so
      any number of workers can serve one team. A payload is delivered locally
      *and* published, and every other worker's listener delivers it to its own
      sockets. Each worker skips its own echo by origin id.

Every Redis key is namespaced by group_session_id, so one session's state can
never be confused with another's.

If REDIS_URL is set but Redis is unreachable, group sessions fail LOUDLY
(`RedisUnavailable`, surfaced as close code 4005) rather than silently
degrading to per-worker rooms — a team split across workers that cannot see
each other's writes looks like a broken app, and a team whose presence is
half-visible silently breaks the team_min gate. Solo chat is unaffected either
way. See `RedisUnavailable`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from fastapi import WebSocket

log = logging.getLogger("group_chat")

# How long a presence entry survives without a heartbeat. A worker that crashes
# stops heartbeating, and its members age out instead of lingering as ghosts
# that keep satisfying the team_min gate.
MEMBER_TTL_SEC = 45

# A coach turn holds this student's lock. Long enough for a slow model call,
# short enough that a worker dying mid-turn does not wedge the student out of
# their own coach. Released in a finally; the TTL is the crash net.
COACH_LOCK_TTL_SEC = 300

# How often a worker refreshes its presence entries. Comfortably inside
# MEMBER_TTL_SEC: a student reading quietly for a minute is still present, and
# only a worker that has actually stopped running lets its entries lapse.
HEARTBEAT_SEC = 15

# Identifies this process in log lines and pub/sub envelopes.
WORKER_ID = f"w{os.getpid()}"


def _key(group_session_id: str, suffix: str) -> str:
    return f"husky:room:{group_session_id}:{suffix}"


class RedisUnavailable(RuntimeError):
    """Redis was configured but cannot be reached.

    Never swallowed: group work refuses to start rather than running in a state
    where teammates on different workers are invisible to each other.
    """


# ---------------------------------------------------------------------------
# Fan-out / presence / locks
# ---------------------------------------------------------------------------


class RedisFanout:
    """Cross-worker presence, broadcast and per-student locks.

    `client` is injectable so the envelope handling, key naming and echo
    suppression can be tested without a server.
    """

    name = "redis"

    # Compare-and-delete: only the holder may release, so a lock that has
    # already expired and been taken by someone else is not freed by the
    # previous holder's finally block.
    _RELEASE_LUA = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, url: str, client=None):
        self._url = url
        if client is not None:
            self._redis = client
        else:
            from redis.asyncio import Redis  # imported here so redis stays optional

            self._redis = Redis.from_url(url, decode_responses=True)
        # Per-instance identity, used to drop our own pub/sub echoes.
        # Deliberately not the pid: one process may hold more than one instance.
        self._origin = f"{WORKER_ID}-{uuid.uuid4().hex[:8]}"
        self._subs: dict[str, tuple] = {}   # gsid -> (pubsub, listener task)

    @property
    def origin(self) -> str:
        return self._origin

    async def ping(self) -> None:
        try:
            await self._redis.ping()
        except Exception as e:
            raise RedisUnavailable(f"Redis ping failed for {self._url!r}: {e}") from e

    # -- presence ---------------------------------------------------------

    async def register(self, gsid: str, socket_id: str, user_id: str, name: str) -> None:
        zkey, hkey = _key(gsid, "members"), _key(gsid, "meta")
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zadd(zkey, {socket_id: time.time()})
                pipe.hset(hkey, socket_id, json.dumps({"user_id": user_id, "name": name}))
                pipe.expire(zkey, MEMBER_TTL_SEC * 4)
                pipe.expire(hkey, MEMBER_TTL_SEC * 4)
                await pipe.execute()
        except Exception as e:
            raise RedisUnavailable(f"presence register failed: {e}") from e

    async def unregister(self, gsid: str, socket_id: str) -> None:
        zkey, hkey = _key(gsid, "members"), _key(gsid, "meta")
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zrem(zkey, socket_id)
                pipe.hdel(hkey, socket_id)
                await pipe.execute()
        except Exception as e:
            # Disconnect cleanup: log, never raise. The socket is already gone
            # and the entry ages out of the ZSET on its own.
            log.error(f"[room] unregister failed for {gsid}: {type(e).__name__}: {e}")

    async def heartbeat(self, gsid: str, socket_ids: list[str]) -> None:
        if not socket_ids:
            return
        zkey, hkey = _key(gsid, "members"), _key(gsid, "meta")
        now = time.time()
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zadd(zkey, {sid: now for sid in socket_ids})
                pipe.expire(zkey, MEMBER_TTL_SEC * 4)
                pipe.expire(hkey, MEMBER_TTL_SEC * 4)
                await pipe.execute()
        except Exception as e:
            log.error(f"[room] heartbeat failed for {gsid}: {type(e).__name__}: {e}")

    async def members(self, gsid: str) -> list[dict]:
        zkey, hkey = _key(gsid, "members"), _key(gsid, "meta")
        try:
            # Evict members whose worker stopped heartbeating, so a crashed
            # worker's ghosts cannot keep satisfying the team_min gate.
            await self._redis.zremrangebyscore(zkey, "-inf", time.time() - MEMBER_TTL_SEC)
            socket_ids = await self._redis.zrange(zkey, 0, -1)
            if not socket_ids:
                return []
            raw = await self._redis.hmget(hkey, socket_ids)
        except Exception as e:
            raise RedisUnavailable(f"presence lookup failed: {e}") from e

        seen: dict[str, str] = {}
        orphans: list[str] = []
        for sid, blob in zip(socket_ids, raw):
            if not blob:
                orphans.append(sid)
                continue
            try:
                meta = json.loads(blob)
            except Exception:
                orphans.append(sid)
                continue
            seen.setdefault(meta["user_id"], meta["name"])
        if orphans:
            try:
                await self._redis.zrem(zkey, *orphans)
            except Exception:
                pass
        return [{"user_id": uid, "name": nm} for uid, nm in seen.items()]

    # -- fan-out ----------------------------------------------------------

    async def publish(self, gsid: str, payload: dict) -> None:
        try:
            envelope = {"origin": self._origin, "payload": payload}
            await self._redis.publish(_key(gsid, "events"), json.dumps(envelope))
        except Exception as e:
            raise RedisUnavailable(f"publish failed: {e}") from e

    async def subscribe(self, gsid: str, handler) -> None:
        """Start delivering other workers' payloads for this session.

        Awaited rather than fired off, so the subscription is live before the
        caller publishes anything: pub/sub has no replay, and an early publish
        would simply be lost.
        """
        if gsid in self._subs:
            return
        channel = _key(gsid, "events")
        try:
            pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            await pubsub.subscribe(channel)
        except Exception as e:
            raise RedisUnavailable(f"subscribe failed: {e}") from e

        async def _listen():
            try:
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(msg["data"])
                    except Exception:
                        continue
                    # Skip what this worker published: it already delivered
                    # those payloads to its own sockets directly.
                    if envelope.get("origin") == self._origin:
                        continue
                    try:
                        await handler(envelope.get("payload") or {})
                    except Exception as e:
                        log.error(f"[room] subscriber handler failed: {type(e).__name__}: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.critical(
                    f"[room] pub/sub listener for {gsid} died: {type(e).__name__}: {e}. "
                    "Members on this worker will stop receiving remote events."
                )

        self._subs[gsid] = (pubsub, asyncio.create_task(_listen()))

    async def unsubscribe(self, gsid: str) -> None:
        entry = self._subs.pop(gsid, None)
        if not entry:
            return
        pubsub, task = entry
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await pubsub.unsubscribe()
            await pubsub.close()
        except Exception:
            pass

    # -- per-student coach lock -------------------------------------------

    async def try_acquire_user(self, gsid: str, user_id: str) -> str | None:
        """One in-flight coach turn per student, across every worker. Returns a
        nonce to release with, or None if the student already has a turn
        running (a second tab, or a double-submit)."""
        nonce = uuid.uuid4().hex
        try:
            ok = await self._redis.set(
                _key(gsid, f"coach:{user_id}"), nonce,
                nx=True, ex=COACH_LOCK_TTL_SEC,
            )
        except Exception as e:
            raise RedisUnavailable(f"coach lock failed: {e}") from e
        return nonce if ok else None

    async def release_user(self, gsid: str, user_id: str, nonce: str) -> None:
        try:
            await self._redis.eval(self._RELEASE_LUA, 1, _key(gsid, f"coach:{user_id}"), nonce)
        except Exception as e:
            log.error(f"[room] coach lock release failed for {gsid}/{user_id[:8]}: {e}")

    async def close(self) -> None:
        for gsid in list(self._subs):
            await self.unsubscribe(gsid)
        try:
            await self._redis.close()
        except Exception:
            pass


class GroupRoom:
    """Live state for one group session: the connected sockets, the shared
    conversation history, and the locks that serialize AI turns.

    Local structures are unchanged from the single-worker design and remain the
    delivery path for sockets on THIS worker. When a fan-out is configured they
    are a local view of a larger room rather than the whole room.
    """

    def __init__(self, group_session_id: str, fanout: RedisFanout | None = None):
        self.group_session_id = group_session_id
        self._fanout = fanout
        # ws -> {"user_id": str, "name": str, "socket_id": str}
        self.connections: dict[WebSocket, dict] = {}
        # Legacy /ws/group only: one shared coach, so one AI turn at a time.
        # The collaborative-study design (/ws/coach) gives every student their
        # own coach and uses per-user locks below instead — private coaches
        # running concurrently is the whole point of that design, so they must
        # not serialise behind each other.
        self.turn_lock = asyncio.Lock()
        # Shared server-side conversation history (same shape as the single-user
        # handler's local list: {"role", "content", optional "attachments"}).
        self.history: list[dict] = []
        self.history_loaded = False

        # --- Collaborative study: N private coaches in one room ---
        # user_id -> {"history": list[dict], "loaded": bool, "conversation_id": str}
        self.private: dict[str, dict] = {}
        # user_id -> Lock. One in-flight coach turn per student, independent of
        # every teammate's. Used when there is no fan-out; with Redis the lock
        # is a key so a second tab on another worker is also excluded.
        self._user_locks: dict[str, asyncio.Lock] = {}
        # Set once the artifact row exists, so teammates' sockets can skip the
        # get-or-create round trip.
        self.artifact_id: str | None = None
        # Refreshes this worker's presence entries while anyone is connected.
        # Started on the first add, stopped when the last socket goes.
        self._heartbeat_task: asyncio.Task | None = None

    # -- coach turn locking ------------------------------------------------

    def user_lock(self, user_id: str) -> asyncio.Lock:
        """This student's in-process coach-turn lock. Created on first use.

        Kept for the in-process deployment and as the local half of the Redis
        case: two tabs on THIS worker are excluded here without a round trip.
        """
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        return lock

    async def acquire_user_turn(self, user_id: str) -> str | None:
        """Claim this student's coach turn across every worker.

        Returns a token to pass to `release_user_turn`, or None if a turn is
        already running for them. With no fan-out the in-process lock is the
        whole answer; with one, the local lock is taken first (cheap, excludes
        this worker's tabs) and then the Redis key (excludes every other
        worker's).
        """
        lock = self.user_lock(user_id)
        if lock.locked():
            return None
        await lock.acquire()
        if self._fanout is None:
            return "local"
        try:
            nonce = await self._fanout.try_acquire_user(self.group_session_id, user_id)
        except Exception:
            lock.release()
            raise
        if nonce is None:
            lock.release()
            return None
        return nonce

    async def release_user_turn(self, user_id: str, token: str | None) -> None:
        if token is None:
            return
        if self._fanout is not None and token != "local":
            await self._fanout.release_user(self.group_session_id, user_id, token)
        lock = self._user_locks.get(user_id)
        if lock is not None and lock.locked():
            lock.release()

    def private_state(self, user_id: str, conversation_id: str) -> dict:
        """This student's private coach history, created empty on first use."""
        st = self.private.get(user_id)
        if st is None:
            st = {"history": [], "loaded": False, "conversation_id": conversation_id}
            self.private[user_id] = st
        return st

    # -- delivery ----------------------------------------------------------

    async def send_to_user(self, user_id: str, payload: dict) -> None:
        """Deliver to every socket belonging to one student ON THIS WORKER.

        Used for private coach output, which teammates must not see — sending it
        through broadcast() would leak one student's coaching into the shared
        room and destroy the independence the design rests on.

        Deliberately not published across workers: the stream belongs to the
        tab that asked for it, and mirroring it would put one student's private
        coaching on the wire for every worker to receive. A second tab of the
        same student on another worker therefore does not mirror the stream; it
        still sees everything shared, which is what teammates see too.
        """
        text = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws, meta in list(self.connections.items()):
            if meta.get("user_id") != user_id:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.remove(ws)

    async def deliver_local(self, payload: dict) -> None:
        """Send to this worker's sockets only. The subscriber's delivery path;
        never re-publishes, or two workers would echo each other forever."""
        text = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws in list(self.connections):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.remove(ws)

    async def broadcast(self, payload: dict, exclude: WebSocket | None = None) -> None:
        """Send a JSON payload to every connected socket in the session
        (optionally skipping one local socket), on this worker and every other.
        Sockets that error are dropped from the roster."""
        text = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws in list(self.connections):
            if ws is exclude:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.remove(ws)

        if self._fanout is not None:
            # `exclude` is a local socket object and cannot be expressed
            # remotely; it is only ever used to skip the sender's own echo of
            # something they already rendered, which no other worker holds.
            await self._fanout.publish(self.group_session_id, payload)

    # -- presence ----------------------------------------------------------

    async def add(self, ws: WebSocket, user_id: str, name: str) -> None:
        socket_id = uuid.uuid4().hex
        self.connections[ws] = {"user_id": user_id, "name": name, "socket_id": socket_id}
        if self._fanout is not None:
            await self._fanout.register(self.group_session_id, socket_id, user_id, name)
            if self._heartbeat_task is None:
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def remove(self, ws: WebSocket) -> None:
        meta = self.connections.pop(ws, None)
        if meta and self._fanout is not None:
            await self._fanout.unregister(self.group_session_id, meta["socket_id"])
        if not self.connections and self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def heartbeat(self) -> None:
        """Refresh this worker's presence entries so they do not age out."""
        if self._fanout is None:
            return
        await self._fanout.heartbeat(
            self.group_session_id,
            [m["socket_id"] for m in self.connections.values()],
        )

    async def _heartbeat_loop(self) -> None:
        """Keep this worker's members alive for as long as their sockets are.

        Without this, presence would lapse after MEMBER_TTL_SEC and a student
        who spent a minute reading a teammate's section — exactly the behaviour
        the study is about — would disappear from the roster and from the
        team_min gate while still connected.
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_SEC)
                if not self.connections:
                    continue
                try:
                    await self.heartbeat()
                except Exception as e:
                    # Logged, not fatal: one missed refresh is survivable, and
                    # raising here would kill the loop and lose every later one.
                    log.error(f"[room] heartbeat loop error: {type(e).__name__}: {e}")
        except asyncio.CancelledError:
            raise

    async def members_snapshot(self) -> list[dict]:
        """Distinct connected users across every worker (a user may have
        several tabs). Async because with a fan-out this is a lookup, not a
        read of local memory — and `team_min` gating depends on it being the
        whole team rather than this worker's slice of it."""
        if self._fanout is not None:
            return await self._fanout.members(self.group_session_id)
        seen: dict[str, str] = {}
        for meta in self.connections.values():
            seen.setdefault(meta["user_id"], meta["name"])
        return [{"user_id": uid, "name": nm} for uid, nm in seen.items()]


class RoomManager:
    def __init__(self):
        self._rooms: dict[str, GroupRoom] = {}
        self._guard = asyncio.Lock()
        self._fanout: RedisFanout | None = None

    # -- configuration -----------------------------------------------------

    def configure(self, url: str | None = None, client=None) -> None:
        """Pick the backend. Called once at startup, before any room exists.

        REDIS_URL unset means in-process rooms, which is correct on exactly one
        Uvicorn worker.
        """
        url = url if url is not None else os.getenv("REDIS_URL", "").strip()
        if not url and client is None:
            self._fanout = None
            return
        self._fanout = RedisFanout(url or "injected", client=client)

    @property
    def backend_name(self) -> str:
        return "redis" if self._fanout is not None else "in-process"

    async def startup_check(self) -> None:
        """Fail loudly at boot if Redis was configured but is unreachable,
        rather than at the moment a student tries to join a team."""
        if self._fanout is not None:
            await self._fanout.ping()

    # -- rooms -------------------------------------------------------------

    async def get(self, group_session_id: str) -> GroupRoom:
        async with self._guard:
            room = self._rooms.get(group_session_id)
            if room is None:
                room = GroupRoom(group_session_id, fanout=self._fanout)
                self._rooms[group_session_id] = room
                if self._fanout is not None:
                    # Subscribe before the caller sends anything: pub/sub has no
                    # replay, so an early publish would be lost.
                    await self._fanout.subscribe(
                        group_session_id, room.deliver_local,
                    )
            return room

    def peek(self, group_session_id: str) -> GroupRoom | None:
        """Return the live room if one exists, without creating it."""
        return self._rooms.get(group_session_id)

    async def drop_if_empty(self, group_session_id: str) -> None:
        async with self._guard:
            room = self._rooms.get(group_session_id)
            if room is not None and not room.connections:
                self._rooms.pop(group_session_id, None)
                if self._fanout is not None:
                    await self._fanout.unsubscribe(group_session_id)

    async def close(self) -> None:
        if self._fanout is not None:
            await self._fanout.close()


rooms = RoomManager()
