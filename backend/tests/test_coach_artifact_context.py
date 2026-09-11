"""The coach reading the team's shared artifact (/ws/coach only).

Two things are being pinned here:

1. What the coach is GIVEN -- the current content of every written section, with
   a character budget, truncation and omission all recorded rather than silent.
2. What that produces in the permanent log -- coach reads that are structurally
   incapable of being counted as human reads. If this second property ever
   breaks, read-before-write inflates toward 1.0 and the study's headline
   result is quietly invalid, which is why it gets its own tests rather than
   being taken on trust from the CHECK constraint.
"""

import asyncio
import uuid

import pytest

import artifact_events as ae


def _sessions_data(sections):
    """A challenge sessions_data blob declaring these sections for session 1."""
    return [{
        "title": "S1", "goal": "g", "brief": "b",
        "seed_question": "q", "system_prompt_extra": "e",
        "sections": sections,
    }]


async def _mk_session(db, sections):
    """A group session whose challenge declares `sections`.

    Returns (group_session_id, user_id, session_data).
    """
    from database import Challenge, GroupChallenge, GroupSession, User

    uid, cid, gid, sid = (str(uuid.uuid4()) for _ in range(4))
    db.add(User(id=uid, email=f"cac_{uuid.uuid4().hex[:10]}@example.com",
                name="reader", password_hash="x"))
    sd = _sessions_data(sections)
    db.add(Challenge(id=cid, title=f"cac {uuid.uuid4().hex[:6]}", description="d",
                     category="c", difficulty="Beginner", total_sessions=1,
                     sessions_data=sd))
    db.add(GroupChallenge(id=gid, challenge_id=cid, created_by=uid))
    db.add(GroupSession(id=sid, group_id=gid, challenge_id=cid, session_number=1))
    await db.flush()
    return sid, uid, sd[0]


async def _write(db, group_session_id, section_key, content, version=1):
    from database import GroupArtifactSection
    db.add(GroupArtifactSection(
        group_session_id=group_session_id, section_key=section_key,
        content=content, version=version,
    ))
    await db.flush()


SECTIONS = [
    {"key": "problem", "title": "Problem statement", "prompt": "p"},
    {"key": "approach", "title": "Approach", "prompt": "p"},
]


# --------------------------------------------------------------------------
# What the coach is given
# --------------------------------------------------------------------------

def test_no_sections_declared_means_no_artifact_context():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            sid, _uid, sd = await _mk_session(db, [])
            await db.commit()

        block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        assert block == ""
        assert manifest == []

    asyncio.run(go())


def test_declared_but_empty_sections_are_not_sent():
    """An empty section tells the coach nothing and must not spend budget."""
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            sid, _uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "")
            await _write(db, sid, "approach", "   ")
            await db.commit()

        block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        assert block == ""
        assert manifest == []

    asyncio.run(go())


def test_written_sections_reach_the_coach_with_title_and_key():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            sid, _uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "PROBLEM-BODY")
            await db.commit()

        block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        assert "PROBLEM-BODY" in block
        assert "Problem statement" in block
        assert "problem" in block
        # The unwritten one is absent entirely, not sent as an empty heading.
        assert "Approach" not in block
        assert [m["section_key"] for m in manifest] == ["problem"]
        assert manifest[0]["truncated"] is False
        assert manifest[0]["chars"] == len("PROBLEM-BODY")

    asyncio.run(go())


def test_oversized_section_is_truncated_and_says_so():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        budget = main._COACH_ARTIFACT_CHAR_BUDGET
        async with AsyncSessionLocal() as db:
            sid, _uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "Z" * (budget + 5000))
            await db.commit()

        block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        assert manifest[0]["truncated"] is True
        assert manifest[0]["chars"] == budget
        # Truncation is stated in the prompt, so the model does not treat a
        # severed sentence as the team's finished text.
        assert "truncated" in block
        # And the budget is actually respected.
        # "Z" rather than a lowercase filler: the surrounding prose and the
        # truncation marker contain plenty of common letters.
        assert block.count("Z") == budget

    asyncio.run(go())


def test_budget_exhaustion_omits_later_sections_and_records_which():
    """Silent omission is the failure mode being prevented here."""
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        budget = main._COACH_ARTIFACT_CHAR_BUDGET
        async with AsyncSessionLocal() as db:
            sid, _uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "Z" * budget)   # eats all of it
            await _write(db, sid, "approach", "APPROACH-BODY")
            await db.commit()

        block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        sent = [m["section_key"] for m in manifest]
        assert sent == ["problem"]
        assert "APPROACH-BODY" not in block
        # The omission is recorded against what WAS sent, so a single event row
        # is enough to see that the coach's view was incomplete.
        assert manifest[0]["budget_omitted"] == ["approach"]
        assert "approach" in block  # named in the omission notice

    asyncio.run(go())


