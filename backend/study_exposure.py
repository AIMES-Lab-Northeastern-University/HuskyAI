"""EXPOSED_Tk for Lucy's study: did the AI actually state a post-test task's
scripted error to the participant?

A participant who never asks about the relevant line may never see a
commission or calculation error, so detection is analysed among exposed
participants (Appendix A2). This module judges exposure from the transcript
with a model, in the same pattern as the PEI judges (OpenAI Agents SDK,
gpt-4.1-mini, structured output, temperature 0): it gets the task's scripted
wrong claim, word for word from Appendix A3, and answers yes or no with
brief reasoning. Paraphrase counts as well as exact wording.

It is a first-pass signal for the research team to spot-check, not coded
data: the export labels it exposed_source = "ai_judge_unvalidated". A failed
judgment is stored as NULL (status "failed"), never as "not exposed".

Runs in the background when a post-test task completes
(study_mode.advance_if_block_done); /admin/study/exposure/rejudge retries
every task that has no successful judgment yet.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import BaseModel
from sqlalchemy import select

from database import (
    AsyncSessionLocal,
    Message,
    StudyExposureJudgment,
    StudyParticipant,
    UserChallengeSession,
)

log = logging.getLogger("study_exposure")

EXPOSURE_CASES = ("explicit_claim", "in_review_or_total", "left_capped_in_review", "none")


class ExposureOutput(BaseModel):
    exposed: bool
    # One of EXPOSURE_CASES.
    exposure_case: str
    reasoning: str


exposure_judge = Agent(
    name="Exposure Judge",
    instructions="""You review a transcript of a participant working with an AI assistant on a short rule-checking task (checking a bill, invoice or timesheet against a policy).

In this task the AI was set up to make one specific mistake, described to you as THE SCRIPTED WRONG CLAIM. Your only job is to decide whether the AI actually stated that wrong claim to the participant at any point in the transcript.

Rules:
- Count it if the AI stated the claim in its own words or in the exact wording. Paraphrase counts.
- Count it if the AI stated it at any point, even if it later corrected itself after the participant challenged it.
- Count it when the AI's corrected document, review or total plainly contains the mistake, as described under WHAT COUNTS for this error type.
- Do not count it if only the participant said it, or if the AI only mentioned the line without stating the wrong claim.
- Judge only what the AI said. Do not judge whether the participant noticed, accepted or challenged it.
- Follow the error type's WHAT COUNTS rules exactly, and pick exposure_case from the cases they list.

Output exposed (true or false), exposure_case, and reasoning: one or two sentences that quote or point to the AI turn that decided it (or say that no AI turn did).""",
    model="gpt-4.1-mini",
    output_type=ExposureOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=400, store=True),
)

_WHAT_COUNTS = {
    "commission": """WHAT COUNTS (commission):
- exposed, exposure_case "explicit_claim": the AI says the {label} line should change in the way the claim describes (for example that the threshold rule applies to it), as its own view.
- exposed, exposure_case "in_review_or_total": the AI gives a corrected document, review or total that includes that change (for example its corrected total is {ai_total}).
- not exposed, exposure_case "none": the AI never says it and never includes it.""",
    "omission": """WHAT COUNTS (omission):
- exposed, exposure_case "explicit_claim": the AI explicitly says the {label} line is correctly capped, or is fine as written.
- exposed, exposure_case "left_capped_in_review": the AI gives a full review of the document, a corrected document or a final/corrected total that still leaves the {label} line capped at {as_written}, without flagging it as an error (for example its corrected total is {ai_total}).
- not exposed, exposure_case "none": neither happened (for example the AI only discussed other lines and never reviewed the whole document or gave a total).
Say in the reasoning which of the two exposed cases applied, if either.""",
    "calculation": """WHAT COUNTS (calculation):
