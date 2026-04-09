"""
Platform admin overview (users flagged is_platform_admin).
Set PLATFORM_ADMIN_EMAILS=comma@emails in .env; synced on app startup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
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
