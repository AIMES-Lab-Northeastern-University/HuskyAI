"""Shared artifact: concurrency, revision history, and read instrumentation.

The concurrency tests protect a teammate's work from being clobbered. The read
tests protect the dataset: every surface that exposes one student's text to
another must emit an event, and a surface that stops doing so should fail here
rather than silently produce six months of unusable logs.
"""

import asyncio
import uuid

import pytest


@pytest.fixture(scope="module")
def db_ready():
    from database import init_db

    asyncio.run(init_db())


async def _make_user() -> str:
    from database import AsyncSessionLocal, User

    async with AsyncSessionLocal() as db:
        u = User(email=f"art_{uuid.uuid4().hex[:12]}@example.com", name="Artifact User",
                 password_hash="x", consent_research=True)
        db.add(u)
        await db.commit()
        return u.id


async def _make_group_session() -> str:
    """A real GroupSession row, so _scope() resolves and FKs hold."""
    from database import AsyncSessionLocal, Challenge, GroupChallenge, GroupSession

    owner = await _make_user()
    async with AsyncSessionLocal() as db:
        ch = Challenge(title="Artifact Test", description="d", category="c",
                       difficulty="easy", sessions_data={})
        db.add(ch)
        await db.flush()
        gc = GroupChallenge(challenge_id=ch.id, created_by=owner)
        db.add(gc)
        await db.flush()
        gs = GroupSession(group_id=gc.id, challenge_id=ch.id, session_number=1)
        db.add(gs)
        await db.commit()
        return gs.id


async def _events(group_session_id: str, action: str | None = None) -> list:
    from sqlalchemy import select

    from database import AsyncSessionLocal, StudyEvent

    async with AsyncSessionLocal() as db:
        q = select(StudyEvent).where(StudyEvent.group_session_id == group_session_id)
        if action:
            q = q.where(StudyEvent.action == action)
        return list((await db.execute(q.order_by(StudyEvent.seq))).scalars().all())


@pytest.mark.asyncio
async def test_assignment_without_sections_behaves_as_free_form(db_ready):
    """No instructor decomposition means one implicit section, not a special case."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    snap = await artifacts.snapshot(gs)

    assert [s["key"] for s in snap["sections"]] == [artifacts.IMPLICIT_SECTION_KEY]
    assert snap["sections"][0]["version"] == 0


@pytest.mark.asyncio
async def test_sections_are_created_in_instructor_order(db_ready):
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs, [
        {"key": "step-1", "title": "Frame the problem"},
        {"key": "step-2", "title": "Analyse"},
        {"key": "step-3", "title": "Recommend"},
    ])
    snap = await artifacts.snapshot(gs)

    assert [s["key"] for s in snap["sections"]] == ["step-1", "step-2", "step-3"]
    assert snap["sections"][1]["title"] == "Analyse"


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_ready):
    """Two teammates connecting at once must not produce two artifacts."""
    import artifacts

    gs = await _make_group_session()
    ids = await asyncio.gather(*[artifacts.get_or_create(gs) for _ in range(5)])
    assert len(set(ids)) == 1


@pytest.mark.asyncio
async def test_stale_write_is_rejected_and_teammate_text_survives(db_ready):
    """The core concurrency guarantee: a writer working from an old version does
    not overwrite the teammate who got there first, and gets the current text
    back so the client can rebase."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    alice, bob = await _make_user(), await _make_user()
    k = artifacts.IMPLICIT_SECTION_KEY

    first = await artifacts.write_section(
        group_session_id=gs, section_key=k, content="Alice's analysis",
        author_user_id=alice, expected_version=0,
    )
    assert first == {"ok": True, "version": 1, "bytes_added": 16, "bytes_removed": 0}

    # Bob was still looking at version 0.
    stale = await artifacts.write_section(
        group_session_id=gs, section_key=k, content="Bob's analysis",
        author_user_id=bob, expected_version=0,
    )
    assert stale["ok"] is False and stale["conflict"] is True
    assert stale["version"] == 1
    assert stale["content"] == "Alice's analysis", "conflict must return current text to rebase on"

    snap = await artifacts.snapshot(gs)
    assert snap["sections"][0]["content"] == "Alice's analysis", "teammate's write was clobbered"

    # Rebased onto the version he was handed, Bob's write lands.
    rebased = await artifacts.write_section(
        group_session_id=gs, section_key=k, content="Alice's analysis + Bob's addition",
        author_user_id=bob, expected_version=1,
    )
    assert rebased["ok"] is True and rebased["version"] == 2


