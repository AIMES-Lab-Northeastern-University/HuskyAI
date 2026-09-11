"""Team-level study arm assignment.

The invariants that matter for a study you only get to run once:

  - an arm is assigned when a GroupSession row is created, and never rewritten
  - every session of one team shares that team's arm (it is a team-level
    intervention; an independent per-session draw would be noise)
  - assignment across a cohort is balanced, not merely random -- a class has
    roughly six teams, where a fair coin gives a 5-1-or-worse split about 22%
    of the time
  - sessions that predate the column keep a NULL arm rather than being
    back-filled with an invented condition
"""

import asyncio
import uuid

import pytest


async def _cohort(db, n_teams, *, classroom_id=None, challenge_id=None):
    """n_teams teams on one challenge in one classroom. Returns (challenge_id, [team]).

    Teams only; sessions are created by the code under test.
    """
    from database import Challenge, Classroom, GroupChallenge, User

    uid = str(uuid.uuid4())
    db.add(User(id=uid, email=f"arm_{uuid.uuid4().hex[:10]}@example.com",
                name="arm", password_hash="x"))
    if challenge_id is None:
        challenge_id = str(uuid.uuid4())
        db.add(Challenge(id=challenge_id, title=f"arm {uuid.uuid4().hex[:6]}",
                         description="d", category="c", difficulty="Beginner",
                         total_sessions=3, sessions_data=[]))
    if classroom_id is None:
        classroom_id = str(uuid.uuid4())
        db.add(Classroom(id=classroom_id, name=f"room {uuid.uuid4().hex[:6]}",
                         join_code=uuid.uuid4().hex[:8], instructor_user_id=uid))
    teams = []
    for _ in range(n_teams):
        gid = str(uuid.uuid4())
        db.add(GroupChallenge(id=gid, challenge_id=challenge_id,
                              classroom_id=classroom_id, created_by=uid,
                              status="active"))
        teams.append(gid)
    await db.flush()
    return challenge_id, classroom_id, teams


def test_arm_is_assigned_when_the_session_is_created():
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 1)
            await db.commit()

        ensured = await main._ensure_group_session(teams[0], 1)
        assert ensured is not None

        async with AsyncSessionLocal() as db:
            gs = await db.get(GroupSession, ensured[0])
            assert gs.arm in main.STUDY_ARMS, f"no arm assigned: {gs.arm!r}"

    asyncio.run(go())


def test_every_session_of_a_team_shares_the_team_s_arm():
    """The team-level property. A per-session draw would break this."""
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 1)
            await db.commit()

        ids = [(await main._ensure_group_session(teams[0], n))[0] for n in (1, 2, 3)]

        async with AsyncSessionLocal() as db:
            arms = [(await db.get(GroupSession, i)).arm for i in ids]
        assert len(set(arms)) == 1, f"one team ended up in multiple arms: {arms}"
        assert arms[0] in main.STUDY_ARMS

    asyncio.run(go())


def test_the_arm_never_changes_once_assigned():
    """Re-ensuring the same session, and creating later ones, must not rewrite it."""
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 1)
            await db.commit()

        sid, _conv, _ch = await main._ensure_group_session(teams[0], 1)
        async with AsyncSessionLocal() as db:
            original = (await db.get(GroupSession, sid)).arm

        # Re-ensure the same session many times, and open later sessions in
        # between -- nothing here may touch the stored arm.
        for _ in range(5):
            again = await main._ensure_group_session(teams[0], 1)
            assert again[0] == sid
            await main._ensure_group_session(teams[0], 2)

        async with AsyncSessionLocal() as db:
            assert (await db.get(GroupSession, sid)).arm == original, (
                "the arm was rewritten after assignment"
            )

    asyncio.run(go())


def test_a_concurrent_create_still_yields_one_arm():
    """Two teammates connecting at once race to insert the session row.

    uq_group_session_num picks a winner and the loser re-reads; the arm must be
    written exactly once, not overwritten by the loser.
    """
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 1)
            await db.commit()

        results = await asyncio.gather(
            *(main._ensure_group_session(teams[0], 1) for _ in range(4)),
            return_exceptions=True,
        )
        ok = [r for r in results if isinstance(r, tuple)]
        assert ok, f"every concurrent create failed: {results}"
        sids = {r[0] for r in ok}
        assert len(sids) == 1, f"the race created more than one session: {sids}"

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                __import__("sqlalchemy").select(GroupSession).where(
                    GroupSession.group_id == teams[0]
                )
            )).scalars().all()
        assert len(rows) == 1
        assert rows[0].arm in main.STUDY_ARMS

    asyncio.run(go())


def test_assignment_is_balanced_across_a_cohort():
    """Stratified, not a coin flip: an even cohort must split exactly evenly.

    This is the assertion a pure 50/50 draw could not support -- with six teams
    a fair coin lands 5-1 or worse about 22% of the time, which is precisely the
    risk the minimisation exists to remove.
    """
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 12)
            await db.commit()

        for gid in teams:
            await main._ensure_group_session(gid, 1)

        async with AsyncSessionLocal() as db:
            import sqlalchemy as sa
            rows = (await db.execute(
                sa.select(GroupSession.group_id, GroupSession.arm)
                .where(GroupSession.group_id.in_(teams))
            )).all()

        arms = [arm for _gid, arm in rows]
        assert len(arms) == 12
        n_control = arms.count(main.ARM_CONTROL)
        n_treatment = arms.count(main.ARM_TREATMENT)
        assert n_control + n_treatment == 12, f"unexpected arm values: {set(arms)}"
        assert abs(n_control - n_treatment) <= 1, (
            f"cohort is unbalanced: {n_control} control vs {n_treatment} treatment"
        )

    asyncio.run(go())


