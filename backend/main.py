import os
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from evaluator import evaluate_conversation
from sqlalchemy import select, update

from database import init_db, AsyncSessionLocal, Conversation, Message, EvalResult, Challenge, UserChallengeSession, User
from auth import router as auth_router, decode_token, pwd_context
from challenges import router as challenges_router, seed_challenges
from classrooms import router as classrooms_router, seed_demo_classroom
from admin import router as admin_router

_backend_dir = Path(__file__).resolve().parent
load_dotenv(_backend_dir / ".env")
load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chat-evaluator")


async def _sync_platform_admin_emails() -> None:
    """Grant is_platform_admin to users whose emails appear in PLATFORM_ADMIN_EMAILS (comma-separated)."""
    raw = os.getenv("PLATFORM_ADMIN_EMAILS", "").strip()
    if not raw:
        return
    emails = {e.strip().lower() for e in raw.split(",") if e.strip()}
    if not emails:
        return
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.email.in_(emails)))
        for u in r.scalars().all():
            if not bool(u.is_platform_admin):
                u.is_platform_admin = True
        await db.commit()
    log.info("Synced platform admin flag for %d email(s)", len(emails))


async def seed_dev_platform_admin() -> None:
    """
    Non-production: ensure a platform admin exists for local QA.
    Sign in with email admin@husky.local or bare login id \"admin\" + SEED_DEV_ADMIN_PASSWORD (default 1234).
    Disabled when ENVIRONMENT=production, or SEED_DEV_ADMIN=0/false/no.
    """
    if os.getenv("ENVIRONMENT", "").strip().lower() in ("production", "prod"):
        return
    if os.getenv("SEED_DEV_ADMIN", "1").strip().lower() in ("0", "false", "no"):
        return
    email = os.getenv("SEED_DEV_ADMIN_EMAIL", "admin@husky.local").strip().lower()
    password = os.getenv("SEED_DEV_ADMIN_PASSWORD", "1234")
    name = (os.getenv("SEED_DEV_ADMIN_NAME", "Platform admin") or "Platform admin").strip()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.email == email))
        u = r.scalar_one_or_none()
        if u:
            if not bool(u.is_platform_admin):
                u.is_platform_admin = True
                await db.commit()
            return
        db.add(
            User(
                email=email,
                name=name,
                password_hash=pwd_context.hash(password),
                is_platform_admin=True,
            )
        )
        await db.commit()
    log.info("Seeded dev platform admin %r (sign in with bare id admin or this email)", email)


api_key = os.getenv("GOOGLE_API_KEY", "")
if not api_key:
    log.warning("GOOGLE_API_KEY is not set — requests will fail")