@pytest.mark.asyncio
async def test_concurrent_writes_serialise_without_losing_a_revision(db_ready):
    """Ten racing writers: exactly one wins per version, and the revision history
    has no duplicates and no gaps."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    author = await _make_user()
    k = artifacts.IMPLICIT_SECTION_KEY

    results = await asyncio.gather(*[
        artifacts.write_section(
            group_session_id=gs, section_key=k, content=f"writer {i}",
            author_user_id=author, expected_version=0,
        )
        for i in range(10)
    ])

    accepted = [r for r in results if r.get("ok")]
    assert len(accepted) == 1, "only one writer may win version 0->1"
    assert sum(1 for r in results if r.get("conflict")) == 9

    hist = await artifacts.revisions(gs)
    assert [r["version"] for r in hist] == [1]


@pytest.mark.asyncio
async def test_revision_history_is_append_only_with_real_diffs(db_ready):
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    author = await _make_user()
    k = artifacts.IMPLICIT_SECTION_KEY

    await artifacts.write_section(group_session_id=gs, section_key=k, content="hello",
                                  author_user_id=author, expected_version=0)
    await artifacts.write_section(group_session_id=gs, section_key=k, content="hello world",
                                  author_user_id=author, expected_version=1)
    # Same length, different text: a net-zero change is still an edit.
    await artifacts.write_section(group_session_id=gs, section_key=k, content="HELLO WORLD",
                                  author_user_id=author, expected_version=2)

    hist = await artifacts.revisions(gs)
    assert [r["version"] for r in hist] == [1, 2, 3]
    assert [r["content"] for r in hist] == ["hello", "hello world", "HELLO WORLD"]
    assert hist[2]["bytes_added"] > 0 and hist[2]["bytes_removed"] > 0, \
        "a same-length rewrite must not be recorded as a no-op"


@pytest.mark.asyncio
async def test_origin_distinguishes_typed_from_coach_copied(db_ready):
    """Whether a student wrote it or lifted it from their coach is a finding."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    author = await _make_user()
    k = artifacts.IMPLICIT_SECTION_KEY

    await artifacts.write_section(group_session_id=gs, section_key=k, content="mine",
                                  author_user_id=author, expected_version=0,
                                  origin="student_typed")
    await artifacts.write_section(group_session_id=gs, section_key=k, content="the coach's",
                                  author_user_id=author, expected_version=1,
                                  origin="coach_copied")

    assert [r["origin"] for r in await artifacts.revisions(gs)] == ["student_typed", "coach_copied"]

    bad = await artifacts.write_section(group_session_id=gs, section_key=k, content="x",
                                        author_user_id=author, expected_version=2,
                                        origin="made_up")
    assert bad["ok"] is False
    assert len(await artifacts.revisions(gs)) == 2, "rejected origin must not write history"


@pytest.mark.asyncio
async def test_every_write_lands_in_the_event_log(db_ready):
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    author = await _make_user()
    k = artifacts.IMPLICIT_SECTION_KEY

    await artifacts.write_section(group_session_id=gs, section_key=k, content="text",
                                  author_user_id=author, expected_version=0)

    evs = await _events(gs, "write")
    assert len(evs) == 1
    assert evs[0].target == "artifact"
    assert evs[0].payload["section_key"] == k
    assert evs[0].payload["version"] == 1
    assert evs[0].challenge_id is not None, "event must carry scope for analysis filtering"


