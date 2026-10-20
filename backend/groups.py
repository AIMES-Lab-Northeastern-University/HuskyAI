"""
Group challenges: 2-4 students share one conversation + one PEI per session,
with the team persisting across all of a challenge's sessions.

Instructor-driven model (2026-06-21 redesign): teams are prof-assigned from the
section roster — see team_router below. There is no student self-join; the old
join-code create/join endpoints were retired in Phase 3. The student-facing
GET /groups/{id} (read a team you belong to) remains. The shared live chat
(multi-client WebSocket, broadcast, serialization) and shared scoring live in main.py.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from challenges import get_current_user, get_db, _assert_user_manages_classroom, _sections_of
from database import (
    Challenge,
    ClassroomChallenge,
    ContestedPair,
    ContestedResponse,
    ClassroomMembership,
    Conversation,
    EvalResult,
    GroupChallenge,
    GroupMember,
    GroupSession,
    Message,
    ReviewPairing,
    User,
)

log = logging.getLogger("groups")

router = APIRouter(prefix="/groups", tags=["groups"])

# Instructor-facing team management (prof-assigned teams from the section roster).
# Classroom-scoped so eligibility = classroom membership; separate from the
# student-facing /groups router above.
team_router = APIRouter(prefix="/classrooms", tags=["group-teams"])


async def _member_count(db: AsyncSession, group_id: str) -> int:
    r = await db.execute(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
    )
    return int(r.scalar_one())


async def _members_payload(db: AsyncSession, group_id: str) -> list[dict]:
    rows = await db.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at)
    )
    return [
        {"user_id": m.user_id, "name": u.name, "joined_at": m.joined_at.isoformat() if m.joined_at else None}
        for m, u in rows.all()
    ]


async def _assert_member(db: AsyncSession, group_id: str, user_id: str) -> None:
    r = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You are not a member of this group")


async def _pairings_payload(db: AsyncSession, group_id: str) -> list[dict]:
    rows = await db.execute(
        select(ReviewPairing.author_user_id, ReviewPairing.reviewer_user_id)
        .where(ReviewPairing.group_id == group_id)
    )
    return [{"author_user_id": a, "reviewer_user_id": r} for a, r in rows.all()]


@router.get("/{group_id}")
async def get_group(
    group_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = (
        await db.execute(select(GroupChallenge).where(GroupChallenge.id == group_id))
    ).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    await _assert_member(db, group.id, user_id)

    sessions = (
        await db.execute(
            select(GroupSession)
            .where(GroupSession.group_id == group.id)
            .order_by(GroupSession.session_number)
        )
    ).scalars().all()

    return {
        "id": group.id,
        "join_code": group.join_code,
        "challenge_id": group.challenge_id,
        "status": group.status,
        "max_members": group.max_members,
        "created_by": group.created_by,
        "members": await _members_payload(db, group.id),
        "sessions": [
            {
                "session_number": s.session_number,
                "status": s.status,
                "conversation_id": s.conversation_id,
                "best_pei": s.best_pei,
                "session_avg_pei": s.session_avg_pei,
            }
            for s in sessions
        ],
    }


# --- Instructor team management (Phase 2) ---------------------------------
#
# Teams are prof-assigned from the section roster. A team is a GroupChallenge
# scoped to (classroom_id, challenge_id); members are GroupMember rows. All
# endpoints are instructor-gated via _assert_user_manages_classroom.


class GroupModeBody(BaseModel):
    mode: str = Field(..., pattern="^(solo|group)$")
    team_min: int = Field(default=2, ge=2, le=4)
    team_max: int = Field(default=4, ge=2, le=4)


class CreateTeamBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class AddMemberBody(BaseModel):
    user_id: str = Field(..., min_length=1)


async def _get_assignment(db: AsyncSession, classroom_id: str, challenge_id: str) -> ClassroomChallenge:
    cc = (
        await db.execute(
            select(ClassroomChallenge).where(
                ClassroomChallenge.classroom_id == classroom_id,
                ClassroomChallenge.challenge_id == challenge_id,
            )
        )
    ).scalar_one_or_none()
    if not cc:
        raise HTTPException(status_code=404, detail="Challenge is not assigned to this section")
    return cc


async def _teams_for(db: AsyncSession, classroom_id: str, challenge_id: str) -> list[GroupChallenge]:
    r = await db.execute(
        select(GroupChallenge)
        .where(
            GroupChallenge.classroom_id == classroom_id,
            GroupChallenge.challenge_id == challenge_id,
        )
        .order_by(GroupChallenge.created_at)
    )
    return list(r.scalars().all())


async def _team_or_404(db: AsyncSession, team_id: str, classroom_id: str, challenge_id: str) -> GroupChallenge:
    t = await db.get(GroupChallenge, team_id)
    if not t or t.classroom_id != classroom_id or t.challenge_id != challenge_id:
        raise HTTPException(status_code=404, detail="Team not found in this section/challenge")
    return t


def _avg(vals: list) -> float | None:
    nums = [v for v in vals if v is not None]
    return round(sum(nums) / len(nums), 1) if nums else None


async def _team_analytics(db: AsyncSession, team: GroupChallenge) -> dict:
    """Contribution analytics for one team, aggregated across all of its sessions.

    Per-student metrics are PURELY about participation (how many prompts each
    member sent and their share of the team's prompts) — these are valid
    attributions from Message.sender_user_id. Quality (PEI + dimension averages)
    is reported at the TEAM level only: the per-turn evaluator scores the whole
    shared conversation up to that turn, so a turn's score reflects the context
    every member built, not the lone author. Per-student skill scoring is a
    separate, deliberate feature (attributed re-evaluation), not done here.

    In the private-coach arm the shared conversation stays empty and every turn
    is in a member's own coach_private conversation, so both are read: a prompt
    there belongs to the conversation's owner, and the team-level quality is the
    mean over every member's turns, as in _end_coach_session.
    """
    members = await _members_payload(db, team.id)
    name_by_id = {m["user_id"]: m["name"] for m in members}

    sessions = (
        await db.execute(
            select(GroupSession)
            .where(GroupSession.group_id == team.id)
            .order_by(GroupSession.session_number)
        )
    ).scalars().all()

    turns_by_user: dict[str, int] = defaultdict(int)
    total_turns = 0
    timeline: list[dict] = []
    all_evals: list[EvalResult] = []
    sessions_with_activity = 0

    for s in sessions:
        convs = (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.group_session_id == s.id,
                    (Conversation.id == s.conversation_id) | (Conversation.kind == "coach_private"),
                )
                .order_by(Conversation.started_at, Conversation.id)
            )
        ).scalars().all()
        session_rows: list[tuple] = []
        for conv in convs:
            umsgs = (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id, Message.role == "user")
                    .order_by(Message.created_at, Message.id)
                )
            ).scalars().all()
            evals = (
                await db.execute(
                    select(EvalResult)
                    .where(EvalResult.conversation_id == conv.id)
                    .order_by(EvalResult.created_at, EvalResult.id)
                )
            ).scalars().all()
            all_evals.extend(evals)
            private = conv.kind == "coach_private"
            # Within a conversation the Nth user message pairs with the Nth eval
            # (both ordered by created_at, id) — the same reconstruction the
            # post-session analysis uses.
            for i, m in enumerate(umsgs):
                sender = m.sender_user_id or (conv.user_id if private else None)
                ev = evals[i] if i < len(evals) else None
                session_rows.append((m.created_at, m.id, sender, i + 1, ev))
        if session_rows:
            sessions_with_activity += 1
        # One timeline per session in the order the prompts were sent. `turn`
        # is the turn within its own conversation: a private coach's third
        # turn is that student's third, whatever teammates did in between.
        session_rows.sort(key=lambda r: (r[0] is None, r[0] or 0, r[1]))
        for _created, _mid, sender, turn, ev in session_rows:
            total_turns += 1
            if sender:
                turns_by_user[sender] += 1
            timeline.append(
                {
                    "session": s.session_number,
                    "turn": turn,
                    "sender_user_id": sender,
                    "sender_name": name_by_id.get(sender, "Unknown"),
                    "pei": ev.pei if ev else None,
                }
            )

    # Resolve names for any prompt author no longer on the team (removed after
    # participating) so their contribution still shows and shares still sum to 100%.
    member_ids = {m["user_id"] for m in members}
    extra_ids = [uid for uid in turns_by_user if uid and uid not in member_ids]
    extra_names: dict[str, str] = {}
    if extra_ids:
        rows = await db.execute(select(User.id, User.name).where(User.id.in_(extra_ids)))
        extra_names = {uid: nm for uid, nm in rows.all()}

    def _share(t: int) -> float:
        return round(100.0 * t / total_turns, 1) if total_turns else 0.0

    participants = [
        {
            "user_id": m["user_id"],
            "name": m["name"],
            "turns": turns_by_user.get(m["user_id"], 0),
            "share_pct": _share(turns_by_user.get(m["user_id"], 0)),
            "on_team": True,
        }
        for m in members
    ]
    participants += [
        {
            "user_id": uid,
            "name": extra_names.get(uid, "Former member"),
            "turns": turns_by_user[uid],
            "share_pct": _share(turns_by_user[uid]),
            "on_team": False,
        }
        for uid in extra_ids
    ]
    participants.sort(key=lambda p: p["turns"], reverse=True)

    return {
        "team": {"id": team.id, "name": team.name, "status": team.status},
        "total_turns": total_turns,
        "sessions_with_activity": sessions_with_activity,
        "members": participants,
        "team_pei_avg": _avg([e.pei for e in all_evals]),
        "team_pei_best": max([e.pei for e in all_evals if e.pei is not None], default=None),
        "team_dimensions": {
            "PSQ": _avg([e.psq for e in all_evals]),
            "CCM": _avg([e.ccm for e in all_evals]),
            "TSI": _avg([e.tsi for e in all_evals]),
            "CLM": _avg([e.clm for e in all_evals]),
            "RAS": _avg([e.ras for e in all_evals]),
        },
        "timeline": timeline,
    }


@team_router.patch("/{classroom_id}/challenges/{challenge_id}/group-mode")
async def set_group_mode(
    classroom_id: str,
    challenge_id: str,
    body: GroupModeBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: switch an assignment between solo and group mode (and set team size)."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    if body.team_min > body.team_max:
        raise HTTPException(status_code=400, detail="team_min cannot exceed team_max")
    cc = await _get_assignment(db, classroom_id, challenge_id)
    cc.mode = body.mode
    cc.team_min = body.team_min
    cc.team_max = body.team_max
    await db.commit()
    return {
        "classroom_id": classroom_id,
        "challenge_id": challenge_id,
        "mode": cc.mode,
        "team_min": cc.team_min,
        "team_max": cc.team_max,
    }


@team_router.get("/{classroom_id}/challenges/{challenge_id}/teams")
async def list_teams(
    classroom_id: str,
    challenge_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: all teams (with members) for this assignment + the roster students
    not yet on a team, so the UI can build/move pods."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    cc = await _get_assignment(db, classroom_id, challenge_id)
    teams = await _teams_for(db, classroom_id, challenge_id)

    out_teams = []
    assigned: set[str] = set()
    for t in teams:
        members = await _members_payload(db, t.id)
        assigned.update(m["user_id"] for m in members)
        out_teams.append(
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "max_members": t.max_members,
                "members": members,
                "review_pairings": await _pairings_payload(db, t.id),
            }
        )

    roster = await db.execute(
        select(User.id, User.name, User.email)
        .join(ClassroomMembership, ClassroomMembership.user_id == User.id)
        .where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.role == "student",
        )
        .order_by(User.name, User.email)
    )
    unassigned = [
        {"user_id": uid, "name": name, "email": email}
        for uid, name, email in roster.all()
        if uid not in assigned
    ]
    ch = await db.get(Challenge, challenge_id)
    return {
        "mode": cc.mode,
        "team_min": cc.team_min,
        "team_max": cc.team_max,
        # So the team builder knows whether to show the reviewer pairings.
        "verification_policy": cc.verification_policy or "none",
        # For the contested-pair form: which session, which section.
        "total_sessions": ch.total_sessions if ch else 1,
        "sections": [{"key": s.get("key"), "title": s.get("title") or s.get("key")}
                     for s in (_sections_of(ch) if ch else []) if s.get("key")],
        "teams": out_teams,
        "unassigned_students": unassigned,
    }


@team_router.get("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/analytics")
async def team_analytics(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: contribution analytics for one team — per-student prompt share
    (participation) plus team-level scoring. See _team_analytics for the
    participation-vs-quality boundary."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)
    return await _team_analytics(db, team)


@team_router.get("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/turn-taking")
async def team_turn_taking(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: turn-taking metrics for one team, one entry per session.

    The same numbers as /research/sessions/{id}/turn-taking, reached through a
    different door. The research route is unscoped (it can read any session in
    the deployment, so it is admin-or-section-instructor by id); this one is
    scoped to a classroom the caller manages, which is the boundary the team's
    contribution analytics already sits behind. Deliberately a second endpoint
    rather than a relaxed guard on the first.

    NOT aggregated across sessions. Alternation and read-before-write are
    defined per session, and averaging rates over sessions of different lengths
    would let a two-turn session outweigh a twenty-turn one.

    Instructor-only by design: showing contribution share to students during a
    session turns the measurement into an incentive.
    """
    from analysis.turn_taking import compute_turn_taking, events_for_group_session

    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)

    members = [
        row for (row,) in (
            await db.execute(
                select(GroupMember.user_id).where(GroupMember.group_id == team.id)
            )
        ).all()
    ]
    names: dict[str, str] = {}
    if members:
        rows = await db.execute(select(User.id, User.name).where(User.id.in_(members)))
        names = {uid: nm for uid, nm in rows.all()}

    sessions = (
        await db.execute(
            select(GroupSession)
            .where(GroupSession.group_id == team.id)
            .order_by(GroupSession.session_number)
        )
    ).scalars().all()

    out = []
    for s in sessions:
        events = await events_for_group_session(db, s.id)
        out.append({
            "group_session_id": s.id,
            "session_number": s.session_number,
            "status": s.status,
            **compute_turn_taking(events, members),
        })

    return {"team_id": team.id, "member_names": names, "sessions": out}


