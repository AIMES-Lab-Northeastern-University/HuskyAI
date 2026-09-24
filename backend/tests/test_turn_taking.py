"""Turn-taking metrics: definitions, determinism, and access scope.

Most of these run against hand-built event lists rather than a database. That
is deliberate — compute_turn_taking is a pure function, and a metric whose value
depends on anything outside the log it was handed is not reproducible from an
exported log, which is the whole point of the module.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta

import pytest

from analysis.turn_taking import METRICS_VERSION, compute_turn_taking

T0 = datetime(2026, 9, 19, 12, 0, 0)
A, B, C = "user-a", "user-b", "user-c"


def ev(seq, actor, action, target="artifact", payload=None, kind="student", secs=0):
    return {
        "seq": seq, "actor_user_id": actor, "actor_kind": kind,
        "target": target, "action": action, "payload": payload or {},
        "server_ts": T0 + timedelta(seconds=secs),
    }


def write(seq, actor, key, secs=0, origin="student_typed"):
    return ev(seq, actor, "write", payload={"section_key": key, "origin": origin, "version": 1}, secs=secs)


def expand(seq, actor, key, secs=0):
    return ev(seq, actor, "section_expand", payload={"section_key": key}, secs=secs)


# ── Determinism ──────────────────────────────────────────────────────────────

def test_replaying_the_same_log_reproduces_identical_metrics():
    """The requirement that makes a published number checkable months later."""
    log = [
        write(1, A, "s1", 0), expand(2, B, "s1", 5), write(3, B, "s2", 9),
        ev(4, A, "read_by_coach", payload={"section_keys": ["s1", "s2"]}, kind="coach", secs=11),
        ev(5, A, "turn", target="coach", payload={"turn": 1, "pei": 55.0}, secs=12),
    ]
    runs = [json.dumps(compute_turn_taking(log, [A, B]), sort_keys=True, default=str) for _ in range(5)]
    assert len(set(runs)) == 1


def test_metrics_do_not_depend_on_the_order_events_are_handed_in():
    """seq is authoritative. A log read back out of order must not change a number."""
    log = [write(1, A, "s1", 0), expand(2, B, "s1", 5), write(3, B, "s2", 9)]
    forward = compute_turn_taking(log, [A, B])
    shuffled = compute_turn_taking(list(reversed(log)), [A, B])
    assert forward == shuffled


def test_response_carries_the_metrics_version():
    assert compute_turn_taking([], [A])["metrics_version"] == METRICS_VERSION


# ── Contribution and equality ────────────────────────────────────────────────

def test_a_member_who_wrote_nothing_is_reported_as_zero_not_omitted():
    """Silence is a finding, not missing data."""
    m = compute_turn_taking([write(1, A, "s1"), write(2, A, "s2")], [A, B, C])
    assert m["contribution_share"] == {A: 1.0, B: 0.0, C: 0.0}
    assert set(m["actors"]) == {A, B, C}


def test_equality_measures_span_even_and_monopolised_teams():
    even = compute_turn_taking([write(1, A, "s1"), write(2, B, "s2")], [A, B])
    solo = compute_turn_taking([write(1, A, "s1"), write(2, A, "s2")], [A, B])

    assert even["equality"]["normalised_entropy"] == 1.0
    assert even["equality"]["gini"] == 0.0
    assert solo["equality"]["normalised_entropy"] == 0.0
    assert solo["equality"]["gini"] > 0.4


def test_alternation_rate_distinguishes_ping_pong_from_a_solo_block():
    ping = compute_turn_taking([write(1, A, "s1"), write(2, B, "s2"), write(3, A, "s3")], [A, B])
    block = compute_turn_taking([write(1, A, "s1"), write(2, A, "s2"), write(3, B, "s3")], [A, B])
    assert ping["alternation_rate"] == 1.0
    assert block["alternation_rate"] == 0.5


# ── The central measure ──────────────────────────────────────────────────────

def test_read_before_write_counts_a_teammate_read_that_preceded_the_write():
    m = compute_turn_taking([
        write(1, A, "s1", 0),
        expand(2, B, "s1", 5),   # B reads A's section…
        write(3, B, "s2", 9),    # …then writes their own
    ], [A, B])
    assert m["read_before_write"] == {"ratio": 1.0, "informed_writes": 1, "eligible_writes": 1}


def test_writing_without_reading_a_teammate_is_recorded_as_uninformed():
    m = compute_turn_taking([
        write(1, A, "s1", 0),
        write(2, B, "s2", 9),    # B never opened A's work
    ], [A, B])
    assert m["read_before_write"] == {"ratio": 0.0, "informed_writes": 0, "eligible_writes": 1}


def test_a_write_with_nothing_yet_to_read_is_excluded_from_the_denominator():
    """A write cannot be informed by a teammate if no teammate had written. Counting
    it as a failure would make every session's opening turns look antisocial."""
    m = compute_turn_taking([write(1, A, "s1"), write(2, A, "s2")], [A, B])
    assert m["read_before_write"]["eligible_writes"] == 0
    assert m["read_before_write"]["ratio"] is None


