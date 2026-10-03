"""Running more than one worker: the pieces that were only correct on one.

- /ws/group serialised turns with an in-process lock and kept the shared
  history in the worker's memory, so teammates on two workers could run turns
  at once and save them under the same turn number.
- Startup sweeps ran on every worker, so each pending score / analysis was
  re-queued once per worker, and a restarting worker failed a sibling's live
  corpus ingest.
- A Redis failure mid-session tore down the socket (losing the turn), and a
  dropped pub/sub connection left a worker deaf for the life of the room.

None of these need a Redis server: the cross-worker parts run on injected
fakes. tests/test_multiworker_redis.py repeats the important ones against a
real server when REDIS_URL is set.
"""

import asyncio
import json
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import coordination
from test_group_room_redis import FakeRedis, FakeWS


@pytest.fixture(scope="module")
def app_ready():
    from database import init_db
    from main import app

    asyncio.run(init_db())
    return app


class _Chunk:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


@pytest.fixture
def model(monkeypatch):
    import main

    gate = threading.Event()
    gate.set()
    seen = []

    async def stream(*_a, **_kw):
        async def gen():
            deadline = time.monotonic() + 5
            while not gate.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            yield _Chunk("coached.")
        return gen()

    async def fake_eval(history, corpus_vector_store_id=None):
        seen.append([m["content"] for m in history])
        return {"scores": {"PEI": 50.0}}

    monkeypatch.setattr(main.client.aio.models, "generate_content_stream", stream)
    monkeypatch.setattr(main, "evaluate_conversation", fake_eval)
    return gate, seen


def _token(uid):
    from auth import create_token
    return create_token(uid)


def _until(ws, types, limit=60):
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if m.get("type") in types:
            return m
    raise AssertionError(f"none of {types}")


async def _team(size=2):
    from database import AsyncSessionLocal, Challenge, GroupChallenge, GroupMember, User

    async with AsyncSessionLocal() as db:
        users = [User(email=f"mw_{uuid.uuid4().hex[:10]}@e.com", name=f"M{i}", password_hash="x")
                 for i in range(size)]
        db.add_all(users); await db.flush()
        ch = Challenge(title="MW", description="d", category="c", difficulty="easy", total_sessions=1,
                       sessions_data=[{"title": "S1", "goal": "g", "brief": "b", "system_prompt_extra": "x"}])
        db.add(ch); await db.flush()
        gc = GroupChallenge(challenge_id=ch.id, created_by=users[0].id, status="open")
        db.add(gc); await db.flush()
        for u in users:
            db.add(GroupMember(group_id=gc.id, user_id=u.id))
        await db.commit()
        return gc.id, [u.id for u in users]


async def _save_elsewhere(conv_id, sender_id):
    """What another worker's turn leaves behind: two saved messages."""
    from database import AsyncSessionLocal, Message
    async with AsyncSessionLocal() as db:
        db.add(Message(conversation_id=conv_id, role="user", content="saved by another worker",
                       sender_user_id=sender_id))
        await db.flush()
        db.add(Message(conversation_id=conv_id, role="assistant", content="its reply"))
        await db.commit()


async def _turn_numbers(conversation_id):
    from database import AsyncSessionLocal, EvalResult
    async with AsyncSessionLocal() as db:
        return sorted(t for (t,) in (await db.execute(select(EvalResult.turn_number).where(
            EvalResult.conversation_id == conversation_id))).all())


async def _group_session_id(gid):
    from database import AsyncSessionLocal, GroupSession
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(GroupSession.id).where(GroupSession.group_id == gid))).scalar_one()


def _group_url(uid, gid):
    return f"/ws/group?token={_token(uid)}&group_id={gid}&session_num=1"


# ---------------------------------------------------------------------------
# /ws/group: shared history and the team-wide turn lock
# ---------------------------------------------------------------------------


def test_a_group_turn_builds_on_a_turn_another_worker_saved(app_ready, model):
    _, seen = model
    gid, (a, b) = asyncio.run(_team())
    client = TestClient(app_ready)
    # Each socket is let finish its handshake (it ends with a presence frame)
    # before the next write: SQLite, the test database, cannot take a write
    # while another connection is mid-handshake. Postgres can.
    with client.websocket_connect(_group_url(a, gid)) as wa:
        conv = _until(wa, {"session_init"})["conversation_id"]
        _until(wa, {"presence"})
        with client.websocket_connect(_group_url(b, gid)) as wb:
            _until(wb, {"presence"})
            asyncio.run(_save_elsewhere(conv, b))
            wa.send_text(json.dumps({"type": "message", "content": "next turn", "attachments": []}))
            _until(wa, {"eval"})
            _until(wb, {"eval"})

    assert seen[-1] == ["saved by another worker", "its reply", "next turn", "coached."]
    assert asyncio.run(_turn_numbers(conv)) == [2], "turn number follows the saved turn"


