# Running more than one Uvicorn worker

Status as of 2026-10-04. Verified with two real Uvicorn processes sharing one
Redis and one Postgres database (see item 12 in `docs/collab-study-pending.md`).

**The short version.** On one worker, nothing here applies: leave `REDIS_URL`
unset and run as before. On more than one, `REDIS_URL` is **required**, not an
optimisation. Without it every worker keeps its own rooms, and teammates the
load balancer puts on different workers cannot see each other — the session
looks live and silently is not one.

---

## What `REDIS_URL` switches on

Everything below is off when `REDIS_URL` is unset, and the code then behaves
exactly as it did on a single worker.

| What | Where | Without Redis | With Redis |
|------|-------|---------------|------------|
| Group rooms: presence, broadcast, per-student coach lock, team turn lock | `backend/group_room.py` | In-process. Correct on one worker only. | Presence is a ZSET + HASH kept alive by a heartbeat; broadcast is pub/sub (each worker skips its own echo); locks are `SET NX PX` with a compare-and-delete release. Any worker can serve any member of a team. |
| Leases for background work | `backend/coordination.py` | Every acquire succeeds (one worker, nothing to coordinate). | A short-TTL key, renewed while the work runs, so score retries, session analyses and corpus ingests run once across workers rather than once per worker. |
| Auth rate limits | `backend/rate_limit.py` | Per-process counters: the effective limit is multiplied by the number of workers. | One shared sliding window per key, including the per-account login limit. |

Two things are shared across workers **without** Redis, because they live in
the database: the study event sequence (`UNIQUE(scope, seq)` in
`backend/events.py`) and artifact versions (`UNIQUE(section_id, version)`). A
cross-worker race on either becomes a retry or an ordinary edit conflict, never
a duplicate or a lost revision.

### When Redis is configured but unreachable

Each piece fails in the direction that is safe for it:

- **Group and coach sessions refuse to start.** `/ws/coach` and `/ws/group`
  close with code **4005** ("Collaboration backend unavailable") rather than
  degrading to per-worker rooms. If Redis is lost *mid-session* the socket is
  closed with **1011** (retryable); the reconnect is then refused with 4005 if
  Redis is still down. The coach workspace stops retrying on 4005, so students
  reload once Redis is back.
- **Solo chat is unaffected.** `/ws` never touches Redis.
- **Startup does not fail.** The lifespan pings Redis and logs a `CRITICAL`
  line ("Group rooms: redis backend UNREACHABLE …") but the app still boots.
  Watch for that line; nothing else will tell you until a team tries to join.
- **Leases fail open.** Every leased job is already safe to run twice
  (conditional updates), so an outage costs a duplicate model call, never a
  lost or corrupted row.
- **Rate limits fall back** to the per-worker counter: the limit loosens by a
  factor of the worker count, rather than locking everyone out.

A Redis *restart* is survivable: in the 2026-10-04 test the pub/sub listeners
re-subscribed (backoff 0.5 s up to 10 s) and sessions recovered in about 5 s.

---

## Startup

Every worker runs the same lifespan. On Postgres, `database.startup_lock`
takes a transaction-scoped advisory lock (`pg_advisory_xact_lock`) around
`init_db()` and the seeders, so workers booting together take turns instead of
racing through `CREATE TABLE`, the defensive `ALTER`s and the
insert-if-missing seeds. It needs no Redis, and it works through Supabase's
transaction pooler (port 6543) because it is transaction-scoped. On SQLite it
is a no-op. If the lock cannot be taken, boot carries on unserialised and logs
an error.

After the lock, every worker sweeps for stuck work (pending analyses, pending
scores, stranded corpus ingests). The leases above make each item run once.

---

## Timeouts, and what a crashed worker costs a team

Constants in `backend/group_room.py` and `backend/coordination.py`:

