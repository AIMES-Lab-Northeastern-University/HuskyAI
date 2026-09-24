"""Study event log: ordering, scoping and dedupe guarantees.

These assert the properties the collaborative study depends on rather than the
implementation. If `log_event` is ever reimplemented (a DB sequence, Redis), these
tests should still pass unchanged — and if one of them starts failing, the
resulting dataset is not recoverable after the fact, which is why they exist.
"""

import asyncio
import uuid

import pytest


@pytest.fixture(scope="module")
def db_ready():
    from database import init_db

    asyncio.run(init_db())


async def _make_user(consent: bool = False) -> str:
    """A bare User row — enough to be an event actor, without going through auth."""
    from database import AsyncSessionLocal, User

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"evt_{uuid.uuid4().hex[:12]}@example.com",
            name="Event Actor",
            password_hash="x",
            consent_research=consent,
        )
        db.add(user)
        await db.commit()
        return user.id


def _solo_scope() -> str:
    """A synthetic session id. The FK is not enforced on SQLite, and these tests
    are about seq allocation, not referential integrity."""
    return f"ucs_{uuid.uuid4().hex[:12]}"


async def _events_for(scope_id: str) -> list:
    from sqlalchemy import select

    from database import AsyncSessionLocal, StudyEvent

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(StudyEvent)
            .where(StudyEvent.user_challenge_session_id == scope_id)
            .order_by(StudyEvent.seq)
        )
        return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_seq_is_gapless_and_ordered_under_concurrency(db_ready):
    """The ordering guarantee. Twenty concurrent writers to one session must
    produce 1..20 with no gaps and no duplicates — a gap or a repeat makes
    "did they read before they wrote?" unanswerable for that session."""
    from events import log_event

    scope = _solo_scope()
    actor = await _make_user()

    await asyncio.gather(*[
        log_event(
            action="open" if i % 2 else "write",
            target="artifact",
            user_challenge_session_id=scope,
            actor_user_id=actor,
            payload={"i": i},
        )
        for i in range(20)
    ])

    events = await _events_for(scope)
    assert [e.seq for e in events] == list(range(1, 21))


@pytest.mark.asyncio
async def test_reads_and_writes_share_one_sequence_space(db_ready):
    """A read interleaved between two writes must sort between them. This is the
    property that makes read-before-write measurable."""
    from events import log_event

    scope = _solo_scope()
    actor = await _make_user()

    await log_event(action="write", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)
    await log_event(action="open", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)
    await log_event(action="write", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)

    assert [e.action for e in await _events_for(scope)] == ["write", "open", "write"]


@pytest.mark.asyncio
async def test_sessions_have_independent_sequence_spaces(db_ready):
    from events import log_event

    scope_a, scope_b = _solo_scope(), _solo_scope()
    actor = await _make_user()

    for _ in range(3):
        await log_event(action="open", target="artifact", user_challenge_session_id=scope_a, actor_user_id=actor)
    await log_event(action="open", target="artifact", user_challenge_session_id=scope_b, actor_user_id=actor)

    assert [e.seq for e in await _events_for(scope_a)] == [1, 2, 3]
    assert [e.seq for e in await _events_for(scope_b)] == [1]


@pytest.mark.asyncio
async def test_duplicate_delivery_is_deduped_without_burning_a_seq(db_ready):
    """At-least-once client delivery: a replayed event must not double-count, and
    must not leave a hole in the sequence that looks like a dropped event."""
    from events import log_event

    scope = _solo_scope()
    actor = await _make_user()
    key = f"idem_{uuid.uuid4().hex[:12]}"

    first = await log_event(
        action="open", target="artifact", user_challenge_session_id=scope,
        actor_user_id=actor, idempotency_key=key,
    )
    second = await log_event(
        action="open", target="artifact", user_challenge_session_id=scope,
        actor_user_id=actor, idempotency_key=key,
    )
    await log_event(action="write", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)

    assert first is not None
    assert second is None, "replayed delivery should be dropped, not recorded twice"
    assert [e.seq for e in await _events_for(scope)] == [1, 2]


