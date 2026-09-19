"""Phase 3: the solo control arm's study behaviour.

Two properties matter and are easy to get wrong:

- Turning the feed OFF must not turn the measurement off. The server keeps
  scoring; only the display changes.
- The consequential revision is enforced server-side. "The student must submit
  one revision that counts" is a property of the study design, so a client that
  skips the step must not be able to close the session.
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


class _FakeChunk:
    """The solo handler reads usage_metadata off the last chunk for token
    logging; the coach handler does not. Carry it so the stub matches the real
    surface rather than only the part one caller happens to touch."""

    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


@pytest.fixture
def stub_model(monkeypatch):
    import main

    async def stream(*_a, **_kw):
        async def gen():
            yield _FakeChunk("coached.")
        return gen()

    async def fake_eval(_h, corpus_vector_store_id=None):
        return {"scores": {"PEI": 58.0}, "classification": "Intermediate"}

    monkeypatch.setattr(main.client.aio.models, "generate_content_stream", stream)
    monkeypatch.setattr(main, "evaluate_conversation", fake_eval)


async def _solo_setup(feed_enabled=True, revision_policy=None):
    """A student in a section with one assigned challenge. Returns (user_id, challenge_id)."""
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          ClassroomMembership, User)

    session = {"title": "S1", "goal": "g", "brief": "b", "seed_question": "q",
               "system_prompt_extra": "x"}
    if not feed_enabled:
        session["feed_enabled"] = False

    async with AsyncSessionLocal() as db:
        inst = User(email=f"ci_{uuid.uuid4().hex[:8]}@e.com", name="Inst", password_hash="x")
        stu = User(email=f"cs_{uuid.uuid4().hex[:8]}@e.com", name="Stu", password_hash="x",
                   consent_research=True)
        db.add_all([inst, stu]); await db.flush()
        room = Classroom(name="Ctl", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=inst.id)
        ch = Challenge(title="Ctl Challenge", description="d", category="c",
                       difficulty="easy", total_sessions=1, sessions_data=[session])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id,
                                  study_arm="control_solo_feed",
                                  revision_policy=revision_policy))
        db.add(ClassroomMembership(user_id=stu.id, classroom_id=room.id, role="student"))
        await db.commit()
        return stu.id, ch.id


def _token(uid):
    from auth import create_token
    return create_token(uid)


def _start(client, uid, cid):
    r = client.post(f"/challenges/{cid}/sessions/1/start",
                    headers={"Authorization": f"Bearer {_token(uid)}"})
    assert r.status_code in (200, 201), r.text
    return r


def _ws(client, uid, cid):
    return client.websocket_connect(f"/ws?token={_token(uid)}&challenge_id={cid}&session_num=1")


def _until(ws, types, limit=30):
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if m.get("type") in types:
            return m
    return None


async def _events(ucs_id, action=None):
    from sqlalchemy import select
    from database import AsyncSessionLocal, StudyEvent
    async with AsyncSessionLocal() as db:
        q = select(StudyEvent).where(StudyEvent.user_challenge_session_id == ucs_id)
        if action:
            q = q.where(StudyEvent.action == action)
        return list((await db.execute(q.order_by(StudyEvent.seq))).scalars().all())


async def _ucs(uid, cid):
    from sqlalchemy import select
    from database import AsyncSessionLocal, UserChallengeSession
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(UserChallengeSession).where(
            UserChallengeSession.user_id == uid,
            UserChallengeSession.challenge_id == cid))).scalar_one()


# ── Feed on (today's behaviour) ──────────────────────────────────────────────

def test_feed_enabled_session_shows_the_score_and_logs_it(app_ready, stub_model):
    uid, cid = asyncio.run(_solo_setup(feed_enabled=True))
    client = TestClient(app_ready)
    _start(client, uid, cid)

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "hello"}))
        ev = _until(ws, {"eval", "eval_suppressed", "eval_error"})

    assert ev["type"] == "eval"
    assert ev["data"]["scores"]["PEI"] == 58.0

    ucs = asyncio.run(_ucs(uid, cid))
    shown = asyncio.run(_events(ucs.id, "feed.shown"))
    assert len(shown) == 1
    assert shown[0].payload["pei"] == 58.0
    assert shown[0].target == "feed"


# ── Feed off ─────────────────────────────────────────────────────────────────

def test_feed_disabled_still_scores_the_turn_server_side(app_ready, stub_model):
    """Removing the intervention must not remove the measurement."""
    from sqlalchemy import select
    from database import AsyncSessionLocal, EvalResult

    uid, cid = asyncio.run(_solo_setup(feed_enabled=False))
    client = TestClient(app_ready)
    _start(client, uid, cid)

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "hello"}))
        ev = _until(ws, {"eval", "eval_suppressed", "eval_error"})

    assert ev["type"] == "eval_suppressed", "the score must not be sent to the client"

    ucs = asyncio.run(_ucs(uid, cid))

    async def scored():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(EvalResult).where(
                EvalResult.conversation_id == ucs.conversation_id))).scalars().all()

    rows = asyncio.run(scored())
    assert len(rows) == 1 and rows[0].pei == 58.0, "the turn must still be scored and stored"


def test_a_suppressed_feed_is_recorded_rather_than_inferred_from_absence(app_ready, stub_model):
    """Absence of a feed.shown is indistinguishable from a logging bug, so the
    suppression is written explicitly on every turn."""
    uid, cid = asyncio.run(_solo_setup(feed_enabled=False))
    client = TestClient(app_ready)
    _start(client, uid, cid)

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "one"}))
        _until(ws, {"eval", "eval_suppressed", "eval_error"})

    ucs = asyncio.run(_ucs(uid, cid))
    assert asyncio.run(_events(ucs.id, "feed.shown")) == []
    suppressed = asyncio.run(_events(ucs.id, "feed.suppressed"))
    assert len(suppressed) == 1
    assert suppressed[0].payload["pei"] == 58.0, "the unseen score is still in the log"


# ── Consequential revision ───────────────────────────────────────────────────

def test_completion_is_refused_until_the_revision_is_submitted(app_ready, stub_model):
    """Server-side, not UI-only."""
    uid, cid = asyncio.run(_solo_setup(revision_policy={"require_revision_on_turn": 1}))
    client = TestClient(app_ready)
    _start(client, uid, cid)
    hdr = {"Authorization": f"Bearer {_token(uid)}"}

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "first attempt"}))
        _until(ws, {"eval", "eval_suppressed", "eval_error"})
        prompt = _until(ws, {"revision_required"}, limit=5)
    assert prompt is not None, "student must be told a revision is now required"

    blocked = client.post(f"/challenges/{cid}/sessions/1/complete", headers=hdr)
    assert blocked.status_code == 409
    assert "revision" in blocked.json()["detail"].lower()

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "revised", "is_revision": True}))
        _until(ws, {"eval", "eval_suppressed", "eval_error"})

    ok = client.post(f"/challenges/{cid}/sessions/1/complete", headers=hdr)
    assert ok.status_code == 200, ok.text


def test_both_scores_are_kept_so_the_delta_is_measurable(app_ready, stub_model):
    """The pre-revision score is retained as its own row: the point is the
    change between seeing the feed and acting on it."""
    from sqlalchemy import select
    from database import AsyncSessionLocal, EvalResult

    uid, cid = asyncio.run(_solo_setup(revision_policy={"require_revision_on_turn": 1}))
    client = TestClient(app_ready)
    _start(client, uid, cid)

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "first"}))
        _until(ws, {"eval", "eval_suppressed", "eval_error"})
        ws.send_text(json.dumps({"type": "message", "content": "revised", "is_revision": True}))
        _until(ws, {"eval", "eval_suppressed", "eval_error"})

    ucs = asyncio.run(_ucs(uid, cid))

    async def rows():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(EvalResult).where(
                EvalResult.conversation_id == ucs.conversation_id
            ).order_by(EvalResult.turn_number))).scalars().all()

    evs = asyncio.run(rows())
    assert len(evs) == 2
    assert evs[0].is_graded_revision is False
    assert evs[1].is_graded_revision is True

    ucs2 = asyncio.run(_ucs(uid, cid))
    submitted = asyncio.run(_events(ucs2.id, "revision.submitted"))
    assert len(submitted) == 1


def test_an_assignment_without_a_revision_policy_completes_as_before(app_ready, stub_model):
    """Regression: the gate must be invisible to every existing assignment."""
    uid, cid = asyncio.run(_solo_setup(revision_policy=None))
    client = TestClient(app_ready)
    _start(client, uid, cid)
    hdr = {"Authorization": f"Bearer {_token(uid)}"}

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "hello"}))
        _until(ws, {"eval", "eval_suppressed", "eval_error"})

    r = client.post(f"/challenges/{cid}/sessions/1/complete", headers=hdr)
    assert r.status_code == 200, r.text


def test_is_revision_is_ignored_when_no_policy_requires_one(app_ready, stub_model):
    """A client cannot mark its own turn as the graded artifact of record."""
    from sqlalchemy import select
    from database import AsyncSessionLocal, EvalResult

    uid, cid = asyncio.run(_solo_setup(revision_policy=None))
    client = TestClient(app_ready)
    _start(client, uid, cid)

    with _ws(client, uid, cid) as ws:
        ws.send_text(json.dumps({"type": "message", "content": "sneaky", "is_revision": True}))
        _until(ws, {"eval", "eval_suppressed", "eval_error"})

    ucs = asyncio.run(_ucs(uid, cid))

    async def rows():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(EvalResult).where(
                EvalResult.conversation_id == ucs.conversation_id))).scalars().all()

    assert all(r.is_graded_revision is False for r in asyncio.run(rows()))
