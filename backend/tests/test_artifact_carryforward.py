"""Session-to-session artifact carry-forward.

Each session owns an independent artifact; when a team starts a new session, the
previous session's final content is copied in once as the starting point.
"""

import asyncio
import uuid

import pytest


async def _mk_team(db, n_sessions: int = 3):
    """A group with n_sessions GroupSessions. Returns (group_id, [session ids])."""
    from database import (Challenge, GroupChallenge, GroupSession, User)

    uid = str(uuid.uuid4())
    db.add(User(id=uid, email=f"cf_{uuid.uuid4().hex[:10]}@example.com",
                name="cf", password_hash="x"))
    cid = str(uuid.uuid4())
    db.add(Challenge(id=cid, title=f"cf {uuid.uuid4().hex[:6]}", description="d",
                     category="c", difficulty="Beginner", total_sessions=n_sessions,
                     sessions_data=[]))
    gid = str(uuid.uuid4())
    db.add(GroupChallenge(id=gid, challenge_id=cid, created_by=uid, status="active"))
    sids = []
    for n in range(1, n_sessions + 1):
        sid = str(uuid.uuid4())
        db.add(GroupSession(id=sid, group_id=gid, challenge_id=cid, session_number=n))
        sids.append(sid)
    await db.flush()
    return gid, sids


async def _write(db, group_session_id, section_key, content, version=1):
    from database import GroupArtifactSection
    db.add(GroupArtifactSection(
        group_session_id=group_session_id, section_key=section_key,
        content=content, version=version,
    ))
    await db.flush()


def test_content_carries_into_the_next_session():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            gid, sids = await _mk_team(db)
            await _write(db, sids[0], "design", "session one design")
            await _write(db, sids[0], "testing", "session one testing")
            await db.commit()

        copied = await main._seed_artifact_from_previous_session(
            gid, sids[1], 2, {"design", "testing"}
        )
        assert copied == 2

        saved = await main._load_artifact_sections(sids[1])
        assert saved["design"]["content"] == "session one design"
        assert saved["testing"]["content"] == "session one testing"
        # Carried, but not yet edited in this session.
        assert saved["design"]["version"] == 0
        assert saved["design"]["carried_from_session_number"] == 1

    asyncio.run(go())


def test_is_idempotent_and_never_overwrites_this_session_s_work():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            gid, sids = await _mk_team(db)
            await _write(db, sids[0], "design", "old text")
            await db.commit()

        assert await main._seed_artifact_from_previous_session(
            gid, sids[1], 2, {"design"}) == 1

        # The team edits it in session 2.
        async with AsyncSessionLocal() as db:
            from database import GroupArtifactSection
            from sqlalchemy import select
            row = (await db.execute(select(GroupArtifactSection).where(
                GroupArtifactSection.group_session_id == sids[1]))).scalar_one()
            row.content = "their own work"
            row.version = 5
            await db.commit()

        # Re-running (e.g. another teammate connects) must not clobber it.
        assert await main._seed_artifact_from_previous_session(
            gid, sids[1], 2, {"design"}) == 0
        saved = await main._load_artifact_sections(sids[1])
        assert saved["design"]["content"] == "their own work"
        assert saved["design"]["version"] == 5

    asyncio.run(go())


def test_skips_an_empty_session_and_uses_the_last_one_with_content():
    """Session 2 left blank -> session 3 should still start from session 1."""

    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            gid, sids = await _mk_team(db)
            await _write(db, sids[0], "design", "real work from session 1")
            await _write(db, sids[1], "design", "   ")  # whitespace only
            await db.commit()

        copied = await main._seed_artifact_from_previous_session(
            gid, sids[2], 3, {"design"})
        assert copied == 1
        saved = await main._load_artifact_sections(sids[2])
        assert saved["design"]["content"] == "real work from session 1"
        assert saved["design"]["carried_from_session_number"] == 1

    asyncio.run(go())


def test_prefers_the_most_recent_session_with_content():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            gid, sids = await _mk_team(db)
            await _write(db, sids[0], "design", "from session 1")
            await _write(db, sids[1], "design", "from session 2")
            await db.commit()

        await main._seed_artifact_from_previous_session(gid, sids[2], 3, {"design"})
        saved = await main._load_artifact_sections(sids[2])
        assert saved["design"]["content"] == "from session 2"
        assert saved["design"]["carried_from_session_number"] == 2

    asyncio.run(go())


def test_session_one_has_nothing_to_carry():
    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            gid, sids = await _mk_team(db)
            await db.commit()
        assert await main._seed_artifact_from_previous_session(
            gid, sids[0], 1, {"design"}) == 0

    asyncio.run(go())


def test_only_sections_that_still_exist_are_carried():
    """A subproblem dropped from the challenge must not drag text forward."""

    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            gid, sids = await _mk_team(db)
            await _write(db, sids[0], "design", "kept")
            await _write(db, sids[0], "retired_section", "should not appear")
            await db.commit()

        copied = await main._seed_artifact_from_previous_session(
            gid, sids[1], 2, {"design"})  # 'retired_section' no longer defined
        assert copied == 1
        saved = await main._load_artifact_sections(sids[1])
        assert set(saved) == {"design"}

    asyncio.run(go())


def test_concurrent_seeding_does_not_duplicate():
    """Two teammates connecting at once must not each insert a copy."""

    async def go():
        import main
        from database import AsyncSessionLocal, GroupArtifactSection, init_db
        from sqlalchemy import func, select

        await init_db()
        async with AsyncSessionLocal() as db:
            gid, sids = await _mk_team(db)
            await _write(db, sids[0], "design", "shared start")
            await _write(db, sids[0], "testing", "shared start 2")
            await db.commit()

        await asyncio.gather(*[
            main._seed_artifact_from_previous_session(
                gid, sids[1], 2, {"design", "testing"})
            for _ in range(4)
        ])

        async with AsyncSessionLocal() as db:
            total = await db.scalar(
                select(func.count()).select_from(GroupArtifactSection).where(
                    GroupArtifactSection.group_session_id == sids[1]))
        assert total == 2, f"expected 2 rows, got {total}"

    asyncio.run(go())
