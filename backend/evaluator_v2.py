"""
Approach 2 PEI evaluator (three-stage pipeline).

Stage 1  — Domain detector   (gpt-4.1-nano)
Stage 2a — Scorer            (gpt-4.1-mini, temperature 0.0, JSON only)
Stage 2b — Feedback writer   (gpt-4.1, warmer, writes prose, sees scores)

Public API: evaluate_conversation_v2(history) -> dict matching EvaluatorSchema.
This is a drop-in alternative to evaluator.evaluate_conversation() so the
judge benchmark can compare v1 (single evaluator) against v2 (split).

All runs are stored in the OpenAI dashboard under workflow_name="HuskyAI-Eval-v2".
View traces at platform.openai.com/traces.
"""

import os
import asyncio
import logging
import time
from pathlib import Path

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

from evaluator import (
    EvaluatorSchema__Scores,
    EvaluatorSchema__Breakdown,
)

_eval_dir = Path(__file__).resolve().parent
load_dotenv(_eval_dir / ".env")
load_dotenv()

log = logging.getLogger("chat-evaluator-v2")

_VECTOR_STORE_ID = os.getenv(
    "OPENAI_VECTOR_STORE_ID",
    "vs_69c5b5732cfc8191a9fbecc9ee76b31f",
)
file_search = FileSearchTool(vector_store_ids=[_VECTOR_STORE_ID])


# ---------------------------------------------------------------------------
# Stage 1 — Domain Detector (same as v1)
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

debugging
  Fixing broken code, interpreting error messages, reading stack traces,
  diagnosing runtime failures, troubleshooting unexpected behavior.

data_analysis
  Writing SQL queries, working with pandas/numpy, statistics, data visualization,
  data science pipelines, ML model training, analyzing datasets.

casual
  Conceptual questions, learning how something works, asking for explanations,
  general knowledge, understanding theory without writing code.

creative
  Writing content, product strategy, UI/UX design thinking, brainstorming ideas,
  business problems, non-technical problem solving.

## Decision Rules
- If both debugging and coding are present, choose DEBUGGING
- If both data_analysis and coding are present, choose DATA_ANALYSIS
- Base your decision primarily on the first user message
- When unsure, choose the domain that best describes the user's GOAL
- Never output more than one domain

## Output
Return: domain (one of: coding, debugging, data_analysis, casual, creative),
confidence (0.0 to 1.0), reasoning (one sentence).
""",
    model="gpt-4.1-nano",
    model_settings=ModelSettings(temperature=0.2, top_p=0.9, max_tokens=256, store=True),
)


# ---------------------------------------------------------------------------
# Stage 2a — Scorer (deterministic, numbers only)
# ---------------------------------------------------------------------------

class ScorerOutput(BaseModel):
    scores: EvaluatorSchema__Scores
    breakdown: EvaluatorSchema__Breakdown
    classification: str
    leading_status: str


scorer = Agent(
    name="PEI Scorer",
    instructions="""You are a strict, deterministic PEI scorer for HuskyAI.

Given a conversation and its domain, score the USER's prompting behavior on
the User Agency Continuum framework. Output ONLY scores, breakdown,
classification, and leading_status. NO prose, NO suggestions, NO red flags.

## Your Process
STEP 1: Read the CONVERSATION DOMAIN from earlier in the input.
STEP 2: Use file search to retrieve:
         - The rubric for that specific domain (e.g. rubric_coding.md)
         - Exemplars at novice, intermediate, advanced levels
         - Relevant sections of the core framework
        Ground your scores in what you retrieve.
STEP 3: Score the conversation using the five dimensions below.
STEP 4: Return ONLY the JSON object matching the schema.

Same input must produce the same output. Be calibrated and consistent.
Scores are always absolute against the framework, never relative.

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
    error messages, what was tried, constraints

  constraint_defined (0 or 1)
    1 = explicit limitations stated (performance, compatibility, style, scope)
    0 = none

  focus_clarity (1-5)
    1 = completely open-ended
    5 = precisely defined desired output or success criteria

  alignment_specified (0 or 1)
    1 = user states what "done" looks like
    0 = no success criteria defined

PSQ = (0.30 * verb) + (0.25 * context) + (0.20 * constraints) +
      (0.15 * focus) + (0.10 * alignment), normalized to 0-100.

### Dimension 2: Conversation Control Metrics (CCM) — weight 25%
  initiative_ratio (0-1): User-initiated direction changes / total turns
  verification_frequency (0-1): Times user verified output / times AI generated code
  course_correction_rate (0-1): User redirections after AI errors / total AI errors
  assumption_challenge_rate (0-1): User challenged AI assumptions / total AI assumptions

