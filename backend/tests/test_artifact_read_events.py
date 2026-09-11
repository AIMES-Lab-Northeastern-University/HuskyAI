"""Artifact read/write event log semantics.

Covers the non-negotiables: one shared seq space, never sampled, idempotent on
retry, coach reads structurally separate from human reads, and shedding that
only ever touches heartbeats and records that it happened.
"""

import asyncio
import uuid

import pytest

import artifact_events as ae


async def _session():
    """A group session to hang events off. Returns (group_session_id, user_id)."""
    from database import (AsyncSessionLocal, Challenge, GroupChallenge,
                          GroupSession, User, init_db)

    await init_db()
    async with AsyncSessionLocal() as db:
        uid, cid, gid, sid = (str(uuid.uuid4()) for _ in range(4))
        db.add(User(id=uid, email=f"re_{uuid.uuid4().hex[:10]}@example.com",
                    name="reader", password_hash="x"))
        db.add(Challenge(id=cid, title=f"re {uuid.uuid4().hex[:6]}", description="d",
                         category="c", difficulty="Beginner", total_sessions=1,
                         sessions_data=[]))
        db.add(GroupChallenge(id=gid, challenge_id=cid, created_by=uid))
        db.add(GroupSession(id=sid, group_id=gid, challenge_id=cid, session_number=1))
        await db.commit()
    return sid, uid


def test_reads_and_writes_share_one_sequence_space():
    """The core research property: read/write order is answerable."""

    async def go():
        sid, uid = await _session()
        await ae.log_student_read(
            group_session_id=sid, user_id=uid, section_key="teammate",
            event_type=ae.EVENT_SECTION_OPEN, idempotency_key="r1", dwell_ms=3200)
        await ae.log_section_write(
            group_session_id=sid, user_id=uid, section_key="mine",
            idempotency_key="w1", version=1, content_len=12)
        await ae.log_student_read(
            group_session_id=sid, user_id=uid, section_key="teammate",
            event_type=ae.EVENT_SECTION_OPEN, idempotency_key="r2", dwell_ms=4000)

        events = await ae.session_events(sid)
        assert [e["seq"] for e in events] == [1, 2, 3], "seq must be monotonic"
        assert [e["event_type"] for e in events] == [
            ae.EVENT_SECTION_OPEN, ae.EVENT_SECTION_WRITE, ae.EVENT_SECTION_OPEN,
        ]
        # The question the whole system exists to answer:
        write_seq = next(e["seq"] for e in events if e["event_type"] == ae.EVENT_SECTION_WRITE)
        reads = [e["seq"] for e in events if e["event_type"] == ae.EVENT_SECTION_OPEN]
        assert any(r < write_seq for r in reads), "should see a read before the write"
        assert any(r > write_seq for r in reads), "should see a read after the write"

    asyncio.run(go())


def test_retry_with_the_same_key_does_not_duplicate_or_drop():
    async def go():
        sid, uid = await _session()
        key = f"read:{uid}:design:episode-1"
        first = await ae.log_student_read(
            group_session_id=sid, user_id=uid, section_key="design",
            event_type=ae.EVENT_SECTION_OPEN, idempotency_key=key, dwell_ms=3100)
        # Same episode replayed after a reconnect, several times.
        repeats = [
            await ae.log_student_read(
                group_session_id=sid, user_id=uid, section_key="design",
                event_type=ae.EVENT_SECTION_OPEN, idempotency_key=key, dwell_ms=3100)
            for _ in range(3)
        ]
        assert all(r["seq"] == first["seq"] for r in repeats)
        assert all(r["duplicate"] for r in repeats)
        events = await ae.session_events(sid)
        assert len(events) == 1, f"expected 1 stored event, got {len(events)}"

    asyncio.run(go())


def test_concurrent_appends_all_land_with_distinct_seqs():
    """Never sampled: 25 concurrent events must all be stored, none merged."""

    async def go():
        sid, uid = await _session()
        await asyncio.gather(*[
            ae.log_student_read(
                group_session_id=sid, user_id=uid, section_key="s",
                event_type=ae.EVENT_SECTION_OPEN,
                idempotency_key=f"k{i}", dwell_ms=3000 + i)
            for i in range(25)
        ])
        events = await ae.session_events(sid)
        seqs = [e["seq"] for e in events]
        assert len(events) == 25, f"events were lost: {len(events)}/25"
        assert len(set(seqs)) == 25, "duplicate seq numbers"
        assert sorted(seqs) == list(range(1, 26))

    asyncio.run(go())


