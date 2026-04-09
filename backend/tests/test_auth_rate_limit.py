"""Auth rate limit: unit test + HTTP 429 when AUTH_RATE_TEST_MAX is low."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from rate_limit import SlidingWindowLimiter, clear_auth_rate_buckets


def test_sliding_window_limiter_blocks_third_when_max_two():
    lim = SlidingWindowLimiter(window_sec=60.0)
    assert lim.hit("k", 2) is True
    assert lim.hit("k", 2) is True
    assert lim.hit("k", 2) is False
    lim.clear()
    assert lim.hit("k", 2) is True


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
async def test_register_returns_429_after_rate_limit(asgi_app, monkeypatch):
    monkeypatch.setenv("AUTH_RATE_TEST_MAX", "2")
    clear_auth_rate_buckets()
    try:
        async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
            r1 = await client.post(
                "/auth/register",
                json={
                    "email": f"rl1_{uuid.uuid4().hex[:10]}@example.com",
                    "name": "R1",
                    "password": "testpassword123",
                },
            )
            r2 = await client.post(
                "/auth/register",
                json={
                    "email": f"rl2_{uuid.uuid4().hex[:10]}@example.com",
                    "name": "R2",
                    "password": "testpassword123",
                },
            )
            r3 = await client.post(
                "/auth/register",
                json={
                    "email": f"rl3_{uuid.uuid4().hex[:10]}@example.com",
                    "name": "R3",
                    "password": "testpassword123",
                },
            )
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert r3.status_code == 429, r3.text
        assert r3.json().get("detail")
    finally:
        monkeypatch.delenv("AUTH_RATE_TEST_MAX", raising=False)
        clear_auth_rate_buckets()
