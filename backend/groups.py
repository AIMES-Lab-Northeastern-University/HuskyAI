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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from challenges import get_current_user, get_db, _assert_user_manages_classroom
from database import (
    ClassroomChallenge,
    ClassroomMembership,
    GroupChallenge,
    GroupMember,
    GroupSession,
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
    return {
        "mode": cc.mode,
        "team_min": cc.team_min,
        "team_max": cc.team_max,
        "teams": out_teams,
        "unassigned_students": unassigned,
    }


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
    await db.execute(delete(GroupMember).where(GroupMember.group_id == team_id))
    await db.execute(delete(GroupChallenge).where(GroupChallenge.id == team_id))
    await db.commit()
    log.info("team deleted team=%s", team_id)
    return {"status": "deleted", "team_id": team_id}