def test_a_member_joining_a_live_room_sees_turns_saved_elsewhere(app_ready, model):
    gid, (a, b) = asyncio.run(_team())
    client = TestClient(app_ready)
    with client.websocket_connect(_group_url(a, gid)) as wa:     # keeps the room alive
        conv = _until(wa, {"session_init"})["conversation_id"]
        _until(wa, {"presence"})
        asyncio.run(_save_elsewhere(conv, b))
        with client.websocket_connect(_group_url(b, gid)) as wb:
            # Everything the handshake sends, up to the presence frame that ends it.
            frames = []
            while not frames or frames[-1].get("type") != "presence":
                frames.append(json.loads(wb.receive_text()))
    init = next(f for f in frames if f["type"] == "session_init")
    history = [f for f in frames if f["type"] == "history"]
    assert init["turn_count"] == 1
    assert history, "the joiner is sent the saved history"
    assert [m["content"] for m in history[0]["messages"]] == ["saved by another worker", "its reply"]


def test_a_group_turn_is_refused_while_another_worker_runs_one(app_ready, model, monkeypatch):
    """The team's turn lock is a Redis key, so a turn running on another
    worker makes this one answer busy instead of starting a second turn."""
    import main

    fake = FakeRedis()
    main.rooms.configure(client=fake)
    try:
        gid, (a, b) = asyncio.run(_team())
        client = TestClient(app_ready)
        with client.websocket_connect(_group_url(a, gid)) as wa:
            conv = _until(wa, {"session_init"})["conversation_id"]
            _until(wa, {"presence"})
            with client.websocket_connect(_group_url(b, gid)) as wb:
                _until(wb, {"presence"})
                gsid = asyncio.run(_group_session_id(gid))
                fake.kv[f"husky:room:{gsid}:turn"] = "held-by-another-worker"
                wa.send_text(json.dumps({"type": "message", "content": "blocked", "attachments": []}))
                assert _until(wa, {"busy", "typing", "eval"})["type"] == "busy"

                del fake.kv[f"husky:room:{gsid}:turn"]      # the other worker finished
                wa.send_text(json.dumps({"type": "message", "content": "now", "attachments": []}))
                _until(wa, {"eval"})
                _until(wb, {"eval"})
                assert f"husky:room:{gsid}:turn" not in fake.kv, "released after the turn"
        assert asyncio.run(_turn_numbers(conv)) == [1]
    finally:
        main.rooms.configure(url="")


def test_two_rooms_on_two_workers_cannot_both_hold_the_team_turn():
    from group_room import GroupRoom, RedisFanout

    async def go():
        store = {}
        wa = GroupRoom("gs1", RedisFanout("redis://fake", client=FakeRedis(store)))
        wb = GroupRoom("gs1", RedisFanout("redis://fake", client=FakeRedis(store)))
        ta = await wa.acquire_group_turn()
        tb = await wb.acquire_group_turn()
        assert ta and tb is None
        assert not wb.turn_lock.locked(), "a refused claim leaves the local lock free"
        await wa.release_group_turn(ta)
        tb = await wb.acquire_group_turn()
        assert tb is not None
        await wb.release_group_turn(tb)

    asyncio.run(go())


def test_in_process_rooms_keep_the_team_turn_lock_local():
    from group_room import GroupRoom

    async def go():
        room = GroupRoom("gs1")
        token = await room.acquire_group_turn()
        assert token == "local"
        assert await room.acquire_group_turn() is None
        await room.release_group_turn(token)
        assert not room.turn_lock.locked()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# Redis failures mid-session
# ---------------------------------------------------------------------------


class _FailingPublish(FakeRedis):
    async def publish(self, channel, data):
        raise ConnectionError("redis went away")