def test_reading_your_own_earlier_section_does_not_count_as_being_informed():
    m = compute_turn_taking([
        write(1, A, "s1", 0),
        write(2, B, "s2", 2),
        expand(3, B, "s2", 5),   # B re-reads their OWN section
        write(4, B, "s3", 9),
    ], [A, B])
    assert m["read_before_write"]["informed_writes"] == 0
    assert m["read_before_write"]["eligible_writes"] == 2


def test_a_read_after_the_write_does_not_count():
    """Ordering is the finding: reading afterwards is a different behaviour."""
    m = compute_turn_taking([
        write(1, A, "s1", 0),
        write(2, B, "s2", 5),
        expand(3, B, "s1", 9),
    ], [A, B])
    assert m["read_before_write"]["ratio"] == 0.0


def test_a_coach_mediated_read_does_not_count_as_the_student_having_read():
    """Open question 4. The metric uses human reads only; if the PI later rules
    the other way, the raw coach reads are still in the log to recompute from."""
    m = compute_turn_taking([
        write(1, A, "s1", 0),
        ev(2, B, "read_by_coach", payload={"section_keys": ["s1"]}, kind="coach", secs=5),
        write(3, B, "s2", 9),
    ], [A, B])
    assert m["read_before_write"]["ratio"] == 0.0
    assert m["totals"]["coach_reads"] == 1


# ── Latency and unread work ──────────────────────────────────────────────────

def test_latency_is_measured_per_section_not_per_panel():
    m = compute_turn_taking([
        write(1, A, "s1", 0),
        expand(2, B, "s2", 3),    # B opened a DIFFERENT section — not a read of s1
        expand(3, B, "s1", 10),   # this is the read of s1
    ], [A, B])
    assert m["median_write_to_read_ms"] == 10000


def test_contributions_nobody_opened_are_counted_separately():
    """A median hides them completely: a team where half the work went unread
    can still post a healthy latency."""
    m = compute_turn_taking([
        write(1, A, "s1", 0), expand(2, B, "s1", 2),
        write(3, A, "s2", 5),   # never read
        write(4, A, "s3", 6),   # never read
    ], [A, B])
    assert m["median_write_to_read_ms"] == 2000
    assert m["writes_never_read_by_a_teammate"] == 2


# ── Coach reliance ───────────────────────────────────────────────────────────

def test_coach_reliance_weighs_copied_text_against_teammate_informed_text():
    m = compute_turn_taking([
        write(1, A, "s1", 0),
        expand(2, B, "s1", 2),
        write(3, B, "s2", 5),                              # teammate-informed
        write(4, B, "s3", 7, origin="coach_copied"),       # lifted from the coach
    ], [A, B])
    assert m["coach_reliance"]["coach_copied_writes"] == 1
    assert m["coach_reliance"]["teammate_informed_writes"] == 1
    assert m["coach_reliance"]["ratio"] == 0.5


def test_a_coach_copied_write_with_nothing_yet_to_adopt_is_not_reliance():
    """The mirror of test_a_write_with_nothing_yet_to_read_is_excluded_from_the
    _denominator. Both terms of the ratio must come from the same population:
    when the only coach-copied write landed before any teammate had written,
    there was no teammate work available to adopt instead, so the session is
    not evidence of choosing the coach over a teammate."""
    m = compute_turn_taking([
        write(1, A, "s1", 0, origin="coach_copied"),
    ], [A, B])
    assert m["coach_reliance"]["ratio"] is None
    # Still described, just not divided: the write happened and is reported.
    assert m["coach_reliance"]["coach_copied_writes"] == 1
    assert m["coach_reliance"]["coach_copied_eligible_writes"] == 0


