"""Test-only ASGI app for the real multi-worker check.

Imports the production app, then swaps the two external LLM calls (Gemini chat
stream, OpenAI evaluator panel) for deterministic local fakes. Kept entirely
under tests/ so no test scaffolding ships in production code.

Run with, for example:

    uvicorn tests.multiworker.mw_app:app --port 8801
    uvicorn tests.multiworker.mw_app:app --port 8801 --workers 2

Environment:
    DATABASE_URL   shared by every worker (required -- must not be per-process)
    REDIS_URL      shared by every worker (required for cross-worker behaviour)
    MW_STREAM_DELAY  seconds the fake Gemini stream takes (default 0.05). Used to
                     hold the turn lock open long enough to test contention.
"""

import asyncio
import os
import sys
from pathlib import Path

# Import the backend package the same way the real server does.
_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))

import main  # noqa: E402

STREAM_DELAY = float(os.getenv("MW_STREAM_DELAY", "0.05"))


class _Chunk:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


class _FakeStream:
    """Mimics `await client.aio.models.generate_content_stream(...)` returning an
    async iterator of chunks."""

    def __init__(self, parts):
        self._parts = parts

    def __aiter__(self):
        async def gen():
            for p in self._parts:
                await asyncio.sleep(STREAM_DELAY)
                yield _Chunk(p)

        return gen()


class _FakeModels:
    async def generate_content_stream(self, *, model, contents, config=None, **kw):
        # Echo something deterministic and identifiable so the test can assert on it.
        return _FakeStream(["FAKE ", "REPLY"])


class _FakeAio:
    def __init__(self):
        self.models = _FakeModels()


class _FakeClient:
    def __init__(self):
        self.aio = _FakeAio()


async def _fake_eval(conversation_history):
    await asyncio.sleep(0)
    return {
        "scores": {"PEI": 70.0, "PSQ": 70.0, "CCM": 70.0, "TSI": 70.0, "CLM": 70.0, "RAS": 70.0},
        "breakdown": {},
        "classification": "Practitioner",
        "leading_status": "student-led",
        "suggestions": [],
        "red_flags": [],
        "strengths": [],
        "turn_summary": "fake",
    }


main.client = _FakeClient()
main.evaluate_conversation = _fake_eval

app = main.app