def test_a_failed_publish_mid_session_still_delivers_locally_and_does_not_raise(caplog):
    from group_room import GroupRoom, RedisFanout

    async def go():
        room = GroupRoom("gs1", RedisFanout("redis://fake", client=_FailingPublish()))
        ws = FakeWS()
        room.connections[ws] = {"user_id": "u1", "name": "A", "socket_id": "s1"}
        for i in range(3):
            await room.broadcast({"type": "stream", "content": str(i)})
        return ws.sent

    with caplog.at_level("CRITICAL", logger="group_chat"):
        sent = asyncio.run(go())
    assert [m["content"] for m in sent] == ["0", "1", "2"]
    assert sum("publish failing" in r.message for r in caplog.records) == 1, "logged once per outage"


class _DroppingPubSubRedis(FakeRedis):
    """The first subscription's stream dies; later ones work."""

    def __init__(self, store=None):
        super().__init__(store)
        self.subscriptions = 0

    def pubsub(self, ignore_subscribe_messages=False):
        ps = super().pubsub(ignore_subscribe_messages)
        self.subscriptions += 1
        if self.subscriptions == 1:
            async def listen():
                raise ConnectionError("connection reset")
                yield  # pragma: no cover
            ps.listen = listen
        return ps


def test_a_dropped_subscription_is_re_established(monkeypatch):
    import group_room
    from group_room import RedisFanout

    monkeypatch.setattr(group_room, "RESUBSCRIBE_BACKOFF_SEC", (0.01,))

    async def go():
        store = {}
        reader_client = _DroppingPubSubRedis(store)
        reader = RedisFanout("redis://fake", client=reader_client)
        writer = RedisFanout("redis://fake", client=FakeRedis(store))
        got = []

        async def handler(payload):
            got.append(payload)

        await reader.subscribe("gs1", handler)
        for _ in range(100):
            if reader_client.subscriptions >= 2:
                break
            await asyncio.sleep(0.01)
        await writer.publish("gs1", {"type": "after_the_drop"})
        for _ in range(100):
            if got:
                break
            await asyncio.sleep(0.01)
        await reader.close()
        return got, reader_client.subscriptions

    got, subs = asyncio.run(go())
    assert subs == 2
    assert got == [{"type": "after_the_drop"}]


# ---------------------------------------------------------------------------
# Leases (coordination.py)
# ---------------------------------------------------------------------------


class FakeLeaseRedis:
    def __init__(self):
        self.kv = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def eval(self, script, numkeys, key, token, *args):
        if self.kv.get(key) != token:
            return 0
        if "del" in script:
            del self.kv[key]
        return 1

    async def exists(self, key):
        return int(key in self.kv)


class BrokenRedis:
    async def set(self, *a, **kw):
        raise ConnectionError("down")

    async def eval(self, *a, **kw):
        raise ConnectionError("down")

    async def exists(self, *a, **kw):
        raise ConnectionError("down")


@pytest.fixture
def leases():
    fake = FakeLeaseRedis()
    coordination.configure(client=fake)
    yield fake
    coordination.configure(None)


