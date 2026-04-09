"""Lightweight API smoke tests — no external API keys required."""

import asyncio
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
def asgi_app():
    """Import app after conftest sets DATABASE_URL; run DB init + seeds (lifespan may not run under httpx)."""
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


@pytest.mark.asyncio
async def test_health(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_register_and_join_classroom_requires_auth_for_join(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        email_a = f"smoke_a_{uuid.uuid4().hex[:12]}@example.com"
        reg_a = await client.post(
            "/auth/register",
            json={
                "email": email_a,
                "name": "Smoke Instructor",
                "password": "testpassword123",
            },
        )
        assert reg_a.status_code == 200, reg_a.text
        token_a = reg_a.json()["access_token"]

        create = await client.post(
            "/classrooms",
            json={"name": "Smoke Test Section"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert create.status_code == 200, create.text
        code = create.json()["join_code"]

        r401 = await client.post("/classrooms/join", json={"code": code})
        assert r401.status_code == 401

        email_b = f"smoke_b_{uuid.uuid4().hex[:12]}@example.com"
        reg_b = await client.post(
            "/auth/register",
            json={
                "email": email_b,
                "name": "Smoke Student",
                "password": "testpassword123",
            },
        )
        assert reg_b.status_code == 200, reg_b.text
        token_b = reg_b.json()["access_token"]

        r_join = await client.post(
            "/classrooms/join",
            json={"code": code},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_join.status_code == 200, r_join.text
        assert r_join.json()["status"] == "joined"


@pytest.mark.asyncio
async def test_challenges_empty_until_class_with_assignments(asgi_app):
    """Users see no challenges until they join a section that has assigned challenges."""
    seed_code = os.getenv("SEED_CLASSROOM_CODE", "HUSKYDMX")
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        email = f"smoke_ch_{uuid.uuid4().hex[:12]}@example.com"
        reg = await client.post(
            "/auth/register",
            json={"email": email, "name": "Smoke Challenges", "password": "testpassword123"},
        )
        assert reg.status_code == 200, reg.text
        token = reg.json()["access_token"]

        empty = await client.get("/challenges", headers={"Authorization": f"Bearer {token}"})
        assert empty.status_code == 200
        assert empty.json() == []

        jr = await client.post(
            "/classrooms/join",
            json={"code": seed_code},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert jr.status_code == 200, jr.text

        filled = await client.get("/challenges", headers={"Authorization": f"Bearer {token}"})
        assert filled.status_code == 200
        assert len(filled.json()) >= 1


@pytest.mark.asyncio
async def test_classrooms_browse_requires_auth(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.get("/classrooms/browse")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_classrooms_browse_lists_seed_section(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        email = f"smoke_br_{uuid.uuid4().hex[:12]}@example.com"
        reg = await client.post(
            "/auth/register",
            json={"email": email, "name": "Smoke Browse", "password": "testpassword123"},
        )
        assert reg.status_code == 200, reg.text
        token = reg.json()["access_token"]
        r = await client.get("/classrooms/browse", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        assert any("Husky" in (item.get("name") or "") for item in rows), rows
