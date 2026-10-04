"""Cross-worker leases for background work that must run once, not once per worker.

Each Uvicorn worker runs the same startup sweeps and owns its own background
tasks (score retries, session analyses, corpus ingests). On one worker that is
exactly right. On several, every worker re-queues the same pending rows at
boot, and a worker that restarts treats its siblings' in-flight work as
abandoned. A lease says "a live worker is on this right now":

    lease = await acquire("rescore:<eval id>")
    if lease is None:
        return              # another live worker holds it
    try:
        ...                 # the work
    finally:
        await lease.release()

A lease is a Redis key with a short TTL that a background task keeps renewing
while the holder runs. A worker that dies stops renewing, so its leases lapse
within LEASE_TTL_SEC and the work becomes claimable again.

Without REDIS_URL there is only one worker, nothing to coordinate with, and
every acquire succeeds: behaviour is exactly what it was before leases existed.

If Redis is configured but failing, acquire also succeeds (fails OPEN). Every
leased job is already safe to run twice -- the writes are conditional UPDATEs
or idempotent -- so a Redis outage costs a duplicate model call, never a lost
or corrupted row. `is_held` is the exception: it answers None ("unknown")
rather than guessing, because its caller takes destructive action on False.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

log = logging.getLogger("coordination")

# How long a lease survives without renewal, i.e. how quickly a dead worker's
# work becomes claimable again.
LEASE_TTL_SEC = 60
# How often a holder renews. Comfortably inside the TTL, so one slow round trip
# does not lose a lease that is still being worked.
LEASE_RENEW_SEC = 20
# Bound every command: a Redis that hangs must not hang the work behind it.
REDIS_TIMEOUT_SEC = 5

# Renew / release only if we still hold it: a lease that already lapsed and was
# taken by another worker must not be extended or freed by the previous holder.
_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_client = None
_client_loop = None
_injected = False


def _key(name: str) -> str:
    return f"husky:lease:{name}"


def configure(client=None) -> None:
    """Test hook: inject a client (or None to drop back to REDIS_URL)."""
    global _client, _injected
    _client = client
    _injected = client is not None


def _redis():
    """The shared client, built on first use; None when REDIS_URL is unset.

    Rebuilt if the running event loop changed: an asyncio client's connections
    belong to the loop that opened them (tests run several loops)."""
    global _client, _client_loop
    if _injected:
        return _client
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or _client_loop is not loop:
        from redis.asyncio import Redis  # imported here so redis stays optional

        _client = Redis.from_url(
            url, decode_responses=True,
            socket_timeout=REDIS_TIMEOUT_SEC, socket_connect_timeout=REDIS_TIMEOUT_SEC,
        )
        _client_loop = loop
    return _client


def enabled() -> bool:
    """True when leases are backed by Redis (i.e. several workers may exist)."""
    return _redis() is not None


class Lease:
    """A held lease. `shared` is False when nothing backs it (no Redis, or
    Redis failing at acquire time) -- it then excludes nobody, by design."""

    def __init__(self, name: str, token: str | None = None):
        self.name = name
        self._token = token
        self._renewer: asyncio.Task | None = None
        if token is not None:
            self._renewer = asyncio.create_task(self._renew_loop())

    @property
    def shared(self) -> bool:
        return self._token is not None

    async def _renew_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(LEASE_RENEW_SEC)
                try:
                    ok = await _redis().eval(
                        _RENEW_LUA, 1, _key(self.name), self._token, LEASE_TTL_SEC)
                except Exception as e:
                    # Keep trying: one failed renewal is survivable inside the TTL.
                    log.warning(f"[lease] renew failed for {self.name}: {type(e).__name__}: {e}")
                    continue
                if not ok:
                    log.warning(f"[lease] {self.name} lapsed while held; another worker may take it")
                    return
        except asyncio.CancelledError:
            pass

    async def release(self) -> None:
        if self._renewer is not None:
            self._renewer.cancel()
            self._renewer = None
        if self._token is None:
            return
        token, self._token = self._token, None
        try:
            await _redis().eval(_RELEASE_LUA, 1, _key(self.name), token)
        except Exception as e:
            # The TTL frees it shortly either way.
            log.warning(f"[lease] release failed for {self.name}: {type(e).__name__}: {e}")


async def acquire(name: str) -> Lease | None:
    """Take the lease, or None if another live worker holds it."""
    r = _redis()
    if r is None:
        return Lease(name)
    token = uuid.uuid4().hex
    try:
        ok = await r.set(_key(name), token, nx=True, ex=LEASE_TTL_SEC)
    except Exception as e:
        log.error(f"[lease] Redis unavailable taking {name} ({type(e).__name__}: {e}); "
                  "running without it (a duplicate run is possible, a lost one is not)")
        return Lease(name)
    return Lease(name, token) if ok else None


async def is_held(name: str) -> bool | None:
    """Whether a live worker holds this lease. False when there is no Redis
    (one worker: nothing else can be running it); None when Redis is
    configured but cannot be asked."""
    r = _redis()
    if r is None:
        return False
    try:
        return bool(await r.exists(_key(name)))
    except Exception as e:
        log.error(f"[lease] Redis unavailable checking {name}: {type(e).__name__}: {e}")
        return None


async def close() -> None:
    global _client, _client_loop
    if _client is not None and not _injected:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client, _client_loop = None, None
