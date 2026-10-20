"""Routed verification: assign one student's contribution to a teammate, and
record whether the check actually happened.

The design decision that shapes this whole module: **outcomes are derived from
the read log, never self-reported.** A reviewer who submits "correct" without
ever opening the section has told you they were willing to claim a check, not
that they performed one. Those are different findings, and the second is the
interesting one. It is detectable only because Phase 1 logs reads as
first-class events with a shared sequence.

So `VerificationResponse` has no "did you read it?" field, and `status` on the
assignment is only ever `pending`, `responded`, `expired` or `reassigned` (the
last is an instructor action, not reviewer behaviour). `responded` says only
that a verdict row exists — never that a check happened. Everything else is
computed.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from challenges import get_current_user, get_db
from database import (ArtifactRevision, AsyncSessionLocal, GroupChallenge, GroupMember,
                      GroupSession, ReviewPairing, StudyEvent, User,
                      VerificationAssignment, VerificationResponse)
from events import log_event

log = logging.getLogger("verification")

router = APIRouter(prefix="/verification", tags=["verification"])

VERDICTS = ("correct", "incorrect", "unsure")
POLICIES = ("none", "round_robin", "random", "instructor_assigned")
# routing_policy on a row an instructor created by moving a pending review. Not
# a selectable policy: it can happen under any of the ones above.
REASSIGN_POLICY = "instructor_reassign"

# Reads that count as having looked at the target. `open` is excluded: opening
# the panel is not reading a particular teammate's section, and counting it
# would let a reviewer clear the bar without ever seeing the work.
READ_ACTIONS = {"section_expand", "dwell"}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def choose_reviewer(members: list[str], author_user_id: str,
                    prior_counts: dict[str, int], policy: str,
                    pairings: dict[str, str] | None = None) -> str | None:
    """Pick a reviewer, excluding the author.

    Round-robin is the default and is implemented as "fewest reviews so far,
    ties broken by stable ordering" rather than by rotating an index. An index
    rotates out of step the moment someone leaves the session or a write is
    rejected, and the resulting imbalance is invisible.

    instructor_assigned follows `pairings` (author -> reviewer) and nothing
    else: no pairing, or a paired reviewer who is no longer on the team, returns
    None. It must never fall through to round-robin — a setting that claims one
    routing and performs another corrupts the arm without any visible sign."""
    candidates = sorted(u for u in members if u != author_user_id)
    if not candidates:
        return None
    if policy == "instructor_assigned":
        reviewer = (pairings or {}).get(author_user_id)
        return reviewer if reviewer in candidates else None
    if policy == "random":
        import random
        return random.choice(candidates)
    return min(candidates, key=lambda u: (prior_counts.get(u, 0), u))


async def assign_review(group_session_id: str, revision_id: str, section_key: str,
                        author_user_id: str, policy: str = "round_robin",
                        due_turn: int | None = None) -> str | None:
    """Route one contribution for review. Returns the assignment id, or None
    when the policy is off or nobody else is on the team."""
    if policy not in POLICIES or policy == "none":
        return None

    async with AsyncSessionLocal() as db:
        gs = await db.get(GroupSession, group_session_id)
        if gs is None:
            return None
        members = [
            uid for (uid,) in (await db.execute(
                select(GroupMember.user_id).where(GroupMember.group_id == gs.group_id)
            )).all()
        ]
        prior = {}
        for (reviewer,) in (await db.execute(
            select(VerificationAssignment.reviewer_user_id).where(
                VerificationAssignment.group_session_id == group_session_id
            )
        )).all():
            prior[reviewer] = prior.get(reviewer, 0) + 1

        pairings = None
        if policy == "instructor_assigned":
            pairings = {
                a: r for a, r in (await db.execute(
                    select(ReviewPairing.author_user_id, ReviewPairing.reviewer_user_id)
                    .where(ReviewPairing.group_id == gs.group_id)
                )).all()
            }

        reviewer = choose_reviewer(members, author_user_id, prior, policy, pairings)
        challenge_id = gs.challenge_id
        if reviewer is None:
            # A solo team has nobody to route to under any policy, which is not
            # news. A team member with no usable pairing is: the instructor
            # meant this work to be checked and it will not be, so say so in
            # the log rather than leave a silent gap.
            if policy == "instructor_assigned" and len(members) > 1:
                reason = ("no_pairing" if author_user_id not in pairings
                          else "reviewer_not_on_team")
                await log_event(
                    action="unrouted", target="verification", actor_kind="system",
                    group_session_id=group_session_id, actor_user_id=author_user_id,
                    challenge_id=challenge_id, ref_id=revision_id,
                    payload={"section_key": section_key, "author": author_user_id,
                             "policy": policy, "reason": reason},
                )
            return None

        assignment = VerificationAssignment(
            group_session_id=group_session_id,
            target_revision_id=revision_id,
            target_section_key=section_key,
            author_user_id=author_user_id,
            reviewer_user_id=reviewer,
            routing_policy=policy,
            due_turn=due_turn,
        )
        db.add(assignment)
        await db.commit()
        assignment_id = assignment.id

    await log_event(
        action="assigned", target="verification", actor_kind="system",
        group_session_id=group_session_id, actor_user_id=reviewer,
        challenge_id=challenge_id, ref_id=assignment_id,
        payload={"section_key": section_key, "author": author_user_id, "policy": policy},
    )
    return assignment_id


# ---------------------------------------------------------------------------
# Outcome classification — derived, never self-reported
# ---------------------------------------------------------------------------


def classify(assignment: dict, response: dict | None, reads: list[dict],
             responses_to_same_target: int = 1) -> str:
    """One of: happened | skipped_unread | skipped_no_response | expired |
    duplicated | reassigned.

    `reads` are this reviewer's section reads of the target section. A read only
    counts if it happened AFTER the work was assigned and BEFORE the verdict was
    submitted — a reviewer who read the section yesterday and rubber-stamped it
    today did not check this revision.
    """
    if responses_to_same_target > 1:
        # Two people checked the same thing: wasted effort the team did not
        # notice, and a different failure from nobody checking.
        return "duplicated"
    if response is None:
        if assignment.get("status") == "reassigned":
            # Taken away by the instructor before it was answered. Not the
            # reviewer's behaviour, so it must not read as a skipped check.
            return "reassigned"
        return "expired" if assignment.get("status") == "expired" else "skipped_no_response"

    submitted = response.get("submitted_at")
    assigned = assignment.get("assigned_at")
    read_in_window = any(
        (assigned is None or r["server_ts"] >= assigned)
        and (submitted is None or r["server_ts"] <= submitted)
        for r in reads
    )
    # The interesting case: a verdict with no read behind it.
    return "happened" if read_in_window else "skipped_unread"


async def outcomes_for_session(db: AsyncSession, group_session_id: str) -> list[dict]:
    """Classify every assignment in one session."""
    assignments = (await db.execute(
        select(VerificationAssignment)
        .where(VerificationAssignment.group_session_id == group_session_id)
        .order_by(VerificationAssignment.assigned_at)
    )).scalars().all()
    if not assignments:
        return []

    responses = (await db.execute(
        select(VerificationResponse).where(
            VerificationResponse.assignment_id.in_([a.id for a in assignments])
        )
    )).scalars().all()
    by_assignment = {r.assignment_id: r for r in responses}

    # How many distinct reviewers answered for the same target revision.
    per_target: dict[str, int] = {}
    for a in assignments:
        if a.id in by_assignment:
            per_target[a.target_revision_id] = per_target.get(a.target_revision_id, 0) + 1

    events = (await db.execute(
        select(StudyEvent).where(
            StudyEvent.group_session_id == group_session_id,
            StudyEvent.target == "artifact",
            StudyEvent.action.in_(tuple(READ_ACTIONS)),
        ).order_by(StudyEvent.seq)
    )).scalars().all()

    out = []
    for a in assignments:
        resp = by_assignment.get(a.id)
        reads = [
            {"server_ts": e.server_ts}
            for e in events
            if e.actor_user_id == a.reviewer_user_id
            and e.actor_kind == "student"
            and (e.payload or {}).get("section_key") == a.target_section_key
        ]
        outcome = classify(
            {"status": a.status, "assigned_at": a.assigned_at},
            {"submitted_at": resp.submitted_at} if resp else None,
            reads,
            per_target.get(a.target_revision_id, 0) if resp else 1,
        )
        out.append({
            "assignment_id": a.id,
            "section_key": a.target_section_key,
            "author_user_id": a.author_user_id,
            "reviewer_user_id": a.reviewer_user_id,
            "routing_policy": a.routing_policy,
            # A row answered before "responded" was stored still reads as
            # pending in the database; report what the response row says.
            "status": "responded" if resp is not None and a.status == "pending" else a.status,
            "replaces_assignment_id": a.replaces_assignment_id,
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
            "outcome": outcome,
            "verdict": resp.verdict if resp else None,
            "checked_against_corpus": bool(resp.checked_against_corpus) if resp else False,
            "reads_of_target": len(reads),
        })
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class RespondBody(BaseModel):
    verdict: str = Field(..., pattern="^(correct|incorrect|unsure)$")
    comment: str | None = None
    checked_against_corpus: bool = False
    evidence_refs: dict | None = None


@router.get("/inbox/{group_session_id}")
async def my_inbox(
    group_session_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reviews assigned to me in this session, with the text to check."""
    rows = (await db.execute(
        select(VerificationAssignment, ArtifactRevision)
        .join(ArtifactRevision, ArtifactRevision.id == VerificationAssignment.target_revision_id)
        .where(
            VerificationAssignment.group_session_id == group_session_id,
            VerificationAssignment.reviewer_user_id == user_id,
            # Work the instructor moved to someone else is no longer theirs.
            VerificationAssignment.status != "reassigned",
        )
        .order_by(VerificationAssignment.assigned_at)
    )).all()
    answered = {
        r for (r,) in (await db.execute(
            select(VerificationResponse.assignment_id).where(
                VerificationResponse.reviewer_user_id == user_id
            )
        )).all()
    }
    return [
        {
            "assignment_id": a.id,
            "section_key": a.target_section_key,
            "author_user_id": a.author_user_id,
            "content": rev.content,
            "version": rev.version,
            "answered": a.id in answered,
            "due_turn": a.due_turn,
        }
        for a, rev in rows
    ]