def test_coach_reliance_counts_only_copies_made_over_available_teammate_work():
    """A coach-copied write before eligibility and one after are different
    findings; only the second is reliance."""
    m = compute_turn_taking([
        write(1, A, "s1", 0, origin="coach_copied"),   # nothing to adopt yet
        write(2, B, "s2", 2),                          # now A has a teammate section
        expand(3, A, "s2", 3),
        write(4, A, "s3", 5),                          # teammate-informed, typed
        write(5, A, "s4", 7, origin="coach_copied"),   # chose the coach instead
    ], [A, B])
    assert m["coach_reliance"]["coach_copied_writes"] == 2
    assert m["coach_reliance"]["coach_copied_eligible_writes"] == 1
    assert m["coach_reliance"]["teammate_informed_writes"] == 1
    assert m["coach_reliance"]["ratio"] == 0.5


def test_ratios_are_null_not_zero_when_nothing_happened():
    """"No eligible writes" and "nobody did it" are different findings."""
    m = compute_turn_taking([], [A, B])
    assert m["read_before_write"]["ratio"] is None
    assert m["coach_reliance"]["ratio"] is None
    assert m["alternation_rate"] is None
    assert m["median_write_to_read_ms"] is None
    assert m["equality"]["gini"] is None


# ── End to end, over the real log ────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_ready():
    from database import init_db
    from main import app

    asyncio.run(init_db())
    return app


def test_metrics_computed_from_a_real_logged_session(app_ready):
    """Drives the real websocket, then reads the metrics back through the API."""
    from fastapi.testclient import TestClient

    from tests.test_coach_socket import (_connect, _drain_until, _group_session_id,
                                         _make_team, _token)

    group_id, users = asyncio.run(_make_team(2, section_defs=[{"key": "s1"}, {"key": "s2"}]))
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws_a:
        _drain_until(ws_a, {"artifact"})
        ws_a.send_text(json.dumps({"type": "artifact_write", "section_key": "s1",
                                   "content": "A's work", "expected_version": 0}))
        _drain_until(ws_a, {"artifact_write_ok"})
    with _connect(client, group_id, users[1]) as ws_b:
        _drain_until(ws_b, {"artifact"})
        ws_b.send_text(json.dumps({"type": "artifact_expand", "section_key": "s1"}))
        ws_b.send_text(json.dumps({"type": "artifact_write", "section_key": "s2",
                                   "content": "B's work", "expected_version": 0}))
        _drain_until(ws_b, {"artifact_write_ok"})

    gs = asyncio.run(_group_session_id(group_id))

    # A student must not be able to read the team's research metrics.
    r = client.get(f"/research/sessions/{gs}/turn-taking",
                   headers={"Authorization": f"Bearer {_token(users[0])}"})
    assert r.status_code == 403, "students must not see contribution share live"

    # An admin may.
    from database import AsyncSessionLocal, User

    async def make_admin():
        async with AsyncSessionLocal() as db:
            u = User(email=f"adm_{uuid.uuid4().hex[:8]}@e.com", name="Admin",
                     password_hash="x", is_platform_admin=True)
            db.add(u)
            await db.commit()
            return u.id

    admin = asyncio.run(make_admin())
    r = client.get(f"/research/sessions/{gs}/turn-taking",
                   headers={"Authorization": f"Bearer {_token(admin)}"})
    assert r.status_code == 200, r.text
    m = r.json()

    assert m["schema_version"] == "1.0.0"
    assert m["metrics_version"] == METRICS_VERSION
    assert m["totals"]["artifact_writes"] == 2
    assert m["contribution_share"] == {users[0]: 0.5, users[1]: 0.5}
    assert m["alternation_rate"] == 1.0
    # B expanded A's section before writing their own.
    assert m["read_before_write"]["ratio"] == 1.0
    assert m["read_before_write"]["eligible_writes"] == 1


# ── The classroom-scoped team route ──────────────────────────────────────────
# Same numbers, different door: /research/... is by session id and unscoped,
# this one is scoped to a classroom the caller manages. The instructor UI reads
# this one, because it also needs one entry per session and the member names.


