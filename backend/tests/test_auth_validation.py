"""Register/login validation (422) and duplicate email (400) — no external APIs."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
def asgi_app():
    from challenges import seed_challenges
    from classrooms import seed_demo_classroom
    from database import init_db
    from main import app

    import asyncio

    async def setup():
        await init_db()
        await seed_challenges()
        await seed_demo_classroom()

    asyncio.run(setup())
    return app


@pytest.mark.asyncio
async def test_register_rejects_invalid_email(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "name": "Test User",
                "password": "validpass1a",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_short_password(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/auth/register",
            json={
                "email": f"u_{uuid.uuid4().hex[:8]}@example.com",
                "name": "Test User",
                "password": "short1",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_password_without_letter(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/auth/register",
            json={
                "email": f"u_{uuid.uuid4().hex[:8]}@example.com",
                "name": "Test User",
                "password": "12345678901",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_password_without_digit(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/auth/register",
            json={
                "email": f"u_{uuid.uuid4().hex[:8]}@example.com",
                "name": "Test User",
                "password": "abcdefghijk",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_empty_name(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/auth/register",
            json={
                "email": f"u_{uuid.uuid4().hex[:8]}@example.com",
                "name": "   ",
                "password": "validpass1a",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_success_meets_rules(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/auth/register",
            json={
                "email": f"ok_{uuid.uuid4().hex[:10]}@example.com",
                "name": "Valid User",
                "password": "testpassword123",
            },
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("access_token")
    assert data.get("user_id")


@pytest.mark.asyncio
async def test_register_duplicate_email_400(asgi_app):
    email = f"dup_{uuid.uuid4().hex[:10]}@example.com"
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r1 = await client.post(
            "/auth/register",
            json={"email": email, "name": "First", "password": "testpassword123"},
        )
        assert r1.status_code == 200, r1.text
        r2 = await client.post(
            "/auth/register",
            json={"email": email, "name": "Second", "password": "testpassword456"},
        )
    assert r2.status_code == 400
    assert "already" in (r2.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_login_invalid_email_format_422(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/auth/login",
            json={"email": "bad", "password": "whatever1x"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_login_wrong_password_401(asgi_app):
    email = f"login_{uuid.uuid4().hex[:10]}@example.com"
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        await client.post(
            "/auth/register",
            json={"email": email, "name": "L", "password": "testpassword123"},
        )
        r = await client.post(
            "/auth/login",
            json={"email": email, "password": "wrongpassword9"},
        )
    assert r.status_code == 401
