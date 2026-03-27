"""
Two-stage PEI evaluator — generated via OpenAI Agent Builder, adapted for HuskyAI.

Stage 1 — Domain Detector (gpt-4.1-nano): classifies conversation domain
Stage 2 — Evaluator (gpt-4.1 + FileSearchTool): scores on all 5 PEI dimensions
"""

import os
import logging
import time
from dotenv import load_dotenv
from pydantic import BaseModel
from agents import (
    Agent,
    FileSearchTool,
    ModelSettings,
    Runner,
    RunConfig,
    TResponseInputItem,
)

load_dotenv()

log = logging.getLogger("chat-evaluator")

# ---------------------------------------------------------------------------
# Pydantic output schema (matches portal-generated EvaluatorSchema)
# ---------------------------------------------------------------------------

class EvaluatorSchema__Scores(BaseModel):
    PSQ: float
    CCM: float
    TSI: float
    CLM: float
    RAS: float
    PEI: float


class EvaluatorSchema__Breakdown(BaseModel):
    verb_specificity: float
    context_completeness: float
    constraint_defined: float
    focus_clarity: float
    initiative_ratio: float
    verification_frequency: float
    decomposition_depth: float
    chunk_size_appropriate: float
    correct_reliance_rate: float


class EvaluatorSchema(BaseModel):
    scores: EvaluatorSchema__Scores
    breakdown: EvaluatorSchema__Breakdown
    classification: str
    leading_status: str
    suggestions: list[str]
    red_flags: list[str]
    strengths: list[str]
    turn_summary: str


# ---------------------------------------------------------------------------
# Stage 1 — Domain Detector
# ---------------------------------------------------------------------------

domain_detector = Agent(
    name="Domain Detector",
    instructions="""You are a conversation domain classifier for an AI prompting evaluation system.

Your only job is to read a student's conversation with an AI assistant and
classify it into exactly one domain.

## Domains

coding
  Writing new code, implementing features, building functions or classes,
  software architecture decisions, code review, refactoring.
  Signal: user is creating something new in code.

debugging
  Fixing broken code, interpreting error messages, reading stack traces,
  diagnosing runtime failures, troubleshooting unexpected behavior.
  Signal: something exists and is not working correctly.

data_analysis
  Writing SQL queries, working with pandas/numpy, statistics, data visualization,
  data science pipelines, ML model training, analyzing datasets.
  Signal: the subject is data — transforming, querying, or understanding it.

casual
  Conceptual questions, learning how something works, asking for explanations,
  general knowledge, understanding theory without writing code.
  Signal: no code being written or debugged, primarily learning or discussing.

creative
  Writing content, product strategy, UI/UX design thinking, brainstorming ideas,
  business problems, non-technical problem solving.
  Signal: output is words, ideas, or strategy — not code or data.

## Decision Rules

- If both debugging and coding are present, choose DEBUGGING (more specific)
- If both data_analysis and coding are present, choose DATA_ANALYSIS
- Base your decision primarily on the first user message
- When unsure, choose the domain that best describes the user's GOAL
- Never output more than one domain

## Output

Return a structured object with:
  domain     — one of: coding, debugging, data_analysis, casual, creative
  confidence — float 0.0 to 1.0 (how certain you are)
  reasoning  — one sentence explaining your choice
""",
    model="gpt-4.1-nano",
    model_settings=ModelSettings(temperature=1, top_p=1, max_tokens=256, store=True),
)


# ---------------------------------------------------------------------------
# Stage 2 — PEI Evaluator
# ---------------------------------------------------------------------------

_VECTOR_STORE_ID = os.getenv(
    "OPENAI_VECTOR_STORE_ID",
    "vs_69c5b5732cfc8191a9fbecc9ee76b31f",  # from portal
)

file_search = FileSearchTool(vector_store_ids=[_VECTOR_STORE_ID])