@pytest.mark.asyncio
async def test_client_ts_is_preserved_but_not_used_for_ordering(db_ready):
    """A read buffered across a dropped socket flushes late with its original
    client_ts. It keeps that timestamp, but sorts by arrival."""
    from datetime import datetime, timedelta

    from events import log_event

    scope = _solo_scope()
    actor = await _make_user()
    old = datetime.utcnow() - timedelta(minutes=5)

    await log_event(action="write", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)
    await log_event(
        action="open", target="artifact", user_challenge_session_id=scope,
        actor_user_id=actor, client_ts=old,
    )

    events = await _events_for(scope)
    assert events[1].client_ts is not None
    assert events[1].client_ts < events[1].server_ts
    assert events[1].seq == 2, "late flush keeps its client_ts but not its place in line"


@pytest.mark.asyncio
async def test_consent_is_snapshotted_per_row(db_ready):
    """Matches EvalResult.consent_research: captured at write time so the export
    is immune to a later toggle."""
    from sqlalchemy import select

    from database import AsyncSessionLocal, User
    from events import log_event

    scope = _solo_scope()
    actor = await _make_user(consent=True)

    await log_event(action="open", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == actor))).scalar_one()
        user.consent_research = False
        await db.commit()

    await log_event(action="open", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)

    assert [e.consent_research for e in await _events_for(scope)] == [True, False]


@pytest.mark.asyncio
async def test_coach_reads_are_distinguishable_from_human_opens(db_ready):
    """A coach-mediated read is attributed to the student but never merged into
    their human opens — they answer different questions (open question 4)."""
    from events import log_event

    scope = _solo_scope()
    actor = await _make_user()

    await log_event(
        action="read_by_coach", target="artifact", actor_kind="coach",
        user_challenge_session_id=scope, actor_user_id=actor,
    )
    await log_event(action="open", target="artifact", user_challenge_session_id=scope, actor_user_id=actor)

    events = await _events_for(scope)
    assert [(e.actor_kind, e.action) for e in events] == [
        ("coach", "read_by_coach"),
        ("student", "open"),
    ]
    assert all(e.actor_user_id == actor for e in events)


@pytest.mark.asyncio
async def test_malformed_events_are_rejected_not_silently_miscategorised(db_ready):
    """A typo'd target would create a category analysis never looks in. Better to
    drop and log loudly than to write a row nobody will find."""
    from events import log_event

    scope = _solo_scope()
    actor = await _make_user()

    assert await log_event(
        action="open", target="artifcat", user_challenge_session_id=scope, actor_user_id=actor
    ) is None
    assert await log_event(
        action="open", target="artifact", actor_kind="robot",
        user_challenge_session_id=scope, actor_user_id=actor,
    ) is None
    # Both scopes set, and neither set: a row must belong to exactly one session.
    assert await log_event(
        action="open", target="artifact", actor_user_id=actor,
        user_challenge_session_id=scope, group_session_id="gs_x",
    ) is None
    assert await log_event(action="open", target="artifact", actor_user_id=actor) is None

    assert await _events_for(scope) == []


@pytest.mark.asyncio
async def test_logging_failure_never_breaks_the_caller(db_ready):
    """log_event is called from the websocket turn path. It must swallow, not raise."""
    from events import log_event

    # payload is JSON-serialised on write; a non-serialisable value fails at commit.
    result = await log_event(
        action="open", target="artifact",
        user_challenge_session_id=_solo_scope(),
        payload={"bad": object()},
    )
    assert result is None


