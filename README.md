# Husky AI

Web application for Northeastern students to practice prompting with a chat model and receive structured feedback. The frontend is React (Vite); the backend is FastAPI with WebSockets, SQLAlchemy, and JWT auth. Chat uses Google Gemini (streaming). Turn-level evaluation uses the OpenAI API (two sequential model calls, file search over a configured vector store).

---

## Table of Contents

1. [Overview](#overview)
2. [Stack](#stack)
3. [Architecture](#architecture)
4. [Evaluation pipeline](#evaluation-pipeline)
5. [Vector store (rubric source)](#vector-store-rubric-source)
6. [PEI scoring](#pei-scoring)
7. [Database schema](#database-schema)
8. [API surface (summary)](#api-surface-summary)
9. [Running locally](#running-locally)
10. [Deploying to Railway](#deploying-to-railway)
11. [Environment variables](#environment-variables)

---

## Overview

- Students work inside **challenges** (multi-session assignments). Chat runs over WebSocket (`/ws`) with a JWT and challenge/session context.
- After each user turn, the server runs an **evaluation pipeline** (OpenAI) and persists scores and full JSON in `eval_results`.
- **Classrooms** (sections) have join codes. **Membership** (`student` | `instructor` | `admin`) controls access. Challenges visible to a student are those linked to their section via `classroom_challenges`.
- Instructors create sections (`POST /classrooms`) and can create challenges assigned to a section (`POST /challenges`). The live app gates `/instructor` to users with instructor or admin membership on at least one section.

---

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18, Vite, Tailwind CSS, react-router-dom |
| Backend | FastAPI, WebSockets, SQLAlchemy (async) |
| Chat | Google Gemini `gemini-2.5-pro` (streaming, `main.py`) |
| Evaluation | OpenAI: domain step `gpt-4.1-nano`, scoring step `gpt-4.1` + `FileSearchTool` on a vector store (`evaluator.py`) |
| Database | PostgreSQL (e.g. Railway) or SQLite (local default) |
| Auth | JWT (python-jose), password hashing (passlib/bcrypt) |
| Migrations | Alembic (`backend/alembic`) for Postgres |

---

## Architecture

```
Browser
  │
  ├── HTTP  → /auth/register, /auth/login
  │           /challenges, /challenges/{id}, …
  │           /classrooms/* (membership, join, browse, PATCH, …)
  │
  └── WSS   → /ws?token=<jwt>&challenge_id=&session_num=
                │
                ├── Gemini (streaming chat)
                │
                └── Evaluation pipeline (per completed user turn)
                      ├── Stage 1: gpt-4.1-nano - domain label for the thread
                      ├── Stage 2: gpt-4.1 + file search - PEI JSON
                      └── Persist Message + EvalResult
```

---

## Evaluation pipeline

Implementation: `backend/evaluator.py`, invoked from the WebSocket handler in `main.py`.

**Stage 1: domain classification**

- Model: `gpt-4.1-nano` (temperature/top_p set in code).
- Output: structured classification (domain, confidence, reasoning) per `EvaluatorSchema` / domain detector instructions in code.
- Domains include: `coding`, `debugging`, `data_analysis`, `casual`, `creative` (defined in the domain-detector prompt in `evaluator.py`).

**Stage 2: scoring**

- Model: `gpt-4.1` with `FileSearchTool` bound to `OPENAI_VECTOR_STORE_ID`.
- Retrieves rubric/exemplar material from the vector store, then returns structured scores and narrative fields consumed by the UI.
- Output is normalized in `_sanitize_eval_dict` (e.g. score clamps, list fields).

**Reliability**

- `evaluate_conversation` retries up to three times with backoff on failures; transient errors are classified heuristically (`_is_transient_eval_error`).
- After exhausted retries, `_default_eval()` returns a safe zeroed schema and a user-visible “evaluation unavailable” style message so the session does not break.

**Historical context**

- The prompt can include a short aggregate profile derived from prior `eval_results` (implementation in `main.py` / evaluator input construction). Scoring rules in code state that dimension scores are absolute; profile informs suggestions, not score targets.

---

## Vector store (rubric source)

Rubric and exemplar documents are stored in an **OpenAI vector store** referenced by `OPENAI_VECTOR_STORE_ID`. File naming and layout are a content concern: names and headings should be clear so file search returns relevant chunks for each domain. The repository does not need to mirror every uploaded file; keep the store ID and keys in `.env` only.

---

## PEI scoring

**Combined index**

```
PEI = 0.25 × PSQ + 0.25 × CCM + 0.20 × TSI + 0.15 × CLM + 0.15 × RAS
```

| Code | Name | Role (summary) |
|------|------|----------------|
| PSQ | Prompt Structural Quality | Structure and completeness of prompts |
| CCM | Conversation Control Metrics | Who drives the thread, verification, corrections |
| TSI | Technical Sophistication Index | Decomposition, technical depth |
| CLM | Cognitive Load Management | Message sizing, incremental work |
| RAS | Reliance Appropriateness Score | Appropriate trust / verification of model output |

**PSQ sub-weights** (from evaluator instructions; see `evaluator.py` for full definitions):

```
PSQ = 0.30×verb_specificity + 0.25×context_completeness + 0.20×constraint_defined
    + 0.15×focus_clarity + 0.10×alignment_specified
```

**Classification bands** (typical): Novice &lt; 40, Intermediate 40-70, Advanced &gt; 70. Aligned with evaluator instructions.

---

## Database schema

ORM definitions: `backend/database.py`.

**users** - `id`, `email`, `name`, `password_hash`, `created_at`, `consent_research`

**classrooms** - `id`, `name`, `join_code`, `instructor_user_id`, `created_at`, `is_active`, `listed_in_directory`

**classroom_memberships** - `id`, `user_id`, `classroom_id`, `role`, `joined_at` (unique per user+classroom)

**classroom_challenges** - `id`, `classroom_id`, `challenge_id`, `sort_order` (assigns challenges to a section)

**conversations** - `id`, `user_id`, `classroom_id` (optional), `started_at`, `ended_at`, `turn_count`

**messages** - `id`, `conversation_id`, `role`, `content`, `created_at`

**eval_results** - `id`, `conversation_id`, `turn_number`, dimension scores, `classification`, `leading_status`, `full_result` (JSON), `created_at`

**challenges** - `id`, `title`, `description`, `category`, `difficulty`, `week`, `total_sessions`, `sessions_data` (JSON), `is_active`, `status`, `created_by_user_id`, `created_at`, `updated_at`

**user_challenge_sessions** - per-user progress per challenge session; links optionally to `conversation_id`, tracks `status`, `best_pei`, timestamps

---

## API surface (summary)

Not exhaustive; see FastAPI OpenAPI at `/docs` when the server is running.

| Area | Examples |
|------|----------|
| Auth | `POST /auth/register`, `POST /auth/login` |
| Challenges | `GET /challenges`, `GET /challenges/{id}`, `POST /challenges` (instructor), session start/progress routes as implemented |
| Classrooms | `GET /classrooms/me`, `POST /classrooms`, `POST /classrooms/join`, `GET /classrooms/browse`, `PATCH /classrooms/{id}`, `GET /classrooms/{id}/summary`, `GET /classrooms/{id}/challenges` |
| Realtime | `WebSocket /ws` |

---

## Running locally

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # set keys; see below
uvicorn main:app --port 8000 --reload
```

**Tests** (no Gemini/OpenAI keys required; isolated SQLite DB via `tests/conftest.py`):

```bash
cd backend
python -m pytest tests -v --tb=short
```

Pre-pilot HTTP path only: `python scripts/e2e_pre_pilot_http.py`. WebSocket + live models: `python scripts/e2e_website_flow.py` (requires keys and, for that script, Postgres per script checks).

**Live keys (optional):** `python scripts/verify_external_ai.py` loads `backend/.env` and checks Gemini, OpenAI, vector store `GET`, and one full `evaluate_conversation()` (set `VERIFY_SKIP_EVAL=1` to skip the eval call). Does not print secrets.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` (or the port Vite prints).

### Seeded test section

Startup seeds challenges and a demo classroom when configured in app lifespan. Default join code is documented in `.env.example` (`SEED_CLASSROOM_CODE`; charset restrictions apply). After a user joins that section, assigned challenges appear in `GET /challenges`.

**Postgres:** from `backend`, run `alembic upgrade head` after pulling schema changes.

**Useful SQL** (Supabase SQL editor or any Postgres client) - adjust email:

```sql
SELECT u.email, cm.role, c.name AS classroom_name, c.join_code
FROM users u
JOIN classroom_memberships cm ON cm.user_id = u.id
JOIN classrooms c ON c.id = cm.classroom_id
WHERE u.email = 'student@example.com';
```

```sql
SELECT c.name, c.join_code, ch.title
FROM classroom_challenges cc
JOIN classrooms c ON c.id = cc.classroom_id
JOIN challenges ch ON ch.id = cc.challenge_id;
```

Listed sections for browse: `classrooms.listed_in_directory = true`; exposed as `GET /classrooms/browse` (no join codes in that response).

---

## Deploying to Railway

Typical layout: two services from one repo.

**Backend** - root `backend`, start command per `nixpacks.toml` (e.g. `uvicorn main:app --host 0.0.0.0 --port $PORT`). Set `DATABASE_URL` from Railway Postgres, plus API keys and `JWT_SECRET`.

**Frontend** - root `frontend`, build `npm run build`, serve static output. Set `VITE_API_URL` and `VITE_WS_URL` to the public backend URLs.

Tables are created on startup via `init_db()`; Postgres-specific column drift is also handled there for small additive changes. Prefer Alembic for team workflows.

---

## Environment variables

| Variable | Where | Purpose |
|----------|--------|---------|
| `GOOGLE_API_KEY` | Backend | Gemini chat |
| `OPENAI_API_KEY` | Backend | Evaluation calls |
| `OPENAI_VECTOR_STORE_ID` | Backend | Vector store for `FileSearchTool` |
| `JWT_SECRET` | Backend | JWT signing (use a long random secret) |
| `DATABASE_URL` | Backend | Postgres URL; omit or leave empty for local SQLite per `db_config.py` |
| `VITE_API_URL` | Frontend | REST base URL |
| `VITE_WS_URL` | Frontend | WebSocket URL |

See `backend/.env.example` for optional variables (seed code, Supabase-style DSN pieces, etc.).

---
