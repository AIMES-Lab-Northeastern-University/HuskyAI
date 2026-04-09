#!/usr/bin/env python3
"""
Verify GOOGLE_API_KEY, OPENAI_API_KEY, and OPENAI_VECTOR_STORE_ID from backend/.env.
Calls live APIs (small billable usage). Does not print secret values.

  cd backend
  python scripts/verify_external_ai.py

Optional: VERIFY_SKIP_EVAL=1  — skip the full two-stage evaluate_conversation() call.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

_backend = Path(__file__).resolve().parents[1]
load_dotenv(_backend / ".env")
load_dotenv()


def _mask(s: str | None) -> str:
    if not s:
        return "(missing)"
    if len(s) <= 8:
        return "(set)"
    return f"(set, len={len(s)})"


def main() -> int:
    g_key = os.getenv("GOOGLE_API_KEY", "").strip()
    o_key = os.getenv("OPENAI_API_KEY", "").strip()
    vs_id = os.getenv("OPENAI_VECTOR_STORE_ID", "").strip()

    print("Env (values not shown):")
    print(f"  GOOGLE_API_KEY          {_mask(g_key)}")
    print(f"  OPENAI_API_KEY          {_mask(o_key)}")
    print(f"  OPENAI_VECTOR_STORE_ID  {_mask(vs_id)}")

    if not g_key:
        print("FAIL: GOOGLE_API_KEY is empty")
        return 1
    if not o_key:
        print("FAIL: OPENAI_API_KEY is empty")
        return 1
    if not vs_id or not vs_id.startswith("vs_"):
        print("FAIL: OPENAI_VECTOR_STORE_ID must be set and look like vs_...")
        return 1

    # --- Google Gemini (minimal generation) ---
    print("\n--- Google Gemini ---")
    try:
        from google import genai
        from google.genai import types

        # Match Workspace (main.py); override with VERIFY_GEMINI_MODEL if needed.
        model = os.getenv("VERIFY_GEMINI_MODEL", "gemini-2.5-flash").strip()
        client = genai.Client(api_key=g_key)
        resp = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(text="Reply with exactly: OK")])],
        )
        text = (resp.text or "").strip()
        if "OK" not in text.upper():
            print(f"WARN: unexpected reply from {model!r}: {text[:200]!r}")
        else:
            print(f"OK: generate_content ({model}) -> contains OK")
    except Exception as e:
        print(f"FAIL: Gemini — {type(e).__name__}: {e}")
        return 1

    # --- OpenAI API key ---
    print("\n--- OpenAI API key ---")
    try:
        r = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {o_key}"},
            params={"limit": 1},
            timeout=30.0,
        )
        if r.status_code != 200:
            print(f"FAIL: GET /v1/models -> {r.status_code} {r.text[:300]}")
            return 1
        print("OK: /v1/models authorized")
    except Exception as e:
        print(f"FAIL: OpenAI HTTP — {type(e).__name__}: {e}")
        return 1

    # --- Vector store exists ---
    print("\n--- OpenAI vector store ---")
    try:
        r = httpx.get(
            f"https://api.openai.com/v1/vector_stores/{vs_id}",
            headers={"Authorization": f"Bearer {o_key}", "OpenAI-Beta": "assistants=v2"},
            timeout=30.0,
        )
        if r.status_code != 200:
            print(f"FAIL: GET vector_stores/{vs_id} -> {r.status_code} {r.text[:400]}")
            return 1
        data = r.json()
        status = data.get("status", "?")
        print(f"OK: vector store status={status!r} id={data.get('id', '?')!r}")
    except Exception as e:
        print(f"FAIL: vector store — {type(e).__name__}: {e}")
        return 1

    # --- Full evaluator pipeline (optional) ---
    if os.getenv("VERIFY_SKIP_EVAL", "").strip().lower() in ("1", "true", "yes"):
        print("\nSKIP: evaluate_conversation (VERIFY_SKIP_EVAL set)")
        return 0

    print("\n--- Husky evaluate_conversation() (2-stage, file search) ---")
    try:
        sys.path.insert(0, str(_backend))
        from evaluator import evaluate_conversation

        history = [
            {"role": "user", "content": "I need to debug a 500 error on login. I checked the server logs."},
            {"role": "assistant", "content": "What do the logs show for the stack trace?"},
            {"role": "user", "content": "NullPointerException in AuthService line 42."},
        ]
        out = asyncio.run(evaluate_conversation(history))
        pei = (out.get("scores") or {}).get("PEI")
        cls_ = out.get("classification")
        print(f"OK: PEI={pei!r} classification={cls_!r} (suggestions={len(out.get('suggestions') or [])})")
    except Exception as e:
        print(f"FAIL: evaluator — {type(e).__name__}: {e}")
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
