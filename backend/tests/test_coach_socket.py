"""/ws/coach: private coaches, the shared artifact, and read instrumentation.

Driven through a real websocket. Every message type exercised here avoids the
LLM entirely — artifact reads and writes are pure server work — so this runs
with no Gemini or OpenAI key, which is what lets it guard the read-coverage
requirement in CI rather than only by hand.
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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


async def _make_team(n_members: int = 2, section_defs=None):
    """A group challenge with n members and a session. Returns (group_id, [user_ids])."""
    from database import (AsyncSessionLocal, Challenge, GroupChallenge, GroupMember,
                          User)

    sessions = [{
        "title": "S1", "goal": "g", "brief": "b",
        "system_prompt_extra": "coach them",
    }]
    if section_defs is not None:
        sessions[0]["artifact_sections"] = section_defs

    async with AsyncSessionLocal() as db:
        users = []
        for i in range(n_members):
            u = User(email=f"coach_{uuid.uuid4().hex[:10]}@e.com", name=f"Member{i}",
                     password_hash="x", consent_research=True)
            db.add(u)
            await db.flush()
            users.append(u.id)
        ch = Challenge(title="Coach Test", description="d", category="c",
                       difficulty="easy", total_sessions=1, sessions_data=sessions)
        db.add(ch)
        await db.flush()
        gc = GroupChallenge(challenge_id=ch.id, created_by=users[0], status="open")
        db.add(gc)
        await db.flush()
        for uid in users:
            db.add(GroupMember(group_id=gc.id, user_id=uid))
        await db.commit()
        return gc.id, users


def _token(user_id: str) -> str:
    from auth import create_token

    return create_token(user_id)


def _connect(client, group_id, user_id):
    return client.websocket_connect(
        f"/ws/coach?token={_token(user_id)}&group_id={group_id}&session_num=1"
    )


def _drain_until(ws, wanted, limit=25):
    """Read frames until one of `wanted` types arrives. Returns it, or None."""
    for _ in range(limit):
        msg = json.loads(ws.receive_text())
        if msg.get("type") in wanted:
            return msg
    return None


def _fence(ws):
    """Wait until the server has processed everything sent so far.

    Read events are fire-and-forget (the server sends no reply), so a test
    cannot wait on them directly. The handler processes messages sequentially,
    so sending something that *does* reply and waiting for that reply proves the
    earlier sends already landed. A malformed artifact_write is the cheapest
    such message: it answers with artifact_error and writes nothing."""
    ws.send_text(json.dumps({"type": "artifact_write", "section_key": None}))
    return _drain_until(ws, {"artifact_error"})


async def _events(group_session_id, action=None):
    from sqlalchemy import select

    from database import AsyncSessionLocal, StudyEvent

    async with AsyncSessionLocal() as db:
        q = select(StudyEvent).where(StudyEvent.group_session_id == group_session_id)
        if action:
            q = q.where(StudyEvent.action == action)
        return list((await db.execute(q.order_by(StudyEvent.seq))).scalars().all())


async def _group_session_id(group_id):
    from sqlalchemy import select

    from database import AsyncSessionLocal, GroupSession

    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(GroupSession.id).where(GroupSession.group_id == group_id)
        )).scalar_one()


def test_each_student_gets_their_own_private_conversation(app_ready):
    """The inverse of /ws/group: one conversation per student, not per team."""
    from sqlalchemy import select

    from database import AsyncSessionLocal, Conversation

    group_id, users = asyncio.run(_make_team(2))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws_a:
        init_a = _drain_until(ws_a, {"session_init"})
        with _connect(client, group_id, users[1]) as ws_b:
            init_b = _drain_until(ws_b, {"session_init"})

    assert init_a["conversation_id"] != init_b["conversation_id"], \
        "teammates must not share a coach conversation"

    async def check():
        async with AsyncSessionLocal() as db:
            convs = (await db.execute(
                select(Conversation).where(Conversation.kind == "coach_private")
            )).scalars().all()
            return {(c.user_id, c.id) for c in convs}

    owned = asyncio.run(check())
    assert {u for u, _ in owned} >= set(users)


def test_reconnecting_reuses_the_same_private_conversation(app_ready):
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        first = _drain_until(ws, {"session_init"})["conversation_id"]
    with _connect(client, group_id, users[0]) as ws:
        second = _drain_until(ws, {"session_init"})["conversation_id"]

    assert first == second, "a reconnect must not orphan the student's coach history"


def test_artifact_is_created_with_the_assignment_decomposition(app_ready):
    """Created on connect with the real section defs — never lazily on write,
    which would lock the team into a default free-form shape."""
    group_id, users = asyncio.run(_make_team(
        1, section_defs=[{"key": "step-1", "title": "Frame"}, {"key": "step-2", "title": "Solve"}]
    ))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        art = _drain_until(ws, {"artifact"})

    assert [s["key"] for s in art["data"]["sections"]] == ["step-1", "step-2"]
    assert art["data"]["sections"][0]["title"] == "Frame"


def test_assignment_without_sections_gets_one_implicit_section(app_ready):
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        art = _drain_until(ws, {"artifact"})

    assert [s["key"] for s in art["data"]["sections"]] == ["body"]


def test_delivering_the_artifact_on_connect_is_not_logged_as_a_read(app_ready):
    """Rendering is not reading. If connect logged an open, every reconnect
    would inflate read counts and the measure would be worthless."""
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})

    gs = asyncio.run(_group_session_id(group_id))
    assert asyncio.run(_events(gs)) == []


def test_human_reads_are_logged_with_section_granularity(app_ready):
    group_id, users = asyncio.run(_make_team(1, section_defs=[{"key": "step-1"}, {"key": "step-2"}]))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_open"}))
        ws.send_text(json.dumps({"type": "artifact_expand", "section_key": "step-2"}))
        ws.send_text(json.dumps({"type": "artifact_dwell", "section_key": "step-2",
                                 "duration_ms": 4200}))
        ws.send_text(json.dumps({"type": "artifact_close"}))
        _fence(ws)

    gs = asyncio.run(_group_session_id(group_id))
    evs = asyncio.run(_events(gs))
    actions = [e.action for e in evs]
    assert actions[:4] == ["open", "section_expand", "dwell", "close"]
    expand = next(e for e in evs if e.action == "section_expand")
    assert expand.payload["section_key"] == "step-2"
    dwell = next(e for e in evs if e.action == "dwell")
    assert dwell.payload["duration_ms"] == 4200


class _SpyWS:
    """A teammate's socket, attached directly to the live room.

    Two concurrent TestClient websockets cannot be used here: each
    `websocket_connect` starts its own blocking portal with its own event loop,
    so a broadcast from one handler would write to a transport owned by another
    loop. Injecting the teammate into the room exercises the real handler and
    the real broadcast path with a single loop."""

    def __init__(self):
        self.received = []

    async def send_text(self, text):
        self.received.append(json.loads(text))

    def of_type(self, t):
        return [m for m in self.received if m.get("type") == t]


def test_write_broadcasts_to_teammates_and_logs_once(app_ready):
    from group_room import rooms

    group_id, users = asyncio.run(_make_team(2))
    client = TestClient(app_ready)
    spy = _SpyWS()

    with _connect(client, group_id, users[0]) as ws_a:
        _drain_until(ws_a, {"artifact"})
        # After connecting: the GroupSession (and its room) is created by the
        # connect path, so it cannot be looked up before.
        gs = asyncio.run(_group_session_id(group_id))
        rooms.peek(gs).add(spy, users[1], "Member1")
        ws_a.send_text(json.dumps({
            "type": "artifact_write", "section_key": "body",
            "content": "Alice's contribution", "expected_version": 0,
        }))
        ack = _drain_until(ws_a, {"artifact_write_ok", "artifact_error", "artifact_conflict"})

    assert ack["type"] == "artifact_write_ok" and ack["version"] == 1

    seen = spy.of_type("artifact_updated")
    assert len(seen) == 1, "teammate did not see the live edit"
    assert seen[0]["content"] == "Alice's contribution"
    assert seen[0]["updated_by_user_id"] == users[0]

    assert len(asyncio.run(_events(gs, "write"))) == 1


def test_broadcast_of_an_edit_is_not_logged_as_a_teammate_read(app_ready):
    """A teammate's screen updating is a render, not a read. Logging it would
    manufacture reads for someone who never looked."""
    from group_room import rooms

    group_id, users = asyncio.run(_make_team(2))
    client = TestClient(app_ready)
    spy = _SpyWS()

    with _connect(client, group_id, users[0]) as ws_a:
        _drain_until(ws_a, {"artifact"})
        # After connecting: the GroupSession (and its room) is created by the
        # connect path, so it cannot be looked up before.
        gs = asyncio.run(_group_session_id(group_id))
        rooms.peek(gs).add(spy, users[1], "Member1")
        ws_a.send_text(json.dumps({
            "type": "artifact_write", "section_key": "body",
            "content": "text", "expected_version": 0,
        }))
        _drain_until(ws_a, {"artifact_write_ok"})

    assert spy.of_type("artifact_updated"), "precondition: teammate got the broadcast"
    reads = [e for e in asyncio.run(_events(gs)) if e.action in ("open", "section_expand", "dwell")]
    assert reads == [], "a broadcast must not count as the teammate reading"


def test_write_ack_echoes_the_saved_content(app_ready):
    """Regression: the ack carried only the version. Teammates learn the new text
    from the artifact_updated broadcast, but the sender is excluded from it — so
    the author's own section rendered as empty until they reloaded the page."""
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "body",
                                 "content": "what I just typed", "expected_version": 0}))
        ack = _drain_until(ws, {"artifact_write_ok", "artifact_error", "artifact_conflict"})

    assert ack["type"] == "artifact_write_ok"
    assert ack["content"] == "what I just typed", \
        "the author cannot render their own save without the text coming back"


