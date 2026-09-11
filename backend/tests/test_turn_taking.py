"""Turn-taking metrics.

The arithmetic is checked against hand-computed values on known sequences, not
just exercised -- an alternation rate that runs without error but divides by the
wrong denominator is exactly the kind of defect that survives code review and
then quietly becomes a published number.
"""

import asyncio
import uuid

import pytest

import artifact_events as ae
from turn_taking import alternation_rate, read_before_write, share_pct


# ---------------------------------------------------------------------------
# Alternation: the maths
# ---------------------------------------------------------------------------

def test_alternation_on_a_hand_computed_sequence():
    # A A B A B B -> adjacent pairs: AA AB BA AB BB -> 3 switches of 5 pairs.
    assert alternation_rate(["A", "A", "B", "A", "B", "B"]) == 0.6


def test_alternation_endpoints():
    assert alternation_rate(["A", "A", "A", "A"]) == 0.0      # one monologue
    assert alternation_rate(["A", "B", "A", "B"]) == 1.0      # strict ping-pong
    assert alternation_rate(["A", "B"]) == 1.0                # one pair, switched
    assert alternation_rate(["A", "A"]) == 0.0                # one pair, held


def test_alternation_is_undefined_below_two_turns():
    """None, not 0.0: with one turn there is no pair, and 0 would read as
    'somebody monologued', which is a different claim from 'no data'."""
    assert alternation_rate([]) is None
    assert alternation_rate(["A"]) is None


def test_alternation_counts_pairs_not_turns():
    """Guards the denominator: 3 turns have 2 adjacent pairs, not 3."""
    assert alternation_rate(["A", "B", "B"]) == 0.5
    assert alternation_rate(["A", "B", "C"]) == 1.0


def test_alternation_handles_more_than_two_actors():
    # A B B C -> AB BB BC -> 2 of 3.
    assert round(alternation_rate(["A", "B", "B", "C"]), 4) == round(2 / 3, 4)


def test_share_pct():
    assert share_pct(1, 4) == 25.0
    assert share_pct(0, 4) == 0.0
    assert share_pct(3, 0) == 0.0      # no turns: 0, not a division error


# ---------------------------------------------------------------------------
# Read-before-write: the definitions
# ---------------------------------------------------------------------------

def _read(seq, uid, section, kind=ae.ACTOR_STUDENT):
    return {"seq": seq, "event_type": ae.EVENT_SECTION_EXPAND, "actor_kind": kind,
            "actor_user_id": uid, "section_key": section}


def _write(seq, uid, section):
    return {"seq": seq, "event_type": ae.EVENT_SECTION_WRITE,
            "actor_kind": ae.ACTOR_STUDENT, "actor_user_id": uid,
            "section_key": section}


def _coach_read(seq, section):
    return {"seq": seq, "event_type": ae.EVENT_SECTION_READ_BY_COACH,
            "actor_kind": ae.ACTOR_COACH, "actor_user_id": None,
            "section_key": section}


def test_reading_a_teammates_section_first_counts_for_both_variants():
    out = read_before_write([
        _read(1, "u1", "approach"),
        _write(2, "u1", "problem"),
    ])
    assert out["writes"] == 1
    assert out["other_section"]["ratio"] == 1.0
    assert out["any_section"]["ratio"] == 1.0


def test_rereading_only_your_own_section_counts_for_the_loose_variant_only():
    """The distinction the headline metric exists to make."""
    out = read_before_write([
        _read(1, "u1", "problem"),
        _write(2, "u1", "problem"),
    ])
    assert out["other_section"]["ratio"] == 0.0, (
        "re-reading the section you then edit is not the collaboration "
        "behaviour being measured"
    )
    assert out["any_section"]["ratio"] == 1.0


def test_a_write_with_no_prior_read_counts_for_neither():
    out = read_before_write([_write(1, "u1", "problem")])
    assert out["other_section"]["ratio"] == 0.0
    assert out["any_section"]["ratio"] == 0.0


def test_a_read_after_the_write_does_not_count():
    """Seq order is the whole point -- 'before' must mean before."""
    out = read_before_write([
        _write(1, "u1", "problem"),
        _read(2, "u1", "approach"),
    ])
    assert out["other_section"]["ratio"] == 0.0
    assert out["any_section"]["ratio"] == 0.0


