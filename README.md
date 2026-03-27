# Husky AI — Be an AI-Ready Husky

A real-time AI prompting coach built for Northeastern University. Students chat with a Gemini-powered assistant on the left and receive live scoring on the right — across five dimensions of AI prompting sophistication — powered by a two-stage OpenAI evaluation agent backed by a structured knowledge base.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Stack](#stack)
3. [Architecture Overview](#architecture-overview)
4. [Evaluator Agent — System Design](#evaluator-agent--system-design)
5. [Knowledge Base Structure](#knowledge-base-structure)
6. [PEI Scoring Framework](#pei-scoring-framework)
7. [Database Schema](#database-schema)
8. [Running Locally](#running-locally)
9. [Deploying to Railway](#deploying-to-railway)
10. [Environment Variables](#environment-variables)
11. [Future Scope](#future-scope)

---

## What It Does

Each message a student sends is evaluated across five dimensions of prompting quality and combined into a single **Prompting Effectiveness Index (PEI)**. The eval panel shows:

- Live PEI score (0–100) with classification: Novice / Intermediate / Advanced
- Five dimension scores: PSQ, CCM, TSI, CLM, RAS
- Coach suggestions specific to the latest message
- Red flags for intervention
- Strengths to reinforce
- Detected conversation domain (coding, debugging, data, casual, creative)

Scores are stored per-turn in the database, enabling historical profile construction, trajectory analysis, and class-wide aggregation for instructors.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS + react-router-dom |
| Backend | FastAPI + WebSockets + SQLAlchemy async |
| Chat model | Google Gemini 2.5 Pro (streaming) |
| Evaluator Stage 1 | OpenAI gpt-4o-mini (domain detection) |
| Evaluator Stage 2 | OpenAI gpt-4o + FileSearchTool (PEI scoring) |
| Knowledge Base | OpenAI Vector Store (persistent) |
| Database | PostgreSQL (Railway) / SQLite (local dev) |
| Auth | JWT (python-jose + passlib/bcrypt) |
| Deployment | Railway (backend + frontend as separate services) |

---

## Architecture Overview

```
Browser
  │
  ├── HTTP  → FastAPI /auth/register, /auth/login
  │           FastAPI /challenges/*
  │
  └── WSS   → FastAPI /ws?token=<jwt>&challenge_id=&session_num=
                │
                ├── Gemini 2.5 Pro  ←  Chat streaming
                │
                └── Evaluator Pipeline (per turn)
                      │
                      ├── Stage 1: gpt-4o-mini
                      │   Domain detection (~500ms)
                      │   coding | debugging | data_analysis | casual | creative
                      │
                      ├── Stage 2: gpt-4o + FileSearchTool
                      │   KB retrieval + PEI scoring (~2000ms)
                      │   Input: conversation + domain + historical profile
                      │
                      └── DB save: Message + EvalResult per turn
```

---

## Evaluator Agent — System Design

### Two-Stage Pipeline

The evaluator operates in two sequential LLM calls per conversation turn:

#### Stage 1 — Domain Detector

| Property | Value |
|---|---|
| Model | `gpt-4o-mini` |
| Temperature | 0.1 (deterministic classification) |
| Input | First 2000 characters of conversation |
| Output | Structured Pydantic object |
| Latency | ~500ms |
| Cost | ~$0.0001 per call |

```python
class DomainClassification(BaseModel):
    domain: Literal["coding", "debugging", "data_analysis", "casual", "creative"]
    confidence: float    # 0.0 - 1.0
    reasoning: str       # one-sentence explanation
```

Domains defined:
- **coding** — writing new code, features, architecture, code review
- **debugging** — fixing bugs, error messages, stack traces, troubleshooting
- **data_analysis** — SQL, pandas, statistics, visualization, data science
- **casual** — conceptual questions, explanations, learning, general Q&A
- **creative** — writing, design, strategy, brainstorming

Fallback: if Stage 1 fails for any reason, domain defaults to `"general"` and Stage 2 proceeds without domain filtering.

---

#### Stage 2 — Evaluator Agent

| Property | Value |
|---|---|
| Model | `gpt-4o` |
| Temperature | 0.2 |
| Tool | `FileSearchTool` |
| Vector store | Persistent OpenAI Vector Store |
| max_num_results | 8 chunks per call |
| Input | Full eval prompt (see below) |
| Output | JSON (PEI scores + breakdown + suggestions) |
| Latency | ~2000ms |
| Cost | ~$0.004 per call |

**Total pipeline latency: ~2.5s**
**Total pipeline cost: ~$0.004 per evaluation turn**
**At 100 students × 10 turns/day: ~$4/day**

---

#### The Eval Prompt (Stage 2 Input)

```
CONVERSATION DOMAIN: {DOMAIN}

STUDENT HISTORICAL PROFILE:
  Sessions completed: {n}
  Average PEI (recent 5 sessions): {avg}
  Strongest dimension: {dim} (avg {score})
  Weakest dimension:   {dim} (avg {score})
  Trend: {improving|stable|declining} ({delta} PEI over last 4 sessions)
  Recurring red flags: {list of top 3 patterns}

INSTRUCTIONS:
  1. Retrieve the {domain} rubric and relevant exemplars from your knowledge base
  2. Score using the PEI framework — scores are absolute, not relative to student history
  3. In suggestions, reference the student's historical weak areas
  4. Flag explicitly if the student is repeating a known red flag pattern
  5. Note if the student is showing improvement vs their historical baseline

CURRENT SESSION ({n} user turns so far):
[Turn 1] USER: ...
[Turn 1] ASSISTANT: ...
...
[Turn N] USER: (latest — weight most heavily for PSQ)

Focus on LATEST message for PSQ. Full arc for CCM and RAS.
Return ONLY valid JSON matching the schema.
```

---

#### Historical Profile Construction

Built from `eval_results` table at evaluation time. Covers:

- Sessions count (distinct conversations)
- Average PEI over last 5 sessions
- Per-dimension averages (PSQ, CCM, TSI, CLM, RAS)
- Strongest and weakest dimensions
- PEI trend (compare last 3 sessions vs previous 3)
- Top 3 recurring red flags (frequency-counted from `full_result` JSON)

New students (no history) receive a `is_new_student: true` flag — the agent calibrates its suggestions accordingly, focusing on foundational habits rather than correction of patterns.

---

### Vector Store Retrieval

When Stage 2 queries the vector store, the domain-hinted prompt causes semantic retrieval of the right files naturally:

```
Query: "CODING rubric PSQ CCM exemplars advanced evaluation coding conversation"

Retrieved chunks (ranked by similarity):
  1. rubric_coding.md — PSQ section                  (0.94)
  2. exemplars_advanced.md — coding exemplar         (0.91)
  3. framework_core.pdf — PSQ formula                (0.88)
  4. exemplars_novice.md — coding exemplar           (0.85)
  5. rubric_coding.md — RAS verification section     (0.83)
  6. scoring_rules.md — red flag definitions         (0.81)
  7. research_prompting_2025.pdf — code quality data (0.79)
  8. exemplars_intermediate.md — coding turn         (0.77)
```

No manual routing — semantic similarity handles domain targeting automatically.

---

## Knowledge Base Structure

```
Vector Store: vs_huskyai_evaluator
│
├── CORE/
│   ├── framework_core.pdf
│   │   Full PEI framework, dimension definitions, scoring formulas,
│   │   leading/led-by paradigm, classification taxonomy (Novice/Intermediate/Advanced)
│   │   Retrieved for: every evaluation (anchor document)
│   │
│   └── scoring_rules.md
│       Exact thresholds, red flag trigger conditions, edge case handling
│       Examples:
│         - RAS < 0.3 for 3+ turns = mandatory red flag
│         - Single-turn conversations: CLM scored at 50 (neutral)
│         - Debugging domain: TSI weighted +10% vs standard formula
│
├── RUBRICS/
│   ├── rubric_coding.md
│   │   Domain: writing code, features, architecture, code review
│   │   Sections:
│   │     PSQ — what good verb specificity looks like in code requests
│   │       ✓ "Refactor this auth middleware to use JWT instead of sessions"
│   │       ✗ "Help me with my login code"
│   │     CCM — what leading looks like when reviewing generated code
│   │       ✓ User specifies acceptance criteria before seeing solution
│   │       ✗ User asks "is this correct?" after every generated function
│   │     RAS — verification behaviors specific to code
│   │       ✓ User runs code locally before accepting
│   │       ✗ User pastes AI output directly into PR without review
│   │     TSI — decomposition signals
│   │       ✓ User breaks feature into auth / data layer / UI before asking
│   │       ✗ User asks "build me a full e-commerce site"
│   │
│   ├── rubric_debugging.md
│   │   Domain: bug fixing, error messages, stack traces, troubleshooting
│   │   Key signals:
│   │     High TSI: user isolates problem to specific layer before asking
│   │     Low PSQ: "my code doesn't work" with no error, no context, no env
│   │     High CCM: user has already ruled out causes, directs hypothesis
│   │     Minimum required context: error message + what was tried + environment
│   │
│   ├── rubric_data_analysis.md
│   │   Domain: SQL, pandas, statistics, visualization, data science
│   │   Key signals:
│   │     Good CLM: user defines business question before asking for SQL
│   │     Good TSI: user mentions data scale, performance, edge cases
│   │     Good RAS: user validates query results make logical sense
│   │     Red flag: accepting SQL output without checking row counts / nulls
│   │
│   └── rubric_casual.md
│       Domain: conceptual questions, learning, explanations, general Q&A
│       Note: TSI weighted lower (no code decomposition expected)
│       Key signals:
│         CLM — is student building understanding incrementally?
│         RAS — is student passively consuming or actively questioning?
│         CCM — does student ask follow-ups or accept first explanation?
│
├── EXEMPLARS/
│   ├── exemplars_novice.md         (PEI 10–35)
│   │   Format per exemplar:
│   │     DOMAIN: coding
│   │     PEI: 18  |  TURN: 1
│   │     USER: "help me make a login system"
│   │     WHY LOW:
│   │       PSQ=12 — no verb beyond "make", no tech stack, no constraints
│   │       CCM=8  — immediately defers to whatever AI suggests
│   │       TSI=5  — zero decomposition of auth problem space
│   │       RAS=15 — accepts first suggestion, asks AI to "write it all"
│   │
│   ├── exemplars_intermediate.md   (PEI 40–65)
│   │   Shows partial improvement:
│   │     User provides some context but missing constraints
│   │     Occasionally challenges AI output but inconsistently
│   │     Some decomposition in complex requests, absent in simple ones
│   │
│   └── exemplars_advanced.md       (PEI 70–90)
│       Format per exemplar:
│         DOMAIN: debugging
│         PEI: 84  |  TURN: 2
│         USER: "The error only occurs when the user has a special char
│                in their email. I've confirmed it's not the regex.
│                I need to understand if this is at the DB layer or the
│                API serializer. Here's the trace: [...]. I've already
│                ruled out encoding issues on the client."
│         WHY HIGH:
│           PSQ=91 — clear scope, evidence provided, constraint defined
│           CCM=85 — user has investigated, directs AI to specific layers
│           TSI=88 — problem isolated to two layers, ruled out client
│           RAS=80 — user verifying hypothesis, not accepting it blindly
│
└── RESEARCH/
    ├── appropriate_reliance_2024.pdf
    │   Key findings referenced by evaluator:
    │   "Over-reliance: accepting AI output without verification in >40%
    │    of code generation events (Zhang et al., 2024)"
    │
    ├── prompting_patterns_2025.pdf
    │   Key findings:
    │   "Students who decompose problems before prompting show 34% higher
    │    code quality outcomes (Mahmoud et al., 2025)"
    │
    ├── ai_literacy_frameworks.pdf
    │   Key findings:
    │   "Control acquisition follows a predictable arc: CCM improves before
    │    PSQ in most learners (NEU AI Literacy Lab, 2025)"
    │
    └── llm_overreliance_studies.pdf
        Key findings:
        "Passive acceptance of AI suggestions correlates with skill
         stagnation in programming learners (Chen et al., 2024)"
```

### File Naming Convention

Names are part of what gets indexed — use descriptive names:
```
✓  rubric_coding.md               ← domain in filename
✓  exemplars_advanced_coding.md   ← level + domain both searchable
✓  research_reliance_zhang2024.pdf
✗  doc1.pdf                       ← meaningless to semantic search
✗  rubric.md                      ← too generic
```

---

## PEI Scoring Framework

### Formula

```
PEI = 0.25 × PSQ + 0.25 × CCM + 0.20 × TSI + 0.15 × CLM + 0.15 × RAS
```

### Dimensions

| Dimension | Full Name | What It Measures |
|---|---|---|
| **PSQ** | Prompt Structural Quality | Verb clarity, context completeness, constraints, focus, alignment |
| **CCM** | Conversation Control Metrics | Initiative ratio, verification frequency, course correction, assumption challenges |
| **TSI** | Technical Sophistication Index | Decomposition depth, tool awareness, error anticipation, iteration |
| **CLM** | Cognitive Load Management | Chunk size, incremental building, clarification seeking, structured thinking |
| **RAS** | Reliance Appropriateness Score | Correct reliance rate, over-reliance events, under-reliance events, trust calibration |

### PSQ Sub-formula

```
PSQ = 0.30 × verb_specificity
    + 0.25 × context_completeness
    + 0.20 × constraint_defined
    + 0.15 × focus_clarity
    + 0.10 × alignment_specified
```

### Classification

| Classification | PEI Range | Description |
|---|---|---|
| Novice | < 40 | Predominantly led-by AI, low structure, minimal verification |
| Intermediate | 40–70 | Mixed control, improving structure, occasional verification |
| Advanced | > 70 | Leading the AI, sophisticated prompting, consistent verification |

### Red Flags for Intervention

- Consistent over-reliance: RAS < 0.3 across 3+ consecutive turns
- Multi-turn degradation: performance drops > 50% from turn 1 to turn 5
- Premature acceptance: accepting incorrect AI suggestions > 40% of turns
- No verification: zero verification attempts across 5+ code generations

---

## Database Schema

```
users
  id            String PK
  email         String UNIQUE
  name          String
  password_hash String
  created_at    DateTime

conversations
  id            String PK
  user_id       String FK → users.id
  started_at    DateTime
  ended_at      DateTime (nullable)
  turn_count    Integer

messages
  id              String PK
  conversation_id String FK → conversations.id
  role            String  ("user" | "assistant")
  content         Text
  created_at      DateTime

eval_results
  id              String PK
  conversation_id String FK → conversations.id
  turn_number     Integer
  pei             Float
  psq             Float
  ccm             Float
  tsi             Float
  clm             Float
  ras             Float
  classification  String  ("Novice" | "Intermediate" | "Advanced")
  leading_status  String  ("Leading" | "Led-by")
  full_result     JSON    (complete evaluator output including suggestions, red flags, domain)
  created_at      DateTime

challenges
  id              String PK
  title           String
  description     Text
  category        String
  difficulty      String
  week            Integer
  total_sessions  Integer
  sessions_data   JSON

user_challenge_sessions
  id              String PK
  user_id         String FK → users.id
  challenge_id    String FK → challenges.id
  session_number  Integer
  status          String  ("not_started" | "in_progress" | "completed")
  best_pei        Float (nullable)
  conversation_id String FK → conversations.id (nullable)
  started_at      DateTime (nullable)
  completed_at    DateTime (nullable)
```

---

## Running Locally

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env    # fill in your keys
uvicorn main:app --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`

### Local environment (`.env`)

```
GOOGLE_API_KEY=your_gemini_key
OPENAI_API_KEY=sk-...
OPENAI_VECTOR_STORE_ID=vs_...
JWT_SECRET=generate_with_python_secrets_token_hex_32
DATABASE_URL=           # leave empty to use SQLite locally
```

---

## Deploying to Railway

Two separate Railway services from the same GitHub repo.

### Backend Service

- Root directory: `backend`
- Start command: auto-detected via `nixpacks.toml` → `uvicorn main:app --host 0.0.0.0 --port $PORT`

Environment variables:
```
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
OPENAI_VECTOR_STORE_ID=...
JWT_SECRET=...
DATABASE_URL=            # auto-injected by Railway PostgreSQL service
```

### Frontend Service

- Root directory: `frontend`
- Build: `npm run build`

Environment variables:
```
VITE_WS_URL=wss://huskyai-production.up.railway.app/ws
VITE_API_URL=https://huskyai-production.up.railway.app
```

### PostgreSQL

Add a PostgreSQL service to the Railway project. `DATABASE_URL` is automatically injected into all services in the same project. Tables are created automatically on startup via `init_db()`.

---

## Environment Variables

| Variable | Service | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Backend | Gemini API key for chat model |
| `OPENAI_API_KEY` | Backend | OpenAI API key for evaluator agent |
| `OPENAI_VECTOR_STORE_ID` | Backend | Persistent vector store ID (`vs_...`) |
| `JWT_SECRET` | Backend | Secret for signing JWT tokens (min 32 chars) |
| `DATABASE_URL` | Backend | PostgreSQL connection string (auto-set by Railway) |
| `VITE_WS_URL` | Frontend | WebSocket URL for chat connection |
| `VITE_API_URL` | Frontend | HTTP URL for auth API calls |

---

## Future Scope

### Phase 2 — Automatic Exemplar Mining (3 months)
Every 100 conversations, a cron job queries the DB for high-scoring sessions (PEI > 78), formats them as exemplar documents, and uploads them to the vector store automatically. The KB improves every week without human intervention.

### Phase 2 — Materialized Student Profiles
A `student_profiles` table stores pre-computed averages, trends, and red flag counts. Updated after every session closes. Eliminates the per-evaluation DB aggregation query, reducing eval latency.

### Phase 3 — Trajectory Analyzer (6 months)
A weekly scheduled agent analyzes each student's full scoring arc and writes a 2-sentence narrative shown on their dashboard: current classification + what to focus on next. Flags declining students to instructors.

### Phase 3 — Personalized Suggestion Generator
Uses the student's historical red flag frequency to generate targeted exercises. A student with 6 instances of "accepts code without verification" receives a specific verification-practice challenge.

### Phase 3 — Collective Mirror (Cross-Classroom)
Two classrooms are paired. Aggregate PEI patterns (radar charts, not individual scores) are transmitted live between paired classes. Students adapt behavior in response to the partner class's patterns, creating a structured feedback loop.

### Phase 4 — KB Drift Detection (12 months)
A quarterly audit agent compares score distributions of recent real conversations against exemplar baselines. If average real PEI has shifted > 5 points from KB midpoints, specific files are flagged for human review.

### Phase 4 — Fine-Tuned Evaluator
Once 10,000+ real evaluated conversations are collected, fine-tune a smaller model (gpt-4o-mini) specifically on HuskyAI data. Reduces cost by 10x while maintaining calibration to real student behavior.

### Phase 4 — Research Paper Auto-Ingestion
Monitor arXiv RSS feeds for papers tagged `cs.AI + education` or `HCI + LLM`. Automatically summarize and upload relevant findings to the RESEARCH/ KB folder quarterly.

---

## Key Performance Indicators

### Primary
1. User Agency Distribution — % of students classified as Leading vs Led-by
2. Average PEI per class per week
3. Reliance Calibration Accuracy (RAS trend)
4. Multi-turn Success Degradation Rate
5. Learning Velocity — PEI improvement per session over the semester

### Secondary
1. Prompt Pattern Adoption Rates
2. Error Recovery Efficiency
3. Challenge Completion Rate
4. Instructor Intervention Rate (red flags triggered)