def test_the_team_route_returns_one_entry_per_session_to_its_instructor(app_ready):
    from fastapi.testclient import TestClient

    from database import (AsyncSessionLocal, Classroom, ClassroomChallenge,
                          ClassroomMembership, GroupChallenge, User)
    from tests.test_coach_socket import (_connect, _drain_until, _make_team, _token)

    group_id, users = asyncio.run(_make_team(2, section_defs=[{"key": "s1"}, {"key": "s2"}]))

    async def attach_to_a_section():
        """Give the team a classroom with an instructor, and enrol a student."""
        async with AsyncSessionLocal() as db:
            inst = User(email=f"ti_{uuid.uuid4().hex[:8]}@e.com", name="Team Inst",
                        password_hash="x")
            db.add(inst)
            await db.flush()
            room = Classroom(name="TT Section", join_code=uuid.uuid4().hex[:8].upper(),
                             instructor_user_id=inst.id)
            db.add(room)
            await db.flush()
            team = await db.get(GroupChallenge, group_id)
            team.classroom_id = room.id
            db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=team.challenge_id,
                                      mode="group"))
            db.add(ClassroomMembership(classroom_id=room.id, user_id=users[0], role="student"))
            await db.commit()
            return inst.id, room.id, team.challenge_id

    inst_id, room_id, challenge_id = asyncio.run(attach_to_a_section())
    client = TestClient(app_ready)

    with _connect(client, group_id, users[0]) as ws_a:
        _drain_until(ws_a, {"artifact"})
        ws_a.send_text(json.dumps({"type": "artifact_write", "section_key": "s1",
                                   "content": "A's work", "expected_version": 0}))
        _drain_until(ws_a, {"artifact_write_ok"})
    with _connect(client, group_id, users[1]) as ws_b:
        _drain_until(ws_b, {"artifact"})
        ws_b.send_text(json.dumps({"type": "artifact_expand", "section_key": "s1"}))
        ws_b.send_text(json.dumps({"type": "artifact_write", "section_key": "s2",
                                   "content": "B's work", "expected_version": 0}))
        _drain_until(ws_b, {"artifact_write_ok"})

    url = f"/classrooms/{room_id}/challenges/{challenge_id}/teams/{group_id}/turn-taking"

    r = client.get(url, headers={"Authorization": f"Bearer {_token(inst_id)}"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["team_id"] == group_id
    assert set(body["member_names"]) == set(users), "names for the legend, keyed by user id"
    assert len(body["sessions"]) == 1, "one entry per session, never averaged together"

    s = body["sessions"][0]
    assert s["session_number"] == 1
    assert s["metrics_version"] == METRICS_VERSION
    assert s["totals"]["artifact_writes"] == 2
    assert s["contribution_share"] == {users[0]: 0.5, users[1]: 0.5}
    assert s["read_before_write"]["ratio"] == 1.0
    # Nobody copied the coach and nobody was eligible-and-typed... B was: their
    # write followed a read of A's section, so reliance has a denominator.
    assert s["coach_reliance"]["coach_copied_eligible_writes"] == 0


def test_a_student_cannot_read_the_team_route(app_ready):
    """Contribution share must not be visible to the people being measured."""
    from fastapi.testclient import TestClient

    from database import (AsyncSessionLocal, Classroom, ClassroomChallenge,
                          ClassroomMembership, GroupChallenge, User)
    from tests.test_coach_socket import _make_team, _token

    group_id, users = asyncio.run(_make_team(2))

    async def attach():
        async with AsyncSessionLocal() as db:
            inst = User(email=f"ts_{uuid.uuid4().hex[:8]}@e.com", name="I", password_hash="x")
            db.add(inst)
            await db.flush()
            room = Classroom(name="TT Section 2", join_code=uuid.uuid4().hex[:8].upper(),
                             instructor_user_id=inst.id)
            db.add(room)
            await db.flush()
            team = await db.get(GroupChallenge, group_id)
            team.classroom_id = room.id
            db.add(ClassroomChallenge(classroom_id=room.id, challenge_id=team.challenge_id,
                                      mode="group"))
            db.add(ClassroomMembership(classroom_id=room.id, user_id=users[0], role="student"))
            await db.commit()
            return room.id, team.challenge_id

    room_id, challenge_id = asyncio.run(attach())
    client = TestClient(app_ready)

    r = client.get(
        f"/classrooms/{room_id}/challenges/{challenge_id}/teams/{group_id}/turn-taking",
        headers={"Authorization": f"Bearer {_token(users[0])}"},
    )
    assert r.status_code == 403