def test_stale_write_returns_a_conflict_the_client_can_rebase_on(app_ready):
    """Second write is based on version 0, which is already stale. Same code
    path a racing teammate hits, without needing a second socket."""
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "body",
                                 "content": "first", "expected_version": 0}))
        first = _drain_until(ws, {"artifact_write_ok", "artifact_conflict", "artifact_error"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "body",
                                 "content": "second", "expected_version": 0}))
        conflict = _drain_until(ws, {"artifact_conflict", "artifact_write_ok", "artifact_error"})

    assert first["type"] == "artifact_write_ok"
    assert conflict["type"] == "artifact_conflict"
    assert conflict["version"] == 1
    assert conflict["content"] == "first", "conflict must carry current text for the rebase"

    gs = asyncio.run(_group_session_id(group_id))
    assert len(asyncio.run(_events(gs, "write"))) == 1, "a rejected write must not be logged"


def test_malformed_write_is_rejected_without_logging(app_ready):
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "body"}))
        err = _drain_until(ws, {"artifact_error", "artifact_write_ok"})

    assert err["type"] == "artifact_error"
    gs = asyncio.run(_group_session_id(group_id))
    assert asyncio.run(_events(gs, "write")) == []


def test_non_member_cannot_open_a_coach_socket(app_ready):
    from starlette.websockets import WebSocketDisconnect

    from database import AsyncSessionLocal, User

    group_id, _users = asyncio.run(_make_team(1))

    async def outsider():
        async with AsyncSessionLocal() as db:
            u = User(email=f"out_{uuid.uuid4().hex[:8]}@e.com", name="Outsider",
                     password_hash="x")
            db.add(u)
            await db.commit()
            return u.id

    stranger = asyncio.run(outsider())
    client = TestClient(app_ready)

    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(client, group_id, stranger) as ws:
            ws.receive_text()
    assert exc.value.code == 4003


