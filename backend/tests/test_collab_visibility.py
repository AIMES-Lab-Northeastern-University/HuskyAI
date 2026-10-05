"""A collaborative session shows up where instructors and students look.

Every turn in the private-coach arm lands in a member's own coach_private
conversation and the session itself on GroupSession — neither of which the
instructor and student progress views read. A team that had taken turns and
finished its session showed as "No activity yet", "Active 0 / Started 0", and
"0/1 sessions" on the student's own list.
"""

import asyncio
import json
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


def _h(uid):
    return {"Authorization": f"Bearer {_token(uid)}"}


@pytest.fixture
def stub_model(monkeypatch):
    import main

    class _Chunk:
        text = "coached."
        usage_metadata = None

    async def stream(*_a, **_kw):
        async def gen():
            yield _Chunk()
        return gen()

    async def fake_eval(_h, corpus_vector_store_id=None):
        return {"scores": {"PEI": 60.0, "PSQ": 55.0}, "classification": "Intermediate"}

    monkeypatch.setattr(main.client.aio.models, "generate_content_stream", stream)
    monkeypatch.setattr(main, "evaluate_conversation", fake_eval)


async def _section_with_team(n_students=3):
    """A section running one collab-arm group challenge, with every student on
    one team. Returns (classroom_id, challenge_id, team_id, instructor, students)."""
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          ClassroomMembership, GroupChallenge, GroupMember, User)

    async with AsyncSessionLocal() as db:
        inst = User(email=f"vi_{uuid.uuid4().hex[:8]}@e.com", name="Inst", password_hash="x")
        db.add(inst); await db.flush()
        students = []
        for i in range(n_students):
            u = User(email=f"vs_{uuid.uuid4().hex[:8]}@e.com", name=f"Stu{i}",
                     password_hash="x", consent_research=True)
            db.add(u); await db.flush()
            students.append(u.id)
        room = Classroom(name="Vis", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=inst.id)
        ch = Challenge(title="Vis Challenge", description="d", category="c",
                       difficulty="easy", total_sessions=1, is_active=True,
                       sessions_data=[{"title": "S", "goal": "g", "brief": "b",
                                       "seed_question": "q"}])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id, mode="group",
                                  study_arm="collab_coach_artifact"))
        for uid in students:
            db.add(ClassroomMembership(classroom_id=room.id, user_id=uid, role="student"))
        team = GroupChallenge(challenge_id=ch.id, classroom_id=room.id,
                              created_by=inst.id, status="active")
        db.add(team); await db.flush()
        for uid in students:
            db.add(GroupMember(group_id=team.id, user_id=uid))
        await db.commit()
        return room.id, ch.id, team.id, inst.id, students


def _until(ws, types, limit=30):
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if m.get("type") in types:
            return m
    return None


def _coach_turn(client, team_id, uid):
    with client.websocket_connect(
        f"/ws/coach?token={_token(uid)}&group_id={team_id}&session_num=1"
    ) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "message", "content": "help me"}))
        _until(ws, {"done", "error"})
        _until(ws, {"eval", "eval_error"})


@pytest.fixture
def finished_team(app_ready, stub_model):
    """Two of three members take a coach turn; the team ends the session. The
    third member never opens it."""
    room, ch, team, inst, students = asyncio.run(_section_with_team(3))
    client = TestClient(app_ready)
    _coach_turn(client, team, students[0])
    _coach_turn(client, team, students[1])
    r = client.post(f"/groups/{team}/sessions/1/end", headers=_h(students[0]))
    assert r.status_code == 200, r.text
    return client, room, ch, team, inst, students


def test_team_analytics_counts_private_coach_turns(finished_team):
    client, room, ch, team, inst, students = finished_team
    r = client.get(f"/classrooms/{room}/challenges/{ch}/teams/{team}/analytics", headers=_h(inst))
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["total_turns"] == 2
    assert a["sessions_with_activity"] == 1
    turns = {m["user_id"]: m["turns"] for m in a["members"]}
    assert turns == {students[0]: 1, students[1]: 1, students[2]: 0}
    assert a["team_pei_avg"] == 60.0
    assert [t["sender_user_id"] for t in a["timeline"]] == students[:2]


def test_section_activity_counts_members_who_took_part(finished_team):
    client, room, ch, team, inst, students = finished_team
    r = client.get(f"/classrooms/{room}/analytics", headers=_h(inst))
    assert r.status_code == 200, r.text
    a = r.json()
    # The member who never opened the session is not credited with it.
    assert a["students_with_activity"] == 2
    assert a["sessions_started"] == 2
    assert a["sessions_completed"] == 2
    row = [c for c in a["by_challenge"] if c["challenge_id"] == ch][0]
    assert (row["sessions_started"], row["sessions_completed"]) == (2, 2)
    assert a["last_activity_at"] is not None


def test_student_drilldown_lists_the_team_session(finished_team):
    client, room, ch, team, inst, students = finished_team
    r = client.get(f"/classrooms/{room}/students/{students[0]}/activity", headers=_h(inst))
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["challenge_sessions"]["sessions_completed"] == 1
    assert [(s["challenge_id"], s["status"]) for s in a["session_rows"]] == [(ch, "completed")]

    absent = client.get(f"/classrooms/{room}/students/{students[2]}/activity",
                        headers=_h(inst)).json()
    assert absent["challenge_sessions"]["sessions_started"] == 0


def test_the_student_s_challenge_list_shows_the_finished_team_session(finished_team):
    client, room, ch, team, inst, students = finished_team
    listing = client.get("/challenges", headers=_h(students[1]))
    assert listing.status_code == 200, listing.text
    mine = [c for c in listing.json() if c["id"] == ch][0]
    assert mine["sessions_completed"] == 1

    detail = client.get(f"/challenges/{ch}", headers=_h(students[1])).json()
    assert detail["sessions"][0]["status"] == "completed"
    assert detail["sessions"][0]["end_reason"] == "manual"
