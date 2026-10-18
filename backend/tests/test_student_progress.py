"""GET /challenges/me/progress: the student's score over time.

One point per ended session, oldest first. A team session plots the student's
own private-coach turns, not the team's. A session run with the feed off is
left out, because the study withholds those scores from the student.
"""

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_ready():
    from database import init_db
    from main import app

    asyncio.run(init_db())
    return app


def _token(uid):
    from auth import create_token
    return create_token(uid)


def _get(app, uid):
    # No `with`: that runs the app's lifespan (see test_group_challenge_detail).
    r = TestClient(app).get("/challenges/me/progress",
                            headers={"Authorization": f"Bearer {_token(uid)}"})
    assert r.status_code == 200, r.text
    return r.json()["sessions"]


T0 = datetime(2026, 9, 1, 12, 0)


async def _user(db, name="Stu"):
    from database import User
    u = User(email=f"prog_{uuid.uuid4().hex[:10]}@e.com", name=name, password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def _challenge(db, title, feed_flags=(True, True, True)):
    from database import Challenge
    ch = Challenge(title=title, description="d", category="c", difficulty="easy",
                   week=2, total_sessions=len(feed_flags),
                   sessions_data=[{"title": f"S{i + 1}", "goal": "g", "brief": "b",
                                   "feed_enabled": f}
                                  for i, f in enumerate(feed_flags)])
    db.add(ch)
    await db.flush()
    return ch


async def _scored_conversation(db, user_id, peis, *, kind="solo", group_session_id=None):
    """A conversation whose turns score `peis`; None is an unscored turn. Each
    dimension is the PEI plus a fixed offset, so averages are easy to check."""
    from database import Conversation, EvalResult
    conv = Conversation(user_id=user_id, kind=kind, group_session_id=group_session_id)
    db.add(conv)
    await db.flush()
    for i, p in enumerate(peis, start=1):
        db.add(EvalResult(
            conversation_id=conv.id, turn_number=i, pei=p,
            psq=None if p is None else p + 1, ccm=None if p is None else p + 2,
            tsi=None if p is None else p + 3, clm=None if p is None else p + 4,
            ras=None if p is None else p + 5,
            score_status="failed" if p is None else None,
        ))
    return conv


async def _solo_session(db, user_id, ch, n, peis, *, completed_at=None, status="completed"):
    from database import UserChallengeSession
    conv = await _scored_conversation(db, user_id, peis)
    db.add(UserChallengeSession(user_id=user_id, challenge_id=ch.id, session_number=n,
                                conversation_id=conv.id, status=status,
                                started_at=T0, completed_at=completed_at))


def test_solo_sessions_plot_oldest_first_with_dimension_averages(app_ready):
    async def setup():
        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            u = await _user(db)
            ch = await _challenge(db, "Solo Progress")
            # Inserted newest first, so the order has to come from completed_at.
            await _solo_session(db, u.id, ch, 2, [80, 90], completed_at=T0 + timedelta(days=7))
            await _solo_session(db, u.id, ch, 1, [40, None, 60], completed_at=T0)
            await db.commit()
            return u.id, ch.id
    uid, cid = asyncio.run(setup())

    sessions = _get(app_ready, uid)
    assert [s["session_number"] for s in sessions] == [1, 2]
    first, second = sessions
    # The unscored turn neither counts as a turn nor drags the average down.
    assert first["avg_pei"] == 50.0 and first["turns"] == 2
    assert first["dimensions"] == {"psq": 51.0, "ccm": 52.0, "tsi": 53.0, "clm": 54.0, "ras": 55.0}
    assert second["avg_pei"] == 85.0
    assert first["challenge_id"] == cid and first["title"] == "Solo Progress"
    assert first["week"] == 2 and first["mode"] == "solo"
    assert first["completed_at"].startswith("2026-09-01")


def test_unfinished_and_unscored_sessions_are_left_out(app_ready):
    async def setup():
        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            u = await _user(db)
            ch = await _challenge(db, "Partial")
            await _solo_session(db, u.id, ch, 1, [70], status="in_progress")
            await _solo_session(db, u.id, ch, 2, [None, None], completed_at=T0)
            await db.commit()
            return u.id
    assert _get(app_ready, asyncio.run(setup())) == []


def test_a_feed_off_session_is_not_shown(app_ready):
    async def setup():
        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            u = await _user(db)
            ch = await _challenge(db, "Feed Off", feed_flags=(True, True, False))
            await _solo_session(db, u.id, ch, 1, [50], completed_at=T0)
            await _solo_session(db, u.id, ch, 3, [95], completed_at=T0 + timedelta(days=14))
            await db.commit()
            return u.id
    sessions = _get(app_ready, asyncio.run(setup()))
    assert [s["session_number"] for s in sessions] == [1]


def test_a_team_session_plots_only_the_students_own_turns(app_ready):
    async def setup():
        from database import AsyncSessionLocal, GroupChallenge, GroupMember, GroupSession
        async with AsyncSessionLocal() as db:
            me = await _user(db, "Me")
            mate = await _user(db, "Mate")
            ch = await _challenge(db, "Team Progress", feed_flags=(True,))
            team = GroupChallenge(challenge_id=ch.id, created_by=me.id, status="active")
            db.add(team)
            await db.flush()
            db.add_all([GroupMember(group_id=team.id, user_id=me.id),
                        GroupMember(group_id=team.id, user_id=mate.id)])
            gs = GroupSession(group_id=team.id, challenge_id=ch.id, session_number=1,
                              status="completed", started_at=T0, completed_at=T0)
            db.add(gs)
            await db.flush()
            await _scored_conversation(db, me.id, [30, 50], kind="coach_private",
                                       group_session_id=gs.id)
            await _scored_conversation(db, mate.id, [90, 90, 90], kind="coach_private",
                                       group_session_id=gs.id)
            await db.commit()
            return me.id, mate.id
    me, mate = asyncio.run(setup())

    (mine,) = _get(app_ready, me)
    assert mine["mode"] == "team" and mine["avg_pei"] == 40.0 and mine["turns"] == 2
    (theirs,) = _get(app_ready, mate)
    assert theirs["avg_pei"] == 90.0


def test_a_student_with_no_sessions_gets_an_empty_list(app_ready):
    async def setup():
        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            u = await _user(db)
            await db.commit()
            return u.id
    assert _get(app_ready, asyncio.run(setup())) == []


def test_progress_requires_sign_in(app_ready):
    assert TestClient(app_ready).get("/challenges/me/progress").status_code == 401