def test_bad_token_is_rejected(app_ready):
    from starlette.websockets import WebSocketDisconnect

    group_id, _ = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/ws/coach?token=garbage&group_id={group_id}&session_num=1"
        ) as ws:
            ws.receive_text()
    assert exc.value.code == 4001


def test_duplicate_read_delivery_is_deduped_over_the_socket(app_ready):
    """A buffered read flushed twice after a reconnect must count once."""
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)
    event_id = f"evt_{uuid.uuid4().hex[:10]}"

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        for _ in range(2):
            ws.send_text(json.dumps({
                "type": "artifact_open", "event_id": event_id,
                "client_ts": "2026-09-19T10:00:00Z",
            }))
        ws.send_text(json.dumps({"type": "artifact_expand", "section_key": "body"}))
        _fence(ws)

    gs = asyncio.run(_group_session_id(group_id))
    opens = asyncio.run(_events(gs, "open"))
    assert len(opens) == 1
    assert opens[0].client_ts is not None, "buffered read must keep its original client_ts"


def test_private_coach_output_never_reaches_a_teammate(app_ready):
    """send_to_user, not broadcast. A leak here would destroy the independence
    the whole design rests on, so it is asserted at the room level."""
    from group_room import GroupRoom

    sent_a, sent_b = [], []

    class FakeWS:
        def __init__(self, sink):
            self.sink = sink

        async def send_text(self, text):
            self.sink.append(json.loads(text))

    room = GroupRoom("gs-test")
    room.add(FakeWS(sent_a), "user-a", "A")
    room.add(FakeWS(sent_b), "user-b", "B")

    asyncio.run(room.send_to_user("user-a", {"type": "stream", "content": "private coaching"}))

    assert sent_a == [{"type": "stream", "content": "private coaching"}]
    assert sent_b == [], "teammate received another student's private coach output"


