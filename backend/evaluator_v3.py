"""
Approach 3 PEI evaluator: per-dimension judges (panel of judges).

Stage 1 — Domain detector       (gpt-4.1-nano)
Stage 2 — Five parallel dimension judges, one per PEI dimension
          (gpt-4.1-mini each, FileSearch grounded on dimension rubrics):
            * PSQ judge
            * CCM judge
            * TSI judge
            * CLM judge
            * RAS judge
Stage 3 — Deterministic aggregator (pure Python, no LLM):
          computes PEI, classification, leading_status from dimension scores
Stage 4 — Feedback writer         (gpt-4.1, sees full breakdown)

Public API: evaluate_conversation_v3(history) -> dict matching EvaluatorSchema.
Drop-in compatible with v1 / v2 for benchmarking against cases.json.

All runs are stored in the OpenAI dashboard under workflow_name="HuskyAI-Eval-v3".
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

_eval_dir = Path(__file__).resolve().parent
load_dotenv(_eval_dir / ".env")
load_dotenv()

log = logging.getLogger("chat-evaluator-v3")

_VECTOR_STORE_ID = os.getenv(
    "OPENAI_VECTOR_STORE_ID",
    "vs_69c5b5732cfc8191a9fbecc9ee76b31f",
)
file_search = FileSearchTool(vector_store_ids=[_VECTOR_STORE_ID])


# ---------------------------------------------------------------------------
# Stage 1 — Domain Detector (same as v1 / v2)
# ---------------------------------------------------------------------------

domain_detector = Agent(
    name="Domain Detector",
    instructions="""You are a conversation domain classifier for an AI prompting evaluation system.

Read the student's conversation and classify it into exactly one domain.

## Domains
- coding         : writing new code, features, refactoring
- debugging      : fixing broken code, errors, stack traces
- data_analysis  : SQL, pandas, statistics, ML pipelines
- casual         : conceptual questions, learning, theory
- creative       : writing, strategy, design, brainstorming

## Rules
- If debugging + coding both present, choose debugging
- If data_analysis + coding both present, choose data_analysis
- Base decision primarily on the first user message
- Choose one domain only

## Output
domain (one of the 5), confidence (0.0-1.0), reasoning (one sentence).
""",
    model="gpt-4.1-nano",
    model_settings=ModelSettings(temperature=0.2, top_p=0.9, max_tokens=256, store=True),
)


# ---------------------------------------------------------------------------
# Stage 2 — Five dimension judges, each with a focused output schema
# ---------------------------------------------------------------------------

class PSQOutput(BaseModel):
    PSQ: float
    verb_specificity: float
    context_completeness: float
    constraint_defined: float
    focus_clarity: float
    notes: str


psq_judge = Agent(
    name="PSQ Judge",
    instructions="""You judge ONLY the Prompt Structural Quality (PSQ) dimension.

Score the USER's prompting on these sub-components for the LATEST user message:

  verb_specificity (1-5)
    1 = no clear verb ("help me", "fix this")
    3 = generic verb ("write", "explain")
    5 = precise action verb ("refactor", "debug", "implement")

  context_completeness (0-100)
    % of necessary context provided: language, environment, existing code,
    error messages, what was tried, relevant constraints.

  constraint_defined (0 or 1)
    1 = explicit limitations stated (performance, compatibility, style, scope)
    0 = none

  focus_clarity (1-5)
    1 = completely open-ended, 5 = precisely defined desired output

  alignment_specified (0 or 1)  (internal, not in output)
    1 = success criteria stated, 0 = none

PSQ = (0.30 * verb_specificity) + (0.25 * context_completeness) +
      (0.20 * constraint_defined * 100) + (0.15 * focus_clarity * 20) +
      (0.10 * alignment_specified * 100)
Normalize to 0-100.

Use file search to retrieve the PSQ section of the rubric and exemplars before scoring.
Same input must produce same output. Output ONLY the structured JSON.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=PSQOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class CCMOutput(BaseModel):
    CCM: float
    initiative_ratio: float
    verification_frequency: float
    notes: str


