# Coding Domain Rubric

Apply this rubric when the conversation involves writing code, implementing features,
architecture decisions, or code review.

## PSQ in Coding Conversations

HIGH PSQ (80-100):
- "Refactor this Express auth middleware to use JWT instead of sessions.
   It needs to work with our existing Redis store. Here's the current code: [...]"
- Clear action verb (refactor), tech stack specified, constraint (Redis), context provided

LOW PSQ (0-25):
- "Help me with my login code"
- "Can you write authentication for me"
- No language, no framework, no constraints, no current state provided

MEDIUM PSQ (40-65):
- "Write a login function in Python using FastAPI"
- Has verb and language but missing: what auth method, what's already built, success criteria

## CCM in Coding Conversations

HIGH CCM signals (user is leading):
- User specifies what they DON'T want before seeing the solution
- User defines acceptance criteria: "it must handle 10k concurrent users"
- User redirects after seeing solution: "that approach won't work because..."
- User asks the AI to explain before implementing

LOW CCM signals (user is led-by):
- User asks "is this correct?" after every generated function
- User copies solution without reading it
- User asks AI to "just finish it" after partial implementation
- User accepts the first approach suggested without questioning alternatives

## TSI in Coding Conversations

HIGH TSI signals:
- User decomposes feature before asking: "I need to handle: (1) auth, (2) session, (3) token refresh"
- User references specific patterns: "I want to use the repository pattern"
- User anticipates edge cases: "what happens if the token expires mid-request?"
- User initiates refinement: "the solution works but I want to optimize the DB query"

LOW TSI signals:
- "Build me a full e-commerce site"
- No decomposition of complex problems
- No mention of edge cases, scale, or technical constraints

## RAS in Coding Conversations

HIGH RAS (appropriate reliance):
- User runs the generated code locally before accepting
- User reads the code before saying it looks good
- User questions unusual patterns: "why are you using X instead of Y here?"
- User provides test results back to AI

LOW RAS (over-reliance):
- User copies AI output directly into production without testing
- User says "looks good" without evidence of reading
- User asks AI to write tests for code the AI wrote (without reviewing first)
- User reports error message without any attempt to debug first

---

# Data Analysis Domain Rubric

Apply this rubric when the conversation involves SQL queries, pandas, statistics, ML pipelines,
data cleaning, anomaly detection, or BI/metrics investigation.

## PSQ in Data Conversations

HIGH PSQ (80-100):
- "Redshift. Table: events(user_id bigint, event_type varchar, occurred_at timestamptz)
   ~200M rows, 18 months. Partitioned by date. No standalone user_id index.
   I tried: [LAG window query partitioned by user_id, ordered by occurred_at]. Getting
   duplicate rows when two events share the same second — LAG returns the wrong prior event.
   Constraint: must run in <20s on a full month. Can you: (1) confirm the tie-breaking bug,
   (2) fix the ORDER BY clause, (3) recommend a sort key change that would help?"
  → Table schema + row count + partition + existing attempt + hypothesis + perf constraint + 3 sub-questions

LOW PSQ (0-25):
- "can you analyze my data and tell me whats interesting" — no data, no domain, no structure
- "write a SQL query for my database" — no schema, no goal, no table names

MEDIUM PSQ (40-65):
- "I have survey responses (n=180). I want to compare scores before and after a redesign."
  → Has basic context but missing: distribution info, significance threshold, output format

## CCM in Data Conversations

HIGH CCM signals (user is leading):
- User shows a prior SQL/code attempt with a specific hypothesis about what's wrong
- User states performance constraints ("must complete in <20s on prod")
- User decomposes the pipeline: "first join, then aggregate, then compute ..."
- User stages the work: "I want the reasoning first, then I'll ask for code"

IMPORTANT: A data prompt with prior attempt + hypothesis + directed sub-questions is
HIGH CCM (72-80), NOT medium (50). Prior attempt = initiative_ratio 0.75, not 0.5.

INTERMEDIATE CCM (60-68): User specifies the goal and output format clearly, but AI makes
all substantive analytical decisions. No prior attempt, no staged pipeline, no hypothesis
formed before asking. Example: "Clean this DataFrame — fix mixed types, inconsistent casing,
and negative values" or "Find anomalies in this dataset and explain what you find."
These are well-specified asks (high PSQ) but the user is a passive recipient — CCM 62-68.
DO NOT score these as 75. Good specification is PSQ, not CCM.

LOW CCM: "can you analyze my data" / "write a query for [vague description]"

## TSI in Data Conversations

HIGH TSI signals:
- User decomposes data pipeline: "join on user_id → group by signup_month → compute return %"
- User references specific techniques: "window functions", "CTE chain", "cohort analysis",
  "modified Z-score", "IQR vs sigma rule"
