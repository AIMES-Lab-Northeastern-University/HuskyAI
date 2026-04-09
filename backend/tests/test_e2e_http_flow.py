"""
Pre-pilot HTTP path (no WebSocket): register → section → assign challenge →
student join → list challenges → start session → challenge detail shows in_progress.

Full chat + eval is covered separately (scripts/e2e_website_flow.py with API keys).
"""

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
async def test_e2e_http_register_section_challenge_join_start(asgi_app):
    tag = uuid.uuid4().hex[:10]

    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        # Instructor
        reg_i = await client.post(
            "/auth/register",
            json={
                "email": f"e2e_ins_{tag}@example.com",
                "name": "E2E Instructor",
                "password": "testpassword123",
            },
        )
        assert reg_i.status_code == 200, reg_i.text
        tok_i = reg_i.json()["access_token"]
        hi = {"Authorization": f"Bearer {tok_i}"}

        sec = await client.post("/classrooms", json={"name": f"E2E Section {tag}"}, headers=hi)
        assert sec.status_code == 200, sec.text
        classroom_id = sec.json()["id"]
        join_code = sec.json()["join_code"]

        ch = await client.post(
            "/challenges",
            json={
                "classroom_id": classroom_id,
                "title": f"E2E Challenge {tag}",
                "description": "End-to-end HTTP test challenge",
                "category": "E2E",
                "difficulty": "Beginner",
                "total_sessions": 1,
            },
            headers=hi,
        )
        assert ch.status_code == 201, ch.text
        challenge_id = ch.json()["id"]

        # Student
        reg_s = await client.post(
            "/auth/register",
            json={
                "email": f"e2e_stu_{tag}@example.com",
                "name": "E2E Student",
                "password": "testpassword123",
            },
        )
        assert reg_s.status_code == 200, reg_s.text
        tok_s = reg_s.json()["access_token"]
        hs = {"Authorization": f"Bearer {tok_s}"}

        join = await client.post("/classrooms/join", json={"code": join_code}, headers=hs)
        assert join.status_code == 200, join.text

        lst = await client.get("/challenges", headers=hs)
        assert lst.status_code == 200, lst.text
        challenges = lst.json()
        ids = {c["id"] for c in challenges}
        assert challenge_id in ids

        mine = next(c for c in challenges if c["id"] == challenge_id)
        assert mine.get("title") == f"E2E Challenge {tag}"

        start = await client.post(
            f"/challenges/{challenge_id}/sessions/1/start",
            headers=hs,
        )
        assert start.status_code == 200, start.text
        assert start.json().get("status") == "in_progress"

        detail = await client.get(f"/challenges/{challenge_id}", headers=hs)
        assert detail.status_code == 200, detail.text
        sessions = detail.json().get("sessions") or []
        assert len(sessions) >= 1
        assert sessions[0].get("status") == "in_progress"
