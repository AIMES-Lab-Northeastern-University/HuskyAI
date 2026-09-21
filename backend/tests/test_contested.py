"""Phase 4: contested input.

The build plan's acceptance criterion: a scripted pair surfaces at the intended
point, the student's choice is recorded, and the inspection flags come from
actual read events — so a student who adopts without expanding either option is
recorded as an uninspected adoption.

That last case is the reason the flags are derived rather than asked.
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


async def _team(n=2):
    """A team plus a platform admin who can script pairs."""
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          GroupChallenge, GroupMember, User)

    async with AsyncSessionLocal() as db:
        admin = User(email=f"adm_{uuid.uuid4().hex[:8]}@e.com", name="Admin",
                     password_hash="x", is_platform_admin=True)
        db.add(admin)
        users = []
        for i in range(n):
            u = User(email=f"ct_{uuid.uuid4().hex[:10]}@e.com", name=f"M{i}",
                     password_hash="x", consent_research=True)
            db.add(u); await db.flush()
            users.append(u.id)
        # A separate owner: making a team member the section instructor would
        # give that "student" legitimate authoring rights and hide the guard
        # this fixture exists to test.
        owner = User(email=f"own_{uuid.uuid4().hex[:8]}@e.com", name="Owner",
                     password_hash="x")
        db.add(owner); await db.flush()
        room = Classroom(name="Contested", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=owner.id)
        ch = Challenge(title="Contested Challenge", description="d", category="c",
                       difficulty="easy", total_sessions=1,
                       sessions_data=[{"title": "S", "goal": "g", "brief": "b",
                                       "seed_question": "q",
                                       "artifact_sections": [{"key": "s1"}, {"key": "s2"}]}])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id, mode="group",
                                  study_arm="collab_coach_artifact"))
        team = GroupChallenge(challenge_id=ch.id, classroom_id=room.id,
                              created_by=owner.id, status="active")
        db.add(team); await db.flush()
        for uid in users:
            db.add(GroupMember(group_id=team.id, user_id=uid))
        await db.commit()
        return team.id, users, admin.id


def _connect(client, gid, uid):
    return client.websocket_connect(f"/ws/coach?token={_token(uid)}&group_id={gid}&session_num=1")


def _until(ws, types, limit=30):
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if m.get("type") in types:
            return m
    return None


async def _gs_id(group_id):
    from sqlalchemy import select
    from database import AsyncSessionLocal, GroupSession
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(GroupSession.id).where(GroupSession.group_id == group_id))).scalar_one()


def _script(client, admin, gs, user_id, key="s1", better=None):
    body = {"subproblem_key": key, "option_a_text": "the teammate's answer",
            "option_b_text": "the coach's answer", "surfaced_to_user_id": user_id}
    if better:
        body["better_option"] = better
    r = client.post(f"/contested/sessions/{gs}/pairs", json=body,
                    headers={"Authorization": f"Bearer {_token(admin)}"})
    assert r.status_code == 200, r.text
    return r.json()["pair_id"]


# ── Authoring ────────────────────────────────────────────────────────────────

def test_a_student_cannot_script_their_own_contested_pair(app_ready):
    gid, users, _admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))

    r = client.post(f"/contested/sessions/{gs}/pairs",
                    json={"subproblem_key": "s1", "option_a_text": "a",
                          "option_b_text": "b", "surfaced_to_user_id": users[0]},
                    headers={"Authorization": f"Bearer {_token(users[0])}"})
    assert r.status_code == 403


def test_a_pair_cannot_target_someone_outside_the_team(app_ready):
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))

    r = client.post(f"/contested/sessions/{gs}/pairs",
                    json={"subproblem_key": "s1", "option_a_text": "a",
                          "option_b_text": "b", "surfaced_to_user_id": admin},
                    headers={"Authorization": f"Bearer {_token(admin)}"})
    assert r.status_code == 400


# ── The acceptance criterion ─────────────────────────────────────────────────

def test_adopting_without_opening_either_option_is_recorded_as_uninspected(app_ready):
    """The plan's named case. A student who takes a side without reading either
    answer must be visible in the data as exactly that."""
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0])

    hdr = {"Authorization": f"Bearer {_token(users[0])}"}
    mine = client.get(f"/contested/sessions/{gs}/mine", headers=hdr).json()
    assert len(mine) == 1 and mine[0]["pair_id"] == pair

    r = client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "a"}, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inspected_a"] is False
    assert body["inspected_b"] is False

    out = client.get(f"/contested/sessions/{gs}/outcomes",
                     headers={"Authorization": f"Bearer {_token(admin)}"}).json()
    assert out["uninspected_adoptions"] == 1
    assert out["pairs"][0]["uninspected_adoption"] is True


def test_expanding_the_section_first_records_an_inspected_adoption(app_ready):
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0], key="s1")
    hdr = {"Authorization": f"Bearer {_token(users[0])}"}
    client.get(f"/contested/sessions/{gs}/mine", headers=hdr)  # marks surfaced

    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_expand", "section_key": "s1"}))
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": None}))  # fence
        _until(ws, {"artifact_error"})

    r = client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "a"}, headers=hdr)
    assert r.json()["inspected_a"] is True


def test_a_read_from_before_the_pair_was_surfaced_does_not_count(app_ready):
    """Reading the section earlier is not inspecting this contested option."""
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)

    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_expand", "section_key": "s1"}))
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": None}))
        _until(ws, {"artifact_error"})

    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0], key="s1")
    hdr = {"Authorization": f"Bearer {_token(users[0])}"}
    client.get(f"/contested/sessions/{gs}/mine", headers=hdr)

    r = client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "a"}, headers=hdr)
    assert r.json()["inspected_a"] is False, \
        "an earlier read must not be credited to a later contested pair"


def test_the_option_labels_do_not_reveal_which_side_is_the_coach(app_ready):
    """Labelling the source would measure trust in labels, not in the work."""
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    _script(client, admin, gs, users[0])

    mine = client.get(f"/contested/sessions/{gs}/mine",
                      headers={"Authorization": f"Bearer {_token(users[0])}"}).json()
    blob = json.dumps(mine).lower()
    assert "coach" not in blob.replace("the coach's answer", "")
    assert set(mine[0]) >= {"option_a", "option_b"}


# ── Accuracy, when ground truth makes it knowable ────────────────────────────

def test_adoption_is_scored_as_accuracy_when_the_better_option_is_known(app_ready):
    """With ground truth, adoption becomes measurable as accuracy rather than
    mere preference — which is where the Phase 2 corpus pays off."""
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0], better="b")
    hdr = {"Authorization": f"Bearer {_token(users[0])}"}
    client.get(f"/contested/sessions/{gs}/mine", headers=hdr)

    r = client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "a"}, headers=hdr)
    assert r.json()["correct"] is False


def test_correctness_is_null_when_no_ground_truth_exists(app_ready):
    """Without a corpus, adoption is a preference and must not be scored."""
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0])
    hdr = {"Authorization": f"Bearer {_token(users[0])}"}
    client.get(f"/contested/sessions/{gs}/mine", headers=hdr)

    r = client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "a"}, headers=hdr)
    assert r.json()["correct"] is None


# ── Guards ───────────────────────────────────────────────────────────────────

def test_only_the_targeted_student_can_answer(app_ready):
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0])

    r = client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "a"},
                    headers={"Authorization": f"Bearer {_token(users[1])}"})
    assert r.status_code == 403


def test_answering_twice_is_refused(app_ready):
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0])
    hdr = {"Authorization": f"Bearer {_token(users[0])}"}

    assert client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "a"},
                       headers=hdr).status_code == 200
    assert client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "b"},
                       headers=hdr).status_code == 409


def test_the_choice_lands_in_the_event_log(app_ready):
    from sqlalchemy import select
    from database import AsyncSessionLocal, StudyEvent

    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))
    pair = _script(client, admin, gs, users[0])
    hdr = {"Authorization": f"Bearer {_token(users[0])}"}
    client.get(f"/contested/sessions/{gs}/mine", headers=hdr)
    client.post(f"/contested/pairs/{pair}/adopt", json={"adopted": "merged"}, headers=hdr)

    async def events():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(StudyEvent).where(
                StudyEvent.group_session_id == gs,
                StudyEvent.target == "contested").order_by(StudyEvent.seq))).scalars().all()

    evs = asyncio.run(events())
    assert [e.action for e in evs] == ["surfaced", "adopted"]
    assert evs[1].payload["adopted"] == "merged"
    assert evs[1].payload["uninspected"] is True
