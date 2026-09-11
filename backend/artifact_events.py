"""Append-only research log for artifact reads and writes.

Design constraints this module exists to enforce:

1. ONE sequence space. Reads and writes share a single monotonic `seq` per group
   session. The research question is whether a student read a teammate's section
   before or after writing their own, which cannot be answered if the two live on
   separate clocks.

2. NEVER sampled. Every qualifying event is written. Duplicates from retries and
   reconnects are collapsed on an idempotency key, which is the opposite of
   dropping: a duplicate is recognised as the same event, not discarded as noise.

3. Human reads and coach reads are structurally separable. `log_student_read` and
   `log_coach_read` are different functions; each hard-codes its own actor_kind
   and rejects the other's event types, and the DB CHECK constraint refuses a
   coach event that carries a user (or a student event that does not). There is
   no code path that can emit a coach read as a human one.

4. Asymmetric retention. Everything here is permanent. Raw dwell samples live in
   ArtifactReadHeartbeat and are the only thing prunable or sheddable -- and when
   shedding happens, `log_heartbeat_shed` records that it happened, so the loss
   is visible in the permanent log rather than silently absorbed.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database import ArtifactEvent, ArtifactReadHeartbeat, AsyncSessionLocal

log = logging.getLogger("artifact_events")

# Event types
EVENT_SECTION_OPEN = "section_open"
EVENT_SECTION_EXPAND = "section_expand"
EVENT_SECTION_WRITE = "section_write"
EVENT_SECTION_READ_BY_COACH = "section_read_by_coach"
EVENT_HEARTBEAT_SHED = "heartbeat_shed"

# A human "read" is one of exactly these. Kept as a frozenset so a caller cannot
# widen it by passing something else through.
STUDENT_READ_TYPES = frozenset({EVENT_SECTION_OPEN, EVENT_SECTION_EXPAND})

ACTOR_STUDENT = "student"
ACTOR_COACH = "coach"
ACTOR_SYSTEM = "system"

_MAX_SEQ_ATTEMPTS = 8


class EventCategoryError(ValueError):
    """Raised when a caller tries to log an event under the wrong actor kind."""


async def _append(
    *,
    group_session_id: str,
    event_type: str,
    actor_kind: str,
    actor_user_id: str | None,
    section_key: str | None,
    idempotency_key: str,
    client_ts: datetime | None = None,
    dwell_ms: int | None = None,
    surface: str | None = None,
    meta: dict | None = None,
) -> dict:
    """Append one event, allocating the next seq for this session.

    seq comes from MAX(seq)+1 under UNIQUE(group_session_id, seq), retried on
    conflict. Deliberately NOT a Redis INCR: Redis is a cache here, and a flush
    would replay seq numbers into what is meant to be a permanent research log.
    The database is the system of record and has to be up regardless.

    Returns the stored event. If `idempotency_key` was already used in this
    session the existing row is returned unchanged -- a retry is recognised, not
    dropped and not duplicated.
    """
    for attempt in range(_MAX_SEQ_ATTEMPTS):
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(
                select(ArtifactEvent).where(
                    ArtifactEvent.group_session_id == group_session_id,
                    ArtifactEvent.idempotency_key == idempotency_key,
                )
            )).scalar_one_or_none()
            if existing is not None:
                return _as_dict(existing, duplicate=True)

            next_seq = (await db.scalar(
                select(func.coalesce(func.max(ArtifactEvent.seq), 0) + 1).where(
                    ArtifactEvent.group_session_id == group_session_id
                )
            )) or 1

            row = ArtifactEvent(
                group_session_id=group_session_id,
                seq=int(next_seq),
                event_type=event_type,
                actor_kind=actor_kind,
                actor_user_id=actor_user_id,
                section_key=section_key,
                client_ts=client_ts,
                server_ts=datetime.utcnow(),
                dwell_ms=dwell_ms,
                surface=surface,
                idempotency_key=idempotency_key,
                meta=meta,
            )
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                # Either another worker took this seq, or the same event arrived
                # twice concurrently. The next loop distinguishes them: a
                # duplicate idempotency key is found and returned, a seq clash
                # simply gets a fresh number.
                continue
            return _as_dict(row, duplicate=False)

    raise RuntimeError(
        f"could not allocate a seq for session {group_session_id} after "
        f"{_MAX_SEQ_ATTEMPTS} attempts"
    )


def _as_dict(row: ArtifactEvent, *, duplicate: bool) -> dict:
    return {
        "id": row.id,
        "seq": row.seq,
        "event_type": row.event_type,
        "actor_kind": row.actor_kind,
        "actor_user_id": row.actor_user_id,
        "section_key": row.section_key,
        "dwell_ms": row.dwell_ms,
        "surface": row.surface,
        "idempotency_key": row.idempotency_key,
        "server_ts": row.server_ts.isoformat() if row.server_ts else None,
        "client_ts": row.client_ts.isoformat() if row.client_ts else None,
        # meta carries the things analysis actually needs and cannot reconstruct:
        # a write's version and content_len, and for a coach read the section
        # version, character count and whether the snapshot was truncated or had
        # sections dropped for budget. Omitting it from the module's only read
        # API left that recorded-but-unreadable, i.e. effectively silent.
        "meta": row.meta,
        "duplicate": duplicate,
    }


# ---------------------------------------------------------------------------
# Public append helpers -- one per actor kind, deliberately not unified
# ---------------------------------------------------------------------------

async def log_student_read(
    *,
    group_session_id: str,
    user_id: str,
    section_key: str,
    event_type: str,
    idempotency_key: str,
    dwell_ms: int | None = None,
    client_ts: datetime | None = None,
    surface: str | None = None,
    meta: dict | None = None,
) -> dict:
    """A human opened or expanded a section and dwelled past the threshold.

    Requires a user_id and refuses anything outside STUDENT_READ_TYPES, so a
    coach read can never be recorded through this function.
    """
    if event_type not in STUDENT_READ_TYPES:
        raise EventCategoryError(
            f"{event_type!r} is not a human read; use log_coach_read for coach "
            f"reads. Allowed: {sorted(STUDENT_READ_TYPES)}"
        )
    if not user_id:
        raise EventCategoryError("a student read must carry the student's user_id")
    return await _append(
        group_session_id=group_session_id,
        event_type=event_type,
        actor_kind=ACTOR_STUDENT,
        actor_user_id=user_id,
        section_key=section_key,
        idempotency_key=idempotency_key,
        client_ts=client_ts,
        dwell_ms=dwell_ms,
        surface=surface,
        meta=meta,
    )


async def log_coach_read(
    *,
    group_session_id: str,
    section_key: str,
    idempotency_key: str,
    meta: dict | None = None,
) -> dict:
    """The AI coach pulled a section into its own context.

    This is NOT a human read and must never be counted as one: the entire point
    of the log is measuring human read-before-write behaviour. Takes no user_id
    at all, so there is nothing to mistakenly attribute a student to.
    """
    return await _append(
        group_session_id=group_session_id,
        event_type=EVENT_SECTION_READ_BY_COACH,
        actor_kind=ACTOR_COACH,
        actor_user_id=None,
        section_key=section_key,
        idempotency_key=idempotency_key,
        meta=meta,
    )


async def log_section_write(
    *,
    group_session_id: str,
    user_id: str,
    section_key: str,
    idempotency_key: str,
    version: int | None = None,
    content_len: int | None = None,
) -> dict:
    """A student committed a change to a section.

    Shares the same seq space as reads, which is what makes "did they read the
    teammate's section before or after writing?" answerable.
    """
    if not user_id:
        raise EventCategoryError("a write must carry the author's user_id")
    return await _append(
        group_session_id=group_session_id,
        event_type=EVENT_SECTION_WRITE,
        actor_kind=ACTOR_STUDENT,
        actor_user_id=user_id,
        section_key=section_key,
        idempotency_key=idempotency_key,
        meta={"version": version, "content_len": content_len},
    )


async def log_heartbeat_shed(
    *, group_session_id: str, dropped: int, reason: str, idempotency_key: str
) -> dict:
    """Record that low-value heartbeat samples were shed.

    Shedding may only ever discard heartbeats -- never a qualifying read. The
    fact that it happened is itself appended to the permanent log so the gap is
    visible to anyone analysing the data, rather than silently absorbed.
    """
    return await _append(
        group_session_id=group_session_id,
        event_type=EVENT_HEARTBEAT_SHED,
        actor_kind=ACTOR_SYSTEM,
        actor_user_id=None,
        section_key=None,
        idempotency_key=idempotency_key,
        meta={"dropped": dropped, "reason": reason},
    )


# ---------------------------------------------------------------------------
# Heartbeats -- the prunable, sheddable tier
# ---------------------------------------------------------------------------

# Above this many heartbeats in one session we stop storing them. Reads are
# never affected; only these samples are.
HEARTBEAT_SOFT_CAP = int(os.getenv("ARTIFACT_HEARTBEAT_CAP", "5000"))


async def record_heartbeat(
    *, group_session_id: str, user_id: str, section_key: str, visible_ms: int
) -> bool:
    """Store one raw dwell sample. Returns False if it was shed.

    Shedding logs a heartbeat_shed event into the permanent log, so the loss is
    recorded. A qualifying read is never routed through here.
    """
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count()).select_from(ArtifactReadHeartbeat).where(
                ArtifactReadHeartbeat.group_session_id == group_session_id
            )
        )
        if (count or 0) >= HEARTBEAT_SOFT_CAP:
            shed = True
        else:
            db.add(ArtifactReadHeartbeat(
                group_session_id=group_session_id,
                user_id=user_id,
                section_key=section_key,
                visible_ms=visible_ms,
            ))
            await db.commit()
            shed = False

    if shed:
        await log_heartbeat_shed(
            group_session_id=group_session_id,
            dropped=1,
            reason="heartbeat_soft_cap",
            idempotency_key=f"shed:{group_session_id}:{datetime.utcnow().isoformat()}",
        )
        return False
    return True


async def session_events(group_session_id: str) -> list[dict]:
    """The session's full event log in seq order. Used by tests and analysis."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ArtifactEvent)
            .where(ArtifactEvent.group_session_id == group_session_id)
            .order_by(ArtifactEvent.seq)
        )).scalars().all()
        return [_as_dict(r, duplicate=False) for r in rows]
