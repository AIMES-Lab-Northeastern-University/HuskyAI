# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Husky AI — a web app where Northeastern students practice prompting against a chat model and receive structured, per-turn feedback. Frontend is React (Vite); backend is FastAPI with async SQLAlchemy, JWT auth, and a WebSocket chat endpoint. Chat runs on Google Gemini (streaming). Each user turn is scored by a multi-stage OpenAI evaluation pipeline that produces a **PEI** (Prompt Effectiveness Index).

`README.md` is the conceptual overview; `docs/collab-study-pending.md` tracks what is built and what is blocked on the PI.

## Commands

Backend (from `backend/`):
```bash
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload      # run API + WebSocket
python -m pytest tests -v --tb=short       # full test suite (isolated SQLite, no API keys needed)
python -m pytest tests/test_smoke.py -v     # single test file
python -m pytest tests/test_auth_validation.py::<name> -v   # single test
python scripts/verify_external_ai.py        # verify live Gemini/OpenAI/vector-store keys (loads backend/.env)
```

Frontend (from `frontend/`):
```bash
npm install
npm run dev        # Vite dev server on :5173, proxies /ws -> ws://localhost:8000
npm run build
```

DB migrations (Postgres only, from `backend/`):
```bash
alembic upgrade head
```

## Architecture

Request flow:
- **HTTP** — auth, challenges, classrooms, admin (see routers below).
- **WebSocket `/ws?token=<jwt>&challenge_id=&session_num=`** (defined in `main.py`) — streams Gemini chat, and after each completed user turn runs the evaluation pipeline and persists a `Message` + `EvalResult`.

Backend modules (`backend/`):
- `main.py` — FastAPI app, lifespan (seeding + JWT-secret checks), `/ws` handler, and `/conversations/*` endpoints (end, export, analysis). Wires routers and CORS (`allow_origins=["*"]`).
- Routers, each an `APIRouter` with its own prefix: `auth.py` (`/auth`), `challenges.py` (`/challenges`), `classrooms.py` (`/classrooms`), `admin.py` (`/admin`).
- `evaluator_v3.py` — **the live per-turn evaluator** (imported in `main.py` as `evaluate_conversation`). Panel-of-judges design: Stage 1 domain detector (`gpt-4.1-nano`), Stage 2 five parallel per-dimension judges (`gpt-4.1-mini`, each FileSearch-grounded on the OpenAI vector store), Stage 3 code-side aggregation → PEI/classification/leading_status, Stage 4 feedback writer (`gpt-4.1`). Uses the `openai-agents` SDK (`Agent`, `Runner`, `FileSearchTool`). Retries with backoff; `_default_eval()` returns a safe zeroed schema on exhausted failure so a turn never breaks the session.
- `session_analysis.py` — end-of-session narrative + takeaways (`gpt-4.1`), generated **asynchronously** and stored on `UserChallengeSession.session_analysis` as a status blob (`pending`/`ready`/`failed`). Retrieved via `/conversations/{id}/analysis`.
- `database.py` — all SQLAlchemy ORM models and `init_db()` + seed functions (`seed_challenges`, `seed_demo_classroom`, `seed_pilot_classroom`, `seed_dev_platform_admin`).
- `db_config.py` — resolves `DATABASE_URL`. Prefers explicit `DATABASE_URL`, then builds a Supabase Postgres URL from `SUPABASE_*` vars, else falls back to local SQLite (`sqlite+aiosqlite:///./huskyai.db`). Note: the DB password is the Postgres password, **not** the Supabase service_role JWT — the code deliberately rejects `sb_secret_`/`eyJ`-prefixed values.
- `auth.py` — JWT (python-jose) + bcrypt password hashing.
- `rate_limit.py` — per-IP sliding-window limiter on auth endpoints; disabled when `HUSKY_TESTING=1`.
- `anonymize.py`, `admin.py` — research-consent-aware data export and platform-admin overview.
- `submissions.py` — team submissions. When a group session ends (any path), `record_submission` freezes the shared artifact + AI team score into `TeamSubmission`; instructors list/grade/download them (`/classrooms/{id}/challenges/{id}/submissions*`), students read theirs (`/groups/{id}/sessions/{n}/submission[/pdf]`). Also owns the team-PEI definition (`coach_session_summary`) that `main.py` imports. PDF text helpers live in `pdf_render.py`.
- **Final review** (`main.py`, `POST /groups/{id}/sessions/{n}/review` and `/ready`): finishing a collab session opens a whole-document review (`frontend/src/components/FinalReview.jsx`); each participant marks ready (`ReviewReadyMark`), any write clears all marks, and the last mark ends the session with `end_reason="team_ready"`. Section briefs/targets are the instructor's `prompt`/`target_words` in `artifact_sections`, sent to students as the `section_guides` frame.
- **Full-document view** (`CoachWorkspace.jsx`, `docMode`): the document panel can expand into a page layout (`Section variant="page"`, Write/Preview editing) with the coach shrunk or hidden. Off by default; opening it logs each non-empty section as a read with `via: "document"`, so sections still start unread on load.

Frontend (`frontend/src/`): `pages/` (routed views), `components/`, `lib/api.js`. Backend base URL comes from `VITE_API_URL` (default `http://localhost:8000`). The Vite proxy only forwards `/ws`; HTTP calls go straight to `API_URL`.

## Key domain concepts

- **PEI** = `0.25·PSQ + 0.25·CCM + 0.20·TSI + 0.15·CLM + 0.15·RAS`. Dimension definitions and PSQ sub-weights live in `evaluator_v3.py`. Bands: Novice <40, Intermediate 40–70, Advanced >70.
- **Challenges** are multi-session assignments (`sessions_data` JSON). **Classrooms** (sections) have join codes; `classroom_challenges` assigns challenges to a section; a student only sees challenges linked to their section.
- **Roles**: `classroom_memberships.role` is `student`/`instructor`/`admin` (per-section). Separately, `users.is_platform_admin` gates `/admin` (set via `PLATFORM_ADMIN_EMAILS` in `.env`, synced on startup).
- **Session end**: `UserChallengeSession.end_reason` is decided server-side (`timer_expired` vs `manual`).

## Vector store

Rubric/exemplar documents live in an OpenAI vector store referenced by `OPENAI_VECTOR_STORE_ID`. Source content lives under `Knowladge Base/` (note the spelling). The repo does not need to mirror uploaded files.

## Tests

`tests/conftest.py` sets `DATABASE_URL` to a temp SQLite file and `HUSKY_TESTING=1` **before** importing `main`/`database` — no Gemini/OpenAI keys required. Raise auth rate limits in a test via `AUTH_RATE_TEST_MAX`. `tests/judge_benchmark/` holds evaluator benchmark fixtures.

## Environment variables

Backend reads (`backend/.env`): `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `OPENAI_VECTOR_STORE_ID`, `DATABASE_URL` **or** `SUPABASE_DB_*`, `JWT_SECRET` (must be ≥32 chars when `ENVIRONMENT=production` — enforced in lifespan), `PLATFORM_ADMIN_EMAILS`, `SEED_CLASSROOM_CODE`. Frontend: `VITE_API_URL`.

## Earlier evaluators

The live evaluator is `evaluator_v3.py` (`evaluate_conversation_v3`). `evaluator.py` and `evaluator_v2.py` are earlier iterations kept in-tree for benchmarking; editing them has no runtime effect.
