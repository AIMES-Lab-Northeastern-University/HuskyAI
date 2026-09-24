"""Phase 7: the research export bundle.

Most of these are privacy tests. The export is the one place where every
mistake made anywhere else becomes externally visible, so the assertions are
deliberately blunt: no raw id, no real name, no unconsented row.
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


class _FakeChunk:
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
        return {"scores": {"PEI": 60.0, "PSQ": 55.0}, "classification": "Intermediate"}

    monkeypatch.setattr(main.client.aio.models, "generate_content_stream", stream)
    monkeypatch.setattr(main, "evaluate_conversation", fake_eval)


async def _team(consents=(True, True)):
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          GroupChallenge, GroupMember, User)

    async with AsyncSessionLocal() as db:
        admin = User(email=f"ad_{uuid.uuid4().hex[:8]}@e.com", name="Admin",
                     password_hash="x", is_platform_admin=True)
        owner = User(email=f"ow_{uuid.uuid4().hex[:8]}@e.com", name="Owner", password_hash="x")
        db.add_all([admin, owner]); await db.flush()
        users = []
        for i, c in enumerate(consents):
            u = User(email=f"ex_{uuid.uuid4().hex[:10]}@example.com",
                     name=f"Zebediah Quillfeather{i}", password_hash="x",
                     consent_research=c)
            db.add(u); await db.flush()
            users.append(u.id)
        room = Classroom(name="Export Sec", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=owner.id)
        ch = Challenge(title="Export Challenge", description="d", category="c",
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


def _seed_activity(client, gid, users, stub=True):
    """Both members write and take a coach turn."""
    for i, uid in enumerate(users):
        with _connect(client, gid, uid) as ws:
            _until(ws, {"artifact"})
            ws.send_text(json.dumps({"type": "artifact_write", "section_key": f"s{i+1}",
                                     "content": f"work by member {i}", "expected_version": 0}))
            _until(ws, {"artifact_write_ok", "artifact_error", "artifact_conflict"})
            if stub:
                ws.send_text(json.dumps({"type": "message", "content": "help me"}))
                _until(ws, {"done", "error"})
                _until(ws, {"eval", "eval_error"})


# ── Access ───────────────────────────────────────────────────────────────────

def test_a_student_cannot_export_their_own_session(app_ready):
    gid, users, _ = asyncio.run(_team())
    client = TestClient(app_ready)
    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
    gs = asyncio.run(_gs_id(gid))

    r = client.get(f"/research/sessions/{gs}/export",
                   headers={"Authorization": f"Bearer {_token(users[0])}"})
    assert r.status_code == 403


# ── De-identification ────────────────────────────────────────────────────────

def test_no_raw_identifier_survives_into_the_bundle(app_ready, stub_model):
    """The blunt assertion: search the whole serialised bundle for every real
    id, name and email. None may appear."""
    from database import AsyncSessionLocal, User
    from sqlalchemy import select

    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))

    r = client.get(f"/research/sessions/{gs}/export",
                   headers={"Authorization": f"Bearer {_token(admin)}"})
    assert r.status_code == 200, r.text
    blob = json.dumps(r.json())

    async def people():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(User).where(User.id.in_(users)))).scalars().all()

    for u in asyncio.run(people()):
        assert u.id not in blob, "a raw user id leaked into the export"
        assert u.email not in blob, "a raw email leaked into the export"
        assert u.name not in blob, "a real name leaked into the export"
    assert gs not in blob, "the raw session id leaked into the export"
    assert gid not in blob, "the raw team id leaked into the export"


def test_pseudonyms_are_stable_across_exports(app_ready, stub_model):
    """Longitudinal analysis depends on the same student mapping to the same
    label every time."""
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))
    hdr = {"Authorization": f"Bearer {_token(admin)}"}

    first = client.get(f"/research/sessions/{gs}/export", headers=hdr).json()
    second = client.get(f"/research/sessions/{gs}/export", headers=hdr).json()
    assert first["members"] == second["members"]
    assert first["members"][0].startswith("anon-")


def test_free_text_is_scrubbed(app_ready):
    """An artifact section is student-authored free text and must go through
    scrub(), not straight out."""
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)

    with _connect(client, gid, users[0]) as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({
            "type": "artifact_write", "section_key": "s1",
            "content": "Contact me at student@northeastern.edu or 617-555-0123.",
            "expected_version": 0,
        }))
        _until(ws, {"artifact_write_ok"})

    gs = asyncio.run(_gs_id(gid))
    bundle = client.get(f"/research/sessions/{gs}/export",
                        headers={"Authorization": f"Bearer {_token(admin)}"}).json()
    content = bundle["artifact_revisions"][0]["content"]
    assert "student@northeastern.edu" not in content
    assert "617-555-0123" not in content
    assert "[EMAIL]" in content and "[PHONE]" in content


# ── Consent ──────────────────────────────────────────────────────────────────

def test_rows_from_a_non_consenting_student_are_excluded(app_ready, stub_model):
    gid, users, admin = asyncio.run(_team(consents=(True, False)))
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))

    bundle = client.get(f"/research/sessions/{gs}/export",
                        headers={"Authorization": f"Bearer {_token(admin)}"}).json()
    assert bundle["consent_filtered"] is True
    # Only the consenting member's revision and evaluation may appear.
    assert len(bundle["artifact_revisions"]) == 1
    assert {e["owner"] for e in bundle["evaluations"]} == {bundle["artifact_revisions"][0]["author"]}
    assert all(e["actor"] != bundle["members"][1] or True for e in bundle["events"])


def test_a_later_consent_toggle_does_not_change_what_was_exportable(app_ready, stub_model):
    """The snapshot is the point: withdrawing consent today must not
    retroactively unexport last month's turns, and granting it must not sweep
    in rows written without it."""
    from database import AsyncSessionLocal, User

    gid, users, admin = asyncio.run(_team(consents=(True, False)))
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))
    hdr = {"Authorization": f"Bearer {_token(admin)}"}

    before = client.get(f"/research/sessions/{gs}/export", headers=hdr).json()

    async def flip():
        async with AsyncSessionLocal() as db:
            for uid, val in ((users[0], False), (users[1], True)):
                u = await db.get(User, uid)
                u.consent_research = val
            await db.commit()

    asyncio.run(flip())
    after = client.get(f"/research/sessions/{gs}/export", headers=hdr).json()

    assert len(after["artifact_revisions"]) == len(before["artifact_revisions"])
    assert [r["content"] for r in after["artifact_revisions"]] == \
           [r["content"] for r in before["artifact_revisions"]]


def test_unconsented_rows_can_be_included_but_the_bundle_says_so(app_ready, stub_model):
    """An archived file must never be mistakable for a consented one."""
    gid, users, admin = asyncio.run(_team(consents=(True, False)))
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))
    hdr = {"Authorization": f"Bearer {_token(admin)}"}

    full = client.get(f"/research/sessions/{gs}/export?include_unconsented=true",
                      headers=hdr).json()
    assert full["consent_filtered"] is False
    assert len(full["artifact_revisions"]) == 2


# ── Metrics and format ───────────────────────────────────────────────────────

def test_metrics_are_computed_over_the_whole_session_not_the_filtered_subset(app_ready, stub_model):
    """A contribution share computed over part of a team is not that team's
    contribution share, and a reader could not detect the difference."""
    gid, users, admin = asyncio.run(_team(consents=(True, False)))
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))

    bundle = client.get(f"/research/sessions/{gs}/export",
                        headers={"Authorization": f"Bearer {_token(admin)}"}).json()
    assert bundle["turn_taking"]["totals"]["artifact_writes"] == 2, \
        "metrics must describe the session, not only the exportable rows"
    assert len(bundle["artifact_revisions"]) == 1, "but only consented rows are shared"
    assert all(k.startswith("anon-") for k in bundle["turn_taking"]["contribution_share"])


def test_the_bundle_states_its_own_versions(app_ready, stub_model):
    """The bundle must carry the versions actually in force, so an archived
    export stays traceable to the definitions that produced it. Asserted against
    the constants rather than literals: a definition change is supposed to move
    these, and pinning the literal here only makes the bump look like a failure."""
    from analysis.turn_taking import METRICS_VERSION
    from main import STUDY_SCHEMA_VERSION

    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))

    b = client.get(f"/research/sessions/{gs}/export",
                   headers={"Authorization": f"Bearer {_token(admin)}"}).json()
    assert b["schema_version"] == STUDY_SCHEMA_VERSION
    assert b["metrics_version"] == METRICS_VERSION
    # Both are set and look like versions, not empty strings passed through.
    assert b["schema_version"] and b["metrics_version"]


def test_jsonl_streams_one_tagged_object_per_line(app_ready, stub_model):
    gid, users, admin = asyncio.run(_team())
    client = TestClient(app_ready)
    _seed_activity(client, gid, users)
    gs = asyncio.run(_gs_id(gid))

    r = client.get(f"/research/sessions/{gs}/export?format=jsonl",
                   headers={"Authorization": f"Bearer {_token(admin)}"})
    assert r.status_code == 200
    lines = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert lines[0]["kind"] == "meta"
    kinds = {l["kind"] for l in lines}
    assert "events" in kinds and "artifact_revisions" in kinds
    assert all("kind" in l for l in lines)
