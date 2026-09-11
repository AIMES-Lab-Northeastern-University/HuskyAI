"""Turn-taking metrics for one group session.

Three measures, all per session:

1. Contribution share -- who sent what fraction of the team's prompts. The same
   quantity _team_analytics already reports; the source of truth (ordered user
   turns for a conversation) and the share arithmetic are shared with it rather
   than reimplemented, because two functions that disagree about who took a turn
   would be worse than either.

2. Alternation rate -- how often consecutive turns change hands. Reported for
   the shared conversation (the primary: it is what "a turn" means everywhere
   else in the app) and separately over artifact writes, which is a different
   behaviour and deserves its own number rather than being averaged in.

3. Read-before-write -- for each artifact write, had that student logged a read
   at a lower seq in the same session? Two variants, both labelled:

     other_section  (HEADLINE) a read of a section OTHER than the one being
                    written. This is the collaboration behaviour the study is
                    about, and matches artifact_events' own framing: "whether a
                    student read a teammate's section before or after writing
                    their own". Re-reading your own section before editing it is
                    not that behaviour.
     any_section    the looser reading, any prior read at all. Kept alongside so
                    whoever analyses the data can choose, and so the gap between
                    the two is itself visible.

   Both rely on reads and writes sharing ONE seq space per session, which
   artifact_events guarantees (MAX(seq)+1 under UNIQUE(group_session_id, seq)).
   Without that, "before" would not be answerable at all.

*** Reads are filtered on actor_kind == 'student'. ***
The coach also reads sections (log_coach_read, when it pulls the artifact into
its context) and those rows carry the requesting student's id in meta as
provenance. Counting them would attribute the coach's reading to the student and
drive read-before-write toward 1.0.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from admin import get_db, require_platform_admin
from artifact_events import (ACTOR_STUDENT, EVENT_SECTION_WRITE,
                             STUDENT_READ_TYPES)
from database import ArtifactEvent, GroupSession, Message, User

log = logging.getLogger("turn_taking")

router = APIRouter(prefix="/research", tags=["research"])


# ---------------------------------------------------------------------------
# Shared with groups._team_analytics
# ---------------------------------------------------------------------------

async def session_turn_authors(db: AsyncSession, conversation_id: str) -> list[str | None]:
    """The author of each user turn in a conversation, in order.

    One definition of "a turn", used by both this module and the team analytics,
    so the two can never disagree about who spoke when. Ordered by
    (created_at, id) -- the same reconstruction the post-session analysis uses,
    and stable when two messages share a timestamp.
    """
    rows = (await db.execute(
        select(Message.sender_user_id)
        .where(Message.conversation_id == conversation_id, Message.role == "user")
        .order_by(Message.created_at, Message.id)
    )).all()
    return [r[0] for r in rows]


def share_pct(count: int, total: int) -> float:
    """One student's share of the team's turns, as a percentage."""
    return round(100.0 * count / total, 1) if total else 0.0


# ---------------------------------------------------------------------------
# Pure metrics
# ---------------------------------------------------------------------------

def alternation_rate(actors: list) -> float | None:
    """Fraction of adjacent turn pairs in which the actor changes.

    A,A,B,A,B,B -> pairs AA AB BA AB BB -> 3 of 5 switch -> 0.6

    None (not 0.0) for fewer than two turns: with one turn there is no pair to
    alternate across, and reporting 0 would read as "one person monologued",
    which is a different claim from "not enough data".
    """
    pairs = list(zip(actors, actors[1:]))
    if not pairs:
        return None
    switches = sum(1 for a, b in pairs if a != b)
    return round(switches / len(pairs), 4)


def read_before_write(events: list[dict]) -> dict:
    """Read-before-write over one session's event log, in seq order.

    `events` are dicts as returned by artifact_events (seq, event_type,
    actor_kind, actor_user_id, section_key). Only student reads count as reads;
    see the module docstring.
    """
    prior_any: dict[str, set[str]] = {}       # user -> sections they have read
    writes = 0
    with_other_section = 0
    with_any_section = 0
    per_write: list[dict] = []

    for ev in sorted(events, key=lambda e: e["seq"]):
        kind = ev.get("actor_kind")
        etype = ev.get("event_type")
        uid = ev.get("actor_user_id")
        skey = ev.get("section_key")

        if kind == ACTOR_STUDENT and etype in STUDENT_READ_TYPES and uid:
            prior_any.setdefault(uid, set()).add(skey)
            continue

        if kind == ACTOR_STUDENT and etype == EVENT_SECTION_WRITE and uid:
            read_sections = prior_any.get(uid, set())
            any_read = bool(read_sections)
            other_read = any(s != skey for s in read_sections)
            writes += 1
            with_any_section += 1 if any_read else 0
            with_other_section += 1 if other_read else 0
            per_write.append({
                "seq": ev["seq"],
                "user_id": uid,
                "section_key": skey,
                "read_other_section_first": other_read,
                "read_any_section_first": any_read,
            })

    def ratio(n: int) -> float | None:
        return round(n / writes, 4) if writes else None

    return {
        "writes": writes,
        # The headline: a read of a section other than the one written.
        "other_section": {
            "writes_preceded_by_read": with_other_section,
            "ratio": ratio(with_other_section),
        },
        # The looser variant, including re-reading the section you then edit.
        "any_section": {
            "writes_preceded_by_read": with_any_section,
            "ratio": ratio(with_any_section),
        },
        "per_write": per_write,
    }


# ---------------------------------------------------------------------------
# Session-level assembly
# ---------------------------------------------------------------------------

async def session_turn_taking(db: AsyncSession, session: GroupSession) -> dict:
    """All three metrics for one group session."""
    authors = (
        await session_turn_authors(db, session.conversation_id)
        if session.conversation_id else []
    )
    # Turns with no recorded author (pre-attribution rows) are excluded from
    # alternation rather than treated as a distinct actor, which would
    # manufacture switches. The count is reported so the exclusion is visible.
    attributed = [a for a in authors if a]
    unattributed = len(authors) - len(attributed)

    counts: dict[str, int] = {}
    for uid in attributed:
        counts[uid] = counts.get(uid, 0) + 1

    names: dict[str, str] = {}
    if counts:
        rows = await db.execute(select(User.id, User.name).where(User.id.in_(list(counts))))
        names = {uid: nm for uid, nm in rows.all()}

    total = len(attributed)
    contribution = sorted(
        (
            {
                "user_id": uid,
                "name": names.get(uid, "Unknown"),
                "turns": n,
                "share_pct": share_pct(n, total),
            }
            for uid, n in counts.items()
        ),
        key=lambda p: p["turns"],
        reverse=True,
    )

    events = (await db.execute(
        select(ArtifactEvent)
        .where(ArtifactEvent.group_session_id == session.id)
        .order_by(ArtifactEvent.seq)
    )).scalars().all()
    event_dicts = [
        {
            "seq": e.seq,
            "event_type": e.event_type,
            "actor_kind": e.actor_kind,
            "actor_user_id": e.actor_user_id,
            "section_key": e.section_key,
        }
        for e in events
    ]
    write_actors = [
        e["actor_user_id"] for e in event_dicts
        if e["event_type"] == EVENT_SECTION_WRITE
        and e["actor_kind"] == ACTOR_STUDENT
        and e["actor_user_id"]
    ]

    return {
        "group_session_id": session.id,
        "group_id": session.group_id,
        "session_number": session.session_number,
        "arm": session.arm,
        "conversation_turns": total,
        "turns_without_author": unattributed,
        "contribution": contribution,
        "alternation": {
            # Primary: the shared conversation, which is what a "turn" means
            # everywhere else in the app.
            "conversation": alternation_rate(attributed),
            # A different behaviour, reported separately rather than blended in.
            "artifact_writes": alternation_rate(write_actors),
            "artifact_write_count": len(write_actors),
        },
        "read_before_write": read_before_write(event_dicts),
    }


@router.get("/sessions/{group_session_id}/turn-taking")
async def turn_taking_endpoint(
    group_session_id: str,
    _: str = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Turn-taking metrics for one group session.

    Platform-admin only, matching the other research/export endpoints. This is
    de-anonymised per-student data, which is why it is not on the instructor
    surface: an instructor sees their own section's contribution analytics
    through /classrooms/..., gated on managing that classroom.
    """
    session = await db.get(GroupSession, group_session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Group session not found")
    return await session_turn_taking(db, session)
