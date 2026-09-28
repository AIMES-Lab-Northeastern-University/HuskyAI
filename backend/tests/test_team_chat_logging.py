"""Team backchannel in the research record (collab-study-pending #3).

Whether team chat is recorded is the PI's decision, so it is a per-assignment
setting — off | metadata | content — defaulting to "off", which is exactly the
behaviour before the setting existed. These tests pin what each mode may and
may not put into the log and the export, because a mode that leaks one step
further than its name says is a consent problem, not a bug.
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


async def _team(logging="off", consents=(True, True)):
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          GroupChallenge, GroupMember, User)

    async with AsyncSessionLocal() as db:
        admin = User(email=f"ad_{uuid.uuid4().hex[:8]}@e.com", name="Admin",
                     password_hash="x", is_platform_admin=True)
        owner = User(email=f"ow_{uuid.uuid4().hex[:8]}@e.com", name="Owner", password_hash="x")
        db.add_all([admin, owner]); await db.flush()
        users = []
        for name, c in zip(("Bartholomew Quince", "Philippa Marchbank"), consents):
            u = User(email=f"tc_{uuid.uuid4().hex[:10]}@example.com", name=name,
                     password_hash="x", consent_research=c)
            db.add(u); await db.flush()
            users.append(u.id)
        room = Classroom(name="Chat Sec", join_code=uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=owner.id)
        ch = Challenge(title="Chat Challenge", description="d", category="c",
                       difficulty="easy", total_sessions=1,
                       sessions_data=[{"title": "S", "goal": "g", "brief": "b",
                                       "seed_question": "q",
                                       "artifact_sections": [{"key": "s1"}]}])
        db.add_all([room, ch]); await db.flush()
        cc = ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id, mode="group",
                                study_arm="collab_coach_artifact",
                                team_chat_logging=logging)
        team = GroupChallenge(challenge_id=ch.id, classroom_id=room.id,
                              created_by=owner.id, status="active")
        db.add_all([cc, team]); await db.flush()
        for uid in users:
            db.add(GroupMember(group_id=team.id, user_id=uid))
        await db.commit()
        return {"gid": team.id, "users": users, "admin": admin.id,
                "owner": owner.id, "cc": cc.id}


def _connect(client, gid, uid):
    return client.websocket_connect(f"/ws/coach?token={_token(uid)}&group_id={gid}&session_num=1")


def _until(ws, types, limit=30):
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if m.get("type") in types:
            return m
    return None


def _chat(client, gid, uid, *messages):
    """Send team-chat messages, then fence: the handler is sequential, so a reply
    to a later message proves the chats were handled before the socket closes."""
    with _connect(client, gid, uid) as ws:
        _until(ws, {"artifact"})
        for m in messages:
            ws.send_text(json.dumps({"type": "team_chat", "content": m}))
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": None}))
        _until(ws, {"artifact_error"})


async def _gs_id(group_id):
    from sqlalchemy import select
    from database import AsyncSessionLocal, GroupSession
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(GroupSession.id).where(GroupSession.group_id == group_id))).scalar_one()


async def _chat_events(gs):
    from sqlalchemy import select
    from database import AsyncSessionLocal, StudyEvent
    async with AsyncSessionLocal() as db:
        return list((await db.execute(
            select(StudyEvent).where(StudyEvent.group_session_id == gs,
                                     StudyEvent.target == "group_chat")
            .order_by(StudyEvent.seq)
        )).scalars().all())


async def _stored_messages(gid):
    from sqlalchemy import select
    from database import AsyncSessionLocal, GroupChatMessage
    async with AsyncSessionLocal() as db:
        return list((await db.execute(
            select(GroupChatMessage).where(GroupChatMessage.group_id == gid)
        )).scalars().all())


def _export(client, gs, admin, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/research/sessions/{gs}/export?{q}",
                      headers={"Authorization": f"Bearer {_token(admin)}"})


def test_off_is_the_default_and_emits_nothing(app_ready):
    t = asyncio.run(_team())
    client = TestClient(app_ready)
    _chat(client, t["gid"], t["users"][0], "shall we split it?")
    gs = asyncio.run(_gs_id(t["gid"]))

    assert asyncio.run(_chat_events(gs)) == []
    # Still stored for replay, exactly as before the setting existed.
    assert [m.content for m in asyncio.run(_stored_messages(t["gid"]))] == ["shall we split it?"]
    assert _export(client, gs, t["admin"]).json()["team_chat"] == []


def test_metadata_logs_who_when_and_length_but_never_text(app_ready):
    t = asyncio.run(_team("metadata"))
    client = TestClient(app_ready)
    _chat(client, t["gid"], t["users"][0], "I will take step two")
    gs = asyncio.run(_gs_id(t["gid"]))

    [e] = asyncio.run(_chat_events(gs))
    assert e.action == "message" and e.actor_user_id == t["users"][0]
    assert e.payload == {"chars": 20, "words": 5, "content_logged": False}
    assert e.condition["team_chat_logging"] == "metadata"
    [stored] = asyncio.run(_stored_messages(t["gid"]))
    assert e.ref_id == stored.id

    bundle = _export(client, gs, t["admin"]).json()
    assert bundle["team_chat"] == []
    assert "step two" not in json.dumps(bundle)


def test_content_exports_scrubbed_text_including_teammates_names(app_ready):
    t = asyncio.run(_team("content"))
    client = TestClient(app_ready)
    _chat(client, t["gid"], t["users"][0],
          "Philippa can you email me at bq@northeastern.edu?")
    gs = asyncio.run(_gs_id(t["gid"]))

    [e] = asyncio.run(_chat_events(gs))
    # The text lives in group_chat_messages, never in the event payload,
    # because payloads are pseudonymised on export but not scrubbed.
    assert e.payload["content_logged"] is True
    assert "northeastern" not in json.dumps(e.payload)

    bundle = _export(client, gs, t["admin"]).json()
    [row] = bundle["team_chat"]
    assert row["seq"] == e.seq
    [ev] = [x for x in bundle["events"] if x["seq"] == e.seq]
    assert row["sender"] == ev["actor"] and row["sender"] in bundle["members"]
    assert "Philippa" not in row["content"]
    assert "bq@northeastern.edu" not in row["content"]
    assert "[NAME]" in row["content"] and "[EMAIL]" in row["content"]


def test_each_message_keeps_the_mode_it_was_sent_under(app_ready):
    """Switching to content later must not sweep in text sent under metadata."""
    t = asyncio.run(_team("metadata"))
    client = TestClient(app_ready)
    _chat(client, t["gid"], t["users"][0], "sent under metadata")

    r = client.patch(f"/classrooms/assignments/{t['cc']}/study",
                     json={"team_chat_logging": "content"},
                     headers={"Authorization": f"Bearer {_token(t['owner'])}"})
    assert r.status_code == 200 and r.json()["team_chat_logging"] == "content"

    _chat(client, t["gid"], t["users"][0], "sent under content")
    gs = asyncio.run(_gs_id(t["gid"]))

    assert [e.payload["content_logged"] for e in asyncio.run(_chat_events(gs))] == [False, True]
    assert [row["content"] for row in _export(client, gs, t["admin"]).json()["team_chat"]] \
        == ["sent under content"]


def test_an_unconsented_senders_text_is_filtered_by_their_snapshot(app_ready):
    t = asyncio.run(_team("content", consents=(True, False)))
    client = TestClient(app_ready)
    _chat(client, t["gid"], t["users"][0], "from the consenting member")
    _chat(client, t["gid"], t["users"][1], "from the other member")
    gs = asyncio.run(_gs_id(t["gid"]))

    consented = _export(client, gs, t["admin"]).json()
    assert [r["content"] for r in consented["team_chat"]] == ["from the consenting member"]
    everyone = _export(client, gs, t["admin"], include_unconsented="true").json()
    assert everyone["consent_filtered"] is False
    assert len(everyone["team_chat"]) == 2


def test_jsonl_carries_team_chat_rows(app_ready):
    t = asyncio.run(_team("content"))
    client = TestClient(app_ready)
    _chat(client, t["gid"], t["users"][0], "hello team")
    gs = asyncio.run(_gs_id(t["gid"]))

    r = _export(client, gs, t["admin"], format="jsonl")
    kinds = [json.loads(l)["kind"] for l in r.text.splitlines() if l.strip()]
    assert "team_chat" in kinds


def test_setting_is_validated_and_listed(app_ready):
    t = asyncio.run(_team())
    client = TestClient(app_ready)
    auth = {"Authorization": f"Bearer {_token(t['owner'])}"}

    bad = client.patch(f"/classrooms/assignments/{t['cc']}/study",
                       json={"team_chat_logging": "everything"}, headers=auth)
    assert bad.status_code == 422

    from database import AsyncSessionLocal, ClassroomChallenge

    async def _room():
        async with AsyncSessionLocal() as db:
            return (await db.get(ClassroomChallenge, t["cc"])).classroom_id
    listed = client.get(f"/classrooms/{asyncio.run(_room())}/challenges", headers=auth).json()
    assert listed[0]["team_chat_logging"] == "off"
