"""
Post-session analysis for HuskyAI.

When a student completes a practice session, the per-turn PEI evaluations
(produced by evaluator_v3) are rolled up into a single session-level analysis:

  * Deterministic part (pure Python): session PEI, level band, per-dimension
    averages, strongest / weakest dimension, and a first-half vs second-half
    trend. These reuse the already-computed, authoritative per-turn scores --
    the LLM never re-scores.
  * LLM part (gpt-4.1): a short narrative, 3 synthesized takeaways, and 1-2
    strengths, written over the FULL transcript + per-turn breakdowns + the
    challenge objective. This is the "full LLM analysis" the student reads.

Public API: analyze_session(transcript, per_turn, challenge) -> dict
The returned dict is stored verbatim on UserChallengeSession.session_analysis.

Runs are stored in the OpenAI dashboard under workflow_name="HuskyAI-SessionAnalysis".
"""

import asyncio
import logging
import time
from datetime import datetime

from pydantic import BaseModel
from agents import Agent, ModelSettings, Runner, RunConfig, TResponseInputItem

log = logging.getLogger("session-analysis")

_MODEL = "gpt-4.1"
_MAX_ATTEMPTS = 3


def _is_transient_error(exc: BaseException) -> bool:
    """Transient = worth retrying (rate limit, timeout, upstream blip). Mirrors
    evaluator_v3._is_transient_eval_error so both stages back off the same way."""
    msg = str(exc).lower()
    return any(
        t in msg
        for t in (
            "rate", "429", "timeout", "timed out", "connection",
            "temporarily", "overloaded", "capacity",
            "503", "502", "524", "unavailable",
        )
    )

# PEI dimension weights + level bands MUST match evaluator_v3._aggregate so the
# session headline is consistent with the per-turn scores students already saw.
_DIMENSIONS = ("PSQ", "CCM", "TSI", "CLM", "RAS")
_WEIGHTS = {"PSQ": 0.25, "CCM": 0.25, "TSI": 0.20, "CLM": 0.15, "RAS": 0.15}
_DIMENSION_NAMES = {
    "PSQ": "Prompt Structural Quality",
    "CCM": "Conversation Control",
    "TSI": "Technical Sophistication",
    "CLM": "Cognitive Load Management",
    "RAS": "Reliance Appropriateness",
}


def _level(pei: float) -> str:
    if pei < 40:
        return "Novice"
    if pei <= 70:
        return "Intermediate"
    return "Advanced"


