"""The study event log's single write path.

Every action in a collaborative-study session — a coach turn, an artifact write,
and above all a *read* of a teammate's work — goes through `log_event`. Nothing
else writes `study_events`, because the ordering guarantee below only holds if
`seq` has exactly one allocator.

MULTI-WORKER SAFE. `seq` is allocated as MAX(seq)+1 for the scope, and the
database enforces it: UNIQUE(scope, seq) means a second allocator that picks the
same number loses its INSERT and retries with a fresh one. There is deliberately
no in-process lock — a lock only orders the writers inside one Uvicorn worker,
so it is both insufficient (two workers still collide) and misleading (it reads
as if the ordering were guaranteed in memory). The constraint is the guarantee.

Deliberately NOT a Redis INCR either. Redis is a cache in this deployment, and a
flush would replay sequence numbers into what is meant to be a permanent
research log. The database is the system of record and has to be up regardless.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from database import AsyncSessionLocal, StudyEvent, User

log = logging.getLogger("study_events")

# Vocabularies. Kept here rather than as DB constraints so a new event type is a
# one-line change, but validated on write so a typo doesn't create a silent
# category that analysis will never find. Mirrored in docs/event-schema.md.
ACTOR_KINDS = {"student", "coach", "system"}
TARGETS = {"coach", "artifact", "group_chat", "feed", "contested", "verification"}

# Retries when someone else took our number. Now that contention is resolved at
# the database rather than serialised in memory, a busy session can lose several
# races in a row: with W concurrent writers a given attempt is only guaranteed to
# make progress for one of them, so the ceiling is generous.
_MAX_SEQ_RETRIES = 8


def _scope_key(group_session_id: str | None, user_challenge_session_id: str | None) -> str:
    """Logging label only. Nothing keys state on this now that there is no lock
    table to key — kept because a scope in an error line is worth having."""
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

    try:
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
                except (IntegrityError, OperationalError) as e:
                    await db.rollback()
                    if attempt == _MAX_SEQ_RETRIES - 1:
                        raise
                    # Someone took our seq, or raced us to the idempotency key,
                    # or (SQLite) held the write lock. The next pass
                    # distinguishes them: a duplicate key is found and returns,
                    # a seq clash simply gets a fresh number.
                    log.debug("seq retry %d for %s.%s (%s)", attempt + 1, target, action, type(e).__name__)
                    continue
    except Exception as e:
        log.error("study event NOT recorded (%s.%s, scope=%s): %s", target, action, scope_key, e)
        return None
