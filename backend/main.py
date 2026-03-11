import os
import json
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from evaluator import evaluate_conversation

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chat-evaluator")

api_key = os.getenv("GOOGLE_API_KEY", "")
if not api_key:
    log.warning("GOOGLE_API_KEY is not set — requests will fail")
client = genai.Client(api_key=api_key)

app = FastAPI(title="Chat Evaluator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHAT_SYSTEM_PROMPT = (
    "You are an expert coding assistant. Help users with programming questions, "
    "debugging, code reviews, architecture decisions, and software engineering tasks.\n\n"
    "Be concise but thorough. Provide working code examples when relevant. "
    "Ask clarifying questions when the request is ambiguous."
)

CHAT_CONFIG = types.GenerateContentConfig(
    system_instruction=CHAT_SYSTEM_PROMPT,
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


def _build_gemini_history(conversation_history: list) -> list:
    """Convert our internal history format to Gemini's Content format."""
    history = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        history.append(
            types.Content(role=role, parts=[types.Part(text=msg["content"])])
        )
    return history


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    conversation_history = []
    client_host = websocket.client.host if websocket.client else "unknown"
    log.info(f"[WS] Client connected from {client_host}")

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

            # Build history and append current user message as the last content
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
                    config=CHAT_CONFIG,
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
                    log.info(
                        f"[TURN {turn}] Chat done -- "
                        f"chunks={chunk_count}, response={len(full_response)} chars"
                    )

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
                await websocket.send_text(json.dumps({"type": "eval", "data": eval_result}))
            except Exception as e:
                log.error(f"[TURN {turn}] Eval error: {type(e).__name__}: {e}", exc_info=True)
                await websocket.send_text(json.dumps({
                    "type": "eval_error",
                    "message": str(e)
                }))

    except WebSocketDisconnect:
        log.info(f"[WS] Client disconnected after {len(conversation_history) // 2} turns")
    except Exception as e:
        log.error(f"[WS] Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