def test_each_student_has_an_independent_turn_lock(app_ready):
    """Private coaches must run concurrently — serialising them would defeat
    the design."""
    from group_room import GroupRoom

    room = GroupRoom("gs-test-2")
    a, b = room.user_lock("user-a"), room.user_lock("user-b")

    assert a is not b
    assert a is room.user_lock("user-a"), "lock must be stable per user"

    async def check():
        await a.acquire()
        try:
            return b.locked()
        finally:
            a.release()

    assert asyncio.run(check()) is False, "one student's turn must not block a teammate's"


# -- A full coach turn, with the model and evaluator stubbed ------------------
# Everything above avoids the LLM. These drive a real turn through the handler
# so the persistence path (_save_turn -> _log_coach_turn -> GroupSession) is
# covered too, without needing a Gemini or OpenAI key.


class _FakeChunk:
    def __init__(self, text):
        self.text = text


async def _fake_stream(*_args, **_kwargs):
    async def gen():
        for piece in ("Here ", "is ", "some ", "coaching."):
            yield _FakeChunk(piece)

    return gen()


@pytest.fixture
def stub_model(monkeypatch):
    """Patch the Gemini stream and the evaluator at their use sites in main."""
    import main

    monkeypatch.setattr(main.client.aio.models, "generate_content_stream", _fake_stream)

    async def fake_eval(_history):
        return {"scores": {"PEI": 63.5, "PSQ": 60, "CCM": 65, "TSI": 62, "CLM": 66, "RAS": 64},
                "classification": "Intermediate", "leading_status": "leading"}

    monkeypatch.setattr(main, "evaluate_conversation", fake_eval)


def test_a_coach_turn_streams_persists_and_logs(app_ready, stub_model):
    from sqlalchemy import select

    from database import AsyncSessionLocal, EvalResult, Message

    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        init = _drain_until(ws, {"session_init"})
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "message", "content": "How should I start?"}))
        done = _drain_until(ws, {"done", "error"})
        ev = _drain_until(ws, {"eval", "eval_error"})

    assert done["type"] == "done"
    assert done["full_response"] == "Here is some coaching."
    assert ev["type"] == "eval" and ev["data"]["scores"]["PEI"] == 63.5

    conv_id = init["conversation_id"]

    async def check():
        async with AsyncSessionLocal() as db:
            msgs = (await db.execute(
                select(Message).where(Message.conversation_id == conv_id)
                .order_by(Message.created_at)
            )).scalars().all()
            evals = (await db.execute(
                select(EvalResult).where(EvalResult.conversation_id == conv_id)
            )).scalars().all()
            return [(m.role, m.content) for m in msgs], evals

    msgs, evals = asyncio.run(check())
    assert msgs == [("user", "How should I start?"), ("assistant", "Here is some coaching.")]
    assert len(evals) == 1 and evals[0].pei == 63.5

    gs = asyncio.run(_group_session_id(group_id))
    turns = asyncio.run(_events(gs, "turn"))
    assert len(turns) == 1
    assert turns[0].target == "coach"
    assert turns[0].actor_user_id == users[0]
    assert turns[0].payload["pei"] == 63.5


def test_a_coach_turn_marks_the_group_session_started(app_ready, stub_model):
    """Regression: /ws/coach persists via the solo saver, which rolls progress
    into a UserChallengeSession that a coach_private conversation does not have.
    Without an explicit mark the team would sit at 'not_started' all session and
    the instructor views would show them as never having begun."""
    from database import AsyncSessionLocal, GroupSession

    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        gs = asyncio.run(_group_session_id(group_id))

        async def status():
            async with AsyncSessionLocal() as db:
                row = await db.get(GroupSession, gs)
                return row.status, row.started_at

        assert asyncio.run(status()) == ("not_started", None)

        ws.send_text(json.dumps({"type": "message", "content": "hello"}))
        _drain_until(ws, {"done", "error"})
        _drain_until(ws, {"eval", "eval_error"})

        st, started = asyncio.run(status())

    assert st == "in_progress"
    assert started is not None