def test_another_students_read_does_not_credit_the_writer():
    out = read_before_write([
        _read(1, "u2", "approach"),
        _write(2, "u1", "problem"),
    ])
    assert out["other_section"]["ratio"] == 0.0


def test_a_coach_pull_is_not_a_read():
    """If this breaks, the coach's reading is attributed to the student and the
    ratio drifts toward 1.0."""
    out = read_before_write([
        _coach_read(1, "approach"),
        _write(2, "u1", "problem"),
    ])
    assert out["other_section"]["ratio"] == 0.0, (
        "a coach pull was counted as the student having read the section"
    )
    assert out["any_section"]["ratio"] == 0.0


def test_a_mixed_session_yields_the_right_ratio():
    """Three writes, two of them preceded by a read of another section."""
    out = read_before_write([
        _read(1, "u1", "approach"),
        _write(2, "u1", "problem"),      # qualifies (read approach first)
        _write(3, "u2", "testing"),      # u2 has read nothing
        _read(4, "u2", "problem"),
        _write(5, "u2", "testing"),      # qualifies (read problem first)
    ])
    assert out["writes"] == 3
    assert out["other_section"]["writes_preceded_by_read"] == 2
    assert out["other_section"]["ratio"] == round(2 / 3, 4)
    flags = [w["read_other_section_first"] for w in out["per_write"]]
    assert flags == [True, False, True]


def test_no_writes_means_the_ratio_is_undefined():
    out = read_before_write([_read(1, "u1", "problem")])
    assert out["writes"] == 0
    assert out["other_section"]["ratio"] is None
    assert out["any_section"]["ratio"] is None


def test_events_are_ordered_by_seq_not_by_input_order():
    """The caller must not be able to change the answer by shuffling."""
    events = [
        _write(2, "u1", "problem"),
        _read(1, "u1", "approach"),
    ]
    assert read_before_write(events)["other_section"]["ratio"] == 1.0


# ---------------------------------------------------------------------------
# The session-level assembly and the endpoint
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def asgi_app():
    from challenges import seed_challenges
    from database import init_db
    from main import app

    async def setup():
        await init_db()
        await seed_challenges()

    asyncio.run(setup())
    return app


async def _admin_headers(client):
    from database import AsyncSessionLocal, User

    email = f"tt_{uuid.uuid4().hex[:10]}@example.com"
    reg = await client.post("/auth/register",
                            json={"email": email, "name": "Res", "password": "testpassword123"})
    assert reg.status_code == 200, reg.text
    uid = reg.json()["user"]["user_id"] if "user" in reg.json() else None
    async with AsyncSessionLocal() as db:
        import sqlalchemy as sa
        u = (await db.execute(sa.select(User).where(User.email == email))).scalar_one()
        u.is_platform_admin = True
        uid = u.id
        await db.commit()
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}, uid


async def _session_with_activity():
    """A group session with two students, chat turns and artifact events."""
    from database import (AsyncSessionLocal, Challenge, Conversation,
                          GroupChallenge, GroupMember, GroupSession, Message, User)

    async with AsyncSessionLocal() as db:
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
        for uid, nm in ((u1, "Ada"), (u2, "Grace")):
            db.add(User(id=uid, email=f"tt_{uuid.uuid4().hex[:10]}@example.com",
                        name=nm, password_hash="x"))
        cid = str(uuid.uuid4())
        db.add(Challenge(id=cid, title=f"tt {uuid.uuid4().hex[:6]}", description="d",
                         category="c", difficulty="Beginner", total_sessions=1,
                         sessions_data=[]))
        gid = str(uuid.uuid4())
        db.add(GroupChallenge(id=gid, challenge_id=cid, created_by=u1, status="active"))
        db.add(GroupMember(group_id=gid, user_id=u1))
        db.add(GroupMember(group_id=gid, user_id=u2))
        sid = str(uuid.uuid4())
        conv = str(uuid.uuid4())
        db.add(Conversation(id=conv, user_id=u1, group_session_id=sid,
                            kind="group_shared"))
        db.add(GroupSession(id=sid, group_id=gid, challenge_id=cid,
                            session_number=1, conversation_id=conv, arm="control"))
        # A A B A -> pairs AA AB BA -> 2 of 3 switch.
        for i, author in enumerate((u1, u1, u2, u1)):
            db.add(Message(id=str(uuid.uuid4()), conversation_id=conv, role="user",
                           content=f"turn {i}", sender_user_id=author))
        await db.commit()

    # u1 reads a section then writes another (qualifies); u2 writes blind.
    await ae.log_student_read(group_session_id=sid, user_id=u1,
                              section_key="approach",
                              event_type=ae.EVENT_SECTION_EXPAND,
                              idempotency_key="r1", dwell_ms=3500)
    await ae.log_section_write(group_session_id=sid, user_id=u1,
                               section_key="problem", idempotency_key="w1",
                               version=1, content_len=10)
    await ae.log_section_write(group_session_id=sid, user_id=u2,
                               section_key="testing", idempotency_key="w2",
                               version=1, content_len=10)
    return sid, u1, u2


