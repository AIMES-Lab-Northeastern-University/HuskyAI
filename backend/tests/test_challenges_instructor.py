"""POST /challenges authorization and happy path — no WebSocket."""

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
async def test_post_challenges_requires_auth(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        r = await client.post(
            "/challenges",
            json={
                "classroom_id": str(uuid.uuid4()),
                "title": "T",
                "description": "D",
                "category": "General",
                "difficulty": "Beginner",
                "total_sessions": 1,
            },
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_post_challenges_student_forbidden(asgi_app):
    """Student in a section cannot create challenges (not instructor on that room)."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        ins_email = f"ins_{uuid.uuid4().hex[:10]}@example.com"
        reg_i = await client.post(
            "/auth/register",
            json={"email": ins_email, "name": "Inst", "password": "testpassword123"},
        )
        assert reg_i.status_code == 200, reg_i.text
        token_i = reg_i.json()["access_token"]
        hi = {"Authorization": f"Bearer {token_i}"}

        cr = await client.post("/classrooms", json={"name": "Instructor Section"}, headers=hi)
        assert cr.status_code == 200, cr.text
        classroom_id = cr.json()["id"]
        join_code = cr.json()["join_code"]

        stu_email = f"stu_{uuid.uuid4().hex[:10]}@example.com"
        reg_s = await client.post(
            "/auth/register",
            json={"email": stu_email, "name": "Stu", "password": "testpassword123"},
        )
        assert reg_s.status_code == 200, reg_s.text
        token_s = reg_s.json()["access_token"]
        hs = {"Authorization": f"Bearer {token_s}"}

        jr = await client.post("/classrooms/join", json={"code": join_code}, headers=hs)
        assert jr.status_code == 200, jr.text

        r = await client.post(
            "/challenges",
            json={
                "classroom_id": classroom_id,
                "title": "Unauthorized",
                "description": "Should fail",
                "category": "General",
                "difficulty": "Beginner",
                "total_sessions": 1,
            },
            headers=hs,
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_challenges_instructor_201(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        email = f"ic_{uuid.uuid4().hex[:10]}@example.com"
        reg = await client.post(
            "/auth/register",
            json={"email": email, "name": "IC", "password": "testpassword123"},
        )
        assert reg.status_code == 200, reg.text
        token = reg.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        cr = await client.post("/classrooms", json={"name": "Challenge Create Section"}, headers=h)
        assert cr.status_code == 200, cr.text
        classroom_id = cr.json()["id"]

        r = await client.post(
            "/challenges",
            json={
                "classroom_id": classroom_id,
                "title": "Custom Challenge",
                "description": "Created in pytest",
                "category": "Test",
                "difficulty": "Beginner",
                "week": 2,
                "total_sessions": 2,
            },
            headers=h,
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body.get("id")
    assert body.get("title") == "Custom Challenge"
    assert body.get("classroom_id") == classroom_id

    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        lst = await client.get(
            f"/classrooms/{classroom_id}/challenges",
            headers=h,
        )
    assert lst.status_code == 200, lst.text
    titles = [x.get("title") for x in lst.json()]
    assert "Custom Challenge" in titles


@pytest.mark.asyncio
async def test_classroom_analytics_instructor_200_student_forbidden(asgi_app):
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as client:
        ins_email = f"an_{uuid.uuid4().hex[:10]}@example.com"
        reg_i = await client.post(
            "/auth/register",
            json={"email": ins_email, "name": "AnInst", "password": "testpassword123"},
        )
        assert reg_i.status_code == 200, reg_i.text
        hi = {"Authorization": f"Bearer {reg_i.json()['access_token']}"}

        cr = await client.post("/classrooms", json={"name": "Analytics Section"}, headers=hi)
        assert cr.status_code == 200, cr.text
        cid = cr.json()["id"]
        code = cr.json()["join_code"]

        stu_email = f"an_{uuid.uuid4().hex[:10]}@example.com"
        reg_s = await client.post(
            "/auth/register",
            json={"email": stu_email, "name": "AnStu", "password": "testpassword123"},
        )
        assert reg_s.status_code == 200, reg_s.text
        hs = {"Authorization": f"Bearer {reg_s.json()['access_token']}"}
        await client.post("/classrooms/join", json={"code": code}, headers=hs)

        bad = await client.get(f"/classrooms/{cid}/analytics", headers=hs)
        assert bad.status_code == 403

        ok = await client.get(f"/classrooms/{cid}/analytics", headers=hi)
        assert ok.status_code == 200, ok.text
        data = ok.json()
        assert data["classroom_id"] == cid
        assert data["student_count"] == 1
        assert data["total_member_count"] == 2
        assert data["assigned_challenge_count"] == 0
        assert data["sessions_started"] == 0
        assert data["sessions_completed"] == 0
        assert data["students_with_activity"] == 0

        stu_id = reg_s.json()["user_id"]
        r_roster = await client.get(f"/classrooms/{cid}/roster", headers=hi)
        assert r_roster.status_code == 200, r_roster.text
        roster = r_roster.json()
        assert len(roster) == 1
        assert roster[0]["user_id"] == stu_id
        assert roster[0]["email"] == stu_email

        bad_roster = await client.get(f"/classrooms/{cid}/roster", headers=hs)
        assert bad_roster.status_code == 403

        act = await client.get(f"/classrooms/{cid}/students/{stu_id}/activity", headers=hi)
        assert act.status_code == 200, act.text
        body = act.json()
        assert body["classroom_id"] == cid
        assert body["student"]["user_id"] == stu_id
        assert body["challenge_sessions"]["sessions_started"] == 0
        assert body["workspace"]["conversations"] == 0
        assert body["session_rows"] == []

        bad_act = await client.get(f"/classrooms/{cid}/students/{stu_id}/activity", headers=hs)
        assert bad_act.status_code == 403

        fake_stu = str(uuid.uuid4())
        nf = await client.get(f"/classrooms/{cid}/students/{fake_stu}/activity", headers=hi)
        assert nf.status_code == 404


# ── Study settings (Phase 3/6 instructor controls) ───────────────────────────

@pytest.mark.asyncio
async def test_study_settings_reject_an_unrecognised_condition():
    """Pattern-constrained rather than free strings: an unknown value would be
    normalised away by study_policy._clean at read time, leaving a config row
    that says one thing and a session that does another."""
    import uuid as _uuid

    from httpx import ASGITransport, AsyncClient

    from auth import create_token
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge,
                          ClassroomMembership, User)
    from main import app

    async with AsyncSessionLocal() as db:
        inst = User(email=f"ss_{_uuid.uuid4().hex[:8]}@e.com", name="I", password_hash="x")
        db.add(inst); await db.flush()
        room = Classroom(name="SS", join_code=_uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=inst.id)
        ch = Challenge(title="SS", description="d", category="c", difficulty="e",
                       sessions_data=[{}])
        db.add_all([room, ch]); await db.flush()
        db.add(ClassroomMembership(user_id=inst.id, classroom_id=room.id, role="instructor"))
        cc = ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id)
        db.add(cc); await db.commit()
        cc_id, tok = cc.id, create_token(inst.id)

    hdr = {"Authorization": f"Bearer {tok}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        bad = await c.patch(f"/classrooms/assignments/{cc_id}/study",
                            json={"coach_prominence": "very_loud"}, headers=hdr)
        assert bad.status_code == 422

        ok = await c.patch(f"/classrooms/assignments/{cc_id}/study",
                           json={"study_arm": "collab_coach_artifact",
                                 "coach_prominence": "isolated",
                                 "verification_policy": "round_robin"}, headers=hdr)
        assert ok.status_code == 200, ok.text
        assert ok.json()["coach_prominence"] == "isolated"


@pytest.mark.asyncio
async def test_only_a_section_instructor_can_change_study_settings():
    import uuid as _uuid

    from httpx import ASGITransport, AsyncClient

    from auth import create_token
    from database import (AsyncSessionLocal, Challenge, Classroom, ClassroomChallenge, User)
    from main import app

    async with AsyncSessionLocal() as db:
        owner = User(email=f"so_{_uuid.uuid4().hex[:8]}@e.com", name="O", password_hash="x")
        other = User(email=f"sx_{_uuid.uuid4().hex[:8]}@e.com", name="X", password_hash="x")
        db.add_all([owner, other]); await db.flush()
        room = Classroom(name="SS2", join_code=_uuid.uuid4().hex[:8].upper(),
                         instructor_user_id=owner.id)
        ch = Challenge(title="SS2", description="d", category="c", difficulty="e",
                       sessions_data=[{}])
        db.add_all([room, ch]); await db.flush()
        cc = ClassroomChallenge(classroom_id=room.id, challenge_id=ch.id)
        db.add(cc); await db.commit()
        cc_id, tok = cc.id, create_token(other.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(f"/classrooms/assignments/{cc_id}/study",
                          json={"study_arm": "collab_coach_artifact"},
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
