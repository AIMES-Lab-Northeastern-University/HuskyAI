"""Contested input: a teammate's answer and the coach's answer disagree on the
same subproblem, and we record which one the student takes.

The subproblem is the artifact section key. The build plan lists "how does the
system know two contributions address the same subproblem?" as a blocking open
question; choosing a sectioned artifact answered it, so nothing here invents a
second decomposition that would have to be reconciled later.

As with routed verification, **whether the student actually looked at either
option is derived from the event log, never asked.** The case worth catching is
an adoption with neither option opened — a student taking a side without
reading either. A self-report cannot distinguish that from a careful choice.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from challenges import get_current_user, get_db
from database import (ContestedPair, ContestedResponse, GroupMember, GroupSession,
                      StudyEvent, User)
from events import log_event

log = logging.getLogger("contested")

router = APIRouter(prefix="/contested", tags=["contested"])

ADOPTIONS = ("a", "b", "neither", "merged")

# An "inspection" is an expand or a dwell on the contested section. Opening the
# artifact panel is not inspecting a particular option.
INSPECT_ACTIONS = {"section_expand", "dwell"}
# Reading the coach's side means having the coach turn in view; the closest
# honest proxy in the log is the student's own coach turn on this section.
COACH_VIEW_ACTIONS = {"turn"}


class AdoptBody(BaseModel):
    adopted: str = Field(..., pattern="^(a|b|neither|merged)$")
    rationale_text: str | None = None
    # Client-measured time on each option. Advisory only — the inspected_*
    # flags come from the server's own log, so a client that lies about dwell
    # cannot manufacture an inspection.
    dwell_ms_a: int | None = None
    dwell_ms_b: int | None = None


async def derive_inspection(db: AsyncSession, pair: ContestedPair) -> tuple[bool, bool]:
    """Did this student actually look at each option before now?

    A: an expand/dwell of the contested section, after the pair was surfaced.
    B: a coach turn of their own in this session, after the pair was surfaced —
       the coach's answer reached them through their own conversation.

    Both windows start at `surfaced_at`: reading the section an hour before the
    pair existed is not inspecting this contested option."""
    since = pair.surfaced_at or pair.created_at
    events = (await db.execute(
        select(StudyEvent).where(
            StudyEvent.group_session_id == pair.group_session_id,
            StudyEvent.actor_user_id == pair.surfaced_to_user_id,
        ).order_by(StudyEvent.seq)
    )).scalars().all()

    inspected_a = any(
        e.target == "artifact" and e.action in INSPECT_ACTIONS
        and e.actor_kind == "student"
        and (e.payload or {}).get("section_key") == pair.subproblem_key
        and (since is None or e.server_ts >= since)
        for e in events
    )
    inspected_b = any(
        e.target == "coach" and e.action in COACH_VIEW_ACTIONS
        and (since is None or e.server_ts >= since)
        for e in events
    )
    return inspected_a, inspected_b


async def surface_pair(pair_id: str) -> None:
    """Mark a scripted pair as shown and log it."""
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        pair = await db.get(ContestedPair, pair_id)
        if pair is None or pair.surfaced_at is not None:
            return
        pair.surfaced_at = datetime.utcnow()
        gs = await db.get(GroupSession, pair.group_session_id)
        await db.commit()
        challenge_id = gs.challenge_id if gs else None
        session_id, user_id, key = pair.group_session_id, pair.surfaced_to_user_id, pair.subproblem_key

    await log_event(
        action="surfaced", target="contested", actor_kind="system",
        group_session_id=session_id, actor_user_id=user_id,
        challenge_id=challenge_id, ref_id=pair_id,
        payload={"subproblem_key": key},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class ScriptPairBody(BaseModel):
    subproblem_key: str
    option_a_text: str
    option_b_text: str
    surfaced_to_user_id: str
    better_option: str | None = Field(None, pattern="^(a|b)$")


@router.post("/sessions/{group_session_id}/pairs")
async def script_pair(
    group_session_id: str,
    body: ScriptPairBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor authors a divergent pair in advance (study v1).

    Deterministic and reliably triggered, which matters more than realism for a
    first run — auto-detection lands behind a flag once there is ground truth
    to label which option was actually better."""
    from database import GroupChallenge
    from main import _assert_can_read_research

    gs = await db.get(GroupSession, group_session_id)
    if gs is None:
        raise HTTPException(status_code=404, detail="Group session not found")
    team = await db.get(GroupChallenge, gs.group_id)
    await _assert_can_read_research(db, user_id, team.classroom_id if team else None)

    is_member = (await db.execute(
        select(GroupMember.id).where(
            GroupMember.group_id == gs.group_id,
            GroupMember.user_id == body.surfaced_to_user_id,
        )
    )).scalar_one_or_none()
    if is_member is None:
        raise HTTPException(status_code=400, detail="That user is not on this team")

    pair = ContestedPair(
        group_session_id=group_session_id,
        subproblem_key=body.subproblem_key[:64],
        option_a_text=body.option_a_text,
        option_b_text=body.option_b_text,
        origin="instructor_scripted",
        better_option=body.better_option,
        surfaced_to_user_id=body.surfaced_to_user_id,
    )
    db.add(pair)
    await db.commit()
    return {"pair_id": pair.id, "subproblem_key": pair.subproblem_key}


