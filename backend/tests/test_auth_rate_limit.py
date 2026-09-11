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
    await clear_auth_rate_buckets()
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
        await clear_auth_rate_buckets()


@pytest.mark.asyncio
async def test_falls_back_to_local_counter_when_redis_is_down(monkeypatch):
    """Redis configured but unreachable must degrade to the per-process counter --
    not fail open (no limiting at all) and not fail closed (nobody can log in)."""
    import rate_limit

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")  # nothing listening
    rate_limit._shared.clear()  # force a rebuild against the dead URL
    await clear_auth_rate_buckets()

    local = rate_limit.SlidingWindowLimiter(60.0)
    try:
        # Still limits: two allowed, third refused, via the local fallback.
        assert await rate_limit._allowed("auth", local, "1.2.3.4", 2) is True
        assert await rate_limit._allowed("auth", local, "1.2.3.4", 2) is True
        assert await rate_limit._allowed("auth", local, "1.2.3.4", 2) is False
    finally:
        rate_limit._shared.clear()
        monkeypatch.delenv("REDIS_URL", raising=False)