def test_without_redis_every_lease_is_granted_and_none_is_held(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    coordination.configure(None)

    async def go():
        a = await coordination.acquire("x")
        b = await coordination.acquire("x")
        held = await coordination.is_held("x")
        await a.release(); await b.release()
        return a, b, held

    a, b, held = asyncio.run(go())
    assert a is not None and b is not None and not a.shared
    assert held is False


def test_a_lease_excludes_a_second_holder_until_released(leases):
    async def go():
        a = await coordination.acquire("job")
        shared = a.shared
        b = await coordination.acquire("job")
        held = await coordination.is_held("job")
        await a.release()
        c = await coordination.acquire("job")
        await c.release()
        return shared, b, held, c

    shared, b, held, c = asyncio.run(go())
    assert shared and b is None and held is True and c is not None
    assert leases.kv == {}


def test_a_stale_holder_cannot_release_someone_else_s_lease(leases):
    async def go():
        a = await coordination.acquire("job")
        leases.kv["husky:lease:job"] = "taken-over"     # a lapsed, b took it
        await a.release()
        return await coordination.is_held("job")

    assert asyncio.run(go()) is True


def test_a_broken_redis_grants_the_lease_but_cannot_say_who_holds_one():
    coordination.configure(client=BrokenRedis())
    try:
        async def go():
            lease = await coordination.acquire("job")
            held = await coordination.is_held("job")
            await lease.release()
            return lease, held

        lease, held = asyncio.run(go())
    finally:
        coordination.configure(None)
    assert lease is not None and not lease.shared, "fails open: the work still runs"
    assert held is None, "but never claims to know who holds it"


def test_a_rescore_another_worker_holds_is_left_to_them(leases, monkeypatch):
    import main

    calls = []

    async def attempts(eval_id):
        calls.append(eval_id)

    monkeypatch.setattr(main, "_rescore_attempts", attempts)
    monkeypatch.setattr(coordination, "LEASE_TTL_SEC", -5)     # the re-check wait becomes 0
    leases.kv["husky:lease:rescore:ev1"] = "another-worker"
    asyncio.run(main._rescore("ev1"))
    assert calls == []

    del leases.kv["husky:lease:rescore:ev1"]
    asyncio.run(main._rescore("ev1"))
    assert calls == ["ev1"]
    assert leases.kv == {}, "released when done"


def test_a_rescore_whose_holder_died_is_taken_over_after_one_lease_lifetime(leases, monkeypatch):
    import main

    calls = []

    async def attempts(eval_id):
        calls.append(eval_id)

    real_sleep = asyncio.sleep

    async def sleep(seconds):
        leases.kv.pop("husky:lease:rescore:ev2", None)     # the dead holder's lease lapses
        await real_sleep(0)

    monkeypatch.setattr(main, "_rescore_attempts", attempts)
    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    leases.kv["husky:lease:rescore:ev2"] = "dead-worker"
    asyncio.run(main._rescore("ev2"))
    assert calls == ["ev2"]


def test_an_analysis_another_worker_is_generating_is_not_started_twice(leases, monkeypatch):
    import main

    built = []

    async def build(conversation_id, user_id):
        built.append(conversation_id)

    monkeypatch.setattr(main, "_build_session_analysis", build)
    leases.kv["husky:lease:analysis:c1:u1"] = "another-worker"
    asyncio.run(main._generate_session_analysis("c1", "u1"))
    assert built == []
    del leases.kv["husky:lease:analysis:c1:u1"]
    asyncio.run(main._generate_session_analysis("c1", "u1"))
    assert built == ["c1"]


# ---------------------------------------------------------------------------
# Corpus: a restart must not fail a sibling's live ingest
# ---------------------------------------------------------------------------


async def _stuck_docs(n=2):
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          CorpusDocument, ReferenceCorpus, User)

    async with AsyncSessionLocal() as db:
        u = User(email=f"mwc_{uuid.uuid4().hex[:8]}@e.com", name="I", password_hash="x")
        db.add(u); await db.flush()
        room = Classroom(name="R", join_code=uuid.uuid4().hex[:8].upper(), instructor_user_id=u.id)
        ch = Challenge(title="C", description="d", category="c", difficulty="easy", total_sessions=1,
                       sessions_data=[{"title": "S1"}])
        db.add_all([room, ch]); await db.flush()
        cc = ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id)
        db.add(cc); await db.flush()
        corpus = ReferenceCorpus(classroom_challenge_id=cc.id, name="ref", created_by_user_id=u.id,
                                 status="building")
        db.add(corpus); await db.flush()
        docs = [CorpusDocument(corpus_id=corpus.id, filename=f"d{i}.txt", mime_type="text/plain",
                               data=b"x", status="indexing", uploaded_by_user_id=u.id)
                for i in range(n)]
        db.add_all(docs)
        await db.commit()
        return [d.id for d in docs]


async def _status(doc_id):
    from database import AsyncSessionLocal, CorpusDocument
    async with AsyncSessionLocal() as db:
        return (await db.get(CorpusDocument, doc_id)).status


def test_release_leaves_a_document_a_live_worker_is_indexing(app_ready, leases):
    import corpus

    live, abandoned = asyncio.run(_stuck_docs())
    leases.kv[f"husky:lease:corpus_doc:{live}"] = "sibling-worker"
    assert asyncio.run(corpus.release_stranded_claims()) == 1
    assert asyncio.run(_status(live)) == "indexing"
    assert asyncio.run(_status(abandoned)) == "failed"


def test_release_does_nothing_when_it_cannot_tell_who_is_alive(app_ready):
    import corpus

    doc, = asyncio.run(_stuck_docs(1))
    coordination.configure(client=BrokenRedis())
    try:
        assert asyncio.run(corpus.release_stranded_claims()) == 0
    finally:
        coordination.configure(None)
    assert asyncio.run(_status(doc)) == "indexing"