def test_the_coach_reads_the_shared_artifact_and_that_read_is_logged(app_ready, stub_model):
    """The artifact enters the student's prompt, and that is recorded as a
    coach-mediated read attributed to them — never merged into human opens."""
    group_id, users = asyncio.run(_make_team(1, section_defs=[{"key": "step-1"}]))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "step-1",
                                 "content": "our working notes", "expected_version": 0}))
        _drain_until(ws, {"artifact_write_ok"})
        ws.send_text(json.dumps({"type": "message", "content": "what next?"}))
        _drain_until(ws, {"done", "error"})
        _drain_until(ws, {"eval", "eval_error"})

    gs = asyncio.run(_group_session_id(group_id))
    coach_reads = asyncio.run(_events(gs, "read_by_coach"))
    assert len(coach_reads) == 1
    assert coach_reads[0].actor_kind == "coach"
    assert coach_reads[0].actor_user_id == users[0]
    assert coach_reads[0].payload["section_keys"] == ["step-1"]
    assert asyncio.run(_events(gs, "open")) == [], "a coach read is not a human open"

    # And the ordering is legible: write, coach read, turn.
    assert [e.action for e in asyncio.run(_events(gs))] == ["write", "read_by_coach", "turn"]


def test_artifact_content_actually_reaches_the_prompt(app_ready, monkeypatch):
    """Guards the injection itself: if the block stopped being appended, the
    read_by_coach event above would still fire and nothing would look wrong."""
    import main

    captured = {}

    async def capturing_stream(*_args, **kwargs):
        captured["contents"] = kwargs.get("contents")

        async def gen():
            yield _FakeChunk("ok")

        return gen()

    monkeypatch.setattr(main.client.aio.models, "generate_content_stream", capturing_stream)

    async def fake_eval(_h):
        return {"scores": {"PEI": 50.0}}

    monkeypatch.setattr(main, "evaluate_conversation", fake_eval)

    group_id, users = asyncio.run(_make_team(1, section_defs=[{"key": "step-1"}]))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "step-1",
                                 "content": "DISTINCTIVE_TEAM_TEXT", "expected_version": 0}))
        _drain_until(ws, {"artifact_write_ok"})
        ws.send_text(json.dumps({"type": "message", "content": "what next?"}))
        _drain_until(ws, {"done", "error"})
        _drain_until(ws, {"eval", "eval_error"})

    blob = str(captured.get("contents"))
    assert "DISTINCTIVE_TEAM_TEXT" in blob, "the shared artifact never reached the coach's prompt"