Score: 80-100 if user clearly leads, 40-70 mixed, 0-40 if AI leads.

### Dimension 3: Technical Sophistication Index (TSI) — weight 20%
  decomposition_depth (1-10): sub-problems identified before asking
  tool_technique_awareness: references to specific patterns, libraries, algorithms
  error_anticipation: proactive edge-case or failure-mode mentions
  solution_iteration: user-initiated refinement cycles

Adjustments: debugging +10% decomposition_depth; casual -10%.

### Dimension 4: Cognitive Load Management (CLM) — weight 15%
  chunk_size_appropriate (0-100): message length appropriate to request complexity
  incremental_building (0-1): iterative vs monolithic
  clarification_seeking (0-1): clarifying questions before acting
  mental_model_indicators: numbered steps, explicit assumptions, defined scope

### Dimension 5: Reliance Appropriateness Score (RAS) — weight 15%
  correct_reliance_rate (0-1)
  over_reliance_events
  under_reliance_events

## Overall Score
PEI = 0.25*PSQ + 0.25*CCM + 0.20*TSI + 0.15*CLM + 0.15*RAS

## Classification
- Novice: PEI < 40
- Intermediate: 40 <= PEI <= 70
- Advanced: PEI > 70

## leading_status
- "user-led" if PEI >= 70 OR initiative_ratio >= 0.6
- "mixed" if 40 <= PEI < 70
- "ai-led" otherwise

Output ONLY the structured JSON. Do not include any commentary.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=ScorerOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=1024, store=True),
)


# ---------------------------------------------------------------------------
# Stage 2b — Feedback Writer (prose, warmer, sees scores)
# ---------------------------------------------------------------------------

class FeedbackOutput(BaseModel):
    suggestions: list[str]
    red_flags: list[str]
    strengths: list[str]
    turn_summary: str


feedback_writer = Agent(
    name="Feedback Writer",
    instructions="""You write feedback for a student practicing AI prompting on HuskyAI.

You receive:
  1. The student's conversation with an AI assistant
  2. The conversation domain (coding, debugging, etc.)
  3. PEI scores already produced by another judge (do NOT re-score)

Your job: produce actionable, encouraging feedback grounded in those scores.

## Your Process
STEP 1: Read the conversation and the upstream scorer output carefully.
STEP 2: Optionally use file search to pull exemplars at the tier ABOVE the
        student's classification (e.g. if Novice, look up Intermediate
        exemplars) for concrete contrast in suggestions.
STEP 3: Write the four feedback fields:

  suggestions (3 to 5 items)
    Specific, actionable improvements tied to the WEAKEST dimensions in
    the scorer output. Each suggestion must reference one concrete thing
    to try in the next prompt.
    Good: "Add a constraint to your next message: state your Python version
           and whether external libraries are allowed."
    Bad:  "Be more specific."

  red_flags
    Things that clearly went wrong. Empty list if none.

  strengths (1 to 3 items)
    What the student did well. Empty list if none.

  turn_summary
    One short paragraph capturing what happened this turn and the single
    most important next step.

## Style Rules
- Address the student directly ("you"); warm but honest.
- Reference the dimension by name when fixing it
  (e.g., "Your PSQ is dragged down by missing constraints...").
- Suggestions must be actionable in the student's NEXT message.
- Do NOT quote raw numeric scores; describe the qualitative gap.
- Trust the upstream scores. Do NOT contradict them.
- Output ONLY the structured JSON.
""",
    model="gpt-4.1",
    tools=[file_search],
    output_type=FeedbackOutput,
    model_settings=ModelSettings(temperature=0.5, top_p=0.9, max_tokens=1024, store=True),
)


# ---------------------------------------------------------------------------
# Helpers (shape-compatible with v1 evaluator.py)
# ---------------------------------------------------------------------------

def _format_conversation(history: list) -> str:
    lines = []
    for i, msg in enumerate(history):
        role = "USER" if msg["role"] == "user" else "ASSISTANT (AI)"
        lines.append(f"[Turn {(i // 2) + 1}] {role}:\n{msg['content']}")
    return "\n\n".join(lines)


def _is_transient_eval_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        t in msg
        for t in (
            "rate", "429", "timeout", "timed out", "connection",
            "temporarily", "overloaded", "capacity",
            "503", "502", "524", "unavailable",
        )
    )


