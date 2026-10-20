"""The student's group-challenge page describes the setup that will actually run.

The page tells students how big their team is and whether team chat is part of
the research record. Those are statements of fact to a consenting participant,
so GET /challenges/{id} must carry the assignment's real settings rather than
leaving the page to assume one configuration.
"""

import asyncio
import uuid

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


async def _setup(logging="metadata", team_min=2, team_max=3, assign=True, mode="group"):
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          ClassroomMembership, GroupChallenge, GroupMember, User)

    async with AsyncSessionLocal() as db:
        owner = User(email=f"ow_{uuid.uuid4().hex[:8]}@e.com", name="Owner", password_hash="x")
        a = User(email=f"gd_{uuid.uuid4().hex[:10]}@e.com", name="Ada Quill", password_hash="x")
        b = User(email=f"gd_{uuid.uuid4().hex[:10]}@e.com", name="Ben Rook", password_hash="x")
        db.add_all([owner, a, b]); await db.flush()
        room = Classroom(name="Detail Sec", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=owner.id)
        ch = Challenge(title="Detail Challenge", description="d", category="c",
                       difficulty="easy", total_sessions=1,
                       sessions_data=[{"title": "S", "goal": "g", "brief": "b",
                                       "seed_question": "q"}])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id, mode=mode,
                                  study_arm="collab_coach_artifact",
                                  team_min=team_min, team_max=team_max,
                                  team_chat_logging=logging))
        for u in (a, b):
            db.add(ClassroomMembership(user_id=u.id, classroom_id=room.id, role="student"))
        if assign:
            team = GroupChallenge(challenge_id=ch.id, classroom_id=room.id,
                                  created_by=owner.id, status="active")
            db.add(team); await db.flush()
            for u in (a, b):
                db.add(GroupMember(group_id=team.id, user_id=u.id))
        await db.commit()
        return ch.id, a.id


def _get(app, cid, uid):
    # No `with`: that runs the app's lifespan, which wires the shared room
    # manager to REDIS_URL and then closes it, breaking later tests that use it.
    r = TestClient(app).get(f"/challenges/{cid}", headers={"Authorization": f"Bearer {_token(uid)}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_assigned_student_sees_the_real_team_size_and_chat_logging(app_ready):
    cid, uid = asyncio.run(_setup(logging="content", team_min=2, team_max=3))
    body = _get(app_ready, cid, uid)
    assert body["group_mode"] is True
    assert body["group"]["member_names"] == ["Ada Quill", "Ben Rook"]
    assert body["group_settings"] == {
        "study_arm": "collab_coach_artifact",
        "team_min": 2,
        "team_max": 3,
        "team_chat_logging": "content",
    }


def test_unassigned_student_still_gets_the_settings_the_page_describes(app_ready):
    cid, uid = asyncio.run(_setup(logging="off", team_min=3, team_max=4, assign=False))
    body = _get(app_ready, cid, uid)
    assert body["group"] is None
    assert body["group_settings"]["team_chat_logging"] == "off"
    assert (body["group_settings"]["team_min"], body["group_settings"]["team_max"]) == (3, 4)


def test_solo_assignment_carries_no_group_settings(app_ready):
    cid, uid = asyncio.run(_setup(mode="solo", assign=False))
    body = _get(app_ready, cid, uid)
    assert body["group_mode"] is False
    assert body["group_settings"] is None
