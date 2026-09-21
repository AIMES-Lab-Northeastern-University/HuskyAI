"""Phase 5: routed verification.

The acceptance criterion from the build plan is that a four-person team
produces a full round-robin and that the outcome classes are each reproducible
in a seeded test. The class that matters most is `skipped_unread` — a verdict
submitted with no read behind it — which is detectable only because reads are
first-class events.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from verification import choose_reviewer, classify

T0 = datetime(2026, 9, 20, 10, 0, 0)


def _read(secs):
    return {"server_ts": T0 + timedelta(seconds=secs)}


# ── The classifier: pure, so every outcome is reproducible ───────────────────

def test_a_verdict_with_a_read_behind_it_happened():
    out = classify(
        {"status": "pending", "assigned_at": T0},
        {"submitted_at": T0 + timedelta(seconds=60)},
        [_read(30)],
    )
    assert out == "happened"


def test_a_verdict_with_no_read_is_skipped_not_completed():
    """The interesting case. A reviewer who never opened the section has told
    you they were willing to claim a check, not that they performed one."""
    out = classify(
        {"status": "pending", "assigned_at": T0},
        {"submitted_at": T0 + timedelta(seconds=60)},
        [],
    )
    assert out == "skipped_unread"


def test_a_read_from_before_the_assignment_does_not_count():
    """Reading it yesterday and rubber-stamping it today is not checking this
    revision."""
    out = classify(
        {"status": "pending", "assigned_at": T0},
        {"submitted_at": T0 + timedelta(seconds=60)},
        [_read(-3600)],
    )
    assert out == "skipped_unread"


def test_a_read_after_the_verdict_does_not_count():
    out = classify(
        {"status": "pending", "assigned_at": T0},
        {"submitted_at": T0 + timedelta(seconds=30)},
        [_read(90)],
    )
    assert out == "skipped_unread"


def test_no_response_is_distinct_from_an_unread_response():
    """Not doing it and claiming to have done it are different behaviours."""
    assert classify({"status": "pending", "assigned_at": T0}, None, []) == "skipped_no_response"
    assert classify({"status": "expired", "assigned_at": T0}, None, []) == "expired"


def test_two_reviewers_on_one_target_is_duplicated():
    """Wasted effort the team did not notice — a different failure from nobody
    checking at all."""
    out = classify(
        {"status": "pending", "assigned_at": T0},
        {"submitted_at": T0 + timedelta(seconds=60)},
        [_read(30)],
        responses_to_same_target=2,
    )
    assert out == "duplicated"


# ── Routing ──────────────────────────────────────────────────────────────────

def test_round_robin_never_assigns_an_author_their_own_work():
    members = ["a", "b", "c", "d"]
    for author in members:
        assert choose_reviewer(members, author, {}, "round_robin") != author


def test_round_robin_balances_by_load_not_by_a_rotating_index():
    """An index rotates out of step the moment someone leaves or a write is
    rejected, and the resulting imbalance is invisible."""
    members = ["a", "b", "c", "d"]
    counts = {"b": 3, "c": 1, "d": 0}
    assert choose_reviewer(members, "a", counts, "round_robin") == "d"


def test_a_solo_member_has_nobody_to_review_their_work():
    assert choose_reviewer(["a"], "a", {}, "round_robin") is None


# ── End to end over the real socket ──────────────────────────────────────────

@pytest.fixture(scope="module")
def app_ready():
    from database import init_db
    from main import app

    asyncio.run(init_db())
    return app


async def _team_with_policy(n=4, policy="round_robin"):
    """A team whose section sets a verification policy."""
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          GroupChallenge, GroupMember, User)

    async with AsyncSessionLocal() as db:
        users = []
        for i in range(n):
            u = User(email=f"v_{uuid.uuid4().hex[:10]}@e.com", name=f"M{i}",
                     password_hash="x", consent_research=True)
            db.add(u); await db.flush()
            users.append(u.id)
        room = Classroom(name="Verif", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=users[0])
        ch = Challenge(title="Verif Challenge", description="d", category="c",
                       difficulty="easy", total_sessions=1,
                       sessions_data=[{"title": "S", "goal": "g", "brief": "b",
                                       "seed_question": "q",
                                       "artifact_sections": [{"key": f"s{i+1}"} for i in range(n)]}])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id, mode="group",
                                  study_arm="collab_coach_artifact",
                                  verification_policy=policy))
        team = GroupChallenge(challenge_id=ch.id, classroom_id=room.id,
                              created_by=users[0], status="active")
        db.add(team); await db.flush()
        for uid in users:
            db.add(GroupMember(group_id=team.id, user_id=uid))
        await db.commit()
        return team.id, users


def _token(uid):
    from auth import create_token
    return create_token(uid)


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


def test_a_four_person_team_produces_a_balanced_round_robin(app_ready):
    """The plan's acceptance criterion."""
    from sqlalchemy import select
    from database import AsyncSessionLocal, VerificationAssignment

    gid, users = asyncio.run(_team_with_policy(4))
    client = TestClient(app_ready)

    for i, uid in enumerate(users):
        with _connect(client, gid, uid) as ws:
            _until(ws, {"artifact"})
            ws.send_text(json.dumps({"type": "artifact_write", "section_key": f"s{i+1}",
                                     "content": f"work from member {i}", "expected_version": 0}))
            _until(ws, {"artifact_write_ok", "artifact_error", "artifact_conflict"})

    gs = asyncio.run(_gs_id(gid))

    async def assignments():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(VerificationAssignment).where(
                VerificationAssignment.group_session_id == gs))).scalars().all()

    rows = asyncio.run(assignments())
    assert len(rows) == 4, "every contribution should be routed"
    assert all(r.author_user_id != r.reviewer_user_id for r in rows), "nobody reviews themselves"
    # Load-balanced: with four writes and four members, no one carries three.
    load = {}
    for r in rows:
        load[r.reviewer_user_id] = load.get(r.reviewer_user_id, 0) + 1
    assert max(load.values()) <= 2, f"unbalanced routing: {load}"