def test_session_metrics_match_the_hand_computation():
    async def go():
        from database import AsyncSessionLocal, GroupSession, init_db
        from turn_taking import session_turn_taking

        await init_db()
        sid, u1, u2 = await _session_with_activity()

        async with AsyncSessionLocal() as db:
            gs = await db.get(GroupSession, sid)
            out = await session_turn_taking(db, gs)

        assert out["conversation_turns"] == 4
        assert out["turns_without_author"] == 0
        assert out["arm"] == "control"

        # A A B A -> 2 switches over 3 pairs.
        assert out["alternation"]["conversation"] == round(2 / 3, 4)
        # Writes: u1 then u2 -> one pair, switched.
        assert out["alternation"]["artifact_writes"] == 1.0
        assert out["alternation"]["artifact_write_count"] == 2

        shares = {p["user_id"]: p["share_pct"] for p in out["contribution"]}
        assert shares[u1] == 75.0
        assert shares[u2] == 25.0

        rbw = out["read_before_write"]
        assert rbw["writes"] == 2
        assert rbw["other_section"]["writes_preceded_by_read"] == 1
        assert rbw["other_section"]["ratio"] == 0.5

    asyncio.run(go())


def test_contribution_share_agrees_with_team_analytics():
    """The two surfaces share one turn definition; this pins that they agree."""
    async def go():
        import groups
        from database import (AsyncSessionLocal, GroupChallenge, GroupSession,
                              init_db)
        from turn_taking import session_turn_taking

        await init_db()
        sid, u1, _u2 = await _session_with_activity()

        async with AsyncSessionLocal() as db:
            gs = await db.get(GroupSession, sid)
            tt = await session_turn_taking(db, gs)
            team = await db.get(GroupChallenge, gs.group_id)
            ta = await groups._team_analytics(db, team)

        tt_share = {p["user_id"]: p["share_pct"] for p in tt["contribution"]}
        ta_share = {p["user_id"]: p["share_pct"] for p in ta["members"] if p["turns"]}
        assert tt_share == ta_share

    asyncio.run(go())


def test_a_session_with_no_activity_reports_undefined_not_zero():
    async def go():
        from database import (AsyncSessionLocal, Challenge, GroupChallenge,
                             GroupSession, User, init_db)
        from turn_taking import session_turn_taking

        await init_db()
        async with AsyncSessionLocal() as db:
            uid, cid, gid, sid = (str(uuid.uuid4()) for _ in range(4))
            db.add(User(id=uid, email=f"tt_{uuid.uuid4().hex[:10]}@example.com",
                        name="n", password_hash="x"))
            db.add(Challenge(id=cid, title=f"tt {uuid.uuid4().hex[:6]}", description="d",
                             category="c", difficulty="Beginner", total_sessions=1,
                             sessions_data=[]))
            db.add(GroupChallenge(id=gid, challenge_id=cid, created_by=uid))
            db.add(GroupSession(id=sid, group_id=gid, challenge_id=cid,
                                session_number=1))
            await db.commit()
            gs = await db.get(GroupSession, sid)
            out = await session_turn_taking(db, gs)

        assert out["conversation_turns"] == 0
        assert out["alternation"]["conversation"] is None
        assert out["alternation"]["artifact_writes"] is None
        assert out["read_before_write"]["other_section"]["ratio"] is None

    asyncio.run(go())


