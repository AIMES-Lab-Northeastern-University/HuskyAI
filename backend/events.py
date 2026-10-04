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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class EventResult:
    """What happened to one event. `saved` and `duplicate` both mean the row is
    in the log (a duplicate was recorded by an earlier delivery); `failed` means
    it is not, and the caller must not tell anyone it is."""

    status: str                 # "saved" | "duplicate" | "failed"
    event_id: str | None = None

    @property
    def recorded(self) -> bool:
        return self.status in ("saved", "duplicate")


_FAILED = EventResult("failed")


def _validate(action, target, actor_kind, group_session_id, user_challenge_session_id) -> bool:
    if bool(group_session_id) == bool(user_challenge_session_id):
        log.error(
            "log_event needs exactly one session scope (got group=%s solo=%s) for %s.%s",
            group_session_id, user_challenge_session_id, target, action,
        )
        return False
    if actor_kind not in ACTOR_KINDS:
        log.error("log_event: unknown actor_kind %r for %s.%s", actor_kind, target, action)
        return False
    if target not in TARGETS:
        log.error("log_event: unknown target %r for action %r", target, action)
        return False
    return True


async def add_event_in(
    db,
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
) -> StudyEvent:
    """Allocate the next seq and add the event to the CALLER's transaction.

    For writes whose record must not be separable from the thing it records:
    an artifact write and its revision commit or roll back together, so the log
    can never show a revision with no event or an event with no revision. The
    caller commits, and on IntegrityError/OperationalError at commit must roll
    back and retry the whole transaction. UNIQUE(scope, seq) is still what keeps
    two allocators from sharing a number.

    Raises ValueError for a malformed event (the same checks log_event makes)."""
    if not _validate(action, target, actor_kind, group_session_id, user_challenge_session_id):
        raise ValueError(f"malformed study event {target}.{action}")

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
        await db.execute(select(func.max(StudyEvent.seq)).where(scope_col == scope_val))
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
    return event


async def record_event(**kwargs) -> EventResult:
    """Append one event in its own transaction and say what happened.

    Writes in its own transaction rather than joining the caller's. That is
    deliberate: a turn save that rolls back for an unrelated reason must not also
    erase the record that the turn was attempted. (Where the two must be one
    unit, use add_event_in.)

    Never raises. A logging failure must not break a student's session, but it is
    logged at ERROR, because a silent gap in this table is the one failure mode
    the study cannot recover from. The status lets a caller that promised the
    client durability (a read ack) keep that promise only when it is true.
    """
    action, target = kwargs.get("action"), kwargs.get("target")
    if not _validate(action, target, kwargs.get("actor_kind", "student"),
                     kwargs.get("group_session_id"), kwargs.get("user_challenge_session_id")):
        return _FAILED

    idempotency_key = kwargs.get("idempotency_key")
    scope_key = _scope_key(kwargs.get("group_session_id"), kwargs.get("user_challenge_session_id"))

    try:
        for attempt in range(_MAX_SEQ_RETRIES):
            async with AsyncSessionLocal() as db:
                # Dedupe before allocating a seq, so a retried client delivery
                # doesn't burn a sequence number and leave a hole.
                if idempotency_key:
                    existing = await db.execute(
                        select(StudyEvent.id).where(StudyEvent.idempotency_key == idempotency_key)
                    )
                    existing_id = existing.scalar_one_or_none()
                    if existing_id is not None:
                        return EventResult("duplicate", existing_id)

                event = await add_event_in(db, **kwargs)
                try:
                    await db.commit()
                    return EventResult("saved", event.id)
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
    return _FAILED


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
    """Append one event and return its id: None if it was a duplicate or the
    write failed. Callers that need to tell those two apart use record_event.
    Never raises."""
    result = await record_event(
        action=action, target=target, actor_kind=actor_kind,
        group_session_id=group_session_id,
        user_challenge_session_id=user_challenge_session_id,
        actor_user_id=actor_user_id, role_label=role_label,
        classroom_id=classroom_id, challenge_id=challenge_id, ref_id=ref_id,
        payload=payload, client_ts=client_ts, idempotency_key=idempotency_key,
        condition=condition, consent_research=consent_research,
    )
    return result.event_id if result.status == "saved" else None