# --------------------------------------------------------------------------
# What lands in the permanent log
# --------------------------------------------------------------------------

def test_coach_reads_land_with_coach_actor_and_no_student():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            sid, uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "PROBLEM-BODY")
            await db.commit()

        _block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        await main._log_coach_artifact_reads(
            group_session_id=sid, conversation_id="conv-1",
            user_id=uid, turn=1, manifest=manifest,
        )

        events = await ae.session_events(sid)
        assert len(events) == 1
        ev = events[0]
        assert ev["event_type"] == ae.EVENT_SECTION_READ_BY_COACH
        assert ev["actor_kind"] == ae.ACTOR_COACH
        assert ev["actor_user_id"] is None, "a coach read must not carry a student"
        assert ev["section_key"] == "problem"
        # Provenance is in meta, where it cannot be mistaken for attribution.
        assert ev["meta"]["requested_by"] == uid
        assert ev["meta"]["turn"] == 1
        assert ev["meta"]["chars"] == len("PROBLEM-BODY")
        assert ev["meta"]["truncated"] is False

    asyncio.run(go())


def test_a_coach_pull_is_not_a_student_read():
    """The double-count trap, pinned.

    meta.requested_by names the student whose turn triggered the pull. Any
    "student reads" query must filter on actor_kind, and this proves such a
    filter excludes coach pulls even though the student's id is present in the
    row. If this breaks, read-before-write inflates toward 1.0.
    """
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            sid, uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "PROBLEM-BODY")
            await db.commit()

        _block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        await main._log_coach_artifact_reads(
            group_session_id=sid, conversation_id="conv-1",
            user_id=uid, turn=1, manifest=manifest,
        )

        events = await ae.session_events(sid)
        student_reads = [
            e for e in events
            if e["actor_kind"] == ae.ACTOR_STUDENT
            and e["event_type"] in ae.STUDENT_READ_TYPES
        ]
        assert student_reads == [], (
            "a coach pull was counted as a human read -- read-before-write is "
            "now measuring the coach's behaviour, not the student's"
        )
        # The student's id IS in the row; only actor_kind separates them.
        assert events[0]["meta"]["requested_by"] == uid

    asyncio.run(go())


def test_the_same_turn_logged_twice_does_not_duplicate():
    """A retried turn must collapse, while a genuine next turn still logs."""
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            sid, uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "PROBLEM-BODY")
            await db.commit()

        _block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        for _ in range(3):
            await main._log_coach_artifact_reads(
                group_session_id=sid, conversation_id="conv-1",
                user_id=uid, turn=1, manifest=manifest,
            )
        assert len(await ae.session_events(sid)) == 1

        await main._log_coach_artifact_reads(
            group_session_id=sid, conversation_id="conv-1",
            user_id=uid, turn=2, manifest=manifest,
        )
        events = await ae.session_events(sid)
        assert len(events) == 2
        assert [e["meta"]["turn"] for e in events] == [1, 2]
        # Same seq space as human reads and writes.
        assert [e["seq"] for e in events] == [1, 2]

    asyncio.run(go())


def test_coach_reads_share_the_sequence_space_with_student_events():
    """Ordering across actor kinds is what makes read-before-write answerable."""
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            sid, uid, sd = await _mk_session(db, SECTIONS)
            await _write(db, sid, "problem", "PROBLEM-BODY")
            await db.commit()

        await ae.log_student_read(
            group_session_id=sid, user_id=uid, section_key="problem",
            event_type=ae.EVENT_SECTION_EXPAND, idempotency_key="s1",
            dwell_ms=3200,
        )
        _block, manifest = await main._build_coach_artifact_context(
            group_session_id=sid, session_data=sd
        )
        await main._log_coach_artifact_reads(
            group_session_id=sid, conversation_id="conv-1",
            user_id=uid, turn=1, manifest=manifest,
        )
        await ae.log_section_write(
            group_session_id=sid, user_id=uid, section_key="problem",
            idempotency_key="w1", version=2, content_len=12,
        )

        events = await ae.session_events(sid)
        assert [e["seq"] for e in events] == [1, 2, 3]
        assert [e["actor_kind"] for e in events] == [
            ae.ACTOR_STUDENT, ae.ACTOR_COACH, ae.ACTOR_STUDENT,
        ]

    asyncio.run(go())
