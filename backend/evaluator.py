import json
import logging
import time
import google.generativeai as genai

log = logging.getLogger("chat-evaluator")

EVAL_SYSTEM_PROMPT = """You are an expert AI interaction quality evaluator specializing in coding conversations.
Your role is to analyze conversations between users and Gemini coding assistants, evaluating the USER\'s prompting technique based on the User Agency Continuum framework.

## Evaluation Framework

### Dimension 1: Prompt Structural Quality (PSQ)
- verb_specificity (1-5): Presence of clear action verbs (refactor, debug, implement, optimize)
- context_completeness (0-100): % of necessary context provided upfront (code snippets, environment, goal)
- constraint_defined (0-1): Whether limitations/requirements are explicitly stated
- focus_clarity (1-5): How well-defined the desired outcome is
- alignment_specified (0-1): Whether success criteria are defined

### Dimension 2: Conversation Control Metrics (CCM)
- initiative_ratio (0-1): User-initiated topic changes / total turns
- verification_frequency (0-1): Times user verified output / times model generated code
- course_correction_rate (0-1): User redirections after errors / total turns after errors
- assumption_challenge_rate (0-1): Challenged model assumptions / total assumptions made
- Score high (80-100) if user leads, medium (40-70) if mixed, low (<40) if led-by

### Dimension 3: Technical Sophistication Index (TSI)
- decomposition_depth (1-10): Sub-problems identified per request
- tool_technique_awareness: References to specific patterns, libraries, algorithms
- error_anticipation: Proactive mention of edge cases or potential issues
- solution_iteration: Refinement cycles initiated by user

### Dimension 4: Cognitive Load Management (CLM)
- chunk_size_appropriate (0-100): Appropriate message size
- incremental_building: Iterative vs monolithic requests ratio
- clarification_seeking: Questions asked before proceeding with unclear tasks
- mental_model_indicators: Use of structured thinking, step-by-step breakdowns

### Dimension 5: Reliance Appropriateness Score (RAS)
- correct_reliance_rate (0-1): Correct self-reliance + correct LLM-reliance / decisions
- over_reliance_events: Blindly accepting suggestions without questioning
- under_reliance_events: Rejecting clearly correct suggestions
- trust_calibration: Confidence expressions aligned with outcome quality

### Overall Score
PEI = 0.25*PSQ + 0.25*CCM + 0.20*TSI + 0.15*CLM + 0.15*RAS

### Classification
- Novice: PEI < 40 (predominantly led-by, low structure)
- Intermediate: PEI 40-70 (mixed control, improving structure)
- Advanced: PEI > 70 (leading, sophisticated prompting)

## CRITICAL INSTRUCTIONS
1. Evaluate only the USER\'s prompting behavior, not the model\'s response quality
2. Be precise and calibrated -- not every user is Advanced
3. Provide actionable, specific suggestions based on actual conversation content
4. Output ONLY valid JSON matching the exact schema -- no other text

## Required JSON Schema
{
  "scores": {
    "PSQ": <number 0-100>,
    "CCM": <number 0-100>,
    "TSI": <number 0-100>,
    "CLM": <number 0-100>,
    "RAS": <number 0-100>,
    "PEI": <number 0-100>
  },
  "breakdown": {
    "verb_specificity": <number 1-5>,
    "context_completeness": <number 0-100>,
    "constraint_defined": <number 0-1>,
    "focus_clarity": <number 1-5>,
    "initiative_ratio": <number 0-1>,
    "verification_frequency": <number 0-1>,
    "decomposition_depth": <number 1-10>,
    "chunk_size_appropriate": <number 0-100>,
    "correct_reliance_rate": <number 0-1>
  },
  "classification": "<Novice|Intermediate|Advanced>",
  "leading_status": "<Leading|Led-by>",
  "suggestions": ["<string>", ...],
  "red_flags": ["<string>", ...],
  "strengths": ["<string>", ...],
  "turn_summary": "<string>"
}"""

eval_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=EVAL_SYSTEM_PROMPT,
    generation_config=genai.GenerationConfig(
        response_mime_type="application/json",
    ),
)


async def evaluate_conversation(conversation_history: list) -> dict:
    """Evaluate the conversation quality using Gemini as the evaluator."""
    conv_text = ""
    for i, msg in enumerate(conversation_history):
        role = "USER" if msg["role"] == "user" else "ASSISTANT (AI)"
        conv_text += f"\n[Turn {(i // 2) + 1}] {role}:\n{msg['content']}\n"

    total_turns = len(conversation_history)
    user_turns = sum(1 for m in conversation_history if m["role"] == "user")

    eval_prompt = (
        f"Analyze this AI coding conversation ({user_turns} user turns, {total_turns} total).\n"
        "Evaluate the USER\'s prompting quality based on the framework provided.\n\n"
        f"<conversation>\n{conv_text}\n</conversation>\n\n"
        "Focus on the LATEST user message most heavily, but consider the full conversation arc "
        "for CCM and RAS scores.\n"
        "Be calibrated: a single vague question should score low (Novice), not high.\n"
        "Provide 3-5 specific, actionable suggestions based on what you actually observed.\n"
        "Return ONLY the JSON object."
    )

    log.info(f"[EVAL] Calling gemini-2.0-flash (JSON mode) for {user_turns}-turn conversation")
    t0 = time.monotonic()

    try:
        response = await eval_model.generate_content_async(eval_prompt)
        elapsed = time.monotonic() - t0

        usage = response.usage_metadata
        log.info(
            f"[EVAL] Response received in {elapsed:.2f}s -- "
            f"in={usage.prompt_token_count} tok, out={usage.candidates_token_count} tok"
        )

        raw_text = response.text.strip()
        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            result = json.loads(raw_text)
            log.debug(f"[EVAL] JSON parsed OK ({len(raw_text)} chars)")
            return result
        except json.JSONDecodeError as je:
            log.error(f"[EVAL] JSON parse failed: {je} -- raw: {raw_text[:300]!r}")
            return _default_eval()

    except Exception as e:
        elapsed = time.monotonic() - t0
        log.error(f"[EVAL] Error after {elapsed:.2f}s: {type(e).__name__}: {e}", exc_info=True)
        return _default_eval()


def _default_eval() -> dict:
    return {
        "scores": {"PSQ": 0, "CCM": 0, "TSI": 0, "CLM": 0, "RAS": 0, "PEI": 0},
        "breakdown": {
            "verb_specificity": 1, "context_completeness": 0,
            "constraint_defined": 0, "focus_clarity": 1,
            "initiative_ratio": 0, "verification_frequency": 0,
            "decomposition_depth": 1, "chunk_size_appropriate": 50,
            "correct_reliance_rate": 0.5
        },
        "classification": "Novice",
        "leading_status": "Led-by",
        "suggestions": ["Unable to evaluate at this time. Please try again."],
        "red_flags": [],
        "strengths": [],
        "turn_summary": "Evaluation unavailable."
    }