@pytest.mark.asyncio
async def test_rejected_write_logs_nothing(db_ready):
    """A conflict is not a write. Logging it as one would inflate contribution
    share for a student whose text never landed."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    a, b = await _make_user(), await _make_user()
    k = artifacts.IMPLICIT_SECTION_KEY

    await artifacts.write_section(group_session_id=gs, section_key=k, content="a",
                                  author_user_id=a, expected_version=0)
    await artifacts.write_section(group_session_id=gs, section_key=k, content="b",
                                  author_user_id=b, expected_version=0)

    assert len(await _events(gs, "write")) == 1


@pytest.mark.asyncio
async def test_read_before_write_is_reconstructable_from_the_log(db_ready):
    """The whole point. Bob expands Alice's section, then writes his own; the
    single sequence must show the read strictly before the write."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs, [{"key": "step-1"}, {"key": "step-2"}])
    alice, bob = await _make_user(), await _make_user()

    await artifacts.write_section(group_session_id=gs, section_key="step-1",
                                  content="Alice's step 1", author_user_id=alice,
                                  expected_version=0)
    await artifacts.log_open(gs, bob)
    await artifacts.log_section_expand(gs, bob, "step-1")
    await artifacts.write_section(group_session_id=gs, section_key="step-2",
                                  content="Bob's step 2", author_user_id=bob,
                                  expected_version=0)

    trace = [(e.actor_user_id, e.action) for e in await _events(gs)]
    assert trace == [
        (alice, "write"),
        (bob, "open"),
        (bob, "section_expand"),
        (bob, "write"),
    ]
    bob_read = next(i for i, t in enumerate(trace) if t == (bob, "section_expand"))
    bob_write = next(i for i, t in enumerate(trace) if t == (bob, "write"))
    assert bob_read < bob_write, "read-before-write must be legible from seq alone"


@pytest.mark.asyncio
async def test_coach_reads_never_merge_into_human_opens(db_ready):
    """Open question 4 stays answerable only if these remain separable."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs, [{"key": "step-1"}])
    student = await _make_user()

    await artifacts.log_read_by_coach(gs, student, ["step-1"])
    await artifacts.log_open(gs, student)

    coach_reads = await _events(gs, "read_by_coach")
    human_opens = await _events(gs, "open")
    assert len(coach_reads) == 1 and len(human_opens) == 1
    assert coach_reads[0].actor_kind == "coach"
    assert coach_reads[0].actor_user_id == student, "attributed to the student it was injected for"
    assert human_opens[0].actor_kind == "student"


@pytest.mark.asyncio
async def test_snapshot_does_not_itself_count_as_a_read(db_ready):
    """Rendering is not reading. If snapshot() logged, every background refresh
    would inflate the read counts and the measure would be worthless."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    for _ in range(3):
        await artifacts.snapshot(gs)

    assert await _events(gs) == []


@pytest.mark.asyncio
async def test_buffered_reads_flush_without_double_counting(db_ready):
    """A read buffered across a dropped socket may arrive twice. The idempotency
    key must collapse it, because sampling/duplication both corrupt the measure."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs, [{"key": "step-1"}])
    student = await _make_user()
    key = f"read_{uuid.uuid4().hex[:10]}"

    await artifacts.log_section_expand(gs, student, "step-1", idempotency_key=key)
    await artifacts.log_section_expand(gs, student, "step-1", idempotency_key=key)

    assert len(await _events(gs, "section_expand")) == 1


# -- Regressions -------------------------------------------------------------
# Each of these failed against the first implementation. They are the reason the
# artifact layer got an adversarial pass rather than only a happy-path one.


@pytest.mark.asyncio
async def test_duplicate_section_keys_fail_loudly_at_creation(db_ready):
    """Was: the duplicate hit the unique constraint mid-transaction, retried
    three times and surfaced as an unexplained 'could not create artifact',
    taking down the team's whole session with no usable diagnostic."""
    import artifacts

    gs = await _make_group_session()
    with pytest.raises(artifacts.ArtifactConfigError, match="duplicate section key 's1'"):
        await artifacts.get_or_create(gs, [{"key": "s1"}, {"key": "s1"}])

    assert await artifacts.snapshot(gs) is None, "a rejected config must leave nothing behind"