| Constant | Value | Meaning |
|----------|-------|---------|
| `HEARTBEAT_SEC` | 15 s | How often a worker refreshes presence for its sockets. |
| `MEMBER_TTL_SEC` | 45 s | Presence without a heartbeat for this long is dropped. |
| `COACH_LOCK_TTL_SEC` | 300 s | One student's private coach turn (`/ws/coach`). |
| `TURN_LOCK_TTL_SEC` | 300 s | The whole team's shared-coach turn (legacy `/ws/group`). |
| `LEASE_TTL_SEC` / `LEASE_RENEW_SEC` | 60 s / 20 s | Background-work lease lifetime and renewal interval. |
| `REDIS_TIMEOUT_SEC` | 5 s | Bound on every Redis command, so a hung Redis surfaces as unavailable instead of hanging a socket. |

Locks are released in a `finally`; the TTL only matters when a worker dies
without running it (SIGKILL, OOM, a host going away). Then:

- **The student whose coach turn was running** reconnects to another worker,
  but their coach answers `busy` until the 300 s lock expires. Their teammates'
  coaches are not affected — the lock is per student.
- **On `/ws/group`** the same happens to the whole team: no AI turn for up to
  300 s.
- **Presence.** The dead worker's members keep counting as present for up to
  45 s, which matters for the `team_min` gate. When they age out, the surviving
  workers' heartbeats push the new roster to their sockets (within one
  heartbeat).
- **Background work** the dead worker held becomes claimable when its lease
  lapses, within 60 s.

300 s is deliberately long: a slow model call plus inline evaluation must fit
inside it, or a live turn would lose its lock to a second one. A worker crash is
therefore a five-minute stall for one student, not data loss.

---

## How to run

```bash
cd backend
REDIS_URL=redis://<host>:6379/0 uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2
```

`--workers` cannot be combined with `--reload`. The default start command in
`backend/nixpacks.toml` runs a single worker; change it there to deploy more.
No sticky sessions are needed at the load balancer once Redis is on.

---

## Pre-deploy checklist

1. `REDIS_URL` is set on the backend service and points at a Redis every worker
   can reach. Use a dedicated instance or database index: keys are namespaced
   `husky:room:*`, `husky:lease:*` and `huskyai:rl:*`, but nothing else
   should be evicting them.
2. The Redis eviction policy does not drop keys with a TTL under memory
   pressure (`noeviction` or a generous `maxmemory`). An evicted lock is a
   second concurrent turn; an evicted presence entry is a teammate vanishing.
3. Database connections fit. Each worker has its own pool: on the session
   pooler or a direct connection that is `DB_POOL_SIZE` + `DB_MAX_OVERFLOW`
   (default 5 + 2 = 7) per worker, against a cap of about 15 on Supabase's
   session pooler. Two workers fit; three do not. Prefer the transaction
   pooler (port 6543), where the app uses no client-side pool.
4. The real-Redis test suite passes against that Redis (below).
5. After deploy, the boot log of **every** worker says
   `Group rooms: redis backend ready`, not `in-process` and not `UNREACHABLE`.
6. Smoke test: two teammates in one team, on different workers. Connections
   are spread by the OS, so open several tabs; to be certain, run two
   single-worker processes on two ports and point one teammate at each, which
   is how this was verified. Each sees the other present, a shared-document
   edit reaches the other, and ending the session ends it for both.

---

## Running the Redis tests

The real-Redis tests are skipped in an ordinary run (that is the "10 skipped"
in the suite summary). Point them at a scratch Redis:

```bash
cd backend
REDIS_URL=redis://localhost:6379/0 .venv/bin/python -m pytest \
  tests/test_multiworker_redis.py tests/test_rate_limit_shared.py tests/test_group_room_redis.py -v
```

`test_multiworker_redis.py` and `test_rate_limit_shared.py` need the server
(10 tests between them): pub/sub delivery, a killed subscription coming back,
key TTLs, lease renewal, a command timeout against a stalled server, and a
rate-limit window shared by independent clients. `test_group_room_redis.py`
runs without a server, through an injected fake; it is listed so one command
covers the whole Redis surface. All of these passed against a real Redis on
2026-10-04.

---

## Known limitation

A score that arrives late (a turn whose first evaluation failed and is retried
in the background) is pushed live only to sockets on the worker that ran the
retry. For a solo student or a private coach on a different worker, the score
is still saved and appears in their history, but it is not pushed to the open
tab, and in the solo arm the `feed.shown` and `revision.opened` events for it
are not logged. Rare, since it needs a failed evaluation first, but it is a
difference between one worker and several.
