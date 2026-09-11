"""Phase 4: shared scoring — best_pei rolls into the GroupSession, and the
group end/analysis endpoints. Gemini + evaluator + analyst are all mocked."""

import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from group_helpers import make_group_team, register as _register


def _group_session_best_pei(group_id: str):
    from database import GroupSession

    sync_url = os.environ["DATABASE_URL"].replace("+aiosqlite", "")
    eng = create_engine(sync_url)
    try:
        with eng.connect() as conn:
            return conn.execute(
                select(GroupSession.best_pei).where(GroupSession.group_id == group_id)
            ).scalar()
    finally:
        eng.dispose()


def _recv_until(ws, wanted, limit=20):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == wanted:
            return msg
    raise AssertionError(f"did not receive {wanted!r} within {limit} messages")


def _patch_ai(monkeypatch):
    import main

    class _Chunk:
        def __init__(self, text):
            self.text = text

    class _Models:
        async def generate_content_stream(self, model, contents, config):
            async def gen():
                yield _Chunk("Answer.")
            return gen()

    class _Aio:
        models = _Models()

    class _FakeClient:
        aio = _Aio()

    async def _fake_eval(history):
        return {"scores": {"PEI": 82}, "classification": "coding", "leading_status": "balanced"}

    async def _fake_analyze(transcript, per_turn, challenge_ctx):
        return {"status": "ready", "session_pei": 82, "narrative": "ok", "takeaways": []}

    monkeypatch.setattr(main, "client", _FakeClient())
    monkeypatch.setattr(main, "evaluate_conversation", _fake_eval)
    monkeypatch.setattr(main, "analyze_session", _fake_analyze)


def test_best_pei_rolls_into_group_session(monkeypatch):
    import main

    _patch_ai(monkeypatch)
    with TestClient(main.app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)
        # Both members must be live for a turn to run (strict group-only).
        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as ws, \
             c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as ws2:
            _recv_until(ws, "session_init")
            _recv_until(ws2, "session_init")
            ws.send_json({"type": "message", "content": "Hi"})
            _recv_until(ws, "eval")  # turn fully persisted by the time eval is sent

        assert _group_session_best_pei(gid) == 82


def test_end_group_session_and_analysis(monkeypatch):
    import main

    _patch_ai(monkeypatch)
    with TestClient(main.app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)
        h1 = {"Authorization": f"Bearer {t1}"}

        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as ws, \
             c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as ws2:
            _recv_until(ws, "session_init")
            _recv_until(ws2, "session_init")
            ws.send_json({"type": "message", "content": "Hi"})
            _recv_until(ws, "eval")

        # End the shared session.
        r = c.post(f"/groups/{gid}/sessions/1/end", headers=h1)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_avg_pei"] == 82.0
        assert body["end_reason"] == "manual"
        assert body["analysis_status"] in ("pending", "ready")

        # Analysis is pollable and membership-gated.
        a = c.get(f"/groups/{gid}/sessions/1/analysis", headers=h1)
        assert a.status_code == 200
        assert a.json().get("status") in ("pending", "ready")

        outsider = _register(c)
        forbidden = c.get(
            f"/groups/{gid}/sessions/1/analysis",
            headers={"Authorization": f"Bearer {outsider}"},
        )
        assert forbidden.status_code == 403