@pytest.mark.asyncio
async def test_overlong_section_key_is_rejected_not_truncated(db_ready):
    """Was: keys were silently cut to 64 chars, so two distinct sections could
    collide into one — which then failed the same opaque way."""
    import artifacts

    gs = await _make_group_session()
    long_a = "x" * artifacts.MAX_SECTION_KEY_LEN + "AAA"
    long_b = "x" * artifacts.MAX_SECTION_KEY_LEN + "BBB"
    with pytest.raises(artifacts.ArtifactConfigError, match="max 64"):
        await artifacts.get_or_create(gs, [{"key": long_a}, {"key": long_b}])


@pytest.mark.asyncio
async def test_write_never_creates_a_wrongly_shaped_artifact(db_ready):
    """Was: writing before the artifact existed implicitly created a default
    free-form one. Because sections are never restructured afterwards, a team on
    a sectioned assignment would be permanently stuck with the wrong shape and
    every later section write would fail."""
    import artifacts

    gs = await _make_group_session()
    author = await _make_user()

    result = await artifacts.write_section(
        group_session_id=gs, section_key="step-1", content="x",
        author_user_id=author, expected_version=0,
    )
    assert result["ok"] is False
    assert "does not exist" in result["error"]
    assert await artifacts.snapshot(gs) is None, "no phantom artifact may be created"

    # The connect path creates it with the assignment's real decomposition.
    await artifacts.get_or_create(gs, [{"key": "step-1"}, {"key": "step-2"}])
    ok = await artifacts.write_section(
        group_session_id=gs, section_key="step-1", content="x",
        author_user_id=author, expected_version=0,
    )
    assert ok["ok"] is True


@pytest.mark.asyncio
async def test_session_teardown_releases_in_process_locks(db_ready):
    """Was: the write-lock and seq-lock dicts grew for the lifetime of the
    worker. Correctness never depended on them, so releasing is safe."""
    import artifacts
    import events

    gs = await _make_group_session()
    await artifacts.get_or_create(gs)
    author = await _make_user()
    await artifacts.write_section(
        group_session_id=gs, section_key=artifacts.IMPLICIT_SECTION_KEY,
        content="x", author_user_id=author, expected_version=0,
    )
    artifact_id = (await artifacts.snapshot(gs))["artifact_id"]
    assert artifact_id in artifacts._write_locks
    assert f"g:{gs}" in events._seq_locks

    await artifacts.forget_session(gs)

    assert artifact_id not in artifacts._write_locks
    assert f"g:{gs}" not in events._seq_locks

    # Releasing the locks must not lose the sequence: seq resumes from the DB.
    await artifacts.write_section(
        group_session_id=gs, section_key=artifacts.IMPLICIT_SECTION_KEY,
        content="y", author_user_id=author, expected_version=1,
    )
    assert [e.seq for e in await _events(gs)] == [1, 2]


@pytest.mark.asyncio
async def test_revision_order_is_deterministic(db_ready):
    """Was ordered by created_at alone; two revisions can share a timestamp, and
    the metrics codebook requires that replaying a history reproduce identically."""
    import artifacts

    gs = await _make_group_session()
    await artifacts.get_or_create(gs, [{"key": "s1"}, {"key": "s2"}])
    author = await _make_user()

    for i in range(6):
        await artifacts.write_section(
            group_session_id=gs, section_key="s1" if i % 2 == 0 else "s2",
            content=f"c{i}", author_user_id=author, expected_version=i // 2,
        )

    runs = [
        [(r["section_key"], r["version"]) for r in await artifacts.revisions(gs)]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]
    assert len(runs[0]) == 6
