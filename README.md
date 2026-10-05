# Husky AI

Web application for Northeastern students to practice prompting with a chat model and receive structured feedback. The frontend is React (Vite); the backend is FastAPI with WebSockets, SQLAlchemy, and JWT auth. Chat uses Google Gemini (streaming). Turn-level evaluation uses the OpenAI API (a panel of per-dimension judges, each grounded with file search over a configured vector store). Data lives in Supabase Postgres (SQLite locally).

---

## Table of Contents

1. [Overview](#overview)
2. [Stack](#stack)
3. [Architecture](#architecture)
4. [Evaluation pipeline](#evaluation-pipeline)
5. [Session analysis](#session-analysis)
6. [Collaborative study](#collaborative-study)
7. [Vector store (rubric source)](#vector-store-rubric-source)
8. [PEI scoring](#pei-scoring)
9. [Database schema](#database-schema)
10. [API surface (summary)](#api-surface-summary)
11. [Running locally](#running-locally)
12. [Deploying](#deploying)
13. [Environment variables](#environment-variables)

---

## Overview

- Students work inside **challenges** (multi-session assignments). Chat runs over WebSocket (`/ws`) with a JWT and challenge/session context.
- After each user turn, the server runs an **evaluation pipeline** (OpenAI) and persists scores and full JSON in `eval_results`.
- **Classrooms** (sections) have join codes. **Membership** (`student` | `instructor` | `admin`) controls access. Challenges visible to a student are those linked to their section via `classroom_challenges`.
- Instructors create sections (`POST /classrooms`) and can create challenges assigned to a section (`POST /challenges`). The live app gates `/instructor` to users with instructor or admin membership on at least one section. Separately, `users.is_platform_admin` (synced from `PLATFORM_ADMIN_EMAILS` on startup) gates `/admin`.
- When a session ends, a session-level **analysis** (narrative and takeaways) is generated in the background.
- A **collaborative study** mode puts students in teams, each with a private coach and a shared document, and records every action in an ordered event log for research.

---

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18, Vite, Tailwind CSS, react-router-dom |
| Backend | FastAPI, WebSockets, SQLAlchemy (async) |
| Chat | Google Gemini `gemini-2.5-pro` (streaming, `main.py`) |
| Evaluation | OpenAI via the `openai-agents` SDK: `gpt-4.1-nano` domain detector, five `gpt-4.1-mini` judges with `FileSearchTool`, `gpt-4.1` feedback writer (`evaluator_v3.py`) |
| Session analysis | OpenAI `gpt-4.1` (`session_analysis.py`) |
| Database | Supabase PostgreSQL (resolved by `db_config.py`), or SQLite (local default) |
| Multi-worker (optional) | Redis, when `REDIS_URL` is set — see [docs/multi-worker-deploy.md](docs/multi-worker-deploy.md) |
| Auth | JWT (python-jose), password hashing (passlib/bcrypt) |
| Migrations | Alembic (`backend/alembic`) for Postgres |

---

## Architecture

```
Browser
  │
  ├── HTTP  → /auth/*, /challenges/*, /classrooms/*, /admin/*
  │           /conversations/{id}/end | export | analysis
  │           /groups/*, /verification/*, /contested/*, /corpus/*, /research/*
  │
  ├── WSS   → /ws?token=<jwt>&challenge_id=&session_num=        (solo chat)
  │             │
  │             ├── Gemini gemini-2.5-pro (streaming chat)
  │             │
  │             └── Evaluation pipeline (per completed user turn, evaluator_v3.py)
  │                   ├── Stage 1: gpt-4.1-nano - domain label
  │                   ├── Stage 2: five gpt-4.1-mini judges in parallel (PSQ, CCM, TSI, CLM, RAS), file search
  │                   ├── Stage 3: code-side aggregation - PEI, classification, leading_status
  │                   ├── Stage 4: gpt-4.1 - feedback
  │                   └── Persist Message + EvalResult
  │
  └── WSS   → /ws/coach?token=<jwt>&group_id=&session_num=      (collaborative study)
                ├── private coach per student (Gemini + the same evaluator)
                ├── shared sectioned document (artifact) and team chat
                └── every action → study_events
```

`main.py` holds the app, lifespan (seeding, JWT-secret check), the WebSocket handlers and the `/conversations/*` endpoints; the other HTTP routes are `APIRouter`s in their own modules (`auth.py`, `challenges.py`, `classrooms.py`, `admin.py`, `groups.py`, `verification.py`, `contested.py`, `corpus.py`, `research_export.py`). `/ws/group` is the older shared-coach team room (one AI conversation per team).

---

## Evaluation pipeline

Implementation: `backend/evaluator_v3.py` (`evaluate_conversation_v3`, imported in `main.py` as `evaluate_conversation`), a panel of judges. `evaluator.py` and `evaluator_v2.py` are earlier iterations kept in-tree for benchmarking (`scripts/run_eval_benchmark.py --evaluator v1|v2|v3`); editing them has no runtime effect.

**Stage 1: domain detection** — `gpt-4.1-nano` labels the conversation as one of `coding`, `debugging`, `data_analysis`, `casual`, `creative`.

**Stage 2: five parallel judges** — one `gpt-4.1-mini` agent per PEI dimension (PSQ, CCM, TSI, CLM, RAS), each with `FileSearchTool` on `OPENAI_VECTOR_STORE_ID` for its rubric and exemplars. When an assignment has a reference corpus, the judges search both stores and an extra grounding judge scores the turn against the corpus alone; grounding is reported alongside PEI, not inside it.

**Stage 3: aggregation (code, no LLM)** — `_aggregate` computes PEI, the classification band and `leading_status` from the judges' scores.

**Stage 4: feedback** — `gpt-4.1` writes suggestions, strengths and red flags from the full breakdown.

**Reliability**

- Each evaluation is attempted up to three times, with backoff on transient errors.
- If all attempts fail, `_default_eval()` returns `eval_failed: true` with **null** scores (not zeros, which would look like a genuinely poor turn). The turn is saved as scoring-pending, does not count toward minimum turns, and is retried in the background up to three more times, waiting 1, 5 and 15 minutes before each attempt (`_schedule_rescore` in `main.py`); if those fail too it is marked `failed`; the late score is pushed to the open tab if there is one.

---

## Session analysis

`backend/session_analysis.py`. When a session ends (`POST /conversations/{id}/end`, or completing a challenge session), a background task rolls the per-turn evaluations into a session-level analysis: a deterministic part (session PEI, band, per-dimension averages, strongest/weakest dimension, first-half vs second-half trend) and a `gpt-4.1` part (a short narrative, three takeaways, one or two strengths). It never re-scores turns.

The result is stored on `UserChallengeSession.session_analysis` as a status blob (`pending` → `ready` or `failed`). The frontend polls `GET /conversations/{id}/analysis`; `POST /conversations/{id}/analysis/retry` regenerates a failed one. Analyses left `pending` by a restart are re-queued at startup. Team sessions have the equivalent at `/groups/{group_id}/sessions/{n}/analysis`.

---

## Collaborative study

A per-assignment study mode (instructor **Study settings**) comparing a solo control arm (chat with the score feed, optionally hidden per session, optional required revision) against a collaborative arm: each team member has a private coach over `/ws/coach`, the team shares one sectioned document (the *artifact*, `backend/artifacts.py`) and a team chat, and every action — writes, reads, coach turns, peer reviews, contested-answer choices — is written to one ordered event log (`study_events`, `backend/events.py`). Behaviour is derived from that log, never self-reported. Instructors get turn-taking metrics, routed peer review, scripted contested answers, a per-assignment reference corpus, and a de-identified per-session export.

Read before changing any of it:

- [docs/collab-study-pending.md](docs/collab-study-pending.md) — what is built, what is blocked on the PI
- [docs/event-schema.md](docs/event-schema.md) — every event type
- [docs/metrics-codebook.md](docs/metrics-codebook.md) — metric definitions
- [docs/data-anonymization.md](docs/data-anonymization.md) — what the exports scrub
- [docs/multi-worker-deploy.md](docs/multi-worker-deploy.md) — running more than one worker

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

**PSQ sub-weights** (from the PSQ judge's instructions; see `evaluator_v3.py` for full definitions):

```
PSQ = 0.30×verb_specificity + 0.25×context_completeness + 0.20×constraint_defined
    + 0.15×focus_clarity + 0.10×alignment_specified
```

**Classification bands** (computed in `_aggregate`): Novice &lt; 40, Intermediate 40-70, Advanced &gt; 70.

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

**user_challenge_sessions** - per-user progress per challenge session; links optionally to `conversation_id`, tracks `status`, `best_pei`, `session_avg_pei`, `end_reason` (`timer_expired` | `manual`, decided server-side), `session_analysis` (JSON status blob), timestamps

**Collaborative study** - `group_challenges`, `group_members`, `group_sessions`, `group_chat_messages` (teams and their sessions); `artifacts`, `artifact_sections`, `artifact_revisions` (the shared document, append-only); `study_events` (the ordered event log); `verification_assignments`, `verification_responses`, `review_pairings` (peer review); `contested_pairs`, `contested_responses`; `reference_corpora`, `corpus_documents`. Study settings live on `classroom_challenges` (`study_arm`, `coach_prominence`, `verification_policy`, `revision_policy`, `team_chat_logging`, `reference_corpus_id`).

---

## API surface (summary)

Not exhaustive; see FastAPI OpenAPI at `/docs` when the server is running.

| Area | Examples |
|------|----------|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/forgot-password`, `POST /auth/reset-password`, `GET`/`PATCH /auth/me` |
| Challenges | `GET /challenges`, `GET /challenges/{id}`, `POST /challenges`, `PATCH /challenges/{id}` (instructor), `POST /challenges/{id}/sessions/{n}/start`, `POST /challenges/{id}/sessions/{n}/complete` |
| Classrooms | `GET /classrooms/me`, `POST /classrooms`, `POST /classrooms/join`, `GET /classrooms/browse`, `PATCH /classrooms/{id}`, `GET /classrooms/{id}/summary`, `GET /classrooms/{id}/challenges`, `GET /classrooms/{id}/analytics`, `PATCH /classrooms/assignments/{id}/study` |
| Conversations | `POST /conversations/{id}/end`, `GET /conversations/{id}/export` (Markdown transcript with per-turn scores, owner only), `GET /conversations/{id}/analysis`, `POST /conversations/{id}/analysis/retry` |
| Teams (instructor) | `/classrooms/{cid}/challenges/{chid}/teams/*` — teams and members, analytics, turn-taking, sessions, reviews, review pairings, contested pairs |
| Study | `/groups/*` (team sessions, end, analysis), `/verification/*` (peer review), `/contested/*`, `/corpus/*` |
| Research export | `GET /research/sessions/{id}/export?format=json\|jsonl[&include_unconsented=true]` (de-identified per-session bundle, instructor/admin), `GET /research/sessions/{id}/turn-taking` |
| Admin | `/admin/overview`, `/admin/users`, `/admin/classrooms/{id}`, `/admin/benchmark/*`, `GET /admin/export/conversations?format=json\|csv` (de-identified per-turn export, consented only by default) |
| Realtime | `WebSocket /ws` (solo), `/ws/coach` (collaborative study), `/ws/group` (legacy shared-coach team room) |

---

## Running locally

### Backend

```bash
cd backend
pip install -r requirements.txt
# create backend/.env with the keys listed under Environment variables (no example file is checked in)
uvicorn main:app --port 8000 --reload
```

**Tests** (no Gemini/OpenAI keys required; isolated SQLite DB via `tests/conftest.py`):

```bash
cd backend
python -m pytest tests -v --tb=short
```

Pre-pilot HTTP path only: `python scripts/e2e_pre_pilot_http.py`. WebSocket + live models: `python scripts/e2e_website_flow.py` (requires keys and, for that script, Postgres per script checks).

**Redis tests** (skipped unless `REDIS_URL` points at a reachable server): see [docs/multi-worker-deploy.md](docs/multi-worker-deploy.md#running-the-redis-tests).

**Live keys (optional):** `python scripts/verify_external_ai.py` loads `backend/.env` and checks Gemini, OpenAI, vector store `GET`, and one full evaluation (set `VERIFY_SKIP_EVAL=1` to skip the eval call). Does not print secrets. Note: that eval call still imports the older `evaluator.py`, not the live `evaluator_v3.py`, so it proves the keys and vector store work but does not exercise the live judge panel.

### Frontend

```bash
cd frontend
npm install
npm run dev
npm test        # vitest
```

Open `http://localhost:5173` (or the port Vite prints).

### Seeded test section

Startup seeds challenges and a demo classroom when configured in app lifespan. The join code comes from `SEED_CLASSROOM_CODE` (charset restrictions apply). After a user joins that section, assigned challenges appear in `GET /challenges`.

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

## Deploying

Typical layout: two services from one repo (Railway, per `backend/nixpacks.toml`), with the database on Supabase.

**Database** - Supabase Postgres. Set `DATABASE_URL` to the Supabase connection string, or set the `SUPABASE_*` pieces and let `db_config.py` build it. The password is the Postgres database password, **not** the Supabase service_role JWT; `db_config.py` rejects `sb_secret_`/`eyJ`-style values. The transaction pooler (port 6543) is preferred.

**Backend** - root `backend`, start command per `nixpacks.toml` (`uvicorn main:app --host 0.0.0.0 --port $PORT`, one worker). Set the database variables, API keys, and `JWT_SECRET` (at least 32 characters; enforced when `ENVIRONMENT=production`). To run more than one worker, `REDIS_URL` is required: see [docs/multi-worker-deploy.md](docs/multi-worker-deploy.md).

**Frontend** - root `frontend`, build `npm run build`, serve static output. Set `VITE_API_URL` and `VITE_WS_URL` to the public backend URLs.

Tables are created on startup via `init_db()`; Postgres-specific column drift is also handled there for small additive changes. Prefer Alembic for team workflows.

---

## Environment variables

| Variable | Where | Purpose |
|----------|--------|---------|
| `GOOGLE_API_KEY` | Backend | Gemini chat |
| `OPENAI_API_KEY` | Backend | Evaluation calls |
| `OPENAI_VECTOR_STORE_ID` | Backend | Vector store for `FileSearchTool` |
| `JWT_SECRET` | Backend | JWT signing; at least 32 characters when `ENVIRONMENT=production` |
| `DATABASE_URL` | Backend | Postgres URL; omit for local SQLite per `db_config.py` |
| `SUPABASE_PROJECT_REF`, `SUPABASE_DB_PASSWORD`, `SUPABASE_DB_*` | Backend | Alternative to `DATABASE_URL`: `db_config.py` builds the Supabase URL |
| `PLATFORM_ADMIN_EMAILS` | Backend | Comma-separated emails granted `/admin`, synced on startup |
| `SEED_CLASSROOM_CODE` | Backend | Join code for the seeded demo section |
| `REDIS_URL` | Backend | Optional; required for more than one worker ([docs/multi-worker-deploy.md](docs/multi-worker-deploy.md)) |
| `RESEARCH_NOTICE_VERSION`, `RESEARCH_NOTICE_ALLOW_DECLINE` | Backend | Consent-notice version (raise to re-show the notice) and optional decline button |
| `RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_BASE_URL` | Backend | Password-reset email |
| `VITE_API_URL` | Frontend | REST base URL |
| `VITE_WS_URL` | Frontend | WebSocket URL |

Other optional backend variables (rate limits, DB pool sizes, proxy headers, dev admin seeding) are read where they are used; `grep -rn getenv backend/*.py` lists them.

---
