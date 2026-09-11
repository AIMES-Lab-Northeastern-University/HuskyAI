"""Instructor authoring of shared-artifact sections.

Before this, sections could only be created by writing JSON into
Challenge.sessions_data by hand -- there was no API surface and no UI, so the
ArtifactPanel was structurally always empty in a real deployment.

The load-bearing property is that what the API writes is exactly what
main._challenge_sections reads back. They are in different modules with
different shapes (validated Pydantic models vs. a permissive JSON reader), so
the round trip gets an explicit test rather than being assumed.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
def asgi_app():
    import asyncio

    from challenges import seed_challenges
    from classrooms import seed_demo_classroom
    from database import init_db
    from main import app

    async def setup():
        await init_db()
        await seed_challenges()
        await seed_demo_classroom()

    asyncio.run(setup())
    return app


SECTIONS = [
    {"key": "root-causes", "title": "Root causes", "prompt": "why?"},
    {"key": "fix-plan", "title": "Fix plan", "prompt": "what changes?"},
]


async def _instructor(client):
    """Register an instructor with a classroom. Returns (headers, classroom_id)."""
    email = f"sec_{uuid.uuid4().hex[:10]}@example.com"
    reg = await client.post(
        "/auth/register",
        json={"email": email, "name": "Inst", "password": "testpassword123"},
    )
    assert reg.status_code == 200, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    cr = await client.post("/classrooms", json={"name": "Sec"}, headers=headers)
    assert cr.status_code == 200, cr.text
    return headers, cr.json()["id"]


async def _create(client, headers, classroom_id, *, sections=None, total_sessions=3):
    body = {
        "classroom_id": classroom_id,
        "title": f"Sections {uuid.uuid4().hex[:6]}",
        "description": "D",
        "category": "General",
        "difficulty": "Beginner",
        "total_sessions": total_sessions,
    }
    if sections is not None:
        body["sections"] = sections
    return await client.post("/challenges", json=body, headers=headers)


@pytest.mark.asyncio
async def test_sections_are_written_into_every_session(asgi_app):
    """Flat authoring, per-session storage: carry-forward matches on key across
    sessions, so a section missing from one session would silently start empty."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        r = await _create(client, headers, classroom_id, sections=SECTIONS, total_sessions=3)
        assert r.status_code == 201, r.text
        cid = r.json()["id"]

    from database import AsyncSessionLocal, Challenge

    async with AsyncSessionLocal() as db:
        ch = await db.get(Challenge, cid)
        assert len(ch.sessions_data) == 3
        for sd in ch.sessions_data:
            assert [s["key"] for s in sd["sections"]] == ["root-causes", "fix-plan"]
            # The generated session fields survive untouched.
            for key in ("title", "goal", "brief", "seed_question", "system_prompt_extra"):
                assert sd.get(key), f"{key} was lost when sections were applied"


@pytest.mark.asyncio
async def test_what_the_api_writes_is_what_the_reader_reads(asgi_app):
    """The round trip across the module boundary."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        r = await _create(client, headers, classroom_id, sections=SECTIONS)
        cid = r.json()["id"]

    import main
    from database import AsyncSessionLocal, Challenge

    async with AsyncSessionLocal() as db:
        ch = await db.get(Challenge, cid)
        parsed = main._challenge_sections(ch.sessions_data[0])

    assert [s["key"] for s in parsed] == ["root-causes", "fix-plan"]
    assert [s["title"] for s in parsed] == ["Root causes", "Fix plan"]
    assert parsed[0]["prompt"] == "why?"


@pytest.mark.asyncio
async def test_duplicate_keys_are_rejected_not_silently_dropped(asgi_app):
    """_challenge_sections drops duplicates when reading, which is right for a
    reader and wrong for an author -- they would save two and find one gone."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        r = await _create(client, headers, classroom_id, sections=[
            {"key": "dup", "title": "First", "prompt": ""},
            {"key": "dup", "title": "Second", "prompt": ""},
        ])
        assert r.status_code == 400, r.text
        assert "dup" in r.json()["detail"]
        assert "unique" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_key_that_would_break_a_lock_name_is_rejected(asgi_app):
    """Keys travel into Redis lock names and websocket payloads."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        for bad in ("has space", "has:colon", "", "-leading"):
            r = await _create(client, headers, classroom_id,
                              sections=[{"key": bad, "title": "T", "prompt": ""}])
            assert r.status_code == 422, f"key {bad!r} was accepted: {r.text}"


@pytest.mark.asyncio
async def test_no_sections_means_no_artifact(asgi_app):
    """The feature stays opt-in: an ordinary challenge is unaffected."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        r = await _create(client, headers, classroom_id)
        assert r.status_code == 201, r.text
        cid = r.json()["id"]

    import main
    from database import AsyncSessionLocal, Challenge

    async with AsyncSessionLocal() as db:
        ch = await db.get(Challenge, cid)
        assert "sections" not in ch.sessions_data[0]
        assert main._challenge_sections(ch.sessions_data[0]) == []


