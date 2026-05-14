"""
Classrooms: join codes, memberships (student / instructor / admin).
Works with any Postgres (including Supabase) via DATABASE_URL; SQLite OK for local dev.
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import decode_token, pwd_context
from database import (
    AsyncSessionLocal,
    Challenge,
    Classroom,
    ClassroomChallenge,
    ClassroomMembership,
    Conversation,
    EvalResult,
    InstructorTestEnrollment,
    User,
    UserChallengeSession,
)

log = logging.getLogger("classrooms")

router = APIRouter(prefix="/classrooms", tags=["classrooms"])

_CODE_ALPHABET = string.ascii_uppercase + string.digits
# Omit ambiguous chars
_CODE_ALPHABET = _CODE_ALPHABET.replace("O", "").replace("0", "").replace("I", "").replace("1", "")


def _generate_join_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _assert_can_manage_classroom(db: AsyncSession, user_id: str, room: Classroom) -> None:
    if room.instructor_user_id == user_id:
        return
    r = await db.execute(
        select(ClassroomMembership).where(
            ClassroomMembership.user_id == user_id,
            ClassroomMembership.classroom_id == room.id,
            ClassroomMembership.role.in_(("instructor", "admin")),
        )
    )
    if r.scalar_one_or_none():
        return
    raise HTTPException(status_code=403, detail="Only a section instructor can update this classroom")


class CreateClassroomBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    listed_in_directory: bool = False
    is_test_section: bool = False


class UpdateClassroomBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    listed_in_directory: Optional[bool] = None


class JoinClassroomBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)


class TestAsStudentBody(BaseModel):
    enabled: bool = True


class ReorderChallengesBody(BaseModel):
    ordered_challenge_ids: list[str] = Field(..., min_length=1)


@router.post("")
async def create_classroom(
    body: CreateClassroomBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor creates a section; caller becomes instructor membership."""
    for _ in range(12):
        code = _generate_join_code()
        existing = await db.execute(select(Classroom).where(Classroom.join_code == code))
        if existing.scalar_one_or_none():
            continue
        room = Classroom(
            name=body.name.strip(),
            join_code=code,
            instructor_user_id=user_id,
            listed_in_directory=bool(body.listed_in_directory),
            is_test_section=bool(body.is_test_section),
        )
        db.add(room)
        await db.flush()
        db.add(
            ClassroomMembership(
                user_id=user_id,
                classroom_id=room.id,
                role="instructor",
            )
        )
        if body.is_test_section:
            db.add(
                InstructorTestEnrollment(
                    user_id=user_id,
                    classroom_id=room.id,
                )
            )
        await db.commit()
        await db.refresh(room)
        log.info("classroom created id=%s code=%s", room.id, code)
        return {
            "id": room.id,
            "name": room.name,
            "join_code": room.join_code,
            "role": "instructor",
            "listed_in_directory": bool(room.listed_in_directory),
            "is_test_section": bool(room.is_test_section),
        }
    raise HTTPException(status_code=500, detail="Could not allocate join code — retry")