@router.post("/{assignment_id}/respond")
async def respond(
    assignment_id: str,
    body: RespondBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a verdict.

    Accepts the verdict even when the reviewer never opened the section — that
    is a finding, not an error to block. Refusing it would hide exactly the
    behaviour the study wants to measure and push it out of the data."""
    a = await db.get(VerificationAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a.reviewer_user_id != user_id:
        raise HTTPException(status_code=403, detail="This review is not assigned to you")
    if a.status == "reassigned":
        raise HTTPException(status_code=409, detail="This review was reassigned to a teammate")

    existing = (await db.execute(
        select(VerificationResponse).where(
            VerificationResponse.assignment_id == assignment_id
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Already reviewed")

    reviewer = await db.get(User, user_id)
    resp = VerificationResponse(
        assignment_id=assignment_id,
        reviewer_user_id=user_id,
        consent_research=bool(reviewer.consent_research) if reviewer else False,
        verdict=body.verdict,
        comment=body.comment,
        checked_against_corpus=body.checked_against_corpus,
        evidence_refs=body.evidence_refs,
        submitted_at=datetime.utcnow(),
    )
    db.add(resp)
    # The fact that a verdict exists, nothing more: whether the reviewer read
    # the work is still derived from the log (classify). Left pending, the
    # export showed "pending" beside a verdict.
    a.status = "responded"
    await db.commit()

    gs = await db.get(GroupSession, a.group_session_id)
    await log_event(
        action="responded", target="verification", actor_kind="student",
        group_session_id=a.group_session_id, actor_user_id=user_id,
        challenge_id=gs.challenge_id if gs else None,
        ref_id=assignment_id,
        payload={"verdict": body.verdict, "section_key": a.target_section_key},
    )
    return {"assignment_id": assignment_id, "verdict": body.verdict}


@router.get("/outcomes/{group_session_id}")
async def session_outcomes(
    group_session_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor/admin view of who checked what, and who only said they did."""
    from main import _assert_can_read_research
    from database import GroupChallenge

    gs = await db.get(GroupSession, group_session_id)
    if gs is None:
        raise HTTPException(status_code=404, detail="Group session not found")
    team = await db.get(GroupChallenge, gs.group_id)
    await _assert_can_read_research(db, user_id, team.classroom_id if team else None)

    rows = await outcomes_for_session(db, group_session_id)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return {"group_session_id": group_session_id, "counts": counts, "assignments": rows}


class ReassignBody(BaseModel):
    reviewer_user_id: str


@router.post("/{assignment_id}/reassign")
async def reassign(
    assignment_id: str,
    body: ReassignBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: move a pending, unanswered review to another teammate.

    Works under every routing policy — a reviewer can go quiet whoever chose
    them. The original row is kept and marked "reassigned" rather than edited,
    so its outcome reads as the instructor's action, not as the reviewer
    skipping the check. The new row is routing_policy "instructor_reassign" and
    its read window starts now: reads before the handover do not count as this
    reviewer checking the work."""
    from challenges import _assert_user_manages_classroom

    a = await db.get(VerificationAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    gs = await db.get(GroupSession, a.group_session_id)
    team = await db.get(GroupChallenge, gs.group_id) if gs else None
    if team is None or not team.classroom_id:
        raise HTTPException(status_code=404, detail="Team not found")
    await _assert_user_manages_classroom(db, user_id, team.classroom_id)

    if gs.status == "completed":
        # The review window was the session. A reviewer added afterwards could
        # no longer read or answer anything that counts.
        raise HTTPException(status_code=409, detail="This session has ended, so its reviews cannot be reassigned")
    if a.status != "pending":
        raise HTTPException(status_code=409, detail=f"This review is {a.status}, not pending")
    answered = (await db.execute(
        select(VerificationResponse.id).where(VerificationResponse.assignment_id == assignment_id)
    )).first()
    if answered is not None:
        raise HTTPException(status_code=409, detail="This review has already been answered")

    new_reviewer = body.reviewer_user_id
    if new_reviewer == a.author_user_id:
        raise HTTPException(status_code=400, detail="A student cannot review their own work")
    if new_reviewer == a.reviewer_user_id:
        raise HTTPException(status_code=400, detail="That student already holds this review")
    on_team = (await db.execute(
        select(GroupMember.id).where(GroupMember.group_id == team.id,
                                     GroupMember.user_id == new_reviewer)
    )).first()
    if on_team is None:
        raise HTTPException(status_code=400, detail="That student is not on this team")

    replacement = VerificationAssignment(
        group_session_id=a.group_session_id,
        target_revision_id=a.target_revision_id,
        target_section_key=a.target_section_key,
        author_user_id=a.author_user_id,
        reviewer_user_id=new_reviewer,
        routing_policy=REASSIGN_POLICY,
        due_turn=a.due_turn,
        replaces_assignment_id=a.id,
    )
    previous_reviewer = a.reviewer_user_id
    a.status = "reassigned"
    db.add(replacement)
    await db.commit()

    await log_event(
        action="reassigned", target="verification", actor_kind="system",
        group_session_id=a.group_session_id, actor_user_id=new_reviewer,
        challenge_id=gs.challenge_id, ref_id=replacement.id,
        payload={"section_key": a.target_section_key, "author": a.author_user_id,
                 "from_reviewer": previous_reviewer, "to_reviewer": new_reviewer,
                 "replaces": a.id},
    )
    try:
        from group_room import rooms
        # Both the new reviewer's inbox and the old one's change; the client
        # refetches its own inbox on this, so one message covers both.
        await rooms.notify(a.group_session_id, {"type": "verification_assigned",
                                                "assignment_id": replacement.id,
                                                "section_key": a.target_section_key})
    except Exception as e:
        log.error(f"could not notify session of reassignment: {e}")

    return {"assignment_id": replacement.id, "replaces_assignment_id": a.id,
            "reviewer_user_id": new_reviewer}