@pytest.mark.asyncio
async def test_solo_turn_save_emits_a_coach_turn_event(db_ready):
    """Coverage check on the real write path: a saved solo turn must land in the
    log. This is the first of the per-surface coverage assertions the build plan
    requires — every path that can display or record study activity gets one, so
    a new surface fails until it is instrumented."""
    from sqlalchemy import select

    from database import AsyncSessionLocal, Conversation, StudyEvent, UserChallengeSession
    from main import _save_turn

    actor = await _make_user()
    async with AsyncSessionLocal() as db:
        conv = Conversation(user_id=actor)
        db.add(conv)
        await db.flush()
        ucs = UserChallengeSession(
            user_id=actor,
            challenge_id=f"ch_{uuid.uuid4().hex[:8]}",
            session_number=1,
            conversation_id=conv.id,
        )
        db.add(ucs)
        await db.commit()
        conv_id, ucs_id = conv.id, ucs.id

    await _save_turn(conv_id, "my prompt", "coach reply", {"scores": {"PEI": 61.5}}, 1)

    async with AsyncSessionLocal() as db:
        events = list((await db.execute(
            select(StudyEvent).where(StudyEvent.user_challenge_session_id == ucs_id)
        )).scalars().all())

    assert len(events) == 1, "a saved turn left no trace in the study log"
    assert (events[0].target, events[0].action) == ("coach", "turn")
    assert events[0].actor_user_id == actor
    assert events[0].payload["pei"] == 61.5
    assert events[0].ref_id is not None, "event must point at the message row it records"


@pytest.mark.asyncio
async def test_orm_columns_all_exist_in_the_database(db_ready):
    """Regression: `create_all` creates missing TABLES but never missing COLUMNS,
    and Alembic does not run against SQLite. Adding Conversation.kind therefore
    left the ORM writing a column the file did not have — which failed at INSERT
    time and surfaced as an empty artifact panel, nowhere near the cause.

    Asserts every mapped column really exists, so the next added column fails
    here instead of in a websocket handler."""
    from sqlalchemy import inspect

    from database import Base, engine

    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        actual = {}
        for name in tables:
            actual[name] = await conn.run_sync(
                lambda c, n=name: {col["name"] for col in inspect(c).get_columns(n)}
            )

    missing = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in actual:
            missing.append(f"{table_name} (whole table)")
            continue
        for col in table.columns:
            if col.name not in actual[table_name]:
                missing.append(f"{table_name}.{col.name}")

    assert not missing, (
        "ORM columns absent from the database: "
        + ", ".join(missing)
        + " — add them to _SQLITE_ADDED_COLUMNS in database.py and to an Alembic migration"
    )


@pytest.mark.asyncio
async def test_no_in_process_lock_orders_the_sequence(db_ready):
    """The allocator must not rely on in-process state.

    A lock only orders writers inside one Uvicorn worker, so a lock-based
    allocator reads as safe while still colliding across workers. The guarantee
    has to come from UNIQUE(scope, seq); this asserts nobody quietly puts the
    lock back."""
    import events

    assert not hasattr(events, "_seq_locks")
    assert not hasattr(events, "_lock_for")


def test_two_event_loops_still_produce_one_gapless_sequence(db_ready):
    """The multi-worker case, as closely as one process can stage it.

    Two threads, each with its own event loop and its own connections, writing
    to one session concurrently — the shape two Uvicorn workers have. Under the
    old in-process lock these two would not have serialised against each other
    at all; the unique constraint is what makes the result 1..20 rather than a
    pile of duplicates."""
    import threading

    from events import log_event

    session_id = _solo_scope()
    actor = asyncio.run(_make_user())

    errors: list[BaseException] = []

    def worker(offset: int):
        async def run():
            await asyncio.gather(*[
                log_event(
                    action="write", target="artifact",
                    user_challenge_session_id=session_id,
                    actor_user_id=actor, payload={"i": offset + i},
                )
                for i in range(10)
            ])
        try:
            asyncio.run(run())
        except BaseException as e:   # surfaced below rather than lost in a thread
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(o,)) for o in (0, 100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"worker raised: {errors!r}"

    rows = asyncio.run(_events_for(session_id))
    seqs = [e.seq for e in rows]
    assert seqs == list(range(1, 21)), f"expected a gapless 1..20, got {seqs}"
    assert len(set(seqs)) == len(seqs), "a repeated seq makes read-before-write unanswerable"