@pytest.mark.asyncio
async def test_edit_replaces_sections_and_preserves_the_rest(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        cid = (await _create(client, headers, classroom_id, sections=SECTIONS)).json()["id"]

        r = await client.patch(f"/challenges/{cid}", headers=headers, json={
            "sections": [{"key": "only-one", "title": "Only one", "prompt": "p"}],
        })
        assert r.status_code == 200, r.text
        assert [s["key"] for s in r.json()["sections"]] == ["only-one"]

    from database import AsyncSessionLocal, Challenge

    async with AsyncSessionLocal() as db:
        ch = await db.get(Challenge, cid)
        for sd in ch.sessions_data:
            assert [s["key"] for s in sd["sections"]] == ["only-one"]
            assert sd["goal"], "session prose was clobbered by a sections edit"


@pytest.mark.asyncio
async def test_an_explicit_empty_list_removes_the_artifact(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        cid = (await _create(client, headers, classroom_id, sections=SECTIONS)).json()["id"]

        r = await client.patch(f"/challenges/{cid}", headers=headers, json={"sections": []})
        assert r.status_code == 200, r.text
        assert r.json()["sections"] == []

    from database import AsyncSessionLocal, Challenge

    async with AsyncSessionLocal() as db:
        ch = await db.get(Challenge, cid)
        assert all("sections" not in sd for sd in ch.sessions_data)


@pytest.mark.asyncio
async def test_an_unrelated_edit_leaves_sections_alone(asgi_app):
    """Absent field vs. explicit [] -- the same distinction the timer fields make."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        cid = (await _create(client, headers, classroom_id, sections=SECTIONS)).json()["id"]

        r = await client.patch(f"/challenges/{cid}", headers=headers,
                               json={"title": "Renamed"})
        assert r.status_code == 200, r.text
        assert [s["key"] for s in r.json()["sections"]] == ["root-causes", "fix-plan"]


@pytest.mark.asyncio
async def test_get_challenge_exposes_sections_for_the_editor(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        headers, classroom_id = await _instructor(client)
        cid = (await _create(client, headers, classroom_id, sections=SECTIONS)).json()["id"]

        r = await client.get(f"/challenges/{cid}", headers=headers)
        assert r.status_code == 200, r.text
        assert [s["key"] for s in r.json()["sections"]] == ["root-causes", "fix-plan"]


# --------------------------------------------------------------------------
# Seed data and the insert-only seeder
# --------------------------------------------------------------------------

def test_a_seeded_challenge_actually_declares_sections():
    """Without this the ArtifactPanel has nothing to show in a running app."""
    import asyncio

    import main
    from challenges import SEED_CHALLENGES, _seed_challenge_id, seed_challenges
    from database import AsyncSessionLocal, Challenge, init_db

    with_sections = [d for d in SEED_CHALLENGES if d.get("sections")]
    assert with_sections, "no seed challenge declares artifact sections"

    async def go():
        await init_db()
        await seed_challenges()
        async with AsyncSessionLocal() as db:
            ch = await db.get(Challenge, _seed_challenge_id(with_sections[0]["title"]))
            assert ch is not None
            for sd in ch.sessions_data:
                parsed = main._challenge_sections(sd)
                assert len(parsed) == len(with_sections[0]["sections"])

    asyncio.run(go())


def test_backfill_reaches_an_already_seeded_challenge():
    """The seeder skips existing titles entirely, so newly-declared sections
    would never reach a deployed database without this path."""
    import asyncio

    from challenges import (SEED_CHALLENGES, _seed_challenge_id,
                            backfill_seed_sections, seed_challenges)
    from database import AsyncSessionLocal, Challenge, init_db

    target = [d for d in SEED_CHALLENGES if d.get("sections")][0]

    async def go():
        await init_db()
        await seed_challenges()
        cid = _seed_challenge_id(target["title"])

        # Simulate a database seeded before sections existed.
        async with AsyncSessionLocal() as db:
            ch = await db.get(Challenge, cid)
            ch.sessions_data = [
                {k: v for k, v in sd.items() if k != "sections"}
                for sd in ch.sessions_data
            ]
            await db.commit()
        async with AsyncSessionLocal() as db:
            ch = await db.get(Challenge, cid)
            assert all("sections" not in sd for sd in ch.sessions_data)

        patched = await backfill_seed_sections()
        assert patched >= 1

        async with AsyncSessionLocal() as db:
            ch = await db.get(Challenge, cid)
            for sd in ch.sessions_data:
                assert [s["key"] for s in sd["sections"]] == \
                    [s["key"] for s in target["sections"]]

        # Idempotent: a second run changes nothing.
        assert await backfill_seed_sections() == 0

    asyncio.run(go())


def test_backfill_never_reverts_an_instructor_edit():
    async def go():
        from challenges import (SEED_CHALLENGES, _seed_challenge_id,
                                backfill_seed_sections, seed_challenges)
        from database import AsyncSessionLocal, Challenge, init_db

        await init_db()
        await seed_challenges()
        target = [d for d in SEED_CHALLENGES if d.get("sections")][0]
        cid = _seed_challenge_id(target["title"])

        async with AsyncSessionLocal() as db:
            ch = await db.get(Challenge, cid)
            ch.sessions_data = [
                {**sd, "sections": [{"key": "authored", "title": "Authored", "prompt": ""}]}
                for sd in ch.sessions_data
            ]
            await db.commit()

        await backfill_seed_sections()

        async with AsyncSessionLocal() as db:
            ch = await db.get(Challenge, cid)
            assert [s["key"] for s in ch.sessions_data[0]["sections"]] == ["authored"], (
                "backfill overwrote sections an instructor had edited"
            )

    import asyncio
    asyncio.run(go())