def test_release_without_redis_frees_every_stranded_document(app_ready, monkeypatch):
    import corpus

    monkeypatch.delenv("REDIS_URL", raising=False)
    coordination.configure(None)
    docs = asyncio.run(_stuck_docs())
    assert asyncio.run(corpus.release_stranded_claims()) >= 2
    assert [asyncio.run(_status(d)) for d in docs] == ["failed", "failed"]


def test_ingest_skips_a_document_whose_lease_another_worker_holds(app_ready, leases, monkeypatch):
    import corpus
    from database import AsyncSessionLocal, CorpusDocument

    async def setup():
        d1, d2 = await _stuck_docs()
        async with AsyncSessionLocal() as db:
            for d in (d1, d2):
                (await db.get(CorpusDocument, d)).status = "pending"
            cid = (await db.get(CorpusDocument, d1)).corpus_id
            await db.commit()
        return cid, d1, d2

    cid, d1, d2 = asyncio.run(setup())
    uploaded = []

    class _Files:
        async def create(self, file, purpose):
            uploaded.append(file[0])
            return type("F", (), {"id": f"file-{file[0]}"})()

    class _VSFiles:
        async def create_and_poll(self, vector_store_id, file_id):
            return None

    class _VS:
        files = _VSFiles()

        async def create(self, name):
            return type("S", (), {"id": "vs-1"})()

    class _Client:
        files = _Files()
        vector_stores = _VS()

    monkeypatch.setattr(corpus, "_openai_client", lambda: _Client())
    leases.kv[f"husky:lease:corpus_doc:{d1}"] = "sibling-worker"
    asyncio.run(corpus._ingest_corpus(cid))
    assert uploaded == ["d1.txt"]
    assert asyncio.run(_status(d1)) == "pending", "left to the worker holding it"
    assert asyncio.run(_status(d2)) == "ready"
    assert f"husky:lease:corpus_doc:{d2}" not in leases.kv


# ---------------------------------------------------------------------------
# Startup and rate limits
# ---------------------------------------------------------------------------


def test_the_startup_lock_is_a_no_op_on_sqlite():
    from database import startup_lock

    async def go():
        async with startup_lock():
            return "ran"

    assert asyncio.run(go()) == "ran"


def test_reset_rate_limit_keys_do_not_carry_the_raw_email(monkeypatch):
    import rate_limit

    monkeypatch.delenv("REDIS_URL", raising=False)

    class _Req:
        headers = {}
        client = type("C", (), {"host": "1.2.3.4"})()

    asyncio.run(rate_limit.clear_reset_rate_buckets())
    asyncio.run(rate_limit.check_reset_rate_limit(_Req(), "Student@Example.edu"))
    keys = list(rate_limit._reset_limiter._buckets)
    assert keys and not any("example.edu" in k.lower() for k in keys)


# ---------------------------------------------------------------------------
# Teammates arriving at the same moment
# ---------------------------------------------------------------------------


def test_teammates_joining_together_share_one_conversation(app_ready):
    """Both sockets get-or-create the session's shared conversation at once.
    Before, each could create one and the later commit won, splitting the team
    across two "shared" conversations (or the second insert failed outright)."""
    import main

    gid, _ = asyncio.run(_team())

    async def both():
        return await asyncio.gather(main._ensure_group_session(gid, 1),
                                    main._ensure_group_session(gid, 1))

    first, second = asyncio.run(both())
    assert first == second


def test_a_duplicate_private_coach_conversation_does_not_lock_the_student_out(app_ready):
    """Two private coach conversations for one student (left by an old race)
    used to make every later connect fail on scalar_one_or_none."""
    import main
    from database import AsyncSessionLocal, Conversation
    from datetime import datetime, timedelta

    gid, (u, _) = asyncio.run(_team())

    async def go():
        gsid, _conv, _ch = await main._ensure_group_session(gid, 1)
        async with AsyncSessionLocal() as db:
            older = Conversation(user_id=u, group_session_id=gsid, kind="coach_private",
                                 started_at=datetime.utcnow() - timedelta(minutes=1))
            newer = Conversation(user_id=u, group_session_id=gsid, kind="coach_private")
            db.add_all([older, newer])
            await db.commit()
            older_id = older.id
        return older_id, await main._ensure_coach_conversation(gsid, u)

    older_id, got = asyncio.run(go())
    assert got == older_id
