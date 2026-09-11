"""Startup analysis sweep must not re-queue the same stuck session on every worker.

The sweep runs in every worker's lifespan. Before it claimed rows, N workers each
found the same `status: "pending"` analyses and each spawned a generator, so a
multi-worker boot paid for N duplicate LLM runs per stuck session.
"""

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest


def _mk_session(db, *, pending_at: datetime | None, status: str = "pending"):
    """Insert a UserChallengeSession carrying the given analysis blob."""
    from database import Challenge, Conversation, User, UserChallengeSession

    uid = str(uuid.uuid4())
    db.add(User(id=uid, email=f"sw_{uuid.uuid4().hex[:10]}@example.com",
                name="sweep", password_hash="x"))
    cid = str(uuid.uuid4())
    ch = Challenge(id=cid, title=f"sweep {uuid.uuid4().hex[:6]}", description="d",
                   category="c", difficulty="Beginner", total_sessions=1, sessions_data=[])
    db.add(ch)
    conv_id = str(uuid.uuid4())
    db.add(Conversation(id=conv_id, user_id=uid))
    blob = {"status": status}
    if pending_at is not None:
        blob["pending_at"] = pending_at.isoformat()
    db.add(UserChallengeSession(
        user_id=uid, challenge_id=cid, session_number=1,
        conversation_id=conv_id, session_analysis=blob,
    ))
    return conv_id


def test_sweep_skips_a_session_a_sibling_worker_just_claimed(monkeypatch):
    """Worker B booting seconds after worker A must not re-spawn A's work."""

    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            # Claimed 5s ago by a "sibling worker" -> inside the grace window.
            fresh = _mk_session(db, pending_at=datetime.utcnow() - timedelta(seconds=5))
            # Orphaned long ago -> genuinely stuck, must be re-queued.
            stale = _mk_session(db, pending_at=datetime.utcnow() - timedelta(hours=2))
            # Already finished -> never touched.
            done = _mk_session(db, pending_at=datetime.utcnow() - timedelta(hours=2),
                               status="ready")
            await db.commit()

        spawned: list[str] = []
        monkeypatch.setattr(main, "_spawn_analysis",
                            lambda conv_id, user_id: spawned.append(conv_id))

        await main._resweep_stuck_analyses()

        assert stale in spawned, "a genuinely orphaned analysis must be re-queued"
        assert fresh not in spawned, "must not re-queue what another worker just claimed"
        assert done not in spawned, "must not re-run a completed analysis"

    asyncio.run(go())


def test_two_workers_sweeping_together_spawn_each_session_once(monkeypatch):
    """The actual bug: two sweeps in a row must not double-spawn."""

    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            stuck = _mk_session(db, pending_at=datetime.utcnow() - timedelta(hours=2))
            await db.commit()

        spawned: list[str] = []
        monkeypatch.setattr(main, "_spawn_analysis",
                            lambda conv_id, user_id: spawned.append(conv_id))

        # Worker A boots and claims it; worker B boots moments later.
        await main._resweep_stuck_analyses()
        await main._resweep_stuck_analyses()

        assert spawned.count(stuck) == 1, (
            f"expected exactly 1 spawn, got {spawned.count(stuck)} "
            "-- every worker is re-queueing the same session"
        )

    asyncio.run(go())


def test_legacy_pending_without_timestamp_is_still_recovered(monkeypatch):
    """Rows predating pending_at must not be skipped forever."""

    async def go():
        import main
        from database import AsyncSessionLocal, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            legacy = _mk_session(db, pending_at=None)
            await db.commit()

        spawned: list[str] = []
        monkeypatch.setattr(main, "_spawn_analysis",
                            lambda conv_id, user_id: spawned.append(conv_id))

        await main._resweep_stuck_analyses()
        assert legacy in spawned

    asyncio.run(go())
