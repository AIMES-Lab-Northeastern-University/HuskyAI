"""Manual reviewer assignment (verification_policy = "instructor_assigned").

The setting used to say "I assign manually" and silently do round-robin. These
pin the fix: reviews follow the instructor's pairings exactly, an author with
no usable pairing is left unrouted and logged, and nothing ever falls back to
round-robin.
"""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from verification import choose_reviewer


# ── Routing rule ─────────────────────────────────────────────────────────────

def test_a_pairing_decides_the_reviewer_regardless_of_load():
    members = ["a", "b", "c"]
    # c already carries the most reviews; round-robin would never pick c.
    assert choose_reviewer(members, "a", {"b": 0, "c": 5}, "instructor_assigned", {"a": "c"}) == "c"


def test_an_unpaired_author_is_not_routed_to_anyone():
    assert choose_reviewer(["a", "b", "c"], "a", {}, "instructor_assigned", {"b": "c"}) is None
    assert choose_reviewer(["a", "b", "c"], "a", {}, "instructor_assigned", None) is None


def test_a_paired_reviewer_who_left_the_team_is_not_replaced():
    assert choose_reviewer(["a", "b"], "a", {}, "instructor_assigned", {"a": "gone"}) is None


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_ready():
    from database import init_db
    from main import app

    asyncio.run(init_db())
    return app


async def _team(policy="instructor_assigned", n=3):
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          GroupChallenge, GroupMember, User)

    async with AsyncSessionLocal() as db:
        owner = User(email=f"rp_own_{uuid.uuid4().hex[:8]}@e.com", name="Instructor", password_hash="x")
        db.add(owner); await db.flush()
        students = []
        for i in range(n):
            u = User(email=f"rp_{uuid.uuid4().hex[:10]}@e.com", name=f"S{i}",
                     password_hash="x", consent_research=True)
            db.add(u); await db.flush()
            students.append(u.id)
        room = Classroom(name="Pairings", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=owner.id)
        ch = Challenge(title="Pairings Challenge", description="d", category="c",
                       difficulty="easy", total_sessions=1,
                       sessions_data=[{"title": "S", "goal": "g", "brief": "b", "seed_question": "q",
                                       "artifact_sections": [{"key": f"s{i+1}"} for i in range(n)]}])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id, mode="group",
                                  study_arm="collab_coach_artifact", verification_policy=policy))
        team = GroupChallenge(challenge_id=ch.id, classroom_id=room.id,
                              created_by=owner.id, status="active")
        db.add(team); await db.flush()
        for uid in students:
            db.add(GroupMember(group_id=team.id, user_id=uid))
        await db.commit()
        return {"owner": owner.id, "students": students, "room": room.id,
                "challenge": ch.id, "team": team.id}


def _hdr(uid):
    from auth import create_token
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _pairings_url(t):
    return f"/classrooms/{t['room']}/challenges/{t['challenge']}/teams/{t['team']}/review-pairings"


def _put(client, t, uid, pairs):
    return client.put(_pairings_url(t), headers=_hdr(uid), json={"pairings": [
        {"author_user_id": a, "reviewer_user_id": r} for a, r in pairs]})


# ── Instructor route ─────────────────────────────────────────────────────────

def test_the_instructor_can_save_pairings_and_they_replace_the_old_map(app_ready):
    t = asyncio.run(_team())
    a, b, c = t["students"]
    client = TestClient(app_ready)

    assert _put(client, t, t["owner"], [(a, b), (b, c)]).status_code == 200
    r = _put(client, t, t["owner"], [(c, a)])
    assert r.status_code == 200, r.text
    saved = {(p["author_user_id"], p["reviewer_user_id"]) for p in r.json()["review_pairings"]}
    assert saved == {(c, a)}, "a save replaces the whole map, so it matches what the instructor saw"


@pytest.mark.parametrize("case", ["self", "outsider", "two_reviewers"])
def test_invalid_pairings_are_refused(app_ready, case):
    t = asyncio.run(_team())
    a, b, c = t["students"]
    pairs = {"self": [(a, a)],
             "outsider": [(a, str(uuid.uuid4()))],
             "two_reviewers": [(a, b), (a, c)]}[case]
    assert _put(TestClient(app_ready), t, t["owner"], pairs).status_code == 400


def test_a_student_cannot_set_pairings(app_ready):
    t = asyncio.run(_team())
    a, b, _ = t["students"]
    assert _put(TestClient(app_ready), t, a, [(b, a)]).status_code in (401, 403)


# ── End to end: a save routes (or does not) by the pairing ───────────────────

def _write(client, gid, uid, key):
    from auth import create_token
    with client.websocket_connect(
            f"/ws/coach?token={create_token(uid)}&group_id={gid}&session_num=1") as ws:
        for _ in range(30):
            if json.loads(ws.receive_text()).get("type") == "artifact":
                break
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": key,
                                 "content": f"work by {uid}", "expected_version": 0}))
        for _ in range(30):
            if json.loads(ws.receive_text()).get("type") in (
                    "artifact_write_ok", "artifact_error", "artifact_conflict"):
                break


async def _routing(team_id):
    from sqlalchemy import select
    from database import AsyncSessionLocal, GroupSession, StudyEvent, VerificationAssignment
    async with AsyncSessionLocal() as db:
        gs = (await db.execute(select(GroupSession.id).where(
            GroupSession.group_id == team_id))).scalar_one()
        rows = (await db.execute(select(VerificationAssignment).where(
            VerificationAssignment.group_session_id == gs))).scalars().all()
        unrouted = (await db.execute(select(StudyEvent).where(
            StudyEvent.group_session_id == gs, StudyEvent.target == "verification",
            StudyEvent.action == "unrouted"))).scalars().all()
        return ({r.author_user_id: r.reviewer_user_id for r in rows},
                [(e.actor_user_id, e.payload.get("reason")) for e in unrouted])


def test_saves_follow_the_pairing_and_an_unpaired_author_is_logged_not_round_robined(app_ready):
    t = asyncio.run(_team())
    a, b, c = t["students"]
    client = TestClient(app_ready)
    # c reviews a. Nobody is named for b.
    assert _put(client, t, t["owner"], [(a, c)]).status_code == 200

    _write(client, t["team"], a, "s1")
    _write(client, t["team"], b, "s2")

    routed, unrouted = asyncio.run(_routing(t["team"]))
    assert routed == {a: c}, "a goes to the paired reviewer, and b goes to nobody"
    assert unrouted == [(b, "no_pairing")], "the gap is recorded, not silent"
