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

# An inspection is the student opening THAT option: each option in the
# contested card starts collapsed, and expanding it logs contested.option_expand
# (and option_dwell when it closes). Until #16 this was inferred from proxies —
# an expand of the artifact section for A, any coach turn for B — which credited
# a student with reading an option they may never have opened.
INSPECT_ACTIONS = {"option_expand", "option_dwell"}
OPTIONS = ("a", "b")


class AdoptBody(BaseModel):
    adopted: str = Field(..., pattern="^(a|b|neither|merged)$")
    rationale_text: str | None = None
    # Client-measured time on each option. Advisory only — the inspected_*
    # flags come from the server's own log, so a client that lies about dwell
    # cannot manufacture an inspection.
    dwell_ms_a: int | None = None
    dwell_ms_b: int | None = None


async def _option_events(db: AsyncSession, pair: ContestedPair) -> list:
    return list((await db.execute(
        select(StudyEvent).where(
            StudyEvent.group_session_id == pair.group_session_id,
            StudyEvent.actor_user_id == pair.surfaced_to_user_id,
            StudyEvent.target == "contested",
            StudyEvent.ref_id == pair.id,
            StudyEvent.action.in_(INSPECT_ACTIONS),
            StudyEvent.actor_kind == "student",
        ).order_by(StudyEvent.seq)
    )).scalars().all())


async def derive_inspection(db: AsyncSession, pair: ContestedPair) -> tuple[bool, bool]:
    """Did this student actually open each option before now?

    Only from this pair's own option_expand / option_dwell events, after the
    pair was surfaced to them."""
    since = pair.surfaced_at or pair.created_at
    seen = {
        (e.payload or {}).get("option")
        for e in await _option_events(db, pair)
        if since is None or e.server_ts >= since
    }
    return "a" in seen, "b" in seen


async def derive_dwell(db: AsyncSession, pair: ContestedPair) -> tuple[int | None, int | None]:
    """Total time each option was open, summed from the log. None when the
    student never had it open long enough to record."""
    totals = {"a": 0, "b": 0}
    for e in await _option_events(db, pair):
        p = e.payload or {}
        if e.action == "option_dwell" and p.get("option") in totals and isinstance(p.get("duration_ms"), int):
            totals[p["option"]] += p["duration_ms"]
    return (totals["a"] or None), (totals["b"] or None)


async def log_option_read(group_session_id: str, user_id: str, data: dict):
    """A student opened (or closed, with dwell) one option of a contested pair.

    Returns the EventResult, or None when the frame names a pair that is not
    this student's in this session (it can never be recorded, so the caller
    acks it anyway to stop the client replaying it)."""
    from database import AsyncSessionLocal
    from events import record_event

    pair_id, option = data.get("pair_id"), data.get("option")
    if not pair_id or option not in OPTIONS:
        return None
    async with AsyncSessionLocal() as db:
        pair = await db.get(ContestedPair, pair_id)
        if (pair is None or pair.group_session_id != group_session_id
                or pair.surfaced_to_user_id != user_id):
            return None
        gs = await db.get(GroupSession, group_session_id)
        challenge_id = gs.challenge_id if gs else None
    if data.get("type") == "contested_option_dwell":
        ms = data.get("duration_ms")
        if not isinstance(ms, int) or ms <= 0:
            return None
        action, payload = "option_dwell", {"option": option, "duration_ms": ms}
        from artifacts import DWELL_FLUSH_REASONS
        if data.get("flush") in DWELL_FLUSH_REASONS:
            payload["flush"] = data["flush"]
    else:
        action, payload = "option_expand", {"option": option}
    client_ts = None
    raw = data.get("client_ts")
    if raw:
        try:
            client_ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            client_ts = None
    return await record_event(
        action=action, target="contested", actor_kind="student",
        group_session_id=group_session_id, actor_user_id=user_id,
        challenge_id=challenge_id, ref_id=pair_id, payload=payload,
        idempotency_key=data.get("event_id"), client_ts=client_ts,
    )


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
    subproblem_key: str = Field(..., min_length=1, max_length=64)
    option_a_text: str = Field(..., min_length=1, max_length=8000)
    option_b_text: str = Field(..., min_length=1, max_length=8000)
    surfaced_to_user_id: str
    better_option: str | None = Field(None, pattern="^(a|b)$")


async def create_scripted_pair(db: AsyncSession, group_session_id: str, group_id: str,
                               body: ScriptPairBody) -> ContestedPair:
    """Validate and store one instructor-scripted pair. Shared by the research
    route and the instructor's team form, so both enforce the same rules.

    Option A is always the teammate's answer and B always the coach's; the
    field names carry that, and nothing downstream may swap them."""
    is_member = (await db.execute(
        select(GroupMember.id).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == body.surfaced_to_user_id,
        )
    )).scalar_one_or_none()
    if is_member is None:
        raise HTTPException(status_code=400, detail="That user is not on this team")
    if not body.option_a_text.strip() or not body.option_b_text.strip():
        raise HTTPException(status_code=400, detail="Both answers need text")

    pair = ContestedPair(
        group_session_id=group_session_id,
        subproblem_key=body.subproblem_key.strip()[:64],
        option_a_text=body.option_a_text.strip(),
        option_b_text=body.option_b_text.strip(),
        origin="instructor_scripted",
        better_option=body.better_option,
        surfaced_to_user_id=body.surfaced_to_user_id,
    )
    db.add(pair)
    await db.commit()
    return pair


async def notify_new_pair(group_session_id: str) -> None:
    """Nudge a live session so the student's client refetches its review and
    contested work (it does so on verification_assigned), making a pair written
    mid-session appear without a reload. Harmless when nobody is connected."""
    try:
        from group_room import rooms
        await rooms.notify(group_session_id, {"type": "verification_assigned"})
    except Exception as e:
        log.error(f"could not notify session of a new contested pair: {e}")


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

    pair = await create_scripted_pair(db, group_session_id, gs.group_id, body)
    await notify_new_pair(group_session_id)
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
    # From the log when it has them; the client's figures only for a client
    # that predates option events.
    logged_a, logged_b = await derive_dwell(db, pair)

    student = await db.get(User, user_id)
    resp = ContestedResponse(
        pair_id=pair_id, user_id=user_id, adopted=body.adopted,
        consent_research=bool(student.consent_research) if student else False,
        inspected_a=inspected_a, inspected_b=inspected_b,
        dwell_ms_a=logged_a if logged_a is not None else body.dwell_ms_a,
        dwell_ms_b=logged_b if logged_b is not None else body.dwell_ms_b,
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
