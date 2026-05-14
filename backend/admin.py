"""
Platform admin overview (users flagged is_platform_admin).
Set PLATFORM_ADMIN_EMAILS=comma@emails in .env; synced on app startup.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import decode_token
from database import (
    AsyncSessionLocal,
    Challenge,
    Classroom,
    ClassroomChallenge,
    ClassroomMembership,
    Conversation,
    EvalResult,
    Message,
    User,
    UserChallengeSession,
)

log = logging.getLogger("admin")

router = APIRouter(prefix="/admin", tags=["admin"])


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


async def require_platform_admin(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    u = await db.get(User, user_id)
    if not u or not bool(u.is_platform_admin):
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return user_id


@router.get("/overview")
async def admin_overview(
    _: str = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    n_users = await db.scalar(select(func.count()).select_from(User)) or 0
    n_classrooms = await db.scalar(select(func.count()).select_from(Classroom)) or 0
    n_memberships = await db.scalar(select(func.count()).select_from(ClassroomMembership)) or 0
    n_challenges = await db.scalar(select(func.count()).select_from(Challenge)) or 0
    n_links = await db.scalar(select(func.count()).select_from(ClassroomChallenge)) or 0

    n_conversations = await db.scalar(select(func.count()).select_from(Conversation)) or 0
    n_messages = await db.scalar(select(func.count()).select_from(Message)) or 0
    n_eval_rows = await db.scalar(select(func.count()).select_from(EvalResult)) or 0
    avg_eval_pei = await db.scalar(select(func.avg(EvalResult.pei)).where(EvalResult.pei.is_not(None)))

    week_ago = datetime.utcnow() - timedelta(days=7)
    users_joined_7d = await db.scalar(select(func.count()).select_from(User).where(User.created_at >= week_ago)) or 0

    student_memberships = await db.scalar(
        select(func.count()).select_from(ClassroomMembership).where(ClassroomMembership.role == "student")
    ) or 0

    ch_sess_started = await db.scalar(
        select(func.count()).select_from(UserChallengeSession).where(
            UserChallengeSession.status.in_(("in_progress", "completed"))
        )
    ) or 0
    ch_sess_completed = await db.scalar(
        select(func.count()).select_from(UserChallengeSession).where(UserChallengeSession.status == "completed")
    ) or 0
    avg_sess_pei = await db.scalar(
        select(func.avg(UserChallengeSession.best_pei)).where(UserChallengeSession.best_pei.is_not(None))
    )

    n_classrooms_active = await db.scalar(
        select(func.count()).select_from(Classroom).where(Classroom.is_active.is_(True))  # noqa: E712
    ) or 0
    n_classrooms_inactive = await db.scalar(
        select(func.count()).select_from(Classroom).where(Classroom.is_active.is_(False))  # noqa: E712
    ) or 0

    r = await db.execute(
        select(Classroom.id, Classroom.name, Classroom.join_code, func.count(ClassroomMembership.id))
        .outerjoin(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
        .where(Classroom.is_active.is_(True))  # noqa: E712
        .group_by(Classroom.id, Classroom.name, Classroom.join_code)
        .order_by(Classroom.name)
        .limit(200)
    )
    classrooms = [
        {"id": row[0], "name": row[1], "join_code": row[2], "member_count": int(row[3] or 0)}
        for row in r.all()
    ]

    analytics = {
        "conversations": int(n_conversations),
        "messages": int(n_messages),
        "eval_rows": int(n_eval_rows),
        "avg_eval_pei": round(float(avg_eval_pei), 2) if avg_eval_pei is not None else None,
        "student_memberships": int(student_memberships),
        "users_joined_last_7_days": int(users_joined_7d),
        "challenge_sessions_started": int(ch_sess_started),
        "challenge_sessions_completed": int(ch_sess_completed),
        "avg_challenge_session_pei": round(float(avg_sess_pei), 2) if avg_sess_pei is not None else None,
        "active_classrooms": int(n_classrooms_active),
        "inactive_classrooms": int(n_classrooms_inactive),
    }

    return {
        "counts": {
            "users": int(n_users),
            "classrooms": int(n_classrooms),
            "memberships": int(n_memberships),
            "challenges": int(n_challenges),
            "classroom_challenge_links": int(n_links),
        },
        "analytics": analytics,
        "classrooms": classrooms,
    }


# ---------------------------------------------------------------------------
# Users list + promote/demote
# ---------------------------------------------------------------------------

class AdminUpdateUserBody(BaseModel):
    is_platform_admin: Optional[bool] = None


@router.get("/users")
async def list_users(
    _: str = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(
            User.id, User.name, User.email,
            User.is_platform_admin, User.created_at,
            func.count(ClassroomMembership.id).label("section_count"),
        )
        .outerjoin(ClassroomMembership, ClassroomMembership.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .limit(1000)
    )
    return [
        {
            "id": row[0],
            "name": row[1],
            "email": row[2],
            "is_platform_admin": bool(row[3]),
            "created_at": row[4].isoformat() if row[4] else None,
            "section_count": int(row[5] or 0),
        }
        for row in r.all()
    ]


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: AdminUpdateUserBody,
    _: str = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if body.is_platform_admin is not None:
        u.is_platform_admin = body.is_platform_admin
    await db.commit()
    await db.refresh(u)
    return {"id": u.id, "name": u.name, "email": u.email, "is_platform_admin": bool(u.is_platform_admin)}


# ---------------------------------------------------------------------------
# Per-user activity drill-down
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/activity")
async def user_activity(
    user_id: str,
    _: str = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    # Workspace stats
    conv_count = await db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    ) or 0
    turn_total = await db.scalar(
        select(func.sum(Conversation.turn_count)).where(Conversation.user_id == user_id)
    ) or 0
    eval_count = await db.scalar(
        select(func.count()).select_from(EvalResult)
        .join(Conversation, Conversation.id == EvalResult.conversation_id)
        .where(Conversation.user_id == user_id)
    ) or 0
    avg_eval_pei = await db.scalar(
        select(func.avg(EvalResult.pei))
        .join(Conversation, Conversation.id == EvalResult.conversation_id)
        .where(Conversation.user_id == user_id, EvalResult.pei.isnot(None))
    )

    # Challenge sessions
    sessions_started = await db.scalar(
        select(func.count()).select_from(UserChallengeSession)
        .where(
            UserChallengeSession.user_id == user_id,
            UserChallengeSession.status.in_(["in_progress", "completed"]),
        )
    ) or 0
    sessions_completed = await db.scalar(
        select(func.count()).select_from(UserChallengeSession)
        .where(UserChallengeSession.user_id == user_id, UserChallengeSession.status == "completed")
    ) or 0
    avg_session_pei = await db.scalar(
        select(func.avg(UserChallengeSession.best_pei))
        .where(UserChallengeSession.user_id == user_id, UserChallengeSession.best_pei.isnot(None))
    )

    # Recent conversations (metadata only — no message text)
    r_conv = await db.execute(
        select(Conversation.id, Conversation.started_at, Conversation.turn_count)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.started_at.desc())
        .limit(20)
    )
    recent_conversations = [
        {
            "id": row[0],
            "started_at": row[1].isoformat() if row[1] else None,
            "turn_count": int(row[2] or 0),
        }
        for row in r_conv.all()
    ]

    # Sections they belong to
    r_sec = await db.execute(
        select(Classroom.id, Classroom.name, ClassroomMembership.role)
        .join(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
        .where(ClassroomMembership.user_id == user_id)
        .order_by(ClassroomMembership.role)
    )
    sections = [{"id": row[0], "name": row[1], "role": row[2]} for row in r_sec.all()]

    return {
        "user": {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "is_platform_admin": bool(u.is_platform_admin),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        },
        "workspace": {
            "conversations": int(conv_count),
            "turns_total": int(turn_total),
            "eval_count": int(eval_count),
            "avg_eval_pei": round(float(avg_eval_pei), 1) if avg_eval_pei is not None else None,
        },
        "challenge_sessions": {
            "sessions_started": int(sessions_started),
            "sessions_completed": int(sessions_completed),
            "avg_pei": round(float(avg_session_pei), 1) if avg_session_pei is not None else None,
        },
        "recent_conversations": recent_conversations,
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Per-classroom drill-down
# ---------------------------------------------------------------------------

@router.get("/classrooms/{classroom_id}")
async def classroom_detail(
    classroom_id: str,
    _: str = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    c = await db.get(Classroom, classroom_id)
    if not c:
        raise HTTPException(status_code=404, detail="Classroom not found")

    # Members with role
    r_mem = await db.execute(
        select(User.id, User.name, User.email, ClassroomMembership.role, ClassroomMembership.joined_at)
        .join(ClassroomMembership, ClassroomMembership.user_id == User.id)
        .where(ClassroomMembership.classroom_id == classroom_id)
        .order_by(ClassroomMembership.role, User.name)
    )
    members = [
        {
            "user_id": row[0],
            "name": row[1],
            "email": row[2],
            "role": row[3],
            "joined_at": row[4].isoformat() if row[4] else None,
        }
        for row in r_mem.all()
    ]

    # Assigned challenges
    r_ch = await db.execute(
        select(Challenge.id, Challenge.title, Challenge.is_active, Challenge.week, Challenge.difficulty)
        .join(ClassroomChallenge, ClassroomChallenge.challenge_id == Challenge.id)
        .where(ClassroomChallenge.classroom_id == classroom_id)
        .order_by(ClassroomChallenge.sort_order)
    )
    challenges = [
        {"id": row[0], "title": row[1], "is_active": bool(row[2]), "week": row[3], "difficulty": row[4]}
        for row in r_ch.all()
    ]

    # Session analytics across students in this section
    student_ids = [m["user_id"] for m in members if m["role"] == "student"]
    ch_ids = [ch["id"] for ch in challenges]
    sessions_started = sessions_completed = 0
    avg_pei = None
    if student_ids and ch_ids:
        sessions_started = await db.scalar(
            select(func.count()).select_from(UserChallengeSession)
            .where(
                UserChallengeSession.user_id.in_(student_ids),
                UserChallengeSession.challenge_id.in_(ch_ids),
            )
        ) or 0
        sessions_completed = await db.scalar(
            select(func.count()).select_from(UserChallengeSession)
            .where(
                UserChallengeSession.user_id.in_(student_ids),
                UserChallengeSession.challenge_id.in_(ch_ids),
                UserChallengeSession.status == "completed",
            )
        ) or 0
        avg_pei = await db.scalar(
            select(func.avg(UserChallengeSession.best_pei))
            .where(
                UserChallengeSession.user_id.in_(student_ids),
                UserChallengeSession.challenge_id.in_(ch_ids),
                UserChallengeSession.best_pei.isnot(None),
            )
        )

    return {
        "id": c.id,
        "name": c.name,
        "join_code": c.join_code,
        "is_active": bool(c.is_active),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "members": members,
        "challenges": challenges,
        "analytics": {
            "student_count": len(student_ids),
            "sessions_started": int(sessions_started),
            "sessions_completed": int(sessions_completed),
            "avg_pei": round(float(avg_pei), 1) if avg_pei is not None else None,
        },
    }


# ---------------------------------------------------------------------------
# PEI evaluator benchmark - admin tab
# ---------------------------------------------------------------------------

class RunBenchmarkBody(BaseModel):
    evaluator: str  # "v1" | "v2" | "v3"
    repeats: int


@router.post("/benchmark/run")
async def admin_benchmark_run(
    body: RunBenchmarkBody,
    _: str = Depends(require_platform_admin),
):
    """Stream benchmark progress as newline-delimited JSON events. Long-running
    (2-10 min). The final event of type=done carries the full report; intermediate
    events of type=progress arrive as each (case, repeat) finishes."""
    evaluator = (body.evaluator or "").strip().lower()
    if evaluator not in ("v1", "v2", "v3"):
        raise HTTPException(status_code=400, detail="evaluator must be one of: v1, v2, v3")
    try:
        repeats = int(body.repeats)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="repeats must be an integer")
    if repeats < 1 or repeats > 10:
        raise HTTPException(status_code=400, detail="repeats must be between 1 and 10")

    async def _stream():
        try:
            # Import lazily so admin module doesn't pay agent-SDK boot cost.
            from scripts.run_eval_benchmark import run_benchmark_stream
        except Exception as e:  # pragma: no cover
            log.error("Could not import benchmark runner: %s", e, exc_info=True)
            yield json.dumps({"type": "error", "error": f"Benchmark runner unavailable: {e}"}) + "\n"
            return
        try:
            async for event in run_benchmark_stream(evaluator, repeats):
                yield json.dumps(event) + "\n"
        except Exception as e:
            log.error("Benchmark run failed: %s", e, exc_info=True)
            yield json.dumps({"type": "error", "error": f"{type(e).__name__}: {e}"}) + "\n"

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={
            # Disable buffering on proxies that respect these headers (nginx, etc.)
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/benchmark/reports")
async def admin_benchmark_reports(
    _: str = Depends(require_platform_admin),
):
    """List prior benchmark reports newest-first."""
    try:
        from scripts.run_eval_benchmark import list_reports
    except Exception as e:
        log.error("Could not import benchmark runner: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Benchmark runner unavailable: {e}")
    return list_reports()


@router.get("/benchmark/reports/{report_id}")
async def admin_benchmark_report_detail(
    report_id: str,
    _: str = Depends(require_platform_admin),
):
    """Return the full report JSON for one prior run."""
    try:
        from scripts.run_eval_benchmark import load_report
    except Exception as e:
        log.error("Could not import benchmark runner: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Benchmark runner unavailable: {e}")
    rep = load_report(report_id)
    if rep is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return rep
