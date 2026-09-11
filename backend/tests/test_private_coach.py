"""Private per-student coach conversations inside a group session.

The property that matters: each student's coach thread is their own. Nobody
else's messages appear in it, and it is not the shared /ws/group thread.
"""

import json

import pytest
from fastapi.testclient import TestClient

from group_helpers import make_group_team


def _recv_until(ws, wanted: str, limit: int = 10) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == wanted:
            return msg
    raise AssertionError(f"did not receive {wanted!r} within {limit} messages")


def _coach_url(token: str, gid: str, role: str | None = None) -> str:
    url = f"/ws/coach?token={token}&group_id={gid}"
    return url + (f"&role={role}" if role else "")


def test_each_student_gets_their_own_conversation():
    from main import app

    with TestClient(app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)
        with c.websocket_connect(_coach_url(t1, gid)) as w1:
            init1 = _recv_until(w1, "session_init")
            with c.websocket_connect(_coach_url(t2, gid)) as w2:
                init2 = _recv_until(w2, "session_init")

        assert init1["private"] is True and init2["private"] is True
        assert init1["conversation_id"] != init2["conversation_id"], (
            "two students share one private conversation -- not private at all"
        )


def test_private_conversation_is_not_the_shared_group_thread():
    from main import app

    with TestClient(app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)
        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as wg:
            shared = _recv_until(wg, "session_init")["conversation_id"]
        with c.websocket_connect(_coach_url(t1, gid)) as wc:
            private = _recv_until(wc, "session_init")["conversation_id"]

    assert shared != private, "the private coach reused the shared group conversation"


def test_reconnecting_resumes_the_same_private_conversation():
    from main import app

    with TestClient(app) as c:
        gid, (t1, _t2) = make_group_team(c, n_students=2)
        with c.websocket_connect(_coach_url(t1, gid)) as w:
            first = _recv_until(w, "session_init")["conversation_id"]
        with c.websocket_connect(_coach_url(t1, gid)) as w:
            second = _recv_until(w, "session_init")["conversation_id"]
    assert first == second, "a reconnect created a second private conversation"


def test_role_label_is_recorded_and_echoed():
    from main import app

    with TestClient(app) as c:
        gid, (t1, _t2) = make_group_team(c, n_students=2)
        with c.websocket_connect(_coach_url(t1, gid, role="backend")) as w:
            init = _recv_until(w, "session_init")
    assert init["role_label"] == "backend"


def test_non_member_cannot_open_a_private_coach():
    from group_helpers import register
    from main import app
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as c:
        gid, _tokens = make_group_team(c, n_students=2)
        outsider = register(c)
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(_coach_url(outsider, gid)) as ws:
                ws.receive_json()


def test_messages_stay_in_their_own_conversation():
    """The isolation property, at the persistence layer.

    Writes a turn into each student's private conversation directly, then asserts
    neither student's message appears in the other's thread, nor in the shared
    group thread.
    """
    import asyncio

    from main import app

    with TestClient(app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)
        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as wg:
            shared_id = _recv_until(wg, "session_init")["conversation_id"]
        with c.websocket_connect(_coach_url(t1, gid)) as w1:
            conv1 = _recv_until(w1, "session_init")["conversation_id"]
        with c.websocket_connect(_coach_url(t2, gid)) as w2:
            conv2 = _recv_until(w2, "session_init")["conversation_id"]

    async def go():
        from database import AsyncSessionLocal, Message
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            db.add(Message(conversation_id=conv1, role="user", content="ALICE SECRET"))
            db.add(Message(conversation_id=conv2, role="user", content="BOB SECRET"))
            await db.commit()

            async def contents(cid):
                rows = (await db.execute(
                    select(Message.content).where(Message.conversation_id == cid)
                )).all()
                return [r[0] for r in rows]

            return await contents(conv1), await contents(conv2), await contents(shared_id)

    c1, c2, cs = asyncio.run(go())
    assert "ALICE SECRET" in c1 and "BOB SECRET" not in c1
    assert "BOB SECRET" in c2 and "ALICE SECRET" not in c2
    assert "ALICE SECRET" not in cs and "BOB SECRET" not in cs, (
        "a private message leaked into the shared group conversation"
    )


def test_shared_group_chat_still_works_alongside():
    """Additive, not a replacement: /ws/group must be unaffected."""
    from main import app

    with TestClient(app) as c:
        gid, (t1, t2) = make_group_team(c, n_students=2)
        # A private coach open at the same time must not disturb the group room.
        with c.websocket_connect(_coach_url(t1, gid)):
            with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as g1:
                assert _recv_until(g1, "session_init")["group_id"] == gid
                with c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as g2:
                    _recv_until(g2, "session_init")
                    for _ in range(10):
                        msg = g1.receive_json()
                        if msg.get("type") == "presence" and len(msg["members"]) == 2:
                            break
                    else:
                        raise AssertionError("group presence broke with a coach socket open")


def test_conversation_kinds_are_distinct_in_the_database():
    import asyncio

    from main import app

    with TestClient(app) as c:
        gid, (t1, _t2) = make_group_team(c, n_students=2)
        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as wg:
            _recv_until(wg, "session_init")
        with c.websocket_connect(_coach_url(t1, gid)) as wc:
            _recv_until(wc, "session_init")

    async def go():
        from database import (AsyncSessionLocal, Conversation,
                             CONVERSATION_GROUP_PRIVATE, CONVERSATION_GROUP_SHARED)
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Conversation.kind).where(Conversation.group_session_id.is_not(None))
            )).all()
            return sorted({r[0] for r in rows})

    kinds = asyncio.run(go())
    assert "group_shared" in kinds and "group_private" in kinds, kinds
