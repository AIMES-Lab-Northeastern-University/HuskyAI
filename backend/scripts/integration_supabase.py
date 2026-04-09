#!/usr/bin/env python3
"""
End-to-end check against the configured DATABASE_URL / SUPABASE_DB_* (not pytest SQLite).

  cd backend
  python scripts/integration_supabase.py

Steps: init_db + seed_challenges + seed_demo_classroom, then HTTP flows, then row counts from Postgres.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

_backend = Path(__file__).resolve().parents[1]
load_dotenv(_backend / ".env")
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


async def main() -> int:
    from db_config import resolve_database_url
    from sqlalchemy import func, select

    url = resolve_database_url()
    if "sqlite" in url.lower():
        print("Refusing to run: DATABASE_URL resolves to SQLite. Set SUPABASE_DB_* or DATABASE_URL for Postgres.")
        return 1

    from database import (
        init_db,
        AsyncSessionLocal,
        User,
        Challenge,
        Classroom,
        ClassroomMembership,
        ClassroomChallenge,
        UserChallengeSession,
    )
    from challenges import seed_challenges
    from classrooms import seed_demo_classroom
    from httpx import ASGITransport, AsyncClient

    print("1) init_db() + seed_challenges() + seed_demo_classroom() ...")
    await init_db()
    await seed_challenges()
    await seed_demo_classroom()

    from main import app

    seed_code = os.getenv("SEED_CLASSROOM_CODE", "HUSKYDMX").strip().upper()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
        print("2) GET /health ...")
        r = await client.get("/health")
        assert r.status_code == 200, r.text

        email_a = f"int_a_{uuid.uuid4().hex[:10]}@example.com"
        email_b = f"int_b_{uuid.uuid4().hex[:10]}@example.com"
        email_c = f"int_c_{uuid.uuid4().hex[:10]}@example.com"

        print("3) POST /auth/register (user A, no class) ...")
        reg_a = await client.post(
            "/auth/register",
            json={"email": email_a, "name": "Integration A", "password": "TestPass123!"},
        )
        assert reg_a.status_code == 200, reg_a.text
        token_a = reg_a.json()["access_token"]

        print("4) GET /challenges (A, not in any section) -> expect [] ...")
        ch_a = await client.get("/challenges", headers={"Authorization": f"Bearer {token_a}"})
        assert ch_a.status_code == 200, ch_a.text
        assert ch_a.json() == [], f"Expected no challenges before joining a class; got {ch_a.json()}"

        print("5) POST /auth/register (B) + join seed section ...")
        reg_b = await client.post(
            "/auth/register",
            json={"email": email_b, "name": "Integration B", "password": "TestPass123!"},
        )
        assert reg_b.status_code == 200, reg_b.text
        token_b = reg_b.json()["access_token"]
        jr = await client.post(
            "/classrooms/join",
            json={"code": seed_code},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert jr.status_code == 200, jr.text
        assert jr.json().get("status") in ("joined", "already_member"), jr.text

        print("6) GET /challenges (B, in seed section) -> expect >= 1 ...")
        ch_b = await client.get("/challenges", headers={"Authorization": f"Bearer {token_b}"})
        assert ch_b.status_code == 200, ch_b.text
        challenges = ch_b.json()
        assert isinstance(challenges, list) and len(challenges) >= 1, "Expected assigned challenges after join"

        print("7) Instructor creates empty section; student C joins -> still no challenges ...")
        cr = await client.post(
            "/classrooms",
            json={"name": "Integration Test Section"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert cr.status_code == 200, cr.text
        join_code = cr.json()["join_code"]

        reg_c = await client.post(
            "/auth/register",
            json={"email": email_c, "name": "Integration C", "password": "TestPass123!"},
        )
        assert reg_c.status_code == 200, reg_c.text
        token_c = reg_c.json()["access_token"]
        jrc = await client.post(
            "/classrooms/join",
            json={"code": join_code},
            headers={"Authorization": f"Bearer {token_c}"},
        )
        assert jrc.status_code == 200, jrc.text
        ch_c = await client.get("/challenges", headers={"Authorization": f"Bearer {token_c}"})
        assert ch_c.status_code == 200, ch_c.text
        assert ch_c.json() == [], "New section has no challenge assignments yet"

        print("8) GET /classrooms/me ...")
        me = await client.get("/classrooms/me", headers={"Authorization": f"Bearer {token_b}"})
        assert me.status_code == 200, me.text
        assert len(me.json()) >= 1

    print("9) Row counts in DB ...")
    async with AsyncSessionLocal() as db:
        n_users = await db.scalar(select(func.count()).select_from(User))
        n_ch = await db.scalar(select(func.count()).select_from(Challenge))
        n_cls = await db.scalar(select(func.count()).select_from(Classroom))
        n_mem = await db.scalar(select(func.count()).select_from(ClassroomMembership))
        n_link = await db.scalar(select(func.count()).select_from(ClassroomChallenge))
        n_ucs = await db.scalar(select(func.count()).select_from(UserChallengeSession))

    print(
        f"    users={n_users}, challenges={n_ch}, classrooms={n_cls}, "
        f"memberships={n_mem}, classroom_challenges={n_link}, user_challenge_sessions={n_ucs}"
    )
    print("OK: integration finished; data should be visible in Supabase Table Editor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