def test_an_odd_cohort_is_balanced_to_within_one():
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 7)
            await db.commit()
        for gid in teams:
            await main._ensure_group_session(gid, 1)

        async with AsyncSessionLocal() as db:
            import sqlalchemy as sa
            arms = [a for _g, a in (await db.execute(
                sa.select(GroupSession.group_id, GroupSession.arm)
                .where(GroupSession.group_id.in_(teams))
            )).all()]

        assert abs(arms.count(main.ARM_CONTROL) - arms.count(main.ARM_TREATMENT)) <= 1

    asyncio.run(go())


def test_a_teams_extra_sessions_do_not_skew_the_cohort():
    """Balance is counted per team, not per session.

    One busy team with several sessions must not drag every later assignment to
    the other arm.
    """
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 4)
            await db.commit()

        # First team runs all three sessions before anyone else starts.
        for n in (1, 2, 3):
            await main._ensure_group_session(teams[0], n)
        for gid in teams[1:]:
            await main._ensure_group_session(gid, 1)

        async with AsyncSessionLocal() as db:
            import sqlalchemy as sa
            rows = (await db.execute(
                sa.select(GroupSession.group_id, GroupSession.arm)
                .where(GroupSession.group_id.in_(teams))
            )).all()
        arm_by_team = {gid: arm for gid, arm in rows}
        assert len(arm_by_team) == 4
        arms = list(arm_by_team.values())
        assert abs(arms.count(main.ARM_CONTROL) - arms.count(main.ARM_TREATMENT)) <= 1, (
            f"per-session counting skewed the cohort: {arms}"
        )

    asyncio.run(go())


def test_separate_classrooms_are_separate_cohorts():
    """Balancing is within a class, not across the whole platform."""
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            cid, _room_a, teams_a = await _cohort(db, 2)
            _cid, _room_b, teams_b = await _cohort(db, 2, challenge_id=cid)
            await db.commit()

        for gid in teams_a + teams_b:
            await main._ensure_group_session(gid, 1)

        async with AsyncSessionLocal() as db:
            import sqlalchemy as sa

            async def arms_of(teams):
                rows = (await db.execute(
                    sa.select(GroupSession.arm)
                    .where(GroupSession.group_id.in_(teams))
                )).scalars().all()
                return list(rows)

            a, b = await arms_of(teams_a), await arms_of(teams_b)

        # Each classroom balances on its own, so each pair is one of each arm.
        for label, arms in (("A", a), ("B", b)):
            assert sorted(arms) == sorted(main.STUDY_ARMS), (
                f"classroom {label} did not balance independently: {arms}"
            )

    asyncio.run(go())


def test_a_preexisting_session_keeps_a_null_arm():
    """Rows created before the column existed must not gain an invented arm."""
    async def go():
        import main
        from database import AsyncSessionLocal, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            cid, _room, teams = await _cohort(db, 1)
            legacy_id = str(uuid.uuid4())
            db.add(GroupSession(id=legacy_id, group_id=teams[0], challenge_id=cid,
                                session_number=1, arm=None))
            await db.commit()

        # Re-ensuring an armless legacy session must not back-fill it.
        ensured = await main._ensure_group_session(teams[0], 1)
        assert ensured[0] == legacy_id

        async with AsyncSessionLocal() as db:
            assert (await db.get(GroupSession, legacy_id)).arm is None, (
                "a legacy session was given a condition it never ran under"
            )

    asyncio.run(go())


def test_analytics_reports_the_arm_without_a_db_query():
    async def go():
        import groups
        import main
        from database import AsyncSessionLocal, GroupChallenge, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            _cid, _room, teams = await _cohort(db, 1)
            await db.commit()
        ids = [(await main._ensure_group_session(teams[0], n))[0] for n in (1, 2)]

        async with AsyncSessionLocal() as db:
            team = await db.get(GroupChallenge, teams[0])
            out = await groups._team_analytics(db, team)
            expected = (await db.get(GroupSession, ids[0])).arm

        assert out["arm"] == expected
        assert out["arm_consistent"] is True
        assert sorted(s["session"] for s in out["session_arms"]) == [1, 2]
        assert all(s["arm"] == expected for s in out["session_arms"])

    asyncio.run(go())


def test_analytics_flags_a_team_whose_sessions_disagree():
    """An inconsistent team is an assignment bug and must be visible, not hidden
    behind the single team-level value."""
    async def go():
        import groups
        import main
        from database import AsyncSessionLocal, GroupChallenge, GroupSession, init_db

        await init_db()
        async with AsyncSessionLocal() as db:
            cid, _room, teams = await _cohort(db, 1)
            db.add(GroupSession(id=str(uuid.uuid4()), group_id=teams[0],
                                challenge_id=cid, session_number=1,
                                arm=main.ARM_CONTROL))
            db.add(GroupSession(id=str(uuid.uuid4()), group_id=teams[0],
                                challenge_id=cid, session_number=2,
                                arm=main.ARM_TREATMENT))
            await db.commit()

        async with AsyncSessionLocal() as db:
            team = await db.get(GroupChallenge, teams[0])
            out = await groups._team_analytics(db, team)

        assert out["arm_consistent"] is False

    asyncio.run(go())