@pytest.mark.asyncio
async def test_endpoint_returns_404_for_an_unknown_session(asgi_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, _uid = await _admin_headers(client)
        r = await client.get(f"/research/sessions/{uuid.uuid4()}/turn-taking", headers=headers)
        assert r.status_code == 404, r.text
        assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_endpoint_requires_platform_admin(asgi_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        email = f"tt_plain_{uuid.uuid4().hex[:8]}@example.com"
        reg = await client.post("/auth/register",
                                json={"email": email, "name": "Plain",
                                      "password": "testpassword123"})
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        r = await client.get(f"/research/sessions/{uuid.uuid4()}/turn-taking", headers=headers)
        assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_endpoint_requires_auth(asgi_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.get(f"/research/sessions/{uuid.uuid4()}/turn-taking")
        assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_endpoint_returns_the_three_metrics(asgi_app):
    from httpx import ASGITransport, AsyncClient

    sid, u1, u2 = await _session_with_activity()
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, _uid = await _admin_headers(client)
        r = await client.get(f"/research/sessions/{sid}/turn-taking", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()

    assert body["group_session_id"] == sid
    assert {p["user_id"] for p in body["contribution"]} == {u1, u2}
    assert body["alternation"]["conversation"] == round(2 / 3, 4)
    assert body["read_before_write"]["other_section"]["ratio"] == 0.5
    assert body["read_before_write"]["any_section"]["ratio"] == 0.5


def test_a_real_coach_pull_does_not_credit_the_student_who_triggered_it():
    """End to end, through session_turn_taking, with a real logged coach read.

    The unit-level coach test above uses synthetic dicts with no meta, so it
    cannot catch a version of this code that reaches into meta.requested_by.
    This one can: the coach row here genuinely carries the student's id as
    provenance, and the ratio must still be 0.

    Two independent things keep this correct, and it is worth knowing which is
    load-bearing: the coach row's actor_user_id is NULL (enforced by the DB
    CHECK constraint), and read_before_write filters on actor_kind. The first is
    what actually holds; the second is defence in depth.
    """
    async def go():
        from database import (AsyncSessionLocal, Challenge, GroupChallenge,
                              GroupSession, User, init_db)
        from turn_taking import session_turn_taking

        await init_db()
        async with AsyncSessionLocal() as db:
            uid, cid, gid, sid = (str(uuid.uuid4()) for _ in range(4))
            db.add(User(id=uid, email=f"tt_{uuid.uuid4().hex[:10]}@example.com",
                        name="Ada", password_hash="x"))
            db.add(Challenge(id=cid, title=f"tt {uuid.uuid4().hex[:6]}", description="d",
                             category="c", difficulty="Beginner", total_sessions=1,
                             sessions_data=[]))
            db.add(GroupChallenge(id=gid, challenge_id=cid, created_by=uid))
            db.add(GroupSession(id=sid, group_id=gid, challenge_id=cid,
                                session_number=1))
            await db.commit()

        # The coach pulls a section on this student's behalf...
        stored = await ae.log_coach_read(
            group_session_id=sid, section_key="approach",
            idempotency_key="coach:conv:1:approach",
            meta={"requested_by": uid, "turn": 1, "chars": 12, "truncated": False},
        )
        assert stored["actor_user_id"] is None
        assert stored["meta"]["requested_by"] == uid

        # ...and then the student writes a different section, having read nothing.
        await ae.log_section_write(group_session_id=sid, user_id=uid,
                                   section_key="problem", idempotency_key="w1",
                                   version=1, content_len=5)

        async with AsyncSessionLocal() as db:
            gs = await db.get(GroupSession, sid)
            out = await session_turn_taking(db, gs)

        rbw = out["read_before_write"]
        assert rbw["writes"] == 1
        assert rbw["other_section"]["ratio"] == 0.0, (
            "the coach's pull was credited to the student who triggered it -- "
            "read-before-write is now measuring the coach, not the student"
        )
        assert rbw["any_section"]["ratio"] == 0.0

    asyncio.run(go())
