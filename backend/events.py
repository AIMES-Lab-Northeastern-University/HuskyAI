"""The study event log's single write path.

Every action in a collaborative-study session — a coach turn, an artifact write,
and above all a *read* of a teammate's work — goes through `log_event`. Nothing
else writes `study_events`, because the ordering guarantee below only holds if
`seq` has exactly one allocator.

SINGLE-WORKER ONLY, same constraint as group_room.py. `seq` is allocated under an
in-process lock, so two Uvicorn workers would allocate the same number. The unique
constraint on (scope, seq) turns that into a retry rather than silent corruption,
but the real fix for multi-worker is a DB sequence per session or Redis.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database import AsyncSessionLocal, StudyEvent, User

log = logging.getLogger("study_events")

# Vocabularies. Kept here rather than as DB constraints so a new event type is a
# one-line change, but validated on write so a typo doesn't create a silent
# category that analysis will never find. Mirrored in docs/event-schema.md.
ACTOR_KINDS = {"student", "coach", "system"}
TARGETS = {"coach", "artifact", "group_chat", "feed", "contested", "verification"}

# How many times to retry when a (scope, seq) collision means someone else took
# our number. Only reachable under multiple workers or a lock bug.
_MAX_SEQ_RETRIES = 5

# One lock per session scope, so unrelated sessions never serialise against each
# other. Created lazily; the dict itself is guarded because asyncio tasks can
# interleave at any await.
_seq_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(scope_key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _seq_locks.get(scope_key)
        if lock is None:
            lock = asyncio.Lock()
            _seq_locks[scope_key] = lock
        return lock


def forget_session(group_session_id: str | None = None, user_challenge_session_id: str | None = None) -> None:
    """Drop a finished session's seq lock so the dict doesn't grow without bound.
    Safe to call on a session that is still live: the next event just recreates
    the lock, and `seq` continues from the database's MAX, not from memory."""
    scope_key = _scope_key(group_session_id, user_challenge_session_id)
    _seq_locks.pop(scope_key, None)


def _scope_key(group_session_id: str | None, user_challenge_session_id: str | None) -> str:
    return f"g:{group_session_id}" if group_session_id else f"u:{user_challenge_session_id}"


async def log_event(
    *,
    action: str,
    target: str,
    actor_kind: str = "student",
    group_session_id: str | None = None,
    user_challenge_session_id: str | None = None,
    actor_user_id: str | None = None,
    role_label: str | None = None,
    classroom_id: str | None = None,
    challenge_id: str | None = None,
    ref_id: str | None = None,
    payload: dict | None = None,
    client_ts: datetime | None = None,
    idempotency_key: str | None = None,
    condition: dict | None = None,
    consent_research: bool | None = None,
) -> str | None:
    """Append one event to the log and return its id (None if it was a duplicate
    or the write failed).

    Writes in its own transaction rather than joining the caller's. That is
    deliberate: a turn save that rolls back for an unrelated reason must not also
    erase the record that the turn was attempted, and the caller cannot hold the
    seq lock across its own commit without serialising the whole session.

    Never raises. A logging failure must not break a student's session — but it is
    logged at ERROR, because a silent gap in this table is the one failure mode
    the study cannot recover from.
    """
    if bool(group_session_id) == bool(user_challenge_session_id):
        log.error(
            "log_event needs exactly one session scope (got group=%s solo=%s) for %s.%s",
            group_session_id, user_challenge_session_id, target, action,
        )
        return None
    if actor_kind not in ACTOR_KINDS:
        log.error("log_event: unknown actor_kind %r for %s.%s", actor_kind, target, action)
        return None
    if target not in TARGETS:
        log.error("log_event: unknown target %r for action %r", target, action)
        return None

    scope_key = _scope_key(group_session_id, user_challenge_session_id)
    lock = await _lock_for(scope_key)

    try:
        async with lock:
            for attempt in range(_MAX_SEQ_RETRIES):
                async with AsyncSessionLocal() as db:
                    # Dedupe before allocating a seq, so a retried client delivery
                    # doesn't burn a sequence number and leave a hole.
                    if idempotency_key:
                        existing = await db.execute(
                            select(StudyEvent.id).where(StudyEvent.idempotency_key == idempotency_key)
                        )
                        if existing.scalar_one_or_none() is not None:
                            return None

                    consent_now = consent_research
                    if consent_now is None:
                        consent_now = False
                        if actor_user_id:
                            actor = await db.get(User, actor_user_id)
                            consent_now = bool(actor.consent_research) if actor else False

                    scope_col = (
                        StudyEvent.group_session_id if group_session_id
                        else StudyEvent.user_challenge_session_id
                    )
                    scope_val = group_session_id or user_challenge_session_id
                    current_max = (
                        await db.execute(
                            select(func.max(StudyEvent.seq)).where(scope_col == scope_val)
                        )
                    ).scalar()

                    event = StudyEvent(
                        group_session_id=group_session_id,
                        user_challenge_session_id=user_challenge_session_id,
                        classroom_id=classroom_id,
                        challenge_id=challenge_id,
                        seq=(current_max or 0) + 1,
                        actor_user_id=actor_user_id,
                        actor_kind=actor_kind,
                        role_label=role_label,
                        target=target,
                        action=action,
                        ref_id=ref_id,
                        payload=payload,
                        client_ts=client_ts,
                        server_ts=datetime.utcnow(),
                        idempotency_key=idempotency_key,
                        consent_research=consent_now,
                        condition=condition,
                    )
                    db.add(event)
                    try:
                        await db.commit()
                        return event.id
                    except IntegrityError:
                        await db.rollback()
                        if attempt == _MAX_SEQ_RETRIES - 1:
                            raise
                        # Someone took our seq (or raced us to the idempotency
                        # key). Re-read MAX and try again.
                        continue
    except Exception as e:
        log.error("study event NOT recorded (%s.%s, scope=%s): %s", target, action, scope_key, e)
        return None