evaluator = Agent(
    name="Evaluator",
    instructions="""You are an expert AI interaction quality evaluator for HuskyAI, a prompting
skills platform for Northeastern University students.

Your role is to evaluate the USER's prompting behavior in a conversation with
an AI coding assistant, using the User Agency Continuum framework.

## Your Process — Follow This Exactly

STEP 1: Read the CONVERSATION DOMAIN at the top of the input.
STEP 2: Use your file search tool to retrieve:
         - The rubric for that specific domain (e.g. rubric_coding.md)
         - Exemplars at novice, intermediate, and advanced levels
         - Relevant sections of the core framework
         Do this BEFORE scoring. Ground your scores in what you retrieve.
STEP 3: Read the STUDENT HISTORICAL PROFILE if provided.
         Use it to personalize suggestions — not to adjust scores.
         Scores are always absolute against the framework, never relative.
STEP 4: Score the conversation using the five dimensions below.
STEP 5: Return ONLY the JSON object. No other text.

---

## Evaluation Framework

### Dimension 1: Prompt Structural Quality (PSQ) — weight 25%

Sub-components:
  verb_specificity (1-5)
    1 = no clear verb ("help me", "fix this")
    3 = generic verb ("write", "explain")
    5 = precise action verb ("refactor", "debug", "implement", "optimize")

  context_completeness (0-100)
    % of necessary context provided: language, environment, existing code,
    error messages, what was already tried, relevant constraints

  constraint_defined (0 or 1)
    1 = explicit limitations stated (performance, compatibility, style, scope)
    0 = no constraints mentioned

  focus_clarity (1-5)
    1 = completely open-ended with no defined endpoint
    5 = precisely defined desired output or success criteria

  alignment_specified (0 or 1)
    1 = user states what "done" looks like or how they will verify success
    0 = no success criteria defined

PSQ = (0.30 × verb) + (0.25 × context) + (0.20 × constraints) +
      (0.15 × focus) + (0.10 × alignment)
Normalize to 0-100.

### Dimension 2: Conversation Control Metrics (CCM) — weight 25%

Turn-level measurements:
  initiative_ratio (0-1): User-initiated direction changes / total turns
  verification_frequency (0-1): Times user verified output / times AI generated code
  course_correction_rate (0-1): User redirections after AI errors / total AI errors
  assumption_challenge_rate (0-1): User challenged AI assumptions / total AI assumptions

Score: 80-100 if user clearly leads, 40-70 if mixed, 0-40 if AI leads.

### Dimension 3: Technical Sophistication Index (TSI) — weight 20%

  decomposition_depth (1-10): sub-problems identified before asking
  tool_technique_awareness: references to specific patterns, libraries, algorithms
  error_anticipation: proactive edge-case or failure-mode mentions
  solution_iteration: user-initiated refinement cycles

Adjust: for debugging domain, weight decomposition_depth +10%.
        for casual domain, weight decomposition_depth -10%.

### Dimension 4: Cognitive Load Management (CLM) — weight 15%

  chunk_size_appropriate (0-100): message length appropriate to request complexity
  incremental_building (0-1): iterative step-by-step vs monolithic requests
  clarification_seeking (0-1): clarifying questions before acting on ambiguity
  mental_model_indicators: numbered steps, explicit assumptions, defined scope

### Dimension 5: Reliance Appropriateness Score (RAS) — weight 15%

  correct_reliance_rate (0-1): (correct self-reliance + correct AI-reliance) / decisions
  over_reliance_events: accepting incorrect AI output without questioning
  under_reliance_events: rejecting clearly correct AI output without reason

## Overall Score
PEI = 0.25*PSQ + 0.25*CCM + 0.20*TSI + 0.15*CLM + 0.15*RAS

## Classification
- Novice: PEI < 40
- Intermediate: PEI 40-70
- Advanced: PEI > 70
""",
    model="gpt-4.1",
    tools=[file_search],
    output_type=EvaluatorSchema,
    model_settings=ModelSettings(temperature=1, top_p=1, max_tokens=2048, store=True),
)


# ---------------------------------------------------------------------------
# Public API — called from main.py after each WebSocket turn
# ---------------------------------------------------------------------------

def _format_conversation(history: list) -> str:
    lines = []
    for i, msg in enumerate(history):
        role = "USER" if msg["role"] == "user" else "ASSISTANT (AI)"
        lines.append(f"[Turn {(i // 2) + 1}] {role}:\n{msg['content']}")
    return "\n\n".join(lines)


async def evaluate_conversation(conversation_history: list) -> dict:
    """
    Run two-stage evaluation. Returns dict matching legacy schema consumed
    by main.py / database.py EvalResult rows.
    """
    t0 = time.monotonic()
    user_turns = sum(1 for m in conversation_history if m["role"] == "user")
    total_turns = len(conversation_history)
    conv_text = _format_conversation(conversation_history)

    log.info(f"[EVAL] Starting two-stage eval ({user_turns} user turns, {total_turns} total)")

    input_text = (
        f"Conversation stats: {user_turns} user turns, {total_turns} total.\n\n"
        f"<conversation>\n{conv_text}\n</conversation>\n\n"
        "Focus on the LATEST user message most heavily. "
        "Be calibrated — a single vague message should score Novice. "
        "Provide 3-5 specific, actionable suggestions."
    )

    conversation: list[TResponseInputItem] = [
        {"role": "user", "content": [{"type": "input_text", "text": input_text}]}
    ]

    try:
        # ── Stage 1: domain detection ──────────────────────────────────────
        s1 = await Runner.run(
            domain_detector,
            input=conversation,
            run_config=RunConfig(workflow_name="HuskyAI-Eval"),
        )
        domain_text = s1.final_output_as(str)
        log.info(f"[EVAL-S1] {domain_text[:120]}")

        # Feed domain detector output into evaluator's context
        conversation.extend([item.to_input_item() for item in s1.new_items])

        # ── Stage 2: PEI evaluation ────────────────────────────────────────
        s2 = await Runner.run(
            evaluator,
            input=conversation,
            run_config=RunConfig(workflow_name="HuskyAI-Eval"),
        )
        result: EvaluatorSchema = s2.final_output

        elapsed = time.monotonic() - t0
        log.info(
            f"[EVAL-S2] Done in {elapsed:.2f}s — "
            f"PEI={result.scores.PEI:.1f} ({result.classification}, {result.leading_status})"
        )

        out = result.model_dump()
        # Flatten nested scores/breakdown for legacy callers
        out["scores"] = result.scores.model_dump()
        out["breakdown"] = result.breakdown.model_dump()
        out["domain_raw"] = domain_text  # bonus metadata
        return out

    except Exception as e:
        elapsed = time.monotonic() - t0
        log.error(f"[EVAL] Failed after {elapsed:.2f}s: {type(e).__name__}: {e}", exc_info=True)
        return _default_eval()


def _default_eval() -> dict:
    return {
        "scores": {"PSQ": 0, "CCM": 0, "TSI": 0, "CLM": 0, "RAS": 0, "PEI": 0},
        "breakdown": {
            "verb_specificity": 1, "context_completeness": 0,
            "constraint_defined": 0, "focus_clarity": 1,
            "initiative_ratio": 0, "verification_frequency": 0,
            "decomposition_depth": 1, "chunk_size_appropriate": 50,
            "correct_reliance_rate": 0.5,
        },
        "classification": "Novice",
        "leading_status": "Led-by",
        "suggestions": ["Evaluation temporarily unavailable. Please try again."],
        "red_flags": [],
        "strengths": [],
        "turn_summary": "Evaluation unavailable.",
    }
