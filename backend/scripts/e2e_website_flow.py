#!/usr/bin/env python3
"""
Simulate the real website: HTTP register, classroom, challenges, start session,
then WebSocket one turn (Gemini + eval) — same paths the React app uses.

  cd backend
  python scripts/e2e_website_flow.py

Requires .env with Supabase DB + GOOGLE_API_KEY + OPENAI_* for full chat/eval.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

_backend = Path(__file__).resolve().parents[1]
load_dotenv(_backend / ".env")
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


def main() -> int:
    from db_config import resolve_database_url

    if "sqlite" in resolve_database_url().lower():
        print("Set SUPABASE_DB_* or DATABASE_URL (Postgres). Refusing SQLite for this E2E.")
        return 1

    from starlette.testclient import TestClient

    from main import app

    tag = uuid.uuid4().hex[:8]
    email_stu = f"e2e_stu_{tag}@example.com"
    password = "E2eTest_Pass_9"
    seed_join = os.getenv("SEED_CLASSROOM_CODE", "HUSKYDMX").strip().upper()

    print("--- HTTP: same routes as frontend (VITE_API_URL) ---")

    with TestClient(app, raise_server_exceptions=True) as client:
        assert client.get("/health").json().get("status") == "ok"

        r = client.post(
            "/auth/register",
            json={"email": email_stu, "name": "E2E Student", "password": password},
        )
        assert r.status_code == 200, r.text
        stu = r.json()
        token_stu = stu["access_token"]
        user_stu_id = stu["user_id"]
        h_stu = {"Authorization": f"Bearer {token_stu}"}

        r = client.post("/classrooms/join", json={"code": seed_join}, headers=h_stu)
        assert r.status_code == 200, r.text
        assert r.json().get("status") in ("joined", "already_member")
        print(f"  joined seed section code={seed_join!r}")

        r = client.get("/challenges", headers=h_stu)
        assert r.status_code == 200, r.text
        challenges = r.json()
        assert len(challenges) >= 1, "No challenges — run seed or check DB"
        ch_id = challenges[0]["id"]
        ch_title = challenges[0].get("title", "?")
        print(f"  challenge[0] id={ch_id} title={ch_title!r}")

        r = client.post(f"/challenges/{ch_id}/sessions/1/start", headers=h_stu)
        assert r.status_code == 200, r.text
        sess = r.json()
        print(f"  started session 1 status={sess.get('status')}")

        ws_url = f"/ws?token={token_stu}&challenge_id={ch_id}&session_num=1"
        print("--- WebSocket: one user message (same as Workspace) ---")

        eval_payload = None
        chat_error = None
        with client.websocket_connect(ws_url) as ws:
            # Optional first frame: challenge_context
            first = ws.receive_json()
            if first.get("type") == "challenge_context":
                print(f"  recv challenge_context title={first.get('data', {}).get('title', '')[:50]!r}")

            ws.send_json({"type": "message", "content": "E2E: one structured question — list 2 debugging steps for a 500 error."})

            deadline = time.time() + 180
            while time.time() < deadline:
                msg = ws.receive_json()
                t = msg.get("type")
                if t == "typing":
                    print("  recv typing")
                elif t == "stream":
                    pass
                elif t == "done":
                    print(f"  recv done (assistant chars={len(msg.get('full_response') or '')})")
                elif t == "eval_start":
                    print("  recv eval_start")
                elif t == "eval":
                    eval_payload = msg.get("data")
                    print(f"  recv eval PEI={eval_payload.get('scores', {}).get('PEI')}")
                    break
                elif t == "eval_error":
                    print("  recv eval_error:", msg.get("message"))
                    break
                elif t == "error":
                    chat_error = msg.get("message")
                    print("  recv error:", chat_error)
                    break
            else:
                print("  TIMEOUT waiting for eval")
                return 1

        if chat_error:
            print("FAIL: chat/eval pipeline reported error (check GOOGLE_API_KEY / OPENAI / billing).")
            return 1
        if not eval_payload:
            print("FAIL: no eval payload (eval_error or timeout).")
            return 1

    print("--- DB verification (AsyncSession, same engine as API) ---")

    async def verify() -> bool:
        from sqlalchemy import select, func
        from database import (
            AsyncSessionLocal,
            User,
            Classroom,
            ClassroomMembership,
            UserChallengeSession,
            Conversation,
            Message,
            EvalResult,
        )

        async with AsyncSessionLocal() as db:
            u_stu = await db.scalar(select(User).where(User.id == user_stu_id))
            assert u_stu

            n_mem = await db.scalar(
                select(func.count()).select_from(ClassroomMembership).where(ClassroomMembership.user_id == user_stu_id)
            )
            assert n_mem >= 1

            ucs = await db.scalar(
                select(UserChallengeSession).where(
                    UserChallengeSession.user_id == user_stu_id,
                    UserChallengeSession.challenge_id == ch_id,
                    UserChallengeSession.session_number == 1,
                )
            )
            assert ucs is not None
            assert ucs.conversation_id is not None, "UCS should link to conversation after WS connect"
            conv_id = ucs.conversation_id

            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            assert conv.user_id == user_stu_id
            assert (conv.turn_count or 0) >= 1

            nm = await db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conv_id))
            assert nm >= 2, f"expected user+assistant messages, got {nm}"

            ne = await db.scalar(select(func.count()).select_from(EvalResult).where(EvalResult.conversation_id == conv_id))
            assert ne >= 1, f"expected eval_results row, got {ne}"

            er = (
                await db.execute(
                    select(EvalResult)
                    .where(EvalResult.conversation_id == conv_id)
                    .order_by(EvalResult.turn_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            assert er is not None and er.pei is not None
            print(f"  users OK; classroom+membership OK; UCS.conversation_id={conv_id[:8]}...")
            print(f"  messages={nm}, eval_results={ne}, last PEI={er.pei}")
            print("  Note: user_challenge_sessions.best_pei is not auto-updated from eval yet (future work).")
        return True

    asyncio.run(verify())
    print("OK: backend + DB + website-equivalent flow succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
