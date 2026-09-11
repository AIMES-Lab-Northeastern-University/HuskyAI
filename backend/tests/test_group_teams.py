"""Instructor team management for group challenges (Phase 2 of the 2026-06-21 redesign).

Covers: creating a challenge in group mode, the group-mode toggle, and team
CRUD + assignment with its constraints (enrolled-only, one team per challenge,
capacity, solo-mode guard, instructor-only).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
def asgi_app():
    import asyncio

    from challenges import seed_challenges
    from database import init_db
    from main import app

    async def setup():
        await init_db()
        await seed_challenges()

    asyncio.run(setup())
    return app


async def _register(client, name="u") -> dict:
    email = f"{name}_{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/auth/register",
        json={"email": email, "name": name, "password": "testpassword123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _uid(client, headers) -> str:
    r = await client.get("/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def _instructor_classroom(client):
    h = await _register(client, "ins")
    cr = await client.post("/classrooms", json={"name": "Sec"}, headers=h)
    assert cr.status_code == 200, cr.text
    return h, cr.json()["id"], cr.json()["join_code"]


async def _enroll(client, join_code):
    h = await _register(client, "stu")
    jr = await client.post("/classrooms/join", json={"code": join_code}, headers=h)
    assert jr.status_code == 200, jr.text
    return h, await _uid(client, h)


async def _group_challenge(client, h, classroom_id, team_min=2, team_max=4):
    r = await client.post(
        "/challenges",
        json={
            "classroom_id": classroom_id,
            "title": "Group C",
            "description": "d",
            "category": "Test",
            "difficulty": "Beginner",
            "total_sessions": 1,
            "mode": "group",
            "team_min": team_min,
            "team_max": team_max,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["mode"] == "group"
    return r.json()["id"]


@pytest.mark.asyncio
async def test_solo_challenge_blocks_team_creation(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        h, cid, _ = await _instructor_classroom(client)
        # Default mode is solo when omitted.
        r = await client.post(
            "/challenges",
            json={
                "classroom_id": cid,
                "title": "Solo C",
                "description": "d",
                "category": "Test",
                "difficulty": "Beginner",
                "total_sessions": 1,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        assert r.json()["mode"] == "solo"
        chid = r.json()["id"]

        t = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams", json={}, headers=h)
        assert t.status_code == 409, t.text

        # Flip to group mode, then team creation works.
        pm = await client.patch(
            f"/classrooms/{cid}/challenges/{chid}/group-mode",
            json={"mode": "group", "team_min": 2, "team_max": 3},
            headers=h,
        )
        assert pm.status_code == 200, pm.text
        assert pm.json()["mode"] == "group" and pm.json()["team_max"] == 3

        t2 = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams", json={}, headers=h)
        assert t2.status_code == 201, t2.text
        assert t2.json()["max_members"] == 3


@pytest.mark.asyncio
async def test_team_assignment_flow_and_constraints(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        h, cid, code = await _instructor_classroom(client)
        chid = await _group_challenge(client, h, cid)

        hs1, u1 = await _enroll(client, code)
        hs2, u2 = await _enroll(client, code)

        # Two unassigned students, no teams yet.
        lst = await client.get(f"/classrooms/{cid}/challenges/{chid}/teams", headers=h)
        assert lst.status_code == 200, lst.text
        assert lst.json()["teams"] == []
        assert {s["user_id"] for s in lst.json()["unassigned_students"]} == {u1, u2}

        team1 = (await client.post(f"/classrooms/{cid}/challenges/{chid}/teams", json={"name": "Team 1"}, headers=h)).json()
        tid1 = team1["id"]

        # Assign u1, idempotent re-add, then u2.
        a1 = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid1}/members", json={"user_id": u1}, headers=h)
        assert a1.status_code == 200 and a1.json()["status"] == "added"
        again = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid1}/members", json={"user_id": u1}, headers=h)
        assert again.json()["status"] == "already_member"
        a2 = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid1}/members", json={"user_id": u2}, headers=h)
        assert len(a2.json()["members"]) == 2

        # Now both are assigned, none unassigned.
        lst2 = await client.get(f"/classrooms/{cid}/challenges/{chid}/teams", headers=h)
        assert lst2.json()["unassigned_students"] == []

        # A second team; u1 cannot also join it (one team per challenge).
        tid2 = (await client.post(f"/classrooms/{cid}/challenges/{chid}/teams", json={}, headers=h)).json()["id"]
        dup = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid2}/members", json={"user_id": u1}, headers=h)
        assert dup.status_code == 409, dup.text

        # Remove u2 from team1 → frees them up.
        rem = await client.delete(f"/classrooms/{cid}/challenges/{chid}/teams/{tid1}/members/{u2}", headers=h)
        assert rem.status_code == 200 and len(rem.json()["members"]) == 1

        # Delete team2.
        d = await client.delete(f"/classrooms/{cid}/challenges/{chid}/teams/{tid2}", headers=h)
        assert d.status_code == 200 and d.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_non_enrolled_student_rejected(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        h, cid, code = await _instructor_classroom(client)
        chid = await _group_challenge(client, h, cid)
        tid = (await client.post(f"/classrooms/{cid}/challenges/{chid}/teams", json={}, headers=h)).json()["id"]

        # A student who never joined this section.
        outsider_h = await _register(client, "out")
        out_uid = await _uid(client, outsider_h)
        r = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid}/members", json={"user_id": out_uid}, headers=h)
        assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_team_capacity_enforced(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        h, cid, code = await _instructor_classroom(client)
        chid = await _group_challenge(client, h, cid, team_min=2, team_max=2)
        tid = (await client.post(f"/classrooms/{cid}/challenges/{chid}/teams", json={}, headers=h)).json()["id"]

        _, u1 = await _enroll(client, code)
        _, u2 = await _enroll(client, code)
        _, u3 = await _enroll(client, code)
        assert (await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid}/members", json={"user_id": u1}, headers=h)).status_code == 200
        assert (await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid}/members", json={"user_id": u2}, headers=h)).status_code == 200
        full = await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid}/members", json={"user_id": u3}, headers=h)
        assert full.status_code == 409, full.text


@pytest.mark.asyncio
async def test_student_sees_group_entry(asgi_app):
    """A student's challenge view exposes group_mode and their assigned team."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        h, cid, code = await _instructor_classroom(client)
        chid = await _group_challenge(client, h, cid)
        hs1, u1 = await _enroll(client, code)
        hs2, _u2 = await _enroll(client, code)

        # Group mode is visible; no team assigned yet.
        d0 = await client.get(f"/challenges/{chid}", headers=hs1)
        assert d0.status_code == 200, d0.text
        assert d0.json()["group_mode"] is True
        assert d0.json()["group"] is None

        # The challenges list also flags it.
        lst = await client.get("/challenges", headers=hs1)
        assert any(c["id"] == chid and c.get("group_mode") for c in lst.json())

        # Assign u1 → u1 now sees their team; u2 still unassigned.
        tid = (await client.post(f"/classrooms/{cid}/challenges/{chid}/teams", json={}, headers=h)).json()["id"]
        await client.post(f"/classrooms/{cid}/challenges/{chid}/teams/{tid}/members", json={"user_id": u1}, headers=h)

        d1 = await client.get(f"/challenges/{chid}", headers=hs1)
        assert d1.json()["group"]["group_id"] == tid
        d2 = await client.get(f"/challenges/{chid}", headers=hs2)
        assert d2.json()["group"] is None


@pytest.mark.asyncio
async def test_non_instructor_forbidden(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        h, cid, code = await _instructor_classroom(client)
        chid = await _group_challenge(client, h, cid)
        hs, _ = await _enroll(client, code)
        # An enrolled student is not an instructor → cannot manage teams.
        r = await client.get(f"/classrooms/{cid}/challenges/{chid}/teams", headers=hs)
        assert r.status_code == 403, r.text