class PairingItem(BaseModel):
    author_user_id: str
    reviewer_user_id: str


class ReviewPairingsBody(BaseModel):
    pairings: list[PairingItem]


@team_router.put("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/review-pairings")
async def set_review_pairings(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    body: ReviewPairingsBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: replace who-reviews-whom for one team (instructor_assigned).

    Replaces the whole map rather than patching one pair, so the saved state is
    always exactly what the instructor saw. Editable at any time: every review
    row records the reviewer it was actually routed to, so a change made
    mid-session is visible in the data without a separate lock or log."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    await _team_or_404(db, team_id, classroom_id, challenge_id)

    members = {
        uid for (uid,) in (await db.execute(
            select(GroupMember.user_id).where(GroupMember.group_id == team_id)
        )).all()
    }
    seen: set[str] = set()
    for p in body.pairings:
        if p.author_user_id not in members or p.reviewer_user_id not in members:
            raise HTTPException(status_code=400, detail="Pairings can only name students on this team")
        if p.author_user_id == p.reviewer_user_id:
            raise HTTPException(status_code=400, detail="A student cannot review their own work")
        if p.author_user_id in seen:
            raise HTTPException(status_code=400, detail="Each student can have only one reviewer")
        seen.add(p.author_user_id)

    await db.execute(delete(ReviewPairing).where(ReviewPairing.group_id == team_id))
    for p in body.pairings:
        db.add(ReviewPairing(group_id=team_id, author_user_id=p.author_user_id,
                             reviewer_user_id=p.reviewer_user_id))
    await db.commit()
    return {"team_id": team_id, "review_pairings": await _pairings_payload(db, team_id)}


@team_router.get("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/sessions")
async def team_sessions(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: this team's sessions that have started, for the research
    data download. A session written ahead of time (e.g. a contested pair) but
    never joined has no data to export, so it is left out."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)
    sessions = (
        await db.execute(
            select(GroupSession)
            .where(GroupSession.group_id == team.id, GroupSession.conversation_id.is_not(None))
            .order_by(GroupSession.session_number)
        )
    ).scalars().all()
    return {"team_id": team.id, "sessions": [
        {"group_session_id": s.id, "session_number": s.session_number, "status": s.status}
        for s in sessions
    ]}


@team_router.get("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/reviews")
async def team_reviews(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: every peer review in this team's sessions with its derived
    outcome, one entry per session, so pending ones can be reassigned. Same
    classification as /verification/outcomes, scoped to a classroom the caller
    manages."""
    from verification import outcomes_for_session

    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)
    sessions = (
        await db.execute(
            select(GroupSession)
            .where(GroupSession.group_id == team.id)
            .order_by(GroupSession.session_number)
        )
    ).scalars().all()
    out = []
    for s in sessions:
        rows = await outcomes_for_session(db, s.id)
        if rows:
            out.append({"group_session_id": s.id, "session_number": s.session_number,
                        "status": s.status, "assignments": rows})
    return {"team_id": team.id, "sessions": out}


class TeamPairBody(BaseModel):
    session_number: int = Field(..., ge=1, le=6)
    subproblem_key: str = Field(..., min_length=1, max_length=64)
    # A is always the teammate's answer and B always the coach's. Named that
    # way here so the form cannot put them the wrong way round.
    teammate_answer: str = Field(..., min_length=1, max_length=8000)
    coach_answer: str = Field(..., min_length=1, max_length=8000)
    surfaced_to_user_id: str
    better_option: str | None = Field(None, pattern="^(a|b)$")


async def _get_or_create_group_session(db: AsyncSession, team: GroupChallenge,
                                       session_number: int) -> GroupSession:
    """The session row a pair attaches to, created ahead of time if the team has
    not started that session yet, so pairs can be written before class.

    Only the bare row — no conversation, no team status change. The coach socket
    runs main._ensure_group_session on connect, which finds this row and fills
    in the rest exactly as it would have."""
    gs = (await db.execute(
        select(GroupSession).where(GroupSession.group_id == team.id,
                                   GroupSession.session_number == session_number)
    )).scalar_one_or_none()
    if gs is None:
        gs = GroupSession(group_id=team.id, challenge_id=team.challenge_id,
                          session_number=session_number, status="not_started")
        db.add(gs)
        await db.commit()
    return gs


@team_router.get("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/contested-pairs")
async def list_team_pairs(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: the scripted pairs for this team, with whether each has been
    shown and what the student chose. Instructor-facing, so A/B are labelled as
    teammate/coach here; the student API never labels them."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)
    rows = (await db.execute(
        select(ContestedPair, GroupSession.session_number)
        .join(GroupSession, GroupSession.id == ContestedPair.group_session_id)
        .where(GroupSession.group_id == team.id)
        .order_by(GroupSession.session_number, ContestedPair.created_at)
    )).all()
    responses = {
        r.pair_id: r for r in (await db.execute(
            select(ContestedResponse).where(
                ContestedResponse.pair_id.in_([p.id for p, _ in rows] or [""]))
        )).scalars().all()
    }
    out = []
    for p, session_number in rows:
        r = responses.get(p.id)
        out.append({
            "pair_id": p.id,
            "session_number": session_number,
            "subproblem_key": p.subproblem_key,
            "surfaced_to_user_id": p.surfaced_to_user_id,
            "teammate_answer": p.option_a_text,
            "coach_answer": p.option_b_text,
            "better_option": p.better_option,
            "surfaced": p.surfaced_at is not None,
            "adopted": r.adopted if r else None,
            "uninspected_adoption": bool(r) and not (r.inspected_a or r.inspected_b),
        })
    return {"team_id": team.id, "pairs": out}


@team_router.post("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/contested-pairs",
                  status_code=201)
async def create_team_pair(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    body: TeamPairBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: script a contested pair for one student in one session.

    The student sees it when they are next in that session: at connect if the
    session has not started, or within moments if it is live."""
    from contested import ScriptPairBody, create_scripted_pair, notify_new_pair

    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)
    ch = await db.get(Challenge, challenge_id)
    if ch is None or body.session_number > (ch.total_sessions or 1):
        raise HTTPException(status_code=400, detail="That session does not exist in this challenge")
    keys = {s.get("key") for s in _sections_of(ch)}
    # With authored sections, the pair must name one: inspection is derived
    # from reads of that section key, so a key no section has could never be
    # inspected and every adoption would read as uninspected.
    if keys and body.subproblem_key not in keys:
        raise HTTPException(status_code=400, detail="Pick one of this challenge's sections")

    gs = await _get_or_create_group_session(db, team, body.session_number)
    if gs.status == "completed":
        raise HTTPException(status_code=409, detail="That session is already finished for this team")
    pair = await create_scripted_pair(db, gs.id, team.id, ScriptPairBody(
        subproblem_key=body.subproblem_key,
        option_a_text=body.teammate_answer,
        option_b_text=body.coach_answer,
        surfaced_to_user_id=body.surfaced_to_user_id,
        better_option=body.better_option,
    ))
    await notify_new_pair(gs.id)
    return {"pair_id": pair.id, "session_number": body.session_number}


@team_router.delete("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/contested-pairs/{pair_id}")
async def delete_team_pair(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    pair_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: remove a pair that has not been shown yet. Once a student has
    seen it, it is part of the record and stays."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)
    pair = await db.get(ContestedPair, pair_id)
    gs = await db.get(GroupSession, pair.group_session_id) if pair else None
    if pair is None or gs is None or gs.group_id != team.id:
        raise HTTPException(status_code=404, detail="Pair not found")
    if pair.surfaced_at is not None:
        raise HTTPException(status_code=409, detail="This pair has already been shown to the student")
    await db.delete(pair)
    await db.commit()
    return {"status": "deleted", "pair_id": pair_id}


@team_router.post("/{classroom_id}/challenges/{challenge_id}/teams", status_code=201)
async def create_team(
    classroom_id: str,
    challenge_id: str,
    body: CreateTeamBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: create an empty team for a group-mode assignment."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    cc = await _get_assignment(db, classroom_id, challenge_id)
    if cc.mode != "group":
        raise HTTPException(status_code=409, detail="This challenge is not in group mode for this section")
    team = GroupChallenge(
        challenge_id=challenge_id,
        classroom_id=classroom_id,
        name=(body.name or None),
        created_by=user_id,
        status="open",
        max_members=cc.team_max,
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    log.info("team created id=%s classroom=%s challenge=%s by=%s", team.id, classroom_id, challenge_id, user_id[:8])
    return {
        "id": team.id,
        "name": team.name,
        "status": team.status,
        "max_members": team.max_members,
        "members": [],
    }


@team_router.post("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/members")
async def add_team_member(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    body: AddMemberBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: assign an enrolled student to a team. A student may be on at most
    one team per (classroom, challenge), and only enrolled section students qualify."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team = await _team_or_404(db, team_id, classroom_id, challenge_id)

    enrolled = (
        await db.execute(
            select(ClassroomMembership).where(
                ClassroomMembership.classroom_id == classroom_id,
                ClassroomMembership.user_id == body.user_id,
                ClassroomMembership.role == "student",
            )
        )
    ).scalar_one_or_none()
    if not enrolled:
        raise HTTPException(status_code=400, detail="That student is not enrolled in this section")

    team_ids = [t.id for t in await _teams_for(db, classroom_id, challenge_id)]
    existing = (
        await db.execute(
            select(GroupMember).where(
                GroupMember.group_id.in_(team_ids),
                GroupMember.user_id == body.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.group_id == team_id:
            return {"status": "already_member", "team_id": team_id, "members": await _members_payload(db, team_id)}
        raise HTTPException(status_code=409, detail="That student is already on another team for this challenge")

    if await _member_count(db, team_id) >= team.max_members:
        raise HTTPException(status_code=409, detail="This team is full")

    db.add(GroupMember(group_id=team_id, user_id=body.user_id))
    await db.commit()
    log.info("team member added team=%s user=%s", team_id, body.user_id[:8])
    return {"status": "added", "team_id": team_id, "members": await _members_payload(db, team_id)}


@team_router.delete("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}/members/{member_user_id}")
async def remove_team_member(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    member_user_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: remove a student from a team."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    await _team_or_404(db, team_id, classroom_id, challenge_id)
    await db.execute(
        delete(GroupMember).where(
            GroupMember.group_id == team_id,
            GroupMember.user_id == member_user_id,
        )
    )
    # Pairings naming someone who left can never be followed. Clearing them
    # makes the gap visible in the team builder now, instead of surfacing only
    # as unrouted reviews mid-session.
    await db.execute(
        delete(ReviewPairing).where(
            ReviewPairing.group_id == team_id,
            (ReviewPairing.author_user_id == member_user_id)
            | (ReviewPairing.reviewer_user_id == member_user_id),
        )
    )
    await db.commit()
    return {"status": "removed", "team_id": team_id, "members": await _members_payload(db, team_id)}


@team_router.delete("/{classroom_id}/challenges/{challenge_id}/teams/{team_id}")
async def delete_team(
    classroom_id: str,
    challenge_id: str,
    team_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: delete a team and its memberships."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    await _team_or_404(db, team_id, classroom_id, challenge_id)
    await db.execute(delete(ReviewPairing).where(ReviewPairing.group_id == team_id))
    await db.execute(delete(GroupMember).where(GroupMember.group_id == team_id))
    await db.execute(delete(GroupChallenge).where(GroupChallenge.id == team_id))
    await db.commit()
    log.info("team deleted team=%s", team_id)
    return {"status": "deleted", "team_id": team_id}