def test_the_three_outcome_classes_are_reproducible_end_to_end(app_ready):
    """happened / skipped_unread / skipped_no_response, over the real socket
    and the real read log."""
    from database import AsyncSessionLocal
    from verification import outcomes_for_session

    gid, users = asyncio.run(_team_with_policy(3))
    client = TestClient(app_ready)
    author, reviewer_reads, reviewer_lazy = users[0], users[1], users[2]

    # Author writes three sections; each is routed to someone else.
    with _connect(client, gid, author) as ws:
        _until(ws, {"artifact"})
        for k in ("s1", "s2", "s3"):
            ws.send_text(json.dumps({"type": "artifact_write", "section_key": k,
                                     "content": f"content {k}", "expected_version": 0}))
            _until(ws, {"artifact_write_ok", "artifact_error", "artifact_conflict"})

    gs = asyncio.run(_gs_id(gid))

    async def inbox_for(uid):
        async with AsyncSessionLocal() as db:
            return await outcomes_for_session(db, gs)

    rows = asyncio.run(inbox_for(None))
    assert len(rows) == 3

    # One reviewer reads then answers; another answers without reading; the
    # third assignment is left alone.
    by_reviewer = {}
    for r in rows:
        by_reviewer.setdefault(r["reviewer_user_id"], []).append(r)

    did_read = rows[0]
    no_read = rows[1]

    with _connect(client, gid, did_read["reviewer_user_id"]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_expand",
                                 "section_key": did_read["section_key"]}))
        # fence: a malformed write replies, proving the read landed first
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": None}))
        _until(ws, {"artifact_error"})

    hdr_read = {"Authorization": f"Bearer {_token(did_read['reviewer_user_id'])}"}
    r1 = client.post(f"/verification/{did_read['assignment_id']}/respond",
                     json={"verdict": "correct"}, headers=hdr_read)
    assert r1.status_code == 200, r1.text

    hdr_lazy = {"Authorization": f"Bearer {_token(no_read['reviewer_user_id'])}"}
    r2 = client.post(f"/verification/{no_read['assignment_id']}/respond",
                     json={"verdict": "correct"}, headers=hdr_lazy)
    assert r2.status_code == 200, r2.text

    final = asyncio.run(inbox_for(None))
    outcomes = {r["assignment_id"]: r["outcome"] for r in final}

    assert outcomes[did_read["assignment_id"]] == "happened"
    assert outcomes[no_read["assignment_id"]] == "skipped_unread", \
        "a verdict with no read behind it must not count as a check"
    remaining = [a for a in outcomes if a not in (did_read["assignment_id"],
                                                  no_read["assignment_id"])]
    assert outcomes[remaining[0]] == "skipped_no_response"


def test_only_the_assigned_reviewer_can_respond(app_ready):
    gid, users = asyncio.run(_team_with_policy(3))
    client = TestClient(app_ready)

    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "s1",
                                 "content": "x", "expected_version": 0}))
        _until(ws, {"artifact_write_ok"})

    gs = asyncio.run(_gs_id(gid))
    from database import AsyncSessionLocal
    from verification import outcomes_for_session

    async def rows():
        async with AsyncSessionLocal() as db:
            return await outcomes_for_session(db, gs)

    a = asyncio.run(rows())[0]
    impostor = next(u for u in users if u != a["reviewer_user_id"])
    r = client.post(f"/verification/{a['assignment_id']}/respond",
                    json={"verdict": "correct"},
                    headers={"Authorization": f"Bearer {_token(impostor)}"})
    assert r.status_code == 403


def test_verification_is_inert_when_the_policy_is_none(app_ready):
    """Regression: an assignment that does not opt in must be untouched."""
    from sqlalchemy import select
    from database import AsyncSessionLocal, VerificationAssignment

    gid, users = asyncio.run(_team_with_policy(3, policy="none"))
    client = TestClient(app_ready)

    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "s1",
                                 "content": "x", "expected_version": 0}))
        _until(ws, {"artifact_write_ok"})

    gs = asyncio.run(_gs_id(gid))

    async def count():
        async with AsyncSessionLocal() as db:
            return len((await db.execute(select(VerificationAssignment).where(
                VerificationAssignment.group_session_id == gs))).scalars().all())

    assert asyncio.run(count()) == 0