ccm_judge = Agent(
    name="CCM Judge",
    instructions="""You judge ONLY the Conversation Control Metrics (CCM) dimension.

Look across ALL turns in the conversation:

  initiative_ratio (0.0-1.0)
    User-initiated direction changes / total turns.

  verification_frequency (0.0-1.0)
    Times user verified AI output / times AI generated content.

  course_correction_rate (0.0-1.0)  (internal, factored into CCM)
    User redirections after AI errors / total AI errors.

  assumption_challenge_rate (0.0-1.0)  (internal, factored into CCM)
    Times user challenged AI assumptions / total AI assumptions.

Score CCM (0-100):
  - 80-100 if the user clearly LEADS the conversation
  - 40-70 if mixed
  - 0-40 if AI leads and user is passive

Use file search to retrieve the CCM rubric and exemplars before scoring.
Output ONLY the structured JSON.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=CCMOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class TSIOutput(BaseModel):
    TSI: float
    decomposition_depth: float
    notes: str


tsi_judge = Agent(
    name="TSI Judge",
    instructions="""You judge ONLY the Technical Sophistication Index (TSI) dimension.

Sub-components (assess across the conversation):
  decomposition_depth (1-10)
    Sub-problems explicitly identified before asking. Higher = better.
  tool_technique_awareness (factored in)
    References to specific patterns, libraries, algorithms.
  error_anticipation (factored in)
    Proactive edge-case or failure-mode mentions.
  solution_iteration (factored in)
    User-initiated refinement cycles.

Score TSI (0-100). Domain adjustments:
  - debugging: weight decomposition_depth +10%
  - casual:    weight decomposition_depth -10%

Use file search to retrieve the TSI rubric and exemplars.
Output ONLY the structured JSON.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=TSIOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class CLMOutput(BaseModel):
    CLM: float
    chunk_size_appropriate: float
    notes: str


clm_judge = Agent(
    name="CLM Judge",
    instructions="""You judge ONLY the Cognitive Load Management (CLM) dimension.

Sub-components:
  chunk_size_appropriate (0-100)
    Message length appropriate to request complexity. Very long monolithic
    messages or way-too-short messages reduce this.
  incremental_building (factored in)
    Iterative step-by-step vs monolithic requests.
  clarification_seeking (factored in)
    Clarifying questions before acting on ambiguity.
  mental_model_indicators (factored in)
    Numbered steps, explicit assumptions, defined scope.

Score CLM (0-100). Use file search to retrieve the CLM rubric and exemplars.
Output ONLY the structured JSON.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=CLMOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class RASOutput(BaseModel):
    RAS: float
    correct_reliance_rate: float
    notes: str


ras_judge = Agent(
    name="RAS Judge",
    instructions="""You judge ONLY the Reliance Appropriateness Score (RAS) dimension.

Sub-components:
  correct_reliance_rate (0.0-1.0)
    (correct self-reliance + correct AI-reliance) / total decisions
  over_reliance_events (factored in)
    Accepting incorrect AI output without questioning.
  under_reliance_events (factored in)
    Rejecting clearly correct AI output without reason.

Score RAS (0-100). For single-turn prompts with no reliance event yet,
default toward 50 (neutral) unless there is clear signal.

Use file search to retrieve the RAS rubric and exemplars.
Output ONLY the structured JSON.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=RASOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


# ---------------------------------------------------------------------------
# Stage 3 — Deterministic aggregator (pure Python, no LLM)
# ---------------------------------------------------------------------------

def _aggregate(
    psq: PSQOutput,
    ccm: CCMOutput,
    tsi: TSIOutput,
    clm: CLMOutput,
    ras: RASOutput,
) -> dict:
    pei = (
        0.25 * psq.PSQ
        + 0.25 * ccm.CCM
        + 0.20 * tsi.TSI
        + 0.15 * clm.CLM
        + 0.15 * ras.RAS
    )

    if pei < 40:
        classification = "Novice"
    elif pei <= 70:
        classification = "Intermediate"
    else:
        classification = "Advanced"

    if pei >= 70 or ccm.initiative_ratio >= 0.6:
        leading_status = "user-led"
    elif pei >= 40:
        leading_status = "mixed"
    else:
        leading_status = "ai-led"

    return {
        "scores": {
            "PSQ": psq.PSQ,
            "CCM": ccm.CCM,
            "TSI": tsi.TSI,
            "CLM": clm.CLM,
            "RAS": ras.RAS,
            "PEI": pei,
        },
        "breakdown": {
            "verb_specificity": psq.verb_specificity,
            "context_completeness": psq.context_completeness,
            "constraint_defined": psq.constraint_defined,
            "focus_clarity": psq.focus_clarity,
            "initiative_ratio": ccm.initiative_ratio,
            "verification_frequency": ccm.verification_frequency,
            "decomposition_depth": tsi.decomposition_depth,
            "chunk_size_appropriate": clm.chunk_size_appropriate,
            "correct_reliance_rate": ras.correct_reliance_rate,
        },
        "classification": classification,
        "leading_status": leading_status,
        "judge_notes": {
            "PSQ": psq.notes,
            "CCM": ccm.notes,
            "TSI": tsi.notes,
            "CLM": clm.notes,
            "RAS": ras.notes,
        },
    }


# ---------------------------------------------------------------------------
# Stage 4 — Feedback writer (sees the aggregated breakdown)
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
  2. The conversation domain
  3. Per-dimension scores AND short notes from five specialist judges
  4. The aggregated PEI score, classification, and leading_status

Your job: produce actionable, encouraging feedback. Do NOT re-score.

## Process
STEP 1: Read the conversation, the five judge outputs, and their notes.
STEP 2: Identify the 2 weakest dimensions by score. Anchor most suggestions there.
STEP 3: Optionally pull exemplars at the tier above the student's classification
        for contrast.
STEP 4: Write fields:
  suggestions (3 to 5): specific, actionable, tied to the weakest dimensions.
  red_flags: clear failures only (empty list if none).
  strengths (1 to 3): what the student did well.
  turn_summary: one short paragraph + single most important next step.

## Style
- Address the student directly ("you"); warm but honest.
- Reference dimension names when explaining (PSQ, CCM, TSI, CLM, RAS).
- Suggestions must be actionable in the NEXT prompt.
- Do NOT quote numeric scores; describe the qualitative gap.
- Trust upstream scores and notes. Do NOT contradict them.
- Output ONLY the structured JSON.
""",
    model="gpt-4.1",
    tools=[file_search],
    output_type=FeedbackOutput,
    model_settings=ModelSettings(temperature=0.5, top_p=0.9, max_tokens=1024, store=True),
)


# ---------------------------------------------------------------------------
# Helpers
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

async def _run_judge(agent: Agent, conversation: list, label: str):
    result = await Runner.run(
        agent,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v3"),
    )
    log.info(f"[EVAL3-{label}] done")
    return result.final_output


async def _evaluate_conversation_v3_once(conversation_history: list, input_text: str) -> dict:
    conversation: list[TResponseInputItem] = [
        {"role": "user", "content": [{"type": "input_text", "text": input_text}]}
    ]

    # Stage 1: Domain
    s1 = await Runner.run(
        domain_detector,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v3"),
    )
    try:
        domain_text = s1.final_output_as(str)
    except Exception:
        domain_text = str(s1.final_output) if s1.final_output is not None else ""
    log.info(f"[EVAL3-S1 domain] {domain_text[:120]!r}")

    conversation.extend([item.to_input_item() for item in s1.new_items])

    # Stage 2: Five parallel dimension judges
    psq_out, ccm_out, tsi_out, clm_out, ras_out = await asyncio.gather(
        _run_judge(psq_judge, conversation, "PSQ"),
        _run_judge(ccm_judge, conversation, "CCM"),
        _run_judge(tsi_judge, conversation, "TSI"),
        _run_judge(clm_judge, conversation, "CLM"),
        _run_judge(ras_judge, conversation, "RAS"),
    )

    # Stage 3: Deterministic aggregation
    aggregated = _aggregate(psq_out, ccm_out, tsi_out, clm_out, ras_out)
    log.info(
        f"[EVAL3-S3 aggregate] PEI={aggregated['scores']['PEI']:.1f} "
        f"({aggregated['classification']})"
    )

    # Stage 4: Feedback writer sees the aggregated breakdown
    aggregate_summary = (
        "<dimension_judge_outputs>\n"
        f"  scores: {aggregated['scores']}\n"
        f"  breakdown: {aggregated['breakdown']}\n"
        f"  classification: {aggregated['classification']}\n"
        f"  leading_status: {aggregated['leading_status']}\n"
        f"  judge_notes: {aggregated['judge_notes']}\n"
        "</dimension_judge_outputs>"
    )
    conversation.append({
        "role": "user",
        "content": [{"type": "input_text", "text": aggregate_summary}],
    })

    s4 = await Runner.run(
        feedback_writer,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v3"),
    )
    feedback_result: FeedbackOutput = s4.final_output
    log.info(
        f"[EVAL3-S4 feedback] {len(feedback_result.suggestions)} suggestions, "
        f"{len(feedback_result.red_flags)} red flags, {len(feedback_result.strengths)} strengths"
    )

    return {
        "scores": aggregated["scores"],
        "breakdown": aggregated["breakdown"],
        "classification": aggregated["classification"],
        "leading_status": aggregated["leading_status"],
        "suggestions": feedback_result.suggestions,
        "red_flags": feedback_result.red_flags,
        "strengths": feedback_result.strengths,
        "turn_summary": feedback_result.turn_summary,
        "domain_raw": domain_text,
        "judge_notes": aggregated["judge_notes"],
    }


async def evaluate_conversation_v3(conversation_history: list) -> dict:
    """
    Approach 3: domain + five parallel dimension judges + deterministic
    aggregation + feedback writer.
    """
    t0 = time.monotonic()
    user_turns = sum(1 for m in conversation_history if m["role"] == "user")
    total_turns = len(conversation_history)
    conv_text = _format_conversation(conversation_history)

    log.info(f"[EVAL3] Starting panel eval ({user_turns} user turns, {total_turns} total)")

    input_text = (
        f"Conversation stats: {user_turns} user turns, {total_turns} total.\n\n"
        f"<conversation>\n{conv_text}\n</conversation>\n\n"
        "Focus on the LATEST user message most heavily. "
        "Be calibrated: a single vague message should score Novice."
    )

    last_err: BaseException | None = None
    for attempt in range(3):
        try:
            out = await _evaluate_conversation_v3_once(conversation_history, input_text)
            elapsed = time.monotonic() - t0
            pei = out.get("scores", {}).get("PEI", 0)
            log.info(f"[EVAL3] Done in {elapsed:.2f}s, PEI={pei:.1f}")
            return _sanitize_eval_dict(out)
        except Exception as e:
            last_err = e
            transient = _is_transient_eval_error(e)
            log.warning(
                "[EVAL3] attempt %s/%s failed: %s: %s (transient=%s)",
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
            f"[EVAL3] Failed after {elapsed:.2f}s: {type(last_err).__name__}: {last_err}",
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
