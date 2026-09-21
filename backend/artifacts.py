"""The shared artifact: the one document a team reads and writes together.

Two responsibilities, kept together because they must not drift apart:

1. **Writes** are per-section and optimistically concurrent. A writer sends the
   version it was looking at; if a teammate got there first the write is
   rejected with the current content so the client can rebase. Nothing is ever
   silently clobbered, and every accepted write appends an ArtifactRevision that
   is never pruned.
2. **Reads are logged as first-class events.** Every function here that exposes
   a teammate's text to someone — a human opening a section, or a coach having
   the artifact injected into its prompt — emits a study event. That is not
   incidental telemetry: a read that goes unlogged cannot be reconstructed later,
   and "did this student read that teammate's work before writing their own?" is
   the question the study exists to answer.

SINGLE-WORKER ONLY, same constraint as group_room.py and events.py: write
serialisation uses an in-process lock per artifact.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import (
    Artifact,
    ArtifactRevision,
    ArtifactSection,
    AsyncSessionLocal,
    GroupChallenge,
    GroupSession,
    User,
)
from events import forget_session as events_forget_session
from events import log_event

log = logging.getLogger("artifacts")

# An artifact whose assignment defines no sections still has exactly one, so the
# read/write path never needs a "sectioned or not" branch. It just looks like a
# free-form document to the student.
IMPLICIT_SECTION_KEY = "body"

# Where a section's new text came from. The difference between text a student
# typed and text they lifted out of their coach is a finding, not bookkeeping.
ORIGINS = {"student_typed", "coach_copied", "verification_edit"}

MAX_SECTION_KEY_LEN = 64


class ArtifactConfigError(ValueError):
    """The instructor's section decomposition is unusable. Raised at creation
    time, loudly: a malformed decomposition that fails silently would leave a
    team with an artifact shaped differently from their assignment, and sections
    are never restructured afterwards."""


def _validate_section_defs(section_defs: list[dict] | None) -> list[dict]:
    """Normalise and check the instructor's decomposition.

    Keys are rejected rather than truncated. Silently cutting a key at 64 chars
    turns two distinct sections into one collision, which used to surface as an
    unexplained failure to create the artifact at all."""
    if not section_defs:
        return [{"key": IMPLICIT_SECTION_KEY, "title": None}]

    out: list[dict] = []
    seen: set[str] = set()
    for i, d in enumerate(section_defs):
        key = str(d.get("key") or f"section-{i + 1}").strip()
        if not key:
            raise ArtifactConfigError(f"section {i + 1} has an empty key")
        if len(key) > MAX_SECTION_KEY_LEN:
            raise ArtifactConfigError(
                f"section key {key[:20]!r}... is {len(key)} chars, max {MAX_SECTION_KEY_LEN}"
            )
        if key in seen:
            raise ArtifactConfigError(f"duplicate section key {key!r}")
        seen.add(key)
        out.append({"key": key, "title": d.get("title") or None})
    return out


_write_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(artifact_id: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _write_locks.get(artifact_id)
        if lock is None:
            lock = asyncio.Lock()
            _write_locks[artifact_id] = lock
        return lock


def forget_artifact(artifact_id: str) -> None:
    """Drop a finished artifact's write lock so the dict doesn't grow without
    bound on a long-running worker. Safe while live: the next write recreates
    the lock, and correctness rests on the DB `version`, not on the lock."""
    _write_locks.pop(artifact_id, None)


async def forget_session(group_session_id: str) -> None:
    """Release the in-process state for a session that has gone quiet — both
    this module's write lock and the event log's seq lock. Called when the last
    member disconnects."""
    async with AsyncSessionLocal() as db:
        artifact_id = (
            await db.execute(
                select(Artifact.id).where(Artifact.group_session_id == group_session_id)
            )
        ).scalar_one_or_none()
    if artifact_id:
        forget_artifact(artifact_id)
    events_forget_session(group_session_id=group_session_id)


def _diff_bytes(old: str, new: str) -> tuple[int, int]:
    """Characters actually added and removed, not just the net length change —
    a rewrite that keeps the length identical is not a no-op edit."""
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


async def _scope(db, group_session_id: str) -> dict:
    """classroom_id / challenge_id for the event log, so analysis can filter
    without joining back through four tables."""
    gs = await db.get(GroupSession, group_session_id)
    if gs is None:
        return {}
    classroom_id = None
    gc = await db.get(GroupChallenge, gs.group_id)
    if gc is not None:
        classroom_id = gc.classroom_id
    return {"classroom_id": classroom_id, "challenge_id": gs.challenge_id}


async def get_or_create(group_session_id: str, section_defs: list[dict] | None = None) -> str:
    """Return the artifact id for a group session, creating it on first touch.

    `section_defs` is the instructor's decomposition for this assignment, as
    [{"key", "title"}] in display order. Absent or empty means a single implicit
    section, i.e. a free-form document. Sections are created once; a later change
    to the assignment does not restructure an artifact a team has already written
    into, because that would orphan revisions and break read attribution.

    Safe to call concurrently: teammates typically connect at the same moment, so
    the check-then-insert is a real race, not a theoretical one. The unique
    constraint on group_session_id is the arbiter — the loser re-reads the
    winner's row rather than failing."""
    defs = _validate_section_defs(section_defs)
    for _ in range(3):
        async with AsyncSessionLocal() as db:
            existing = (
                await db.execute(
                    select(Artifact).where(Artifact.group_session_id == group_session_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id

            artifact = Artifact(group_session_id=group_session_id)
            db.add(artifact)
            try:
                await db.flush()
            except IntegrityError:
                # A teammate created it between our SELECT and our INSERT.
                await db.rollback()
                continue

            for i, d in enumerate(defs):
                db.add(ArtifactSection(
                    artifact_id=artifact.id,
                    key=d["key"],
                    title=d["title"],
                    sort_order=i,
                ))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue
            return artifact.id

    # Three losses in a row means the winner's row is committed; read it.
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(Artifact).where(Artifact.group_session_id == group_session_id))
        ).scalar_one_or_none()
        if existing is None:
            raise RuntimeError(f"could not create or find artifact for session {group_session_id}")
        return existing.id


async def snapshot(group_session_id: str) -> dict | None:
    """Current state of the artifact, for rendering or for coach injection.

    Deliberately does NOT log a read. Callers know why they are reading — a human
    opening a panel and a coach ingesting the text answer different questions, so
    each calls the matching log_* helper explicitly. Making this function log
    would collapse that distinction and quietly inflate human read counts."""
    async with AsyncSessionLocal() as db:
        artifact = (
            await db.execute(select(Artifact).where(Artifact.group_session_id == group_session_id))
        ).scalar_one_or_none()
        if artifact is None:
            return None
        sections = (
            await db.execute(
                select(ArtifactSection)
                .where(ArtifactSection.artifact_id == artifact.id)
                .order_by(ArtifactSection.sort_order)
            )
        ).scalars().all()
        return {
            "artifact_id": artifact.id,
            "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
            "updated_by_user_id": artifact.updated_by_user_id,
            "sections": [
                {
                    "key": s.key,
                    "title": s.title,
                    "content": s.content,
                    "version": s.version,
                    "updated_by_user_id": s.updated_by_user_id,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                for s in sections
            ],
        }


async def write_section(
    *,
    group_session_id: str,
    section_key: str,
    content: str,
    author_user_id: str,
    expected_version: int,
    origin: str = "student_typed",
    role_label: str | None = None,
) -> dict:
    """Apply one section write under optimistic concurrency.

    Returns {"ok": True, "version", "bytes_added", "bytes_removed"} on success,
    or {"ok": False, "conflict": True, "version", "content"} when the writer was
    working from a stale version — the current text comes back so the client can
    rebase instead of losing the teammate's edit.
    """
    if origin not in ORIGINS:
        return {"ok": False, "error": f"unknown origin {origin!r}"}

    # Deliberately does NOT create the artifact. Creating one here would use the
    # default shape, and because sections are never restructured afterwards a
    # team on a sectioned assignment would be permanently stuck with a free-form
    # document. The connect path calls get_or_create() with the assignment's
    # decomposition; a write arriving before that is a bug worth surfacing.
    async with AsyncSessionLocal() as db:
        artifact_id = (
            await db.execute(
                select(Artifact.id).where(Artifact.group_session_id == group_session_id)
            )
        ).scalar_one_or_none()
    if artifact_id is None:
        return {"ok": False, "error": "artifact does not exist for this session"}

    lock = await _lock_for(artifact_id)

    async with lock:
        async with AsyncSessionLocal() as db:
            section = (
                await db.execute(
                    select(ArtifactSection).where(
                        ArtifactSection.artifact_id == artifact_id,
                        ArtifactSection.key == section_key,
                    )
                )
            ).scalar_one_or_none()
            if section is None:
                return {"ok": False, "error": f"no section {section_key!r}"}

            if section.version != expected_version:
                return {
                    "ok": False,
                    "conflict": True,
                    "version": section.version,
                    "content": section.content,
                }

            old = section.content or ""
            added, removed = _diff_bytes(old, content)
            new_version = section.version + 1
            now = datetime.utcnow()

            section.content = content
            section.version = new_version
            section.updated_at = now
            section.updated_by_user_id = author_user_id

            author = await db.get(User, author_user_id)
            revision = ArtifactRevision(
                artifact_id=artifact_id,
                section_id=section.id,
                section_key=section.key,
                version=new_version,
                content=content,
                author_user_id=author_user_id,
                origin=origin,
                bytes_added=added,
                bytes_removed=removed,
                consent_research=bool(author.consent_research) if author else False,
            )
            db.add(revision)
            await db.flush()
            revision_id = revision.id

            artifact = await db.get(Artifact, artifact_id)
            if artifact is not None:
                artifact.updated_at = now
                artifact.updated_by_user_id = author_user_id

            scope = await _scope(db, group_session_id)
            section_id = section.id
            await db.commit()

    await log_event(
        action="write",
        target="artifact",
        actor_kind="student",
        group_session_id=group_session_id,
        actor_user_id=author_user_id,
        role_label=role_label,
        ref_id=section_id,
        payload={
            "section_key": section_key,
            "version": new_version,
            "origin": origin,
            "bytes_added": added,
            "bytes_removed": removed,
        },
        **scope,
    )
    return {
        "ok": True, "version": new_version,
        "bytes_added": added, "bytes_removed": removed,
        # Returned so the caller can route this contribution for review (Phase 5)
        # without re-querying for the revision it just created.
        "revision_id": revision_id,
    }


async def revisions(group_session_id: str, section_key: str | None = None) -> list[dict]:
    """Full write history, oldest first. Append-only and never pruned."""
    async with AsyncSessionLocal() as db:
        artifact = (
            await db.execute(select(Artifact).where(Artifact.group_session_id == group_session_id))
        ).scalar_one_or_none()
        if artifact is None:
            return []
        q = select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact.id)
        if section_key is not None:
            q = q.where(ArtifactRevision.section_key == section_key)
        # (created_at, section_key, version) rather than created_at alone: two
        # revisions can share a timestamp, and the determinism requirement means
        # replaying the same history must produce the same order every time.
        rows = (await db.execute(q.order_by(
            ArtifactRevision.created_at,
            ArtifactRevision.section_key,
            ArtifactRevision.version,
        ))).scalars().all()
        return [
            {
                "section_key": r.section_key,
                "version": r.version,
                "content": r.content,
                "author_user_id": r.author_user_id,
                "origin": r.origin,
                "bytes_added": r.bytes_added,
                "bytes_removed": r.bytes_removed,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


# -- Reads -------------------------------------------------------------------
# Each of these is a measurement. They fire on a real human action or a real
# prompt injection, never on a background render, prefetch or off-screen mount.


async def _log_read(
    group_session_id: str,
    action: str,
    actor_user_id: str,
    actor_kind: str,
    payload: dict,
    role_label: str | None,
    idempotency_key: str | None,
    client_ts: datetime | None,
) -> None:
    async with AsyncSessionLocal() as db:
        scope = await _scope(db, group_session_id)
    await log_event(
        action=action,
        target="artifact",
        actor_kind=actor_kind,
        group_session_id=group_session_id,
        actor_user_id=actor_user_id,
        role_label=role_label,
        payload=payload,
        client_ts=client_ts,
        idempotency_key=idempotency_key,
        **scope,
    )


async def log_open(
    group_session_id: str,
    user_id: str,
    *,
    role_label: str | None = None,
    idempotency_key: str | None = None,
    client_ts: datetime | None = None,
) -> None:
    """A person actually opened the artifact panel."""
    await _log_read(
        group_session_id, "open", user_id, "student", {}, role_label, idempotency_key, client_ts
    )


async def log_section_expand(
    group_session_id: str,
    user_id: str,
    section_key: str,
    *,
    role_label: str | None = None,
    idempotency_key: str | None = None,
    client_ts: datetime | None = None,
) -> None:
    """A person expanded one section — the finest-grained read, and the one that
    makes "did they look at Sam's step 2?" answerable."""
    await _log_read(
        group_session_id, "section_expand", user_id, "student",
        {"section_key": section_key}, role_label, idempotency_key, client_ts,
    )


async def log_close(
    group_session_id: str,
    user_id: str,
    *,
    role_label: str | None = None,
    idempotency_key: str | None = None,
    client_ts: datetime | None = None,
) -> None:
    """A person closed the artifact panel. Paired with `open`, this bounds how
    long the artifact was actually on screen, which is what makes a missing or
    downsampled dwell heartbeat recoverable rather than fatal."""
    await _log_read(
        group_session_id, "close", user_id, "student", {}, role_label, idempotency_key, client_ts
    )


async def log_dwell(
    group_session_id: str,
    user_id: str,
    section_key: str,
    duration_ms: int,
    *,
    role_label: str | None = None,
    idempotency_key: str | None = None,
    client_ts: datetime | None = None,
) -> None:
    """Heartbeat with time-on-section. The one read event class that may be
    downsampled or expired later; open/expand/read_by_coach are permanent."""
    await _log_read(
        group_session_id, "dwell", user_id, "student",
        {"section_key": section_key, "duration_ms": duration_ms},
        role_label, idempotency_key, client_ts,
    )


async def log_read_by_coach(
    group_session_id: str,
    on_behalf_of_user_id: str,
    section_keys: list[str],
    *,
    role_label: str | None = None,
) -> None:
    """The artifact was injected into a student's coach prompt.

    Attributed to that student but recorded with actor_kind="coach" and never
    merged into their human opens: whether a coach-mediated read counts as the
    student having read their teammate's work is open question 4, and that
    question stays answerable only if the two are kept apart in the data."""
    await _log_read(
        group_session_id, "read_by_coach", on_behalf_of_user_id, "coach",
        {"section_keys": section_keys}, role_label, None, None,
    )