def _avg(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def aggregate_session(per_turn: list[dict]) -> dict:
    """Deterministic rollup of per-turn scores. No LLM. Safe on empty input."""
    scored = [t for t in per_turn if t.get("pei") is not None]
    n = len(scored)

    dimension_averages: dict[str, float | None] = {}
    for dim in _DIMENSIONS:
        dimension_averages[dim] = _avg([t.get("scores", {}).get(dim) for t in scored])

    session_pei = _avg([t["pei"] for t in scored])
    # Per-turn PEI trajectory, for the trend sparkline in the UI.
    pei_series = [round(float(t["pei"]), 1) for t in scored]

    # Strongest / weakest by dimension average (ignore dimensions with no data).
    ranked = [(d, v) for d, v in dimension_averages.items() if v is not None]
    strongest = max(ranked, key=lambda kv: kv[1])[0] if ranked else None
    weakest = min(ranked, key=lambda kv: kv[1])[0] if ranked else None

    # First-half vs second-half PEI trend (needs >= 2 scored turns to be meaningful).
    trend = None
    if n >= 2:
        mid = n // 2
        first = _avg([t["pei"] for t in scored[:mid]]) if mid else _avg([scored[0]["pei"]])
        second = _avg([t["pei"] for t in scored[mid:]])
        if first is not None and second is not None:
            delta = round(second - first, 1)
            if delta >= 5:
                direction = "improving"
            elif delta <= -5:
                direction = "declining"
            else:
                direction = "steady"
            trend = {
                "first_half_pei": first,
                "second_half_pei": second,
                "delta": delta,
                "direction": direction,
            }

    return {
        "session_pei": session_pei,
        "level": _level(session_pei) if session_pei is not None else None,
        "dimension_averages": dimension_averages,
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
        "trend": trend,
        "pei_series": pei_series,
        "turns_analyzed": n,
    }


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

class SessionAnalysisOutput(BaseModel):
    narrative: str            # 2-3 sentence overview of the whole session
    takeaways: list[str]      # exactly 3, the recurring things to improve next session
    strengths: list[str]      # 1-2, what to keep doing


session_analyst = Agent(
    name="Session Analyst",
    instructions="""You write a post-session analysis for a student practicing AI
prompting on HuskyAI. The student just finished a full practice session (one or
more turns), and each turn was already scored on the PEI dimensions
(PSQ = Prompt Structural Quality, CCM = Conversation Control,
TSI = Technical Sophistication, CLM = Cognitive Load Management,
RAS = Reliance Appropriateness).

You receive:
  1. The challenge objective (what the student was practicing).
  2. A deterministic rollup: session PEI, level, per-dimension averages,
     strongest/weakest dimension, and a first-half vs second-half trend.
  3. A per-turn breakdown: each turn's score and one-line summary, PLUS the
     specific suggestions and red flags the per-turn evaluator already raised.
  4. The full conversation transcript.

Your job: synthesize the SESSION as a whole. Do NOT re-score and do NOT just
restate one turn -- look for patterns ACROSS turns.

Write these fields:
  narrative (2-3 sentences): how the session went overall. If the trend shows the
    student improved or declined across the session, say so explicitly.
  takeaways (exactly 3): CONSOLIDATE the per-turn suggestions and red flags above
    into the 3 most important recurring themes to fix NEXT session -- do not
    invent fresh advice and do not just copy one turn's suggestion verbatim.
    EACH takeaway MUST be grounded in a SPECIFIC moment from THIS conversation:
    reference what the student actually wrote, asked, or left out (e.g. a
    particular prompt or turn). A takeaway that could be pasted into any
    student's report is WRONG -- rewrite it to cite this conversation.
      BAD  (generic): "Explicitly state all technical parameters in your prompt."
      GOOD (specific): "In your opening prompt you asked for a scoring function
                        but never said how ties should break -- decide that up
                        front instead of leaving it to the AI."
  strengths (1-2): what the student did well and should keep doing -- also
    grounded in something specific they actually did this session.

Style:
- Address the student directly ("you"); warm but honest.
- Reference dimension names by their full words, not the acronyms.
- Do NOT quote numeric scores; describe the qualitative gap instead.
- Quote or paraphrase the student's own words where it makes a point land.
- Trust the provided scores, suggestions, and trend. Do NOT contradict them.
- Output ONLY the structured JSON.
""",
    model=_MODEL,
    output_type=SessionAnalysisOutput,
    model_settings=ModelSettings(temperature=0.4, top_p=0.9, max_tokens=900, store=True),
)


def _format_transcript(transcript: list[dict]) -> str:
    lines = []
    turn = 0
    for msg in transcript:
        if msg["role"] == "user":
            turn += 1
            lines.append(f"[Turn {turn}] STUDENT:\n{msg['content']}")
        else:
            lines.append(f"[Turn {turn}] AI:\n{msg['content']}")
    return "\n\n".join(lines)


def _format_per_turn(per_turn: list[dict]) -> str:
    blocks = []
    for t in per_turn:
        pei = t.get("pei")
        pei_s = f"{pei:.0f}" if pei is not None else "n/a"
        summary = (t.get("turn_summary") or "").strip().replace("\n", " ")
        head = f"Turn {t.get('turn')}: PEI={pei_s}, {t.get('classification') or '?'}"
        if summary:
            head += f" — {summary}"
        lines = [head]
        # Surface the concrete per-turn feedback so the analyst consolidates it
        # rather than inventing generic advice.
        for s in (t.get("suggestions") or []):
            lines.append(f"    · suggestion: {str(s).strip()}")
        for r in (t.get("red_flags") or []):
            lines.append(f"    · red flag: {str(r).strip()}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _build_input(transcript: list[dict], per_turn: list[dict], rollup: dict, challenge: dict | None) -> str:
    objective = ""
    if challenge:
        title = challenge.get("title") or ""
        obj = challenge.get("objective") or challenge.get("description") or ""
        objective = f"<challenge>\n  title: {title}\n  objective: {obj}\n</challenge>\n\n"

    dim_avgs = ", ".join(
        f"{d} ({_DIMENSION_NAMES[d]})={rollup['dimension_averages'].get(d)}"
        for d in _DIMENSIONS
    )
    trend = rollup.get("trend")
    trend_s = (
        f"{trend['direction']} (first half {trend['first_half_pei']} -> "
        f"second half {trend['second_half_pei']})"
        if trend else "not enough turns to assess"
    )

    return (
        f"{objective}"
        "<session_rollup>\n"
        f"  session_pei: {rollup.get('session_pei')}\n"
        f"  level: {rollup.get('level')}\n"
        f"  dimension_averages: {dim_avgs}\n"
        f"  strongest_dimension: {rollup.get('strongest_dimension')}\n"
        f"  weakest_dimension: {rollup.get('weakest_dimension')}\n"
        f"  trend: {trend_s}\n"
        f"  turns_analyzed: {rollup.get('turns_analyzed')}\n"
        "</session_rollup>\n\n"
        "<per_turn>\n"
        f"{_format_per_turn(per_turn)}\n"
        "</per_turn>\n\n"
        "<transcript>\n"
        f"{_format_transcript(transcript)}\n"
        "</transcript>"
    )


async def analyze_session(
    transcript: list[dict],
    per_turn: list[dict],
    challenge: dict | None = None,
) -> dict:
    """
    Produce the full post-session analysis dict (status="ready").

    transcript: ordered [{"role": "user"|"assistant", "content": str}, ...]
    per_turn:   ordered [{"turn": int, "pei": float|None, "scores": {PSQ..RAS},
                          "classification": str, "turn_summary": str}, ...]
    challenge:  optional {"title", "objective"/"description"}.
    """
    t0 = time.monotonic()
    rollup = aggregate_session(per_turn)

    analysis = {
        "status": "ready",
        **rollup,
        "narrative": "",
        "takeaways": [],
        "strengths": [],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model": _MODEL,
    }

    # No scored turns -> nothing meaningful to synthesize; return the (empty) rollup.
    if rollup["turns_analyzed"] == 0:
        analysis["narrative"] = "This session has no scored turns to analyze yet."
        return analysis

    input_text = _build_input(transcript, per_turn, rollup, challenge)
    conversation: list[TResponseInputItem] = [
        {"role": "user", "content": [{"type": "input_text", "text": input_text}]}
    ]

    # Retry the synthesis call on transient failures (rate limit / timeout /
    # upstream blip), with exponential backoff -- same policy as the per-turn
    # evaluator. The last error is re-raised so the caller marks the session
    # analysis "failed" rather than storing a half-built result.
    last_err: BaseException | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            result = await Runner.run(
                session_analyst,
                input=conversation,
                run_config=RunConfig(workflow_name="HuskyAI-SessionAnalysis"),
            )
            out: SessionAnalysisOutput = result.final_output
            analysis["narrative"] = out.narrative
            analysis["takeaways"] = out.takeaways[:3]
            analysis["strengths"] = out.strengths[:2]
            last_err = None
            break
        except Exception as e:
            last_err = e
            transient = _is_transient_error(e)
            log.warning(
                "[SESSION-ANALYSIS] attempt %s/%s failed: %s: %s (transient=%s)",
                attempt + 1, _MAX_ATTEMPTS, type(e).__name__, e, transient,
            )
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep((0.5 * (2 ** attempt)) if transient else 0.3)
    if last_err is not None:
        raise last_err

    log.info(
        "[SESSION-ANALYSIS] done in %.2fs: PEI=%s level=%s turns=%s",
        time.monotonic() - t0, rollup["session_pei"], rollup["level"], rollup["turns_analyzed"],
    )
    return analysis