def _sanitize_eval_dict(out: dict) -> dict:
    scores = dict(out.get("scores") or {})
    for k in ("PSQ", "CCM", "TSI", "CLM", "RAS", "PEI"):
        if k in scores and scores[k] is not None:
            try:
                scores[k] = max(0.0, min(100.0, float(scores[k])))
            except (TypeError, ValueError):
                scores[k] = 0.0
    out["scores"] = scores
    for key in ("suggestions", "red_flags", "strengths"):
        v = out.get(key)
        if not isinstance(v, list):
            out[key] = []
        else:
            out[key] = [str(x) for x in v if x is not None]
    if not out.get("classification"):
        out["classification"] = "Novice"
    if not out.get("leading_status"):
        out["leading_status"] = "Led-by"
    if not out.get("turn_summary"):
        out["turn_summary"] = ""
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def _evaluate_conversation_v2_once(conversation_history: list, input_text: str) -> dict:
    conversation: list[TResponseInputItem] = [
        {"role": "user", "content": [{"type": "input_text", "text": input_text}]}
    ]

    # Stage 1: Domain detection
    s1 = await Runner.run(
        domain_detector,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v2"),
    )
    try:
        domain_text = s1.final_output_as(str)
    except Exception:
        domain_text = str(s1.final_output) if s1.final_output is not None else ""
    log.info(f"[EVAL2-S1 domain] {domain_text[:120]!r}")

    conversation.extend([item.to_input_item() for item in s1.new_items])

    # Stage 2a: Deterministic scoring
    s2a = await Runner.run(
        scorer,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v2"),
    )
    score_result: ScorerOutput = s2a.final_output
    log.info(f"[EVAL2-S2a scorer] PEI={score_result.scores.PEI:.1f}")

    # Thread scorer output forward + a plain-text summary for the feedback writer
    score_summary = (
        "<scorer_output>\n"
        f"  scores: {score_result.scores.model_dump()}\n"
        f"  breakdown: {score_result.breakdown.model_dump()}\n"
        f"  classification: {score_result.classification}\n"
        f"  leading_status: {score_result.leading_status}\n"
        "</scorer_output>"
    )
    conversation.extend([item.to_input_item() for item in s2a.new_items])
    conversation.append({
        "role": "user",
        "content": [{"type": "input_text", "text": score_summary}],
    })

    # Stage 2b: Feedback generation
    s2b = await Runner.run(
        feedback_writer,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v2"),
    )
    feedback_result: FeedbackOutput = s2b.final_output
    log.info(
        f"[EVAL2-S2b feedback] {len(feedback_result.suggestions)} suggestions, "
        f"{len(feedback_result.red_flags)} red flags, {len(feedback_result.strengths)} strengths"
    )

    out = {
        "scores": score_result.scores.model_dump(),
        "breakdown": score_result.breakdown.model_dump(),
        "classification": score_result.classification,
        "leading_status": score_result.leading_status,
        "suggestions": feedback_result.suggestions,
        "red_flags": feedback_result.red_flags,
        "strengths": feedback_result.strengths,
        "turn_summary": feedback_result.turn_summary,
        "domain_raw": domain_text,
    }
    return out


async def evaluate_conversation_v2(conversation_history: list) -> dict:
    """
    Approach 2: domain detection + split scorer + feedback writer.
    Drop-in compatible with evaluator.evaluate_conversation() for benchmarking.
    """
    t0 = time.monotonic()
    user_turns = sum(1 for m in conversation_history if m["role"] == "user")
    total_turns = len(conversation_history)
    conv_text = _format_conversation(conversation_history)

    log.info(f"[EVAL2] Starting three-stage eval ({user_turns} user turns, {total_turns} total)")

    input_text = (
        f"Conversation stats: {user_turns} user turns, {total_turns} total.\n\n"
        f"<conversation>\n{conv_text}\n</conversation>\n\n"
        "Focus on the LATEST user message most heavily. "
        "Be calibrated: a single vague message should score Novice."
    )

    last_err: BaseException | None = None
    for attempt in range(3):
        try:
            out = await _evaluate_conversation_v2_once(conversation_history, input_text)
            elapsed = time.monotonic() - t0
            pei = out.get("scores", {}).get("PEI", 0)
            log.info(f"[EVAL2] Done in {elapsed:.2f}s, PEI={pei:.1f}")
            return _sanitize_eval_dict(out)
        except Exception as e:
            last_err = e
            transient = _is_transient_eval_error(e)
            log.warning(
                "[EVAL2] attempt %s/%s failed: %s: %s (transient=%s)",
                attempt + 1, 3, type(e).__name__, e, transient,
            )
            if attempt < 2 and transient:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if attempt < 2:
                await asyncio.sleep(0.3)
                continue
            break

    elapsed = time.monotonic() - t0
    if last_err is not None:
        log.error(
            f"[EVAL2] Failed after {elapsed:.2f}s: {type(last_err).__name__}: {last_err}",
            exc_info=True,
        )
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
