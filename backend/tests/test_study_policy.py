"""CoachPolicy: the single resolution point for an experimental condition.

The plan's warning is the reason this file exists — "no `if prominence ==`
checks scattered through the websocket handlers, because that is how conditions
drift apart mid-study". A condition read in six places is eventually honoured in
five, and the resulting dataset mixes two conditions under one label, which is
not detectable after the fact.
"""

import asyncio
import uuid

import pytest

from study_policy import CoachPolicy


@pytest.fixture(scope="module")
def db_ready():
    from database import init_db

    asyncio.run(init_db())


# ── The questions handlers ask ───────────────────────────────────────────────

def test_on_request_is_todays_behaviour():
    p = CoachPolicy(prominence="on_request")
    assert p.injects_artifact is True
    assert p.takes_unsolicited_turns is False
    assert p.posts_to_shared_space is False


def test_ambient_lets_the_coach_act_unprompted():
    p = CoachPolicy(prominence="ambient")
    assert p.injects_artifact is True
    assert p.takes_unsolicited_turns is True
    assert p.posts_to_shared_space is True


def test_isolated_keeps_the_team_artifact_out_of_the_prompt():
    """The coach stays reachable, but the team's work does not reach it unless a
    student explicitly copies it in — which is logged as origin=coach_copied."""
    p = CoachPolicy(prominence="isolated")
    assert p.injects_artifact is False
    assert p.takes_unsolicited_turns is False
    assert p.posts_to_shared_space is False


def test_the_policy_is_immutable():
    """A condition that can be mutated mid-session is a condition that will be."""
    p = CoachPolicy()
    with pytest.raises(Exception):
        p.prominence = "ambient"


def test_condition_stamp_is_self_describing():
    c = CoachPolicy(arm="collab_coach_artifact", prominence="isolated").as_condition()
    assert c == {"arm": "collab_coach_artifact", "prominence": "isolated", "corpus": None}


# ── Resolution ───────────────────────────────────────────────────────────────

def test_an_unrecognised_value_falls_back_instead_of_being_honoured(db_ready):
    """A typo in a config row must not silently create a fourth condition that
    analysis will never look for."""
    from sqlalchemy import select

    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge, User)
    from study_policy import resolve_for_classroom_challenge

    async def setup():
        async with AsyncSessionLocal() as db:
            u = User(email=f"pol_{uuid.uuid4().hex[:8]}@e.com", name="I", password_hash="x")
            db.add(u); await db.flush()
            room = Classroom(name="S", join_code=uuid.uuid4().hex[:8].upper(),
                             instructor_user_id=u.id)
            ch = Challenge(title="C", description="d", category="c", difficulty="e",
                           sessions_data=[{}])
            db.add_all([room, ch]); await db.flush()
            cc = ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id,
                                    study_arm="typo_arm", coach_prominence="loud")
            db.add(cc); await db.commit()
            return room.id, ch.id

    room_id, ch_id = asyncio.run(setup())
    p = asyncio.run(resolve_for_classroom_challenge(room_id, ch_id))
    assert p.arm == "control_solo_feed"
    assert p.prominence == "on_request"


def test_an_unconfigured_assignment_behaves_as_it_does_today(db_ready):
    from study_policy import resolve_for_classroom_challenge

    p = asyncio.run(resolve_for_classroom_challenge("no-such-room", "no-such-challenge"))
    assert p.arm == "control_solo_feed"
    assert p.prominence == "on_request"
    assert p.is_collab_arm is False


def test_prominence_is_read_from_the_assignment(db_ready):
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          GroupChallenge, GroupSession, User)
    from study_policy import resolve_for_group_session

    async def setup():
        async with AsyncSessionLocal() as db:
            u = User(email=f"pol_{uuid.uuid4().hex[:8]}@e.com", name="I", password_hash="x")
            db.add(u); await db.flush()
            room = Classroom(name="S", join_code=uuid.uuid4().hex[:8].upper(),
                             instructor_user_id=u.id)
            ch = Challenge(title="C", description="d", category="c", difficulty="e",
                           sessions_data=[{}])
            db.add_all([room, ch]); await db.flush()
            db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id, mode="group",
                                      study_arm="collab_coach_artifact",
                                      coach_prominence="isolated"))
            team = GroupChallenge(challenge_id=ch.id, classroom_id=room.id, created_by=u.id)
            db.add(team); await db.flush()
            gs = GroupSession(group_id=team.id, challenge_id=ch.id, session_number=1)
            db.add(gs); await db.commit()
            return gs.id

    gs_id = asyncio.run(setup())
    p = asyncio.run(resolve_for_group_session(gs_id))
    assert p.prominence == "isolated"
    assert p.is_collab_arm is True
    assert p.injects_artifact is False