def test_coach_reads_are_never_human_reads():
    async def go():
        sid, uid = await _session()
        await ae.log_coach_read(
            group_session_id=sid, section_key="design", idempotency_key="c1")
        coach = (await ae.session_events(sid))[0]
        assert coach["actor_kind"] == ae.ACTOR_COACH
        assert coach["actor_user_id"] is None, "a coach read must not carry a student"
        assert coach["event_type"] == ae.EVENT_SECTION_READ_BY_COACH

        # Filtering the way analysis would: human reads only.
        humans = [e for e in await ae.session_events(sid)
                  if e["actor_kind"] == ae.ACTOR_STUDENT
                  and e["event_type"] in ae.STUDENT_READ_TYPES]
        assert humans == [], "a coach read leaked into the human-read set"

    asyncio.run(go())


def test_a_coach_read_does_not_suppress_the_student_s_own_later_read():
    """The coach reading a section first must not make the student's real read
    stop counting -- they are independent events on the same timeline."""

    async def go():
        sid, uid = await _session()
        await ae.log_coach_read(
            group_session_id=sid, section_key="design", idempotency_key="c1")
        await ae.log_student_read(
            group_session_id=sid, user_id=uid, section_key="design",
            event_type=ae.EVENT_SECTION_OPEN, idempotency_key="r1", dwell_ms=3500)

        events = await ae.session_events(sid)
        assert len(events) == 2
        assert events[0]["actor_kind"] == ae.ACTOR_COACH
        assert events[1]["actor_kind"] == ae.ACTOR_STUDENT
        assert events[1]["actor_user_id"] == uid
        assert events[1]["seq"] > events[0]["seq"]

    asyncio.run(go())


def test_student_helper_refuses_a_coach_event_type():
    async def go():
        sid, uid = await _session()
        with pytest.raises(ae.EventCategoryError):
            await ae.log_student_read(
                group_session_id=sid, user_id=uid, section_key="d",
                event_type=ae.EVENT_SECTION_READ_BY_COACH, idempotency_key="x")
        with pytest.raises(ae.EventCategoryError):
            await ae.log_student_read(
                group_session_id=sid, user_id="", section_key="d",
                event_type=ae.EVENT_SECTION_OPEN, idempotency_key="y")

    asyncio.run(go())


def test_db_rejects_a_coach_event_carrying_a_student():
    """Second line of defence: even a direct insert cannot conflate them."""

    async def go():
        from sqlalchemy.exc import IntegrityError
        from database import ArtifactEvent, AsyncSessionLocal

        sid, uid = await _session()
        async with AsyncSessionLocal() as db:
            db.add(ArtifactEvent(
                group_session_id=sid, seq=1,
                event_type=ae.EVENT_SECTION_READ_BY_COACH,
                actor_kind=ae.ACTOR_COACH,
                actor_user_id=uid,          # <- forbidden
                section_key="design", idempotency_key="bad",
            ))
            with pytest.raises(IntegrityError):
                await db.commit()

    asyncio.run(go())


def test_shedding_only_drops_heartbeats_and_records_that_it_happened():
    async def go():
        sid, uid = await _session()
        original = ae.HEARTBEAT_SOFT_CAP
        ae.HEARTBEAT_SOFT_CAP = 2
        try:
            assert await ae.record_heartbeat(
                group_session_id=sid, user_id=uid, section_key="d", visible_ms=500)
            assert await ae.record_heartbeat(
                group_session_id=sid, user_id=uid, section_key="d", visible_ms=500)
            # Over the cap now.
            assert await ae.record_heartbeat(
                group_session_id=sid, user_id=uid, section_key="d", visible_ms=500) is False

            events = await ae.session_events(sid)
            shed = [e for e in events if e["event_type"] == ae.EVENT_HEARTBEAT_SHED]
            assert len(shed) == 1, "shedding was not recorded in the permanent log"

            # A real read still gets through untouched while shedding is active.
            await ae.log_student_read(
                group_session_id=sid, user_id=uid, section_key="d",
                event_type=ae.EVENT_SECTION_OPEN, idempotency_key="r1", dwell_ms=3000)
            reads = [e for e in await ae.session_events(sid)
                     if e["event_type"] == ae.EVENT_SECTION_OPEN]
            assert len(reads) == 1, "a qualifying read was shed -- never allowed"
        finally:
            ae.HEARTBEAT_SOFT_CAP = original

    asyncio.run(go())