@router.post("/join")
async def join_classroom(
    body: JoinClassroomBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw = body.code.strip().upper().replace(" ", "")
    result = await db.execute(select(Classroom).where(Classroom.join_code == raw, Classroom.is_active == True))  # noqa: E712
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Invalid or inactive class code")

    existing = await db.execute(
        select(ClassroomMembership).where(
            ClassroomMembership.user_id == user_id,
            ClassroomMembership.classroom_id == room.id,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "already_member", "classroom_id": room.id, "name": room.name}

    # Instructor record owns the class; if they join their own code, they already have membership
    db.add(
        ClassroomMembership(
            user_id=user_id,
            classroom_id=room.id,
            role="student",
        )
    )
    await db.commit()
    return {"status": "joined", "classroom_id": room.id, "name": room.name}


@router.post("/{classroom_id}/join-listed")
async def join_listed_classroom(
    classroom_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Join a section directly from the public directory. Only sections the
    instructor marked listed_in_directory=True can be joined this way; unlisted
    sections still require the private join code via POST /classrooms/join."""
    room = await db.get(Classroom, classroom_id)
    if not room or not room.is_active:
        raise HTTPException(status_code=404, detail="Section not found")
    if not room.listed_in_directory:
        raise HTTPException(status_code=403, detail="This section is not open for direct join — ask the instructor for a join code")

    existing = await db.execute(
        select(ClassroomMembership).where(
            ClassroomMembership.user_id == user_id,
            ClassroomMembership.classroom_id == room.id,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "already_member", "classroom_id": room.id, "name": room.name}

    db.add(
        ClassroomMembership(
            user_id=user_id,
            classroom_id=room.id,
            role="student",
        )
    )
    await db.commit()
    return {"status": "joined", "classroom_id": room.id, "name": room.name}


@router.get("/me")
async def list_my_classrooms(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Classroom, ClassroomMembership.role)
        .join(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
        .where(ClassroomMembership.user_id == user_id, Classroom.is_active == True)  # noqa: E712
    )
    result = await db.execute(q)
    rows = result.all()
    te_result = await db.execute(
        select(InstructorTestEnrollment.classroom_id).where(InstructorTestEnrollment.user_id == user_id)
    )
    test_room_ids = {row[0] for row in te_result.all()}
    out = []
    for room, role in rows:
        entry = {
            "id": room.id,
            "name": room.name,
            "role": role,
            "listed_in_directory": bool(room.listed_in_directory),
            "is_test_section": bool(getattr(room, "is_test_section", False)),
        }
        if role in ("instructor", "admin"):
            entry["join_code"] = room.join_code
            entry["test_as_student_enabled"] = room.id in test_room_ids
        out.append(entry)
    return out


@router.get("/browse")
async def browse_listed_classrooms(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sections the instructor chose to list (signed-in users only). Join codes are not exposed here."""
    stmt = (
        select(Classroom.id, Classroom.name, func.count(ClassroomMembership.id))
        .outerjoin(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
        .where(
            Classroom.is_active.is_(True),
            Classroom.listed_in_directory.is_(True),
        )
        .group_by(Classroom.id, Classroom.name)
        .order_by(Classroom.name)
    )
    result = await db.execute(stmt)
    return [
        {"id": row[0], "name": row[1], "member_count": int(row[2] or 0)}
        for row in result.all()
    ]


@router.patch("/{classroom_id}")
async def update_classroom(
    classroom_id: str,
    body: UpdateClassroomBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.name is None and body.listed_in_directory is None:
        raise HTTPException(status_code=400, detail="Provide name and/or listed_in_directory")

    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")

    await _assert_can_manage_classroom(db, user_id, room)

    if body.name is not None:
        room.name = body.name.strip()
    if body.listed_in_directory is not None:
        room.listed_in_directory = body.listed_in_directory
    await db.commit()
    await db.refresh(room)
    return {
        "id": room.id,
        "name": room.name,
        "listed_in_directory": bool(room.listed_in_directory),
        "join_code": room.join_code,
    }


@router.post("/{classroom_id}/test-as-student")
async def set_test_as_student_mode(
    classroom_id: str,
    body: TestAsStudentBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: opt in/out of seeing this section's challenges on the student Challenges list (try flows)."""
    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")
    await _assert_can_manage_classroom(db, user_id, room)

    existing = await db.execute(
        select(InstructorTestEnrollment).where(
            InstructorTestEnrollment.user_id == user_id,
            InstructorTestEnrollment.classroom_id == classroom_id,
        )
    )
    row = existing.scalar_one_or_none()

    if body.enabled:
        if not row:
            db.add(InstructorTestEnrollment(user_id=user_id, classroom_id=classroom_id))
        await db.commit()
        return {"enabled": True}
    if row:
        await db.execute(
            delete(InstructorTestEnrollment).where(
                InstructorTestEnrollment.user_id == user_id,
                InstructorTestEnrollment.classroom_id == classroom_id,
            )
        )
    await db.commit()
    return {"enabled": False}


@router.post("/{classroom_id}/challenges/reorder")
async def reorder_classroom_challenges(
    classroom_id: str,
    body: ReorderChallengesBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")
    await _assert_can_manage_classroom(db, user_id, room)

    linked = await db.execute(
        select(ClassroomChallenge.challenge_id).where(ClassroomChallenge.classroom_id == classroom_id)
    )
    linked_ids = {row[0] for row in linked.all()}
    if set(body.ordered_challenge_ids) != linked_ids:
        raise HTTPException(
            status_code=400,
            detail="ordered_challenge_ids must include every challenge assigned to this section, with no extras",
        )

    seen: set[str] = set()
    for ch_id in body.ordered_challenge_ids:
        if ch_id in seen:
            raise HTTPException(status_code=400, detail="Duplicate challenge id in list")
        seen.add(ch_id)

    for i, ch_id in enumerate(body.ordered_challenge_ids):
        r = await db.execute(
            select(ClassroomChallenge).where(
                ClassroomChallenge.classroom_id == classroom_id,
                ClassroomChallenge.challenge_id == ch_id,
            )
        )
        link = r.scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=400, detail=f"Challenge {ch_id} is not assigned to this section")
        link.sort_order = i
    await db.commit()
    return {"status": "ok"}


@router.delete("/{classroom_id}/challenges/{challenge_id}")
async def unlink_challenge_from_classroom(
    classroom_id: str,
    challenge_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove assignment from section (does not delete the challenge row)."""
    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")
    await _assert_can_manage_classroom(db, user_id, room)
    await db.execute(
        delete(ClassroomChallenge).where(
            ClassroomChallenge.classroom_id == classroom_id,
            ClassroomChallenge.challenge_id == challenge_id,
        )
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/{classroom_id}/challenges")
async def list_classroom_linked_challenges(
    classroom_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor-only: challenges assigned to this section."""
    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")
    await _assert_can_manage_classroom(db, user_id, room)
    q = (
        select(Challenge, ClassroomChallenge.sort_order)
        .join(ClassroomChallenge, ClassroomChallenge.challenge_id == Challenge.id)
        .where(ClassroomChallenge.classroom_id == classroom_id)
        .order_by(ClassroomChallenge.sort_order, Challenge.title)
    )
    result = await db.execute(q)
    return [
        {
            "id": c.id,
            "title": c.title,
            "description": c.description,
            "category": c.category,
            "difficulty": c.difficulty,
            "total_sessions": c.total_sessions,
            "is_active": bool(c.is_active),
            "week": c.week,
            "sort_order": int(sort_order),
        }
        for c, sort_order in result.all()
    ]


@router.get("/{classroom_id}/summary")
async def classroom_summary(
    classroom_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Member-only: basic stats, no transcripts (aggregate-friendly)."""
    mem_result = await db.execute(
        select(ClassroomMembership).where(
            ClassroomMembership.user_id == user_id,
            ClassroomMembership.classroom_id == classroom_id,
        )
    )
    membership = mem_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this classroom")

    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")

    n_members = await db.scalar(
        select(func.count()).select_from(ClassroomMembership).where(ClassroomMembership.classroom_id == classroom_id)
    )
    return {
        "id": room.id,
        "name": room.name,
        "member_count": int(n_members or 0),
        "your_role": membership.role,
        "listed_in_directory": bool(room.listed_in_directory),
    }


@router.get("/{classroom_id}/analytics")
async def classroom_instructor_analytics(
    classroom_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Instructor-only: aggregate activity for this section’s students on assigned challenges.
    Section-level only (no per-student breakdown); use GET .../roster and
    .../students/{id}/activity for drill-down. No transcripts.
    """
    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")
    await _assert_can_manage_classroom(db, user_id, room)

    stu_rows = await db.execute(
        select(ClassroomMembership.user_id).where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.role == "student",
        )
    )
    student_ids = [row[0] for row in stu_rows.all()]

    ch_rows = await db.execute(
        select(ClassroomChallenge.challenge_id)
        .where(ClassroomChallenge.classroom_id == classroom_id)
        .order_by(ClassroomChallenge.sort_order, ClassroomChallenge.challenge_id)
    )
    challenge_ids = [row[0] for row in ch_rows.all()]

    n_total_members = await db.scalar(
        select(func.count()).select_from(ClassroomMembership).where(ClassroomMembership.classroom_id == classroom_id)
    )

    out: dict = {
        "classroom_id": classroom_id,
        "student_count": len(student_ids),
        "total_member_count": int(n_total_members or 0),
        "assigned_challenge_count": len(challenge_ids),
        "sessions_started": 0,
        "sessions_completed": 0,
        "avg_best_pei": None,
        "students_with_activity": 0,
        "workspace_conversations": 0,
        "workspace_turns_total": 0,
        "students_in_workspace": 0,
        "eval_turns_count": 0,
        "avg_eval_pei": None,
        "students_idle_count": 0,
        "last_activity_at": None,
        "by_challenge": [],
    }

    conv_scope = ()
    if student_ids:
        conv_scope = (
            Conversation.classroom_id == classroom_id,
            Conversation.user_id.in_(student_ids),
        )
        n_wc = await db.scalar(select(func.count()).select_from(Conversation).where(*conv_scope))
        out["workspace_conversations"] = int(n_wc or 0)
        wt = await db.scalar(
            select(func.coalesce(func.sum(Conversation.turn_count), 0)).where(*conv_scope)
        )
        out["workspace_turns_total"] = int(wt or 0)
        ws = await db.execute(select(Conversation.user_id).where(*conv_scope).distinct())
        out["students_in_workspace"] = len(ws.all())

        ne = await db.scalar(
            select(func.count())
            .select_from(EvalResult)
            .join(Conversation, EvalResult.conversation_id == Conversation.id)
            .where(*conv_scope)
        )
        out["eval_turns_count"] = int(ne or 0)
        ae = await db.scalar(
            select(func.avg(EvalResult.pei))
            .select_from(EvalResult)
            .join(Conversation, EvalResult.conversation_id == Conversation.id)
            .where(*conv_scope, EvalResult.pei.is_not(None))
        )
        if ae is not None:
            out["avg_eval_pei"] = round(float(ae), 2)

    base_scope = ()
    if student_ids and challenge_ids:
        base_scope = (
            UserChallengeSession.user_id.in_(student_ids),
            UserChallengeSession.challenge_id.in_(challenge_ids),
        )

        n_started = await db.scalar(
            select(func.count()).select_from(UserChallengeSession).where(
                *base_scope,
                UserChallengeSession.status.in_(("in_progress", "completed")),
            )
        )
        out["sessions_started"] = int(n_started or 0)

        n_completed = await db.scalar(
            select(func.count()).select_from(UserChallengeSession).where(
                *base_scope,
                UserChallengeSession.status == "completed",
            )
        )
        out["sessions_completed"] = int(n_completed or 0)

        avg_pei = await db.scalar(
            select(func.avg(UserChallengeSession.best_pei)).where(
                *base_scope,
                UserChallengeSession.best_pei.is_not(None),
            )
        )
        if avg_pei is not None:
            out["avg_best_pei"] = round(float(avg_pei), 2)

        act_rows = await db.execute(
            select(UserChallengeSession.user_id)
            .where(
                *base_scope,
                UserChallengeSession.status.in_(("in_progress", "completed")),
            )
            .distinct()
        )
        out["students_with_activity"] = len(act_rows.all())

        st_started = await db.execute(
            select(UserChallengeSession.challenge_id, func.count())
            .where(
                *base_scope,
                UserChallengeSession.status.in_(("in_progress", "completed")),
            )
            .group_by(UserChallengeSession.challenge_id)
        )
        started_map = {row[0]: int(row[1]) for row in st_started.all()}

        st_done = await db.execute(
            select(UserChallengeSession.challenge_id, func.count())
            .where(*base_scope, UserChallengeSession.status == "completed")
            .group_by(UserChallengeSession.challenge_id)
        )
        done_map = {row[0]: int(row[1]) for row in st_done.all()}

        st_avg = await db.execute(
            select(UserChallengeSession.challenge_id, func.avg(UserChallengeSession.best_pei))
            .where(*base_scope, UserChallengeSession.best_pei.is_not(None))
            .group_by(UserChallengeSession.challenge_id)
        )
        avg_map = {row[0]: round(float(row[1]), 2) for row in st_avg.all() if row[1] is not None}

        titles = await db.execute(select(Challenge.id, Challenge.title).where(Challenge.id.in_(challenge_ids)))
        title_map = {row[0]: row[1] for row in titles.all()}

        out["by_challenge"] = [
            {
                "challenge_id": cid,
                "title": title_map.get(cid, ""),
                "sessions_started": started_map.get(cid, 0),
                "sessions_completed": done_map.get(cid, 0),
                "avg_best_pei": avg_map.get(cid),
            }
            for cid in challenge_ids
        ]

    out["students_idle_count"] = max(0, out["student_count"] - out["students_with_activity"])

    last_candidates: list = []
    if student_ids and conv_scope:
        m_conv = await db.scalar(select(func.max(Conversation.started_at)).where(*conv_scope))
        if m_conv is not None:
            last_candidates.append(m_conv)
    if base_scope:
        m1 = await db.scalar(select(func.max(UserChallengeSession.started_at)).where(*base_scope))
        m2 = await db.scalar(select(func.max(UserChallengeSession.completed_at)).where(*base_scope))
        for m in (m1, m2):
            if m is not None:
                last_candidates.append(m)
    if last_candidates:
        latest = max(last_candidates)
        if hasattr(latest, "isoformat"):
            out["last_activity_at"] = latest.isoformat() + ("Z" if latest.tzinfo is None else "")

    return out


def _iso_dt(dt) -> str | None:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat() + ("Z" if getattr(dt, "tzinfo", None) is None else "")
    return None


@router.get("/{classroom_id}/roster")
async def classroom_roster(
    classroom_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor-only: student members (id, name, email) for drill-down and contact."""
    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")
    await _assert_can_manage_classroom(db, user_id, room)

    r = await db.execute(
        select(User.id, User.name, User.email, ClassroomMembership.joined_at)
        .join(ClassroomMembership, ClassroomMembership.user_id == User.id)
        .where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.role == "student",
        )
        .order_by(User.name, User.email)
    )
    rows = r.all()
    return [
        {
            "user_id": uid,
            "name": name,
            "email": email,
            "joined_at": _iso_dt(joined),
        }
        for uid, name, email, joined in rows
    ]


@router.get("/{classroom_id}/students/{student_user_id}/activity")
async def classroom_student_activity(
    classroom_id: str,
    student_user_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Instructor-only: per-student activity on this section’s assigned challenges and workspace.
    No chat transcripts — counts, PEI summaries, and session rows only.
    """
    room = await db.get(Classroom, classroom_id)
    if not room:
        raise HTTPException(status_code=404, detail="Classroom not found")
    await _assert_can_manage_classroom(db, user_id, room)

    mem = await db.execute(
        select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.user_id == student_user_id,
            ClassroomMembership.role == "student",
        )
    )
    if not mem.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Student not found in this section")

    stu = await db.get(User, student_user_id)
    if not stu:
        raise HTTPException(status_code=404, detail="User not found")

    ch_rows = await db.execute(
        select(ClassroomChallenge.challenge_id, ClassroomChallenge.sort_order)
        .where(ClassroomChallenge.classroom_id == classroom_id)
        .order_by(ClassroomChallenge.sort_order, ClassroomChallenge.challenge_id)
    )
    ch_ordered = ch_rows.all()
    challenge_ids = [row[0] for row in ch_ordered]
    sort_map = {row[0]: int(row[1]) for row in ch_ordered}

    conv_scope = (
        Conversation.classroom_id == classroom_id,
        Conversation.user_id == student_user_id,
    )
    n_conv = await db.scalar(select(func.count()).select_from(Conversation).where(*conv_scope))
    turns = await db.scalar(
        select(func.coalesce(func.sum(Conversation.turn_count), 0)).where(*conv_scope)
    )
    ne = await db.scalar(
        select(func.count())
        .select_from(EvalResult)
        .join(Conversation, EvalResult.conversation_id == Conversation.id)
        .where(*conv_scope)
    )
    ae = await db.scalar(
        select(func.avg(EvalResult.pei))
        .select_from(EvalResult)
        .join(Conversation, EvalResult.conversation_id == Conversation.id)
        .where(*conv_scope, EvalResult.pei.is_not(None))
    )
    m_conv = await db.scalar(select(func.max(Conversation.started_at)).where(*conv_scope))

    last_candidates: list = []
    if m_conv is not None:
        last_candidates.append(m_conv)

    out_workspace = {
        "conversations": int(n_conv or 0),
        "turns_total": int(turns or 0),
        "eval_turns": int(ne or 0),
        "avg_eval_pei": round(float(ae), 2) if ae is not None else None,
        "last_workspace_at": _iso_dt(m_conv),
    }

    sessions_started = 0
    sessions_completed = 0
    avg_best = None
    by_challenge: list = []
    session_rows: list = []

    if challenge_ids:
        base = (
            UserChallengeSession.user_id == student_user_id,
            UserChallengeSession.challenge_id.in_(challenge_ids),
        )
        sessions_started = int(
            await db.scalar(
                select(func.count()).select_from(UserChallengeSession).where(
                    *base,
                    UserChallengeSession.status.in_(("in_progress", "completed")),
                )
            )
            or 0
        )
        sessions_completed = int(
            await db.scalar(
                select(func.count()).select_from(UserChallengeSession).where(
                    *base,
                    UserChallengeSession.status == "completed",
                )
            )
            or 0
        )
        ab = await db.scalar(
            select(func.avg(UserChallengeSession.best_pei)).where(
                *base,
                UserChallengeSession.best_pei.is_not(None),
            )
        )
        if ab is not None:
            avg_best = round(float(ab), 2)

        m1 = await db.scalar(select(func.max(UserChallengeSession.started_at)).where(*base))
        m2 = await db.scalar(select(func.max(UserChallengeSession.completed_at)).where(*base))
        for m in (m1, m2):
            if m is not None:
                last_candidates.append(m)

        st_started = await db.execute(
            select(UserChallengeSession.challenge_id, func.count())
            .where(
                *base,
                UserChallengeSession.status.in_(("in_progress", "completed")),
            )
            .group_by(UserChallengeSession.challenge_id)
        )
        started_map = {row[0]: int(row[1]) for row in st_started.all()}
        st_done = await db.execute(
            select(UserChallengeSession.challenge_id, func.count())
            .where(*base, UserChallengeSession.status == "completed")
            .group_by(UserChallengeSession.challenge_id)
        )
        done_map = {row[0]: int(row[1]) for row in st_done.all()}
        st_avg = await db.execute(
            select(UserChallengeSession.challenge_id, func.avg(UserChallengeSession.best_pei))
            .where(*base, UserChallengeSession.best_pei.is_not(None))
            .group_by(UserChallengeSession.challenge_id)
        )
        avg_map = {row[0]: round(float(row[1]), 2) for row in st_avg.all() if row[1] is not None}
        titles = await db.execute(select(Challenge.id, Challenge.title).where(Challenge.id.in_(challenge_ids)))
        title_map = {row[0]: row[1] for row in titles.all()}

        by_challenge = [
            {
                "challenge_id": cid,
                "title": title_map.get(cid, ""),
                "sort_order": sort_map.get(cid, 0),
                "sessions_started": started_map.get(cid, 0),
                "sessions_completed": done_map.get(cid, 0),
                "avg_best_pei": avg_map.get(cid),
            }
            for cid in challenge_ids
        ]

        sr = await db.execute(
            select(
                UserChallengeSession.challenge_id,
                UserChallengeSession.session_number,
                UserChallengeSession.status,
                UserChallengeSession.best_pei,
                UserChallengeSession.started_at,
                UserChallengeSession.completed_at,
                Challenge.title,
            )
            .join(Challenge, Challenge.id == UserChallengeSession.challenge_id)
            .where(*base)
            .order_by(UserChallengeSession.challenge_id, UserChallengeSession.session_number)
        )
        for row in sr.all():
            cid, snum, st, bpei, sa, ca, ctitle = row
            session_rows.append(
                {
                    "challenge_id": cid,
                    "challenge_title": ctitle,
                    "session_number": int(snum),
                    "status": st,
                    "best_pei": round(float(bpei), 2) if bpei is not None else None,
                    "started_at": _iso_dt(sa),
                    "completed_at": _iso_dt(ca),
                }
            )
        session_rows.sort(
            key=lambda x: (sort_map.get(x["challenge_id"], 0), x["challenge_id"], x["session_number"])
        )

    last_activity_at = None
    if last_candidates:
        latest = max(last_candidates)
        last_activity_at = _iso_dt(latest)

    return {
        "classroom_id": classroom_id,
        "student": {
            "user_id": stu.id,
            "name": stu.name,
            "email": stu.email,
        },
        "workspace": {**out_workspace, "last_activity_at": last_activity_at},
        "challenge_sessions": {
            "sessions_started": sessions_started,
            "sessions_completed": sessions_completed,
            "avg_best_pei": avg_best,
        },
        "by_challenge": by_challenge,
        "session_rows": session_rows,
    }


# --- Seeded demo section (join code + one challenge) for local / QA testing ---

DEMO_SECTION_NAME = "Husky Test Section"
DEFAULT_SEED_JOIN_CODE = "HUSKYDMX"
DEMO_CHALLENGE_TITLE = "Debug a Failing Web App"

# --- Seeded pilot section (join code + all active challenges) for pilot invitations ---

PILOT_SECTION_NAME = "HuskyAI Pilot"
DEFAULT_PILOT_JOIN_CODE = "TRYHUSKY"
SEED_INSTRUCTOR_EMAIL = os.getenv("SEED_INSTRUCTOR_EMAIL", "husky.test.instructor@example.com").strip().lower()
SEED_INSTRUCTOR_NAME = os.getenv("SEED_INSTRUCTOR_NAME", "Husky Test Instructor").strip()
SEED_INSTRUCTOR_PASSWORD = os.getenv("SEED_INSTRUCTOR_PASSWORD", "TestHusky_Demo1")


def _validate_seed_join_code(raw: str) -> str:
    code = raw.strip().upper().replace(" ", "")
    if len(code) < 4 or len(code) > 16:
        raise ValueError("SEED_CLASSROOM_CODE must be 4–16 characters")
    for c in code:
        if c not in _CODE_ALPHABET:
            raise ValueError(
                f"SEED_CLASSROOM_CODE uses invalid character {c!r} "
                f"(allowed: A–Z except O/I, digits except 0/1)"
            )
    return code


async def seed_demo_classroom() -> None:
    """Ensure demo instructor, fixed join-code section, and one linked challenge exist."""
    try:
        code = _validate_seed_join_code(os.getenv("SEED_CLASSROOM_CODE", DEFAULT_SEED_JOIN_CODE))
    except ValueError as e:
        log.warning("seed_demo_classroom skipped: %s", e)
        return

    async with AsyncSessionLocal() as db:
        r_user = await db.execute(select(User).where(User.email == SEED_INSTRUCTOR_EMAIL))
        instructor = r_user.scalar_one_or_none()
        if not instructor:
            instructor = User(
                email=SEED_INSTRUCTOR_EMAIL,
                name=SEED_INSTRUCTOR_NAME,
                password_hash=pwd_context.hash(SEED_INSTRUCTOR_PASSWORD),
            )
            db.add(instructor)
            await db.flush()
            log.info("Created seed instructor %s", SEED_INSTRUCTOR_EMAIL)

        r_room = await db.execute(select(Classroom).where(Classroom.join_code == code))
        room = r_room.scalar_one_or_none()
        if not room:
            room = Classroom(
                name=DEMO_SECTION_NAME,
                join_code=code,
                instructor_user_id=instructor.id,
                listed_in_directory=True,
            )
            db.add(room)
            await db.flush()
            db.add(
                ClassroomMembership(
                    user_id=instructor.id,
                    classroom_id=room.id,
                    role="instructor",
                )
            )
            log.info("Created seed classroom %r join_code=%s", DEMO_SECTION_NAME, code)
        else:
            log.debug("Seed classroom with code %s already exists", code)
            if not room.listed_in_directory:
                room.listed_in_directory = True
                await db.commit()
                log.info("Set listed_in_directory=True on seed classroom %s", code)

        r_ch = await db.execute(select(Challenge).where(Challenge.title == DEMO_CHALLENGE_TITLE))
        challenge = r_ch.scalar_one_or_none()
        if not challenge:
            log.warning(
                "seed_demo_classroom: challenge %r missing — ensure seed_challenges() ran first",
                DEMO_CHALLENGE_TITLE,
            )
            await db.commit()
            return

        r_link = await db.execute(
            select(ClassroomChallenge).where(
                ClassroomChallenge.classroom_id == room.id,
                ClassroomChallenge.challenge_id == challenge.id,
            )
        )
        if r_link.scalar_one_or_none():
            await db.commit()
            return

        db.add(
            ClassroomChallenge(
                classroom_id=room.id,
                challenge_id=challenge.id,
                sort_order=0,
            )
        )
        await db.commit()
        log.info(
            "Linked seed challenge %r to classroom %s (students who join %s will see it)",
            DEMO_CHALLENGE_TITLE,
            room.id,
            code,
        )


async def seed_pilot_classroom() -> None:
    """Ensure a 'HuskyAI Pilot' section exists with every active challenge linked.
    This is the section the Admin -> Invite email template points to by default."""
    try:
        code = _validate_seed_join_code(os.getenv("SEED_PILOT_CODE", DEFAULT_PILOT_JOIN_CODE))
    except ValueError as e:
        log.warning("seed_pilot_classroom skipped: %s", e)
        return

    async with AsyncSessionLocal() as db:
        # Reuse the seeded test instructor as the owner
        r_user = await db.execute(select(User).where(User.email == SEED_INSTRUCTOR_EMAIL))
        instructor = r_user.scalar_one_or_none()
        if not instructor:
            log.warning(
                "seed_pilot_classroom skipped: seed instructor %s missing - ensure seed_demo_classroom() ran first",
                SEED_INSTRUCTOR_EMAIL,
            )
            return

        r_room = await db.execute(select(Classroom).where(Classroom.join_code == code))
        room = r_room.scalar_one_or_none()
        if not room:
            room = Classroom(
                name=PILOT_SECTION_NAME,
                join_code=code,
                instructor_user_id=instructor.id,
                listed_in_directory=True,
                is_test_section=True,
            )
            db.add(room)
            await db.flush()
            db.add(
                ClassroomMembership(
                    user_id=instructor.id,
                    classroom_id=room.id,
                    role="instructor",
                )
            )
            log.info("Created pilot classroom %r join_code=%s", PILOT_SECTION_NAME, code)
        else:
            # Keep the pilot listed and flagged as a test section even if it was edited
            changed = False
            if not room.listed_in_directory:
                room.listed_in_directory = True
                changed = True
            if not getattr(room, "is_test_section", False):
                room.is_test_section = True
                changed = True
            if changed:
                await db.flush()

        # Link every active challenge that isn't already linked to this room
        r_existing = await db.execute(
            select(ClassroomChallenge.challenge_id).where(ClassroomChallenge.classroom_id == room.id)
        )
        already_linked = {row[0] for row in r_existing.all()}

        max_sort = await db.scalar(
            select(func.coalesce(func.max(ClassroomChallenge.sort_order), -1)).where(
                ClassroomChallenge.classroom_id == room.id
            )
        )
        next_order = int(max_sort or -1) + 1

        r_ch = await db.execute(
            select(Challenge)
            .where(Challenge.is_active == True)  # noqa: E712
            .order_by(Challenge.week.asc().nulls_last(), Challenge.title)
        )
        added = 0
        for ch in r_ch.scalars().all():
            if ch.id in already_linked:
                continue
            db.add(
                ClassroomChallenge(
                    classroom_id=room.id,
                    challenge_id=ch.id,
                    sort_order=next_order,
                )
            )
            next_order += 1
            added += 1

        await db.commit()
        log.info(
            "seed_pilot_classroom: classroom=%s code=%s linked_now=%d already_linked=%d",
            room.id,
            code,
            added,
            len(already_linked),
        )