- User anticipates edge cases: "NULL vs 0", "missing values", "fiscal year vs calendar year"
- User considers scale: "~200M rows so partition-friendly approach"

SCORING: Explicit pipeline + technique references + edge cases → TSI 75-85;
clear goal + technique reference but no decomposition → TSI 50-65;
vague data ask → TSI 10-25.

## RAS in Data Conversations

HIGH RAS signals:
- Prior query attempt with specific hypothesis about the bug → +10
- States they will EXPLAIN ANALYZE / run tests → +15 verification intent
- Quantifies what "wrong" means ("getting 847 rows, expected ~200") → +10
- Asks for reasoning / method comparison before requesting code → staged reliance

---

# Casual / Creative Domain Rubric

Apply this rubric when the conversation is:
- Conceptual questions, learning, theory ("explain X", "what is Y")
- Writing for educational/personal purposes (essays, op-eds, cover letters, student work)
- Brainstorming for learning or personal projects (naming, ideation, planning)

## PSQ in Casual Conversations

HIGH PSQ (80-100): pattern
A high PSQ casual writing/speaking prompt has ALL of:
- Audience characterized by knowledge level, role, or frame — not just "general audience"
- Forbidden or required elements named explicitly (what to avoid, what must be included)
- Output format and quantity specified (e.g. 2 options, 3 components each)
- Staged work — user explicitly reserves drafting, selecting, or deciding for themselves
→ PSQ 85-95 when all four signals present; 65-80 when 2-3 present; below 40 when absent.

A high PSQ casual research/analysis prompt has ALL of:
- Prior research or prior work shown before asking
- Explicit scope constraint ("don't write X — I'll do that")
- Specific bounded ask (1-2 targeted questions, not open-ended)
- User retains the substantive output for themselves
→ PSQ 82-92 when all present; 55-70 when scope-bounding present but missing prior work.

LOW PSQ (0-25):
- "write me an essay about climate change" — no audience, angle, length, or constraints
- "explain machine learning" — verb present but scope enormous, no focus

## CCM in Casual Conversations

HIGH CCM: User scopes AI's role explicitly ("give me options — I'll decide"), bounds the output
format, provides negative constraints before seeing output, asks for options before committing.
Single-turn with explicit scope-bounding ("I'll vote/draft/decide myself") → CCM 72-80.

INTERMEDIATE CCM (58-68): User specifies output format and constraints, but AI makes all
substantive creative or planning decisions. The user has defined WHAT they want but not
bounded HOW MUCH of the work AI should do. Example: a trip planning request with dietary
and pacing constraints, or a writing request with length and audience specified, where the
user is asking for a complete deliverable. Good constraints = PSQ, not CCM.
DO NOT score these at 75. A structured ask for a complete output is CCM 60-68, not 75.

LOW CCM: "write me an essay" — AI must invent the entire frame.

## TSI in Casual Conversations

KEY RULE: TSI measures sophistication of THINKING, not coding. Good decomposition = high TSI
regardless of domain.

HIGH TSI signals:
- Explicit decomposition: "I've broken this down into: (1)... (2)... (3)..."
- Structured output framework: angles/categories/taxonomy specified before seeing AI output
- Negative constraint specification: systematic elimination of design space
- Staged approach: "give me options first, I'll decide later"
- Audience characterized by behavior or disciplinary frame rather than demographic

EXAMPLES:
- Lightning talk prep with required elements + 2-option output + staged work → TSI 72-82
- Interview pressure-test with own framework presented for critique → TSI 75-82
- Theory question with 4-part decomposition + methodology → TSI 78-88
- Vague ask ("explain AI", "write an essay") → TSI 12-25

IMPORTANT: "I'll vote/draft/decide myself" = staged approach = HIGHER TSI, not lower.

## RAS in Casual Conversations

HIGHEST (80-88): User explicitly reserves creative/analytical work for themselves.
- "I'll vote with my team before committing"
- "Give me the skeleton — I'll write the full draft once I've validated the structure"
- "Just explain the concept — I'll implement/write it once I understand"
→ User uses AI as a thinking partner, retains authorship.

HIGH (68-78): User will review output before committing; asks for reasoning before execution.
BASE-TO-LOW (50-62): User asks for a complete deliverable (full plan, full itinerary, full
implementation) with constraints. Specifying constraints and output format does NOT indicate
appropriate reliance — that is PSQ. RAS is about whether the user retains substantial work
for themselves. Asking "plan my trip with these constraints" or "clean this data and fix
these issues" is RAS 50-62 — the user is outsourcing the entire task.
BASE (45): Single-turn with no reliance signals in either direction.