- exposed, exposure_case "explicit_claim": the AI states the slipped working or the slipped amount for the {label} line ({slip}).
- exposed, exposure_case "in_review_or_total": the AI gives a corrected document, review or total that uses the slipped amount (for example its corrected total is {ai_total}).
- not exposed, exposure_case "none": the AI never states the slip, or only ever gives the correct amount for that line.""",
}

_JUDGE_INPUT = """ERROR TYPE: {error_type}

THE SCRIPTED WRONG CLAIM (from the study design, describing what the AI does):
{claim}

THE LINE IT CONCERNS: {label} (as written: {as_written}; correct: {correct})

{what_counts}

TRANSCRIPT:
{transcript}"""

_judge_version: str | None = None


def judge_version() -> str:
    """A fingerprint of the judge (model, instructions, sampling, output
    schema, per-type rules), so a change to any of them is visible in the
    export."""
    global _judge_version
    if _judge_version is None:
        ms = exposure_judge.model_settings
        parts = {"model": exposure_judge.model, "instructions": exposure_judge.instructions,
                 "temperature": ms.temperature, "top_p": ms.top_p, "max_tokens": ms.max_tokens,
                 "output": ExposureOutput.__name__, "rules": _WHAT_COUNTS, "input": _JUDGE_INPUT}
        digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()
        _judge_version = f"exp-{digest[:12]}"
    return _judge_version


def judge_input(letter: str, error_type: str, transcript: list[tuple[str, str]]) -> str:
    """The judge's input for one task: the claim, the line, the rules for the
    error type and the transcript as [Participant] / [AI] turns."""
    from study_challenges import ERROR_ROLE, LUCY_SETS, _amount, _money

    s = LUCY_SETS[letter]
    line = s["lines"][ERROR_ROLE[error_type]]
    what = _WHAT_COUNTS[error_type].format(
        label=line["label"], as_written=_amount(line["as_written"]),
        ai_total=_money(s["scripted"][error_type]["accepted_total"]),
        slip=f"${s['slip_value']}")
    text = "\n\n".join(f"[{'Participant' if role == 'user' else 'AI'}]\n{content}"
                       for role, content in transcript) or "(no messages)"
    return _JUDGE_INPUT.format(
        error_type=error_type, claim=s["scripted"][error_type]["claim"], label=line["label"],
        as_written=_amount(line["as_written"]), correct=_amount(line["correct"]),
        what_counts=what, transcript=text)


async def judge_transcript(letter: str, error_type: str,
                           transcript: list[tuple[str, str]]) -> dict:
    """One model call. Returns {exposed, exposure_case, reasoning}; raises on
    failure (the caller stores it as failed)."""
    result = await Runner.run(
        exposure_judge,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": judge_input(letter, error_type, transcript)}]}],
        run_config=RunConfig(workflow_name="HuskyAI-Study-Exposure"),
    )
    out = result.final_output
    case = out.exposure_case if out.exposure_case in EXPOSURE_CASES else "none"
    return {"exposed": bool(out.exposed), "exposure_case": case,
            "reasoning": out.reasoning.strip()}


async def _transcript(conversation_id: str | None) -> list[tuple[str, str]]:
    if not conversation_id:
        return []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Message.role, Message.content)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at))).all()
    return [(r, c) for r, c in rows if r in ("user", "assistant")]


async def judge_task(participant_id: str, challenge_id: str, force: bool = False) -> str:
    """Judge one post-test task and store the result. Returns "judged",
    "failed", "skipped" (already judged, or not a post-test task)."""
    import study_mode
    from study_challenges import set_letter_of

    async with AsyncSessionLocal() as db:
        participant = await db.get(StudyParticipant, participant_id)
        if participant is None or study_mode.phase_of(participant, challenge_id) != "posttest":
            return "skipped"
        task = study_mode.task_number_for(participant, challenge_id)
        error_type = study_mode.error_type_for(participant, challenge_id)
        letter = set_letter_of(challenge_id)
        existing = (await db.execute(select(StudyExposureJudgment).where(
            StudyExposureJudgment.participant_id == participant_id,
            StudyExposureJudgment.task == task))).scalar_one_or_none()
        if existing is not None and existing.status == "judged" and not force:
            return "skipped"
        ucs = (await db.execute(select(UserChallengeSession).where(
            UserChallengeSession.user_id == participant.user_id,
            UserChallengeSession.challenge_id == challenge_id,
            UserChallengeSession.session_number == study_mode.STUDY_SESSION_NUMBER,
        ))).scalar_one_or_none()
    if task is None or error_type is None or letter is None or ucs is None \
            or ucs.status != "completed":
        return "skipped"
    conversation_id = ucs.conversation_id
    try:
        verdict = await judge_transcript(letter, error_type, await _transcript(conversation_id))
        status = "judged"
    except Exception as e:
        log.error("exposure judge failed for participant %s task %s: %s: %s",
                  participant_id[:8], task, type(e).__name__, e)
        verdict = {"exposed": None, "exposure_case": None,
                   "reasoning": f"judge failed: {type(e).__name__}"}
        status = "failed"
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(StudyExposureJudgment).where(
            StudyExposureJudgment.participant_id == participant_id,
            StudyExposureJudgment.task == task))).scalar_one_or_none()
        if row is not None and row.status == "judged" and not force:
            return "skipped"     # a concurrent run finished first
        if row is None:
            row = StudyExposureJudgment(participant_id=participant_id, task=task)
            db.add(row)
        row.challenge_id = challenge_id
        row.error_type = error_type
        row.conversation_id = conversation_id
        row.status = status
        row.exposed = verdict["exposed"]
        row.exposure_case = verdict["exposure_case"]
        row.reasoning = verdict["reasoning"]
        row.judge_version = judge_version()
        from datetime import datetime
        row.judged_at = datetime.utcnow()
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            log.warning("could not store exposure judgment: %s", e)
            return "failed"
    return status


# The test suite never reaches the model on its own: a completion there would
# otherwise call OpenAI. Tests that exercise the judge stub judge_transcript
# and turn this on.
AUTO_JUDGE = os.getenv("HUSKY_TESTING") != "1"
_tasks: set[asyncio.Task] = set()


def schedule_judgment(participant_id: str, challenge_id: str) -> None:
    """Judge a just-completed post-test task in the background. Never raises:
    a failure here must not fail the completion."""
    if not AUTO_JUDGE:
        return
    try:
        task = asyncio.get_running_loop().create_task(judge_task(participant_id, challenge_id))
    except RuntimeError:
        log.warning("no event loop to judge exposure for %s", participant_id[:8])
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def rejudge_missing(concurrency: int = 4) -> dict:
    """Judge every completed post-test task that has no successful judgment
    (never judged, or failed). Returns counts by outcome."""
    import study_mode

    async with AsyncSessionLocal() as db:
        participants = (await db.execute(select(StudyParticipant))).scalars().all()
        done = set((await db.execute(
            select(StudyExposureJudgment.participant_id, StudyExposureJudgment.task)
            .where(StudyExposureJudgment.status == "judged"))).all())
        todo = []
        for p in participants:
            if not study_mode.is_lucy_participant(p):
                continue
            sessions = await study_mode._study_sessions(db, p)
            for cid in p.task_order.get("posttest") or ():
                s = sessions.get(cid)
                n = study_mode.task_number_for(p, cid)
                if s is not None and s.status == "completed" and (p.id, n) not in done:
                    todo.append((p.id, cid))
    sem = asyncio.Semaphore(concurrency)
    counts = {"judged": 0, "failed": 0, "skipped": 0}

    async def one(pid, cid):
        async with sem:
            counts[await judge_task(pid, cid)] += 1

    await asyncio.gather(*(one(pid, cid) for pid, cid in todo))
    return counts
