"""Integration tests for the group WebSocket: membership gate, presence, a
broadcast streaming turn (Gemini mocked), and strict min-2-live gating."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from group_helpers import make_group_team, register


def _recv_until(ws, wanted: str, limit: int = 8) -> dict:
    """Pull messages until one of the wanted type arrives."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == wanted:
            return msg
    raise AssertionError(f"did not receive {wanted!r} within {limit} messages")


def test_non_member_is_rejected():
    from main import app

    with TestClient(app) as c:
        gid, _tokens = make_group_team(c, n_students=2)
        outsider = register(c)
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(f"/ws/group?token={outsider}&group_id={gid}") as ws:
                ws.receive_json()


def test_connect_emits_session_init_and_presence():
    from main import app

    with TestClient(app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)

        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as ws1:
            assert _recv_until(ws1, "session_init")["group_id"] == gid
            # Member 2 joins → member 1 sees presence reflecting both.
            with c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as ws2:
                _recv_until(ws2, "session_init")
                for _ in range(10):
                    msg = ws1.receive_json()
                    if msg.get("type") == "presence" and len(msg["members"]) == 2:
                        break
                else:
                    raise AssertionError("did not see a 2-member presence on ws1")


def test_single_member_cannot_run_turn():
    """Strict group-only: one connected member is told to wait, no AI turn runs."""
    from main import app

    with TestClient(app) as c:
        gid, (t1, _t2) = make_group_team(c, n_students=2)
        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as ws:
            _recv_until(ws, "session_init")
            ws.send_json({"type": "message", "content": "Solo attempt"})
            w = _recv_until(ws, "waiting", limit=10)
            assert w["needed"] == 2 and w["present"] == 1


def test_team_chat_is_separate_persisted_stream():
    """Team backchannel: broadcasts to other members (not the sender), persists,
    and replays on reconnect — all without any LLM/turn machinery."""
    from main import app

    with TestClient(app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)

        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as ws1, \
             c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as ws2:
            _recv_until(ws1, "session_init")
            _recv_until(ws2, "session_init")
            ws1.send_json({"type": "team_chat", "content": "let's ask about edge cases"})
            tc = _recv_until(ws2, "team_chat", limit=20)
            assert tc["content"] == "let's ask about edge cases"
            assert tc["sender_user_id"]

        # A (re)connecting member replays the backchannel from the DB.
        with c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as ws3:
            hist = _recv_until(ws3, "team_chat_history", limit=20)
            assert any(m["content"] == "let's ask about edge cases" for m in hist["messages"])


def test_streaming_turn_broadcasts_to_all(monkeypatch):
    import main

    class _Chunk:
        def __init__(self, text):
            self.text = text

    class _Models:
        async def generate_content_stream(self, model, contents, config):
            async def gen():
                for t in ("Hello ", "team"):
                    yield _Chunk(t)
            return gen()

    class _Aio:
        models = _Models()

    class _FakeClient:
        aio = _Aio()

    async def _fake_eval(history):
        return {"scores": {"PEI": 75}, "classification": "coding", "leading_status": "balanced"}

    monkeypatch.setattr(main, "client", _FakeClient())
    monkeypatch.setattr(main, "evaluate_conversation", _fake_eval)

    with TestClient(main.app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)

        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as ws1, \
             c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as ws2:
            _recv_until(ws1, "session_init")
            _recv_until(ws2, "session_init")

            ws1.send_json({"type": "message", "content": "Hi"})

            # The non-sender sees the authored prompt; both see the streamed reply.
            um = _recv_until(ws2, "user_message", limit=20)
            assert um["content"] == "Hi" and um["sender_user_id"]
            done1 = _recv_until(ws1, "done", limit=20)
            done2 = _recv_until(ws2, "done", limit=20)
            assert done1["full_response"] == "Hello team"
            assert done2["full_response"] == "Hello team"

            # The shared evaluation is broadcast to every member.
            eval1 = _recv_until(ws1, "eval", limit=20)
            eval2 = _recv_until(ws2, "eval", limit=20)
            assert eval1["data"]["scores"]["PEI"] == 75
            assert eval2["data"]["scores"]["PEI"] == 75