@router.get("/sessions/{group_session_id}/mine")
async def my_pairs(
    group_session_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Contested pairs waiting for me. Fetching marks them surfaced."""
    pairs = (await db.execute(
        select(ContestedPair).where(
            ContestedPair.group_session_id == group_session_id,
            ContestedPair.surfaced_to_user_id == user_id,
        ).order_by(ContestedPair.created_at)
    )).scalars().all()
    answered = {
        p for (p,) in (await db.execute(
            select(ContestedResponse.pair_id).where(ContestedResponse.user_id == user_id)
        )).all()
    }
    out = []
    for p in pairs:
        if p.surfaced_at is None:
            await surface_pair(p.id)
        out.append({
            "pair_id": p.id,
            "subproblem_key": p.subproblem_key,
            # Deliberately NOT labelled "teammate" / "coach" in the payload: the
            # study is about which answer they pick, and labelling the source
            # would measure trust in labels instead.
            "option_a": p.option_a_text,
            "option_b": p.option_b_text,
            "answered": p.id in answered,
        })
    return out


@router.post("/pairs/{pair_id}/adopt")
async def adopt(
    pair_id: str,
    body: AdoptBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the student's choice, with inspection derived from the log."""
    pair = await db.get(ContestedPair, pair_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="Pair not found")
    if pair.surfaced_to_user_id != user_id:
        raise HTTPException(status_code=403, detail="This was not surfaced to you")

    existing = (await db.execute(
        select(ContestedResponse).where(ContestedResponse.pair_id == pair_id)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Already answered")

    inspected_a, inspected_b = await derive_inspection(db, pair)

    student = await db.get(User, user_id)
    resp = ContestedResponse(
        pair_id=pair_id, user_id=user_id, adopted=body.adopted,
        consent_research=bool(student.consent_research) if student else False,
        inspected_a=inspected_a, inspected_b=inspected_b,
        dwell_ms_a=body.dwell_ms_a, dwell_ms_b=body.dwell_ms_b,
        rationale_text=body.rationale_text,
        responded_at=datetime.utcnow(),
    )
    db.add(resp)
    await db.commit()

    gs = await db.get(GroupSession, pair.group_session_id)
    await log_event(
        action="adopted", target="contested", actor_kind="student",
        group_session_id=pair.group_session_id, actor_user_id=user_id,
        challenge_id=gs.challenge_id if gs else None, ref_id=pair_id,
        payload={
            "adopted": body.adopted,
            "inspected_a": inspected_a,
            "inspected_b": inspected_b,
            "uninspected": not (inspected_a or inspected_b),
            "subproblem_key": pair.subproblem_key,
        },
    )
    return {
        "pair_id": pair_id, "adopted": body.adopted,
        "inspected_a": inspected_a, "inspected_b": inspected_b,
        "correct": (None if pair.better_option is None
                    else body.adopted == pair.better_option),
    }


@router.get("/sessions/{group_session_id}/outcomes")
async def outcomes(
    group_session_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor/admin view: what was adopted, and whether anything was read."""
    from database import GroupChallenge
    from main import _assert_can_read_research

    gs = await db.get(GroupSession, group_session_id)
    if gs is None:
        raise HTTPException(status_code=404, detail="Group session not found")
    team = await db.get(GroupChallenge, gs.group_id)
    await _assert_can_read_research(db, user_id, team.classroom_id if team else None)

    pairs = (await db.execute(
        select(ContestedPair).where(ContestedPair.group_session_id == group_session_id)
    )).scalars().all()
    responses = {
        r.pair_id: r for r in (await db.execute(
            select(ContestedResponse).where(
                ContestedResponse.pair_id.in_([p.id for p in pairs] or [""])
            )
        )).scalars().all()
    }

    rows, uninspected = [], 0
    for p in pairs:
        r = responses.get(p.id)
        is_uninspected = bool(r) and not (r.inspected_a or r.inspected_b)
        if is_uninspected:
            uninspected += 1
        rows.append({
            "pair_id": p.id,
            "subproblem_key": p.subproblem_key,
            "user_id": p.surfaced_to_user_id,
            "origin": p.origin,
            "adopted": r.adopted if r else None,
            "inspected_a": bool(r.inspected_a) if r else None,
            "inspected_b": bool(r.inspected_b) if r else None,
            "uninspected_adoption": is_uninspected,
            "correct": (None if (r is None or p.better_option is None)
                        else r.adopted == p.better_option),
        })
    return {
        "group_session_id": group_session_id,
        "pairs": rows,
        "uninspected_adoptions": uninspected,
        "answered": len(responses),
        "total": len(pairs),
    }