def test_ending_a_coach_session_aggregates_across_private_conversations(app_ready, stub_model):
    """Regression: the shared end endpoint averaged EvalResult over
    gs.conversation_id — the shared conversation, which in this arm exists but
    holds no messages, because every student talks to their own. It reported
    avg_pei=None / turns=0 and would then have run a narrative analysis over an
    empty transcript."""
    from database import AsyncSessionLocal, GroupSession
    from main import app

    group_id, users = asyncio.run(_make_team(2))
    client = TestClient(app_ready)

    for u in users:
        with _connect(client, group_id, u) as ws:
            _drain_until(ws, {"artifact"})
            ws.send_text(json.dumps({"type": "message", "content": "hello coach"}))
            _drain_until(ws, {"done", "error"})
            _drain_until(ws, {"eval", "eval_error"})

    r = client.post(f"/groups/{group_id}/sessions/1/end",
                    headers={"Authorization": f"Bearer {_token(users[0])}"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["arm"] == "collab_coach_artifact"
    assert body["turns"] == 2, "both students' turns must be counted"
    assert body["session_avg_pei"] == 63.5
    # Per-student averages are reported rather than collapsed: what a team's
    # single score means when everyone has their own coach is a research call.
    assert set(body["per_student"]) == set(users)
    assert all(v["turns"] == 1 for v in body["per_student"].values())
    assert body["analysis_status"] is None, "no narrative analysis in this arm yet"

    gs = asyncio.run(_group_session_id(group_id))

    async def status():
        async with AsyncSessionLocal() as db:
            row = await db.get(GroupSession, gs)
            return row.status, row.end_reason

    assert asyncio.run(status()) == ("completed", "manual")


def test_ending_still_works_for_the_legacy_shared_coach_arm(app_ready):
    """The arm switch must not break /ws/group teams, which have a shared
    conversation and no private ones."""
    from database import AsyncSessionLocal, Conversation, GroupSession

    group_id, users = asyncio.run(_make_team(1))

    async def seed_shared():
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            gs = (await db.execute(
                select(GroupSession).where(GroupSession.group_id == group_id)
            )).scalar_one_or_none()
            if gs is None:
                from database import Challenge, GroupChallenge
                team = await db.get(GroupChallenge, group_id)
                gs = GroupSession(group_id=group_id, challenge_id=team.challenge_id,
                                  session_number=1, status="in_progress")
                db.add(gs)
                await db.flush()
            conv = Conversation(user_id=users[0], group_session_id=gs.id, kind="group_shared")
            db.add(conv)
            await db.flush()
            gs.conversation_id = conv.id
            await db.commit()
            return gs.id

    asyncio.run(seed_shared())
    client = TestClient(app_ready)
    r = client.post(f"/groups/{group_id}/sessions/1/end",
                    headers={"Authorization": f"Bearer {_token(users[0])}"})

    assert r.status_code == 200, r.text
    assert "arm" not in r.json(), "legacy arm must keep its original response shape"


def test_isolated_prominence_keeps_the_artifact_out_of_the_coach_prompt(app_ready, monkeypatch):
    """The condition must change real behaviour, not just a label in the log.
    Under `isolated` the team's work must not reach the coach, and no
    read_by_coach may be recorded — a read that did not happen."""
    import main
    from sqlalchemy import select

    from database import AsyncSessionLocal, ClassroomChallenge, GroupChallenge

    captured = {}

    async def capturing_stream(*_a, **kw):
        captured["contents"] = kw.get("contents")

        async def gen():
            yield _FakeChunk("ok")

        return gen()

    monkeypatch.setattr(main.client.aio.models, "generate_content_stream", capturing_stream)

    async def fake_eval(_h):
        return {"scores": {"PEI": 50.0}}

    monkeypatch.setattr(main, "evaluate_conversation", fake_eval)

    group_id, users = asyncio.run(_make_team(1, section_defs=[{"key": "s1"}]))

    async def set_isolated():
        """Attach the team to a section configured as isolated."""
        from database import Classroom, User
        async with AsyncSessionLocal() as db:
            team = await db.get(GroupChallenge, group_id)
            inst = User(email=f"i_{uuid.uuid4().hex[:8]}@e.com", name="I", password_hash="x")
            db.add(inst); await db.flush()
            room = Classroom(name="Iso", join_code=uuid.uuid4().hex[:8].upper(),
                             instructor_user_id=inst.id)
            db.add(room); await db.flush()
            team.classroom_id = room.id
            db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=team.challenge_id,
                                      mode="group", study_arm="collab_coach_artifact",
                                      coach_prominence="isolated"))
            await db.commit()

    asyncio.run(set_isolated())

    client = TestClient(app_ready)
    with _connect(client, group_id, users[0]) as ws:
        init = _drain_until(ws, {"session_init"})
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "s1",
                                 "content": "SECRET_TEAM_TEXT", "expected_version": 0}))
        _drain_until(ws, {"artifact_write_ok"})
        ws.send_text(json.dumps({"type": "message", "content": "what next?"}))
        _drain_until(ws, {"done", "error"})
        _drain_until(ws, {"eval", "eval_error"})

    assert init["condition"]["prominence"] == "isolated"
    assert "SECRET_TEAM_TEXT" not in str(captured.get("contents")), \
        "isolated must keep the team artifact out of the coach prompt"

    gs = asyncio.run(_group_session_id(group_id))
    assert asyncio.run(_events(gs, "read_by_coach")) == [], \
        "no coach read may be logged when the artifact was never injected"


def test_the_resolved_condition_is_stamped_on_every_event(app_ready, stub_model):
    """An exported log must say what condition produced it, without a join
    against a config table that may have changed since."""
    group_id, users = asyncio.run(_make_team(1))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws:
        _drain_until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "message", "content": "hi"}))
        _drain_until(ws, {"done", "error"})
        _drain_until(ws, {"eval", "eval_error"})

    gs = asyncio.run(_group_session_id(group_id))
    turns = asyncio.run(_events(gs, "turn"))
    assert turns[0].condition == {
        "arm": "collab_coach_artifact", "prominence": "on_request", "corpus": None,
    }