client = genai.Client(api_key=api_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = os.getenv("ENVIRONMENT", "").strip().lower()
    jwt_secret = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
    if env in ("production", "prod"):
        if len(jwt_secret) < 32:
            raise RuntimeError(
                "JWT_SECRET must be at least 32 characters when ENVIRONMENT=production"
            )
    elif not os.getenv("HUSKY_TESTING") and len(jwt_secret) < 32:
        log.warning(
            "JWT_SECRET is shorter than 32 characters — use a long random secret in production "
            "(e.g. openssl rand -hex 32)."
        )
    await init_db()
    await seed_dev_platform_admin()
    await _sync_platform_admin_emails()
    log.info("Database initialized")
    await seed_challenges()
    await seed_demo_classroom()
    yield


app = FastAPI(title="Husky AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(challenges_router)
app.include_router(classrooms_router)
app.include_router(admin_router)

BASE_SYSTEM_PROMPT = (
    "You are an expert AI tutor helping students develop their AI prompting and reasoning skills. "
    "Be a thoughtful coach: guide users to think more deeply, ask clarifying questions, "
    "and help them reason through problems step by step. "
    "Provide concrete, specific feedback rather than generic praise."
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


def _build_gemini_history(conversation_history: list) -> list:
    history = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        history.append(
            types.Content(role=role, parts=[types.Part(text=msg["content"])])
        )
    return history


async def _save_turn(conversation_id: str, user_msg: str, assistant_msg: str, eval_data: dict, turn_num: int):
    try:
        async with AsyncSessionLocal() as db:
            db.add(Message(conversation_id=conversation_id, role="user", content=user_msg))
            db.add(Message(conversation_id=conversation_id, role="assistant", content=assistant_msg))
            scores = eval_data.get("scores", {})
            db.add(EvalResult(
                conversation_id=conversation_id,
                turn_number=turn_num,
                pei=scores.get("PEI"),
                psq=scores.get("PSQ"),
                ccm=scores.get("CCM"),
                tsi=scores.get("TSI"),
                clm=scores.get("CLM"),
                ras=scores.get("RAS"),
                classification=eval_data.get("classification"),
                leading_status=eval_data.get("leading_status"),
                full_result=eval_data,
            ))
            res = await db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(turn_count=turn_num)
            )
            if res.rowcount != 1:
                log.warning(
                    "turn_count update affected %s rows (expected 1) for conversation_id=%s",
                    res.rowcount,
                    conversation_id,
                )
            await db.commit()
    except Exception as e:
        log.error(f"DB save failed for turn {turn_num}: {e}")


async def _close_conversation(conversation_id: str):
    try:
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, conversation_id)
            if conv:
                conv.ended_at = datetime.utcnow()
                await db.commit()
    except Exception as e:
        log.error(f"Failed to close conversation: {e}")


async def _build_system_prompt(challenge_id: str | None, session_num: int | None) -> tuple[str, dict | None]:
    """Return (system_prompt, session_data_dict) for the given challenge/session."""
    if not challenge_id:
        return BASE_SYSTEM_PROMPT, None

    try:
        async with AsyncSessionLocal() as db:
            ch = await db.get(Challenge, challenge_id)
            if not ch:
                return BASE_SYSTEM_PROMPT, None
            idx = (session_num or 1) - 1
            if idx < 0 or idx >= len(ch.sessions_data):
                idx = 0
            sd = ch.sessions_data[idx]
            extra = sd.get("system_prompt_extra", "")
            prompt = (
                f"You are an expert AI tutor coaching a student through the following challenge:\n\n"
                f"CHALLENGE: {ch.title}\n"
                f"SESSION {idx + 1}: {sd['title']}\n"
                f"GOAL: {sd['goal']}\n\n"
                f"CONTEXT FOR THIS SESSION:\n{sd['brief']}\n\n"
                f"YOUR COACHING ROLE:\n{extra}\n\n"
                f"Always stay in the context of this specific challenge and session. "
                f"Guide the student to think through the problem rather than just giving answers. "
                f"Ask probing questions. Celebrate good reasoning explicitly."
            )
            return prompt, sd
    except Exception as e:
        log.error(f"Failed to build challenge system prompt: {e}")
        return BASE_SYSTEM_PROMPT, None


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
    challenge_id: str = Query(None),
    session_num: int = Query(None),
):
    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return
    user_id = decode_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()

    system_prompt, session_data = await _build_system_prompt(challenge_id, session_num)
    chat_config = types.GenerateContentConfig(system_instruction=system_prompt)

    conversation_id = None
    try:
        async with AsyncSessionLocal() as db:
            conv = Conversation(user_id=user_id)
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
            conversation_id = conv.id

            # Link conversation to challenge session if applicable
            if challenge_id and session_num:
                from sqlalchemy import select as sa_select
                result = await db.execute(
                    sa_select(UserChallengeSession).where(
                        UserChallengeSession.user_id == user_id,
                        UserChallengeSession.challenge_id == challenge_id,
                        UserChallengeSession.session_number == session_num,
                    )
                )
                ucs = result.scalar_one_or_none()
                if ucs and not ucs.conversation_id:
                    ucs.conversation_id = conversation_id
                    await db.commit()
    except Exception as e:
        log.error(f"Failed to create conversation record: {e}")

    # Send session context to client immediately if challenge mode
    if session_data:
        await websocket.send_text(json.dumps({
            "type": "challenge_context",
            "data": {
                "title": session_data.get("title"),
                "goal": session_data.get("goal"),
                "brief": session_data.get("brief"),
                "seed_question": session_data.get("seed_question"),
            }
        }))

    conversation_history = []
    client_host = websocket.client.host if websocket.client else "unknown"
    mode = f"challenge={challenge_id}/session={session_num}" if challenge_id else "free"
    log.info(f"[WS] User {user_id[:8]}... connected ({mode}) (conv: {conversation_id})")

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") != "message":
                log.debug(f"[WS] Ignoring non-message packet: type={data.get('type')}")
                continue

            user_content = data.get("content", "").strip()
            if not user_content:
                log.warning("[WS] Received empty message content, skipping")
                continue

            turn = len(conversation_history) // 2 + 1
            preview = user_content[:120]
            ellipsis = "..." if len(user_content) > 120 else ""
            log.info(f"[TURN {turn}] User ({len(user_content)} chars): {preview!r}{ellipsis}")

            gemini_history = _build_gemini_history(conversation_history)
            contents = gemini_history + [
                types.Content(role="user", parts=[types.Part(text=user_content)])
            ]

            conversation_history.append({"role": "user", "content": user_content})

            await websocket.send_text(json.dumps({"type": "typing"}))
            log.debug(f"[TURN {turn}] Sent 'typing' signal to client")

            # -- Chat streaming --
            full_response = ""
            chunk_count = 0
            last_chunk = None
            log.info(f"[TURN {turn}] Streaming chat -> gemini-2.5-pro (history depth: {len(gemini_history)})")

            try:
                async for chunk in await client.aio.models.generate_content_stream(
                    model="gemini-2.5-pro",
                    contents=contents,
                    config=chat_config,
                ):
                    text = chunk.text
                    if text:
                        full_response += text
                        chunk_count += 1
                        await websocket.send_text(json.dumps({
                            "type": "stream",
                            "content": text
                        }))
                    last_chunk = chunk

                usage = last_chunk.usage_metadata if last_chunk else None
                if usage:
                    log.info(
                        f"[TURN {turn}] Chat done -- "
                        f"chunks={chunk_count}, "
                        f"in={usage.prompt_token_count} tok, "
                        f"out={usage.candidates_token_count} tok, "
                        f"response={len(full_response)} chars"
                    )
                else:
                    log.info(f"[TURN {turn}] Chat done -- chunks={chunk_count}, response={len(full_response)} chars")

            except Exception as e:
                err_str = str(e)
                if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
                    log.error(f"[TURN {turn}] AUTH FAILED -- check GOOGLE_API_KEY")
                    msg = "Authentication failed -- is GOOGLE_API_KEY set correctly?"
                elif "quota" in err_str.lower() or "rate" in err_str.lower() or "429" in err_str:
                    log.warning(f"[TURN {turn}] Rate limited: {e}")
                    msg = "Rate limited. Please wait a moment and try again."
                elif "billing" in err_str.lower() or "credit" in err_str.lower():
                    log.error(f"[TURN {turn}] BILLING ISSUE: {e}")
                    msg = "Billing issue -- check your Google Cloud / AI Studio account."
                else:
                    log.error(f"[TURN {turn}] Chat stream error: {type(e).__name__}: {e}", exc_info=True)
                    msg = f"Chat error: {type(e).__name__}: {e}"
                await websocket.send_text(json.dumps({"type": "error", "message": msg}))
                conversation_history.pop()
                continue

            conversation_history.append({"role": "assistant", "content": full_response})

            await websocket.send_text(json.dumps({
                "type": "done",
                "full_response": full_response
            }))
            log.debug(f"[TURN {turn}] Sent 'done' to client")

            # -- Evaluation --
            await websocket.send_text(json.dumps({"type": "eval_start"}))
            log.info(f"[TURN {turn}] Starting eval (total history: {len(conversation_history)} msgs)")

            eval_result = None
            try:
                eval_result = await evaluate_conversation(conversation_history)
                scores = eval_result.get("scores", {})
                log.info(
                    f"[TURN {turn}] Eval -> "
                    f"PEI={scores.get('PEI', 0):.1f}  "
                    f"PSQ={scores.get('PSQ', 0):.1f}  "
                    f"CCM={scores.get('CCM', 0):.1f}  "
                    f"TSI={scores.get('TSI', 0):.1f}  "
                    f"CLM={scores.get('CLM', 0):.1f}  "
                    f"RAS={scores.get('RAS', 0):.1f}  "
                    f"| {eval_result.get('classification')} / {eval_result.get('leading_status')}"
                )
                log.debug(f"[TURN {turn}] Suggestions: {eval_result.get('suggestions', [])}")
                log.debug(f"[TURN {turn}] Red flags:   {eval_result.get('red_flags', [])}")
                # Persist before notifying the client so a fast disconnect cannot cancel the save.
                if conversation_id:
                    await _save_turn(conversation_id, user_content, full_response, eval_result, turn)
                await websocket.send_text(json.dumps({"type": "eval", "data": eval_result}))
            except Exception as e:
                log.error(f"[TURN {turn}] Eval error: {type(e).__name__}: {e}", exc_info=True)
                await websocket.send_text(json.dumps({
                    "type": "eval_error",
                    "message": str(e)
                }))

    except WebSocketDisconnect:
        log.info(f"[WS] User {user_id[:8]}... disconnected after {len(conversation_history) // 2} turns")
        if conversation_id:
            await _close_conversation(conversation_id)
    except Exception as e:
        log.error(f"[WS] Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
        if conversation_id:
            await _close_conversation(conversation_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
