"""Room manager for live group-challenge chats.

Holds the shared state for one group session: who is connected, the lock that
serializes AI turns, and the fan-out that pushes events to every member.

Two backends:

  memory  (default -- used when REDIS_URL is unset)
      Everything lives in this process. SINGLE WORKER ONLY: a second Uvicorn
      worker gets its own independent copy of every room, so presence, the turn
      lock and broadcasts all stop working across workers.

  redis   (used when REDIS_URL is set)
      Presence, fan-out and the turn lock move to Redis so any number of workers
      can serve members of the same group session.

Sockets themselves always stay process-local -- a WebSocket cannot be handed to
another process. So each worker keeps the sockets it owns, and a broadcast is
delivered locally *and* published to Redis, where every other worker picks it up
and delivers to its own sockets.

Every Redis key is namespaced by group_session_id, so one session's turn lock can
never block another session.

If REDIS_URL is set but Redis is unreachable, group chat fails loudly (the caller
closes the websocket) instead of silently degrading to the broken single-worker
behaviour. See `RedisUnavailable`.

Note: the shared conversation history is deliberately NOT held here. It lives in
Postgres and is reloaded per turn inside the turn lock (see main.py's group
handler), so two workers can never drift apart on what the model has seen.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import WebSocket

log = logging.getLogger("group_chat")

# A member is considered gone once its heartbeat is older than this. Must be
# comfortably larger than HEARTBEAT_SEC so a busy worker isn't evicted while it
# is still alive.
MEMBER_TTL_SEC = 30
HEARTBEAT_SEC = 10

# The turn lock's TTL. The critical section is a Gemini stream plus a full
# evaluation (several OpenAI calls), so it is long by design; a watchdog extends
# it while the turn is genuinely running. If a worker dies mid-turn the lock is
# released automatically once this elapses instead of wedging the session.
TURN_LOCK_TTL_SEC = 60
TURN_LOCK_EXTEND_EVERY_SEC = 20

# Artifact section locks. A student holds one while a section is open for editing.
# Renewed server-side by the room heartbeat for as long as the holder's socket is
# still attached to this worker, so a live editor never loses its lock and a dead
# one is released without any client cooperation. Deliberately NOT client-renewed:
# a client cannot forget, and cannot keep a lock alive after its socket is gone.
SECTION_LOCK_TTL_SEC = int(os.getenv("SECTION_LOCK_TTL_SEC", "60"))


def _section_key(group_session_id: str, section_key: str) -> str:
    return f"huskyai:artifact:{group_session_id}:{section_key}:lock"


def _section_pattern(group_session_id: str) -> str:
    return f"huskyai:artifact:{group_session_id}:*:lock"

# Identifies this process in logs. NOT used to filter pub/sub echoes -- that is
# done per backend instance (see RedisBackend._origin), so two backends living in
# one process (tests, or any future in-process fan-out) stay distinguishable.
WORKER_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


class RedisUnavailable(RuntimeError):
    """Redis was configured but cannot be reached. Never swallowed: group chat
    must fail visibly rather than pretend to work."""


def _key(group_session_id: str, suffix: str) -> str:
    return f"huskyai:room:{group_session_id}:{suffix}"


class TurnToken:
    """Opaque handle returned by `GroupRoom.try_acquire_turn()`. Carries the
    backend's lock handle plus the watchdog task that keeps it alive."""

    __slots__ = ("handle", "extender")

    def __init__(self, handle, extender: asyncio.Task | None = None):
        self.handle = handle
        self.extender = extender


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class MemoryBackend:
    """Process-local backend. Equivalent to the pre-migration behaviour."""

    name = "memory"

    def __init__(self):
        # group_session_id -> {socket_id: {"user_id", "name"}}
        self._members: dict[str, dict[str, dict]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # group_session_id -> {section_key: lock record (plus a private _expires)}
        self._section_locks: dict[str, dict[str, dict]] = {}

    async def ping(self) -> None:
        return None

    async def register(self, gsid: str, socket_id: str, user_id: str, name: str) -> None:
        self._members.setdefault(gsid, {})[socket_id] = {"user_id": user_id, "name": name}

    async def unregister(self, gsid: str, socket_id: str) -> None:
        room = self._members.get(gsid)
        if room:
            room.pop(socket_id, None)
            if not room:
                self._members.pop(gsid, None)

    async def heartbeat(self, gsid: str, socket_ids: list[str]) -> None:
        return None

    async def members(self, gsid: str) -> list[dict]:
        seen: dict[str, str] = {}
        for meta in self._members.get(gsid, {}).values():
            seen.setdefault(meta["user_id"], meta["name"])
        return [{"user_id": uid, "name": nm} for uid, nm in seen.items()]

    async def publish(self, gsid: str, envelope: dict) -> None:
        # Single process: the publisher already delivered to every socket there is.
        return None

    async def subscribe(self, gsid: str, handler) -> None:
        return None

    async def unsubscribe(self, gsid: str) -> None:
        return None

    async def try_acquire(self, gsid: str) -> TurnToken | None:
        lock = self._locks.setdefault(gsid, asyncio.Lock())
        if lock.locked():
            return None
        await lock.acquire()
        return TurnToken(lock)

    async def release(self, gsid: str, token: TurnToken) -> None:
        lock = token.handle
        if lock.locked():
            lock.release()

    # -- artifact section locks -------------------------------------------

    def _sections(self, gsid: str) -> dict[str, dict]:
        return self._section_locks.setdefault(gsid, {})

    def _purge_expired(self, gsid: str) -> None:
        now = time.time()
        held = self._sections(gsid)
        for k in [k for k, v in held.items() if v["_expires"] <= now]:
            held.pop(k, None)

    async def acquire_section(self, gsid: str, section_key: str, record: dict) -> tuple[bool, dict]:
        self._purge_expired(gsid)
        held = self._sections(gsid)
        existing = held.get(section_key)
        if existing is not None:
            return False, {k: v for k, v in existing.items() if not k.startswith("_")}
        held[section_key] = {**record, "_expires": time.time() + SECTION_LOCK_TTL_SEC}
        return True, record

    async def release_section(self, gsid: str, section_key: str, nonce: str) -> bool:
        self._purge_expired(gsid)
        held = self._sections(gsid)
        existing = held.get(section_key)
        if existing is None or existing.get("nonce") != nonce:
            return False
        held.pop(section_key, None)
        return True

    async def renew_section(self, gsid: str, section_key: str, nonce: str) -> bool:
        held = self._sections(gsid)
        existing = held.get(section_key)
        if existing is None or existing.get("nonce") != nonce:
            return False
        existing["_expires"] = time.time() + SECTION_LOCK_TTL_SEC
        return True

    async def section_locks(self, gsid: str) -> list[dict]:
        self._purge_expired(gsid)
        return [
            {k: v for k, v in rec.items() if not k.startswith("_")}
            for rec in self._sections(gsid).values()
        ]

    async def close(self) -> None:
        return None


class RedisBackend:
    """Redis-backed backend: presence in a ZSET + HASH, fan-out over pub/sub, and
    one lock key per group session."""

    name = "redis"

    def __init__(self, url: str):
        from redis.asyncio import Redis  # imported here so redis stays optional

        self._url = url
        self._redis = Redis.from_url(url, decode_responses=True)
        # Per-instance identity used to drop our own pub/sub echoes. Deliberately
        # not the process id: one process may hold more than one backend.
        self._origin = f"{WORKER_ID}-{uuid.uuid4().hex[:8]}"
        # group_session_id -> (pubsub, listener task)
        self._subs: dict[str, tuple] = {}
        self._acquire_script = self._redis.register_script(self._ACQUIRE_LUA)
        self._release_script = self._redis.register_script(self._RELEASE_LUA)
        self._renew_script = self._redis.register_script(self._RENEW_LUA)

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
            raise RedisUnavailable(f"register failed: {e}") from e

    async def unregister(self, gsid: str, socket_id: str) -> None:
        zkey, hkey = _key(gsid, "members"), _key(gsid, "meta")
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zrem(zkey, socket_id)
                pipe.hdel(hkey, socket_id)
                await pipe.execute()
        except Exception as e:
            # Disconnect cleanup: log, don't raise. The socket is already gone and
            # the entry ages out of the ZSET on its own.
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
            # Evict members whose worker stopped heartbeating (e.g. it crashed),
            # so ghosts can't keep satisfying the team_min gate.
            await self._redis.zremrangebyscore(zkey, "-inf", time.time() - MEMBER_TTL_SEC)
            socket_ids = await self._redis.zrange(zkey, 0, -1)
            if not socket_ids:
                return []
            raw = await self._redis.hmget(hkey, socket_ids)
        except Exception as e:
            raise RedisUnavailable(f"members lookup failed: {e}") from e

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

    async def publish(self, gsid: str, envelope: dict) -> None:
        try:
            payload = {**envelope, "origin": self._origin}
            await self._redis.publish(_key(gsid, "events"), json.dumps(payload))
        except Exception as e:
            raise RedisUnavailable(f"publish failed: {e}") from e

    async def subscribe(self, gsid: str, handler) -> None:
        if gsid in self._subs:
            return
        channel = _key(gsid, "events")
        try:
            pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            # Awaited, so the subscription is live before the caller sends
            # anything -- pub/sub has no replay, an early publish would be lost.
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
                    # Skip what this worker published: it already delivered those
                    # to its own sockets directly.
                    if envelope.get("origin") == self._origin:
                        continue
                    try:
                        await handler(envelope)
                    except Exception as e:
                        log.error(f"[room] subscriber handler failed: {type(e).__name__}: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.critical(
                    f"[room] pub/sub listener for {gsid} died: {type(e).__name__}: {e}. "
                    "Members on this worker will stop receiving remote events."
                )

        task = asyncio.create_task(_listen())
        self._subs[gsid] = (pubsub, task)

    async def unsubscribe(self, gsid: str) -> None:
        entry = self._subs.pop(gsid, None)
        if not entry:
            return
        pubsub, task = entry
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass

    # -- turn lock --------------------------------------------------------

    async def try_acquire(self, gsid: str) -> TurnToken | None:
        """Single atomic non-blocking acquire (SET NX PX under the hood).

        redis.asyncio.lock.Lock is used rather than a Redlock: we run a single
        Redis instance, where Redlock's multi-master quorum buys nothing. Lock
        gives the two properties that matter -- an ownership token, so a worker
        can only ever release its own lock, and extend() for the watchdog.
        """
        lock = self._redis.lock(
            _key(gsid, "turnlock"),
            timeout=TURN_LOCK_TTL_SEC,
            blocking=False,
            thread_local=False,
        )
        try:
            acquired = await lock.acquire(blocking=False)
        except Exception as e:
            raise RedisUnavailable(f"turn lock acquire failed: {e}") from e
        if not acquired:
            return None

        async def _extend():
            # Keep a genuinely-running turn alive past the TTL. If this worker
            # dies the task dies with it and the lock expires on its own.
            while True:
                await asyncio.sleep(TURN_LOCK_EXTEND_EVERY_SEC)
                try:
                    await lock.extend(TURN_LOCK_TTL_SEC, replace_ttl=True)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning(f"[room] turn lock extend failed for {gsid}: {e}")
                    return

        return TurnToken(lock, asyncio.create_task(_extend()))

    async def release(self, gsid: str, token: TurnToken) -> None:
        if token.extender:
            token.extender.cancel()
            try:
                await token.extender
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        try:
            await token.handle.release()
        except Exception as e:
            # Most likely the TTL already elapsed and someone else holds it now.
            # Release is token-guarded, so we cannot have stolen another holder's
            # lock -- just record it.
            log.warning(f"[room] turn lock release failed for {gsid}: {type(e).__name__}: {e}")

    # -- artifact section locks -------------------------------------------
    #
    # Same primitive as the turn lock above -- SET NX PX plus a Lua-guarded
    # release keyed on an ownership nonce -- but the *value* is the holder
    # record rather than an opaque token. redis.asyncio.lock.Lock stores its own
    # token, so there is no way to read back WHO holds it, and this feature has
    # to answer exactly that ("Alex is editing this section") for both the denial
    # and the broadcast. Keeping identity inside the lock value means the holder
    # info can never skew from the lock's own lifetime, which a companion
    # metadata key would (the lock expires, the metadata lingers, the UI shows a
    # phantom editor).

    _ACQUIRE_LUA = """
    local existing = redis.call('GET', KEYS[1])
    if existing then
      return {0, existing}
    end
    redis.call('SET', KEYS[1], ARGV[1], 'PX', tonumber(ARGV[2]))
    return {1, ARGV[1]}
    """

    _RELEASE_LUA = """
    local existing = redis.call('GET', KEYS[1])
    if not existing then return 0 end
    local ok, rec = pcall(cjson.decode, existing)
    if ok and rec['nonce'] == ARGV[1] then
      redis.call('DEL', KEYS[1])
      return 1
    end
    return 0
    """

    _RENEW_LUA = """
    local existing = redis.call('GET', KEYS[1])
    if not existing then return 0 end
    local ok, rec = pcall(cjson.decode, existing)
    if ok and rec['nonce'] == ARGV[1] then
      redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]))
      return 1
    end
    return 0
    """

    async def acquire_section(self, gsid: str, section_key: str, record: dict) -> tuple[bool, dict]:
        """Atomically take the section, or report who already holds it.

        Returns (True, our_record) or (False, holder_record). The check and the
        set happen inside one Lua call, so two students on different workers can
        never both believe they hold it.
        """
        try:
            got, raw = await self._acquire_script(
                keys=[_section_key(gsid, section_key)],
                args=[json.dumps(record), int(SECTION_LOCK_TTL_SEC * 1000)],
            )
        except Exception as e:
            raise RedisUnavailable(f"section lock acquire failed: {e}") from e
        if int(got) == 1:
            return True, record
        try:
            return False, json.loads(raw)
        except Exception:
            # Unparseable holder record: treat as held but unattributable rather
            # than handing out a second lock on the same section.
            return False, {}

    async def release_section(self, gsid: str, section_key: str, nonce: str) -> bool:
        try:
            freed = await self._release_script(
                keys=[_section_key(gsid, section_key)], args=[nonce]
            )
        except Exception as e:
            log.error(f"[room] section release failed for {gsid}/{section_key}: {e}")
            return False
        return int(freed) == 1

    async def renew_section(self, gsid: str, section_key: str, nonce: str) -> bool:
        try:
            ok = await self._renew_script(
                keys=[_section_key(gsid, section_key)],
                args=[nonce, int(SECTION_LOCK_TTL_SEC * 1000)],
            )
        except Exception as e:
            log.error(f"[room] section renew failed for {gsid}/{section_key}: {e}")
            return False
        return int(ok) == 1

    async def section_locks(self, gsid: str) -> list[dict]:
        """Every currently-held section lock in this session, on any worker.
        Expired keys simply aren't there, so this needs no purge pass."""
        out: list[dict] = []
        try:
            async for k in self._redis.scan_iter(match=_section_pattern(gsid), count=100):
                raw = await self._redis.get(k)
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except Exception:
                    continue
        except Exception as e:
            raise RedisUnavailable(f"section lock listing failed: {e}") from e
        return out

    async def close(self) -> None:
        for gsid in list(self._subs):
            await self.unsubscribe(gsid)
        try:
            await self._redis.aclose()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------

class GroupRoom:
    """Live state for one group session.

    The sockets in `_local` belong to this worker. Presence, the turn lock and
    the fan-out live in the backend, so they are shared across workers when the
    Redis backend is active.
    """

    def __init__(self, group_session_id: str, backend):
        self.group_session_id = group_session_id
        self._backend = backend
        # ws -> socket_id, for sockets this worker owns.
        self._local: dict[WebSocket, str] = {}
        self._heartbeat_task: asyncio.Task | None = None
        # section_key -> (socket_id, nonce) for locks held by THIS worker's
        # sockets. Only these get renewed here; a lock held on another worker is
        # that worker's to keep alive, and stops being renewed the moment its
        # holder's socket goes away.
        self._held_sections: dict[str, tuple[str, str]] = {}

    # -- membership -------------------------------------------------------

    async def add(self, ws: WebSocket, user_id: str, name: str) -> str:
        """Register a socket with the session. Returns its socket_id."""
        socket_id = uuid.uuid4().hex
        # Subscribe before registering, so we cannot miss an event published
        # between the two.
        await self._backend.subscribe(self.group_session_id, self._deliver_remote)
        await self._backend.register(self.group_session_id, socket_id, user_id, name)
        self._local[ws] = socket_id
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return socket_id

    async def remove(self, ws: WebSocket) -> None:
        socket_id = self._local.pop(ws, None)
        if socket_id:
            await self._backend.unregister(self.group_session_id, socket_id)

    async def members_snapshot(self) -> list[dict]:
        """Distinct connected users across every worker (a user may have several
        tabs open, possibly served by different workers)."""
        return await self._backend.members(self.group_session_id)

    def local_count(self) -> int:
        """Sockets this worker owns. Logging/diagnostics only."""
        return len(self._local)

    def socket_id_for(self, ws: WebSocket) -> str | None:
        """This socket's id, while it is still registered on this worker."""
        return self._local.get(ws)

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_SEC)
                if not self._local:
                    continue
                await self._backend.heartbeat(
                    self.group_session_id, list(self._local.values())
                )
                # Keep alive every section lock held by a socket still attached
                # here. A holder whose socket vanished stops being renewed and
                # its lock lapses on its own.
                live = set(self._local.values())
                for section_key, (owner, nonce) in list(self._held_sections.items()):
                    if owner not in live:
                        self._held_sections.pop(section_key, None)
                        continue
                    if not await self._backend.renew_section(
                        self.group_session_id, section_key, nonce
                    ):
                        # Lost it (expired, or force-released elsewhere).
                        self._held_sections.pop(section_key, None)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"[room] heartbeat loop stopped: {type(e).__name__}: {e}")

    # -- fan-out ----------------------------------------------------------

    async def broadcast(self, payload: dict, exclude: WebSocket | None = None) -> None:
        """Send a JSON payload to every connected socket in this session, on any
        worker (optionally skipping one). Sockets that error are dropped."""
        exclude_id = self._local.get(exclude) if exclude is not None else None
        await self._deliver_local(payload, exclude_id)
        await self._backend.publish(
            self.group_session_id,
            {"payload": payload, "exclude_socket_id": exclude_id},
        )

    async def _deliver_remote(self, envelope: dict) -> None:
        await self._deliver_local(
            envelope.get("payload") or {}, envelope.get("exclude_socket_id")
        )

    async def _deliver_local(self, payload: dict, exclude_id: str | None) -> None:
        text = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws, socket_id in list(self._local.items()):
            if exclude_id is not None and socket_id == exclude_id:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            socket_id = self._local.pop(ws, None)
            if socket_id:
                await self._backend.unregister(self.group_session_id, socket_id)

    # -- turn lock --------------------------------------------------------

    # -- artifact section locks -------------------------------------------

    async def acquire_section(
        self, ws: WebSocket, section_key: str, user_id: str, name: str
    ) -> tuple[bool, dict]:
        """Take a section for editing. Returns (True, record) or (False, holder)."""
        socket_id = self._local.get(ws)
        if socket_id is None:
            return False, {}
        now = datetime.now(timezone.utc)
        record = {
            "section_key": section_key,
            "holder_user_id": user_id,
            "holder_name": name,
            "socket_id": socket_id,
            "nonce": uuid.uuid4().hex,
            "acquired_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=SECTION_LOCK_TTL_SEC)).isoformat(),
        }
        ok, holder = await self._backend.acquire_section(
            self.group_session_id, section_key, record
        )
        if ok:
            self._held_sections[section_key] = (socket_id, record["nonce"])
        return ok, holder

    async def release_section(self, ws: WebSocket, section_key: str) -> bool:
        """Release a section this socket holds. False if it didn't hold it."""
        socket_id = self._local.get(ws)
        held = self._held_sections.get(section_key)
        if socket_id is None or held is None or held[0] != socket_id:
            return False
        freed = await self._backend.release_section(
            self.group_session_id, section_key, held[1]
        )
        if freed:
            self._held_sections.pop(section_key, None)
        return freed

    async def release_sections_for_socket(self, socket_id: str) -> list[str]:
        """Release everything a departing socket held. This is the primary
        disconnect path -- the TTL is only a backstop for the worker dying."""
        freed: list[str] = []
        for section_key, (owner, nonce) in list(self._held_sections.items()):
            if owner != socket_id:
                continue
            if await self._backend.release_section(self.group_session_id, section_key, nonce):
                freed.append(section_key)
            self._held_sections.pop(section_key, None)
        return freed

    async def section_locks(self) -> list[dict]:
        """Every held section lock in this session, across all workers."""
        return await self._backend.section_locks(self.group_session_id)

    def holds_section(self, ws: WebSocket, section_key: str) -> bool:
        """Whether this exact socket holds the lock, per this worker's own view.
        A cheap pre-check; the authoritative check reads the lock from Redis."""
        socket_id = self._local.get(ws)
        held = self._held_sections.get(section_key)
        return socket_id is not None and held is not None and held[0] == socket_id

    async def try_acquire_turn(self) -> TurnToken | None:
        """Atomically take this session's turn lock, or return None if a turn is
        already in flight (on this or any other worker)."""
        return await self._backend.try_acquire(self.group_session_id)

    async def release_turn(self, token: TurnToken) -> None:
        await self._backend.release(self.group_session_id, token)

    # -- teardown ---------------------------------------------------------

    async def shutdown(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._heartbeat_task = None
        await self._backend.unsubscribe(self.group_session_id)


class RoomManager:
    def __init__(self):
        self._rooms: dict[str, GroupRoom] = {}
        self._guard = asyncio.Lock()
        self._backend = None

    # -- backend selection ------------------------------------------------

    @property
    def backend_name(self) -> str:
        return self._backend.name if self._backend else "uninitialised"

    def configure(self, redis_url: str | None = None) -> None:
        """Pick a backend. Called once at startup (and by tests)."""
        url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "").strip()
        if url:
            self._backend = RedisBackend(url)
            log.info(f"[room] using Redis backend ({url.split('@')[-1]}) -- multi-worker safe")
        else:
            self._backend = MemoryBackend()
            log.warning(
                "[room] REDIS_URL is not set -- group rooms are held in this process's "
                "memory. THIS IS SINGLE-WORKER ONLY: running more than one Uvicorn "
                "worker will silently break presence, the turn lock and broadcasts."
            )

    async def startup_check(self) -> None:
        """Verify the backend is reachable. Raises RedisUnavailable if Redis was
        configured but is down -- the caller logs it and keeps group chat closed
        rather than falling back to broken in-memory behaviour."""
        if self._backend is None:
            self.configure()
        await self._backend.ping()

    # -- rooms ------------------------------------------------------------

    async def get(self, group_session_id: str) -> GroupRoom:
        if self._backend is None:
            self.configure()
        async with self._guard:
            room = self._rooms.get(group_session_id)
            if room is None:
                room = GroupRoom(group_session_id, self._backend)
                self._rooms[group_session_id] = room
            return room

    async def drop_if_empty(self, group_session_id: str) -> None:
        """Tear down this worker's room once it owns no more sockets. Other
        workers keep their own rooms; the shared state lives in the backend."""
        async with self._guard:
            room = self._rooms.get(group_session_id)
            if room is not None and room.local_count() == 0:
                self._rooms.pop(group_session_id, None)
            else:
                room = None
        if room is not None:
            await room.shutdown()

    async def close(self) -> None:
        for gsid in list(self._rooms):
            room = self._rooms.pop(gsid)
            await room.shutdown()
        if self._backend is not None:
            await self._backend.close()


rooms = RoomManager()
