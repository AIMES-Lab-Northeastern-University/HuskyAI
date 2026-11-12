"""Anonymous-participant study mode (the Wihbey/Butler HuskyAI study).

Participants sign in with a code instead of an email. Each has a condition
fixed at creation ("feedback" = HuskyAI | "no_feedback" = standard) and moves
through the blocks (pretest -> training -> posttest -> done). In Lucy's design
the pretest block is empty: tasks 1-3 are training, 4-6 post-test. PEI feedback
is visible only in the training block of the feedback condition; scoring
itself is never affected.

Everything here is inert unless STUDY_MODE_ENABLED is set: the only HTTP
surface (/auth/study-login) returns 404 without it, and nothing else imports
this module's state.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import random
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from database import (
    STUDY_BLOCKS,
    STUDY_CONDITIONS,
    AsyncSessionLocal,
    Challenge,
    EvalResult,
    Message,
    StudyEnrollment,
    StudyEvent,
    StudyParticipant,
    StudyParticipantStatus,
    StudyExposureJudgment,
    StudyTaskAnswer,
    User,
    UserChallengeSession,
)

log = logging.getLogger("study_mode")

# Blocks that hold tasks, in order. "done" is the terminal state, not a block.
TASK_BLOCKS = STUDY_BLOCKS[:-1]

# No 0/O, 1/I/L: codes are read aloud and typed from paper. 31 symbols x 12
# characters is ~59 bits, far past guessing at any rate the auth limiter allows.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 12
_CODE_GROUP = 4


def study_mode_enabled() -> bool:
    """Read per call, so the flag takes effect without a code change and tests
    can toggle it."""
    return os.getenv("STUDY_MODE_ENABLED", "").strip().lower() in ("1", "true", "yes")


def counterbalance_enabled() -> bool:
    """STUDY_COUNTERBALANCE: Latin-square task orders at creation. Off by
    default, so every new participant does the tasks in the fixed order."""
    return os.getenv("STUDY_COUNTERBALANCE", "").strip().lower() in ("1", "true", "yes")


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        log.error("%s is not an integer; using %d", name, default)
        return default
    return max(lo, min(hi, value))


def task_minutes() -> int:
    """STUDY_TASK_MINUTES: the per-task cap, snapshotted onto each study session
    when it starts (UserChallengeSession.time_limit_minutes)."""
    return _int_env("STUDY_TASK_MINUTES", 10, 1, 120)


def session_minutes() -> int:
    """STUDY_SESSION_MINUTES: how long a participant's study session lasts,
    counted from their first sign-in."""
    return _int_env("STUDY_SESSION_MINUTES", 60, 1, 24 * 60)


def answer_minutes() -> int:
    """STUDY_ANSWER_MINUTES: after the session window closes, how long a
    finished task whose end-of-task questions are still unanswered keeps the
    participant's access open, so the questions (which gate the completion
    code) can still be answered. Inside the window they are untimed."""
    return _int_env("STUDY_ANSWER_MINUTES", 10, 1, 120)


# A finish that reaches the server this close to the deadline counts as the
# timer's: the browser ends the task when its countdown hits zero, and that
# request must not be recorded as a manual finish.
END_GRACE_SECONDS = 2
# After the session window closes, a task that was already running may finish;
# requests stay allowed this long past its end, so the browser can still
# finish it and show its completion code.
EXPIRY_TAIL_SECONDS = 60


# --- Codes -------------------------------------------------------------------

def _new_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    return "-".join(raw[i:i + _CODE_GROUP] for i in range(0, _CODE_LENGTH, _CODE_GROUP))


def normalize_code(code: str) -> str:
    """Case, spaces and dashes are presentation, not part of the code."""
    return "".join(ch for ch in (code or "").upper() if ch not in " -\t\r\n")


def hash_code(code: str) -> str:
    """SHA-256 hex of the normalised code. A fast hash is enough for the same
    reason as PasswordResetToken: the code is high-entropy random, so there is
    nothing to brute-force, and it must be indexable for lookup."""
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


# --- Tasks -------------------------------------------------------------------

def block_tasks() -> dict[str, list[str]]:
    """Task ids per block. Stubbed: empty unless STUDY_BLOCK_TASKS holds a JSON
    object like {"pretest": ["id", ...], "training": [...], "posttest": [...]}."""
    tasks: dict[str, list[str]] = {b: [] for b in TASK_BLOCKS}
    raw = os.getenv("STUDY_BLOCK_TASKS", "").strip()
    if not raw:
        return tasks
    cfg = json.loads(raw)
    if not isinstance(cfg, dict) or set(cfg) - set(TASK_BLOCKS):
        raise ValueError(f"STUDY_BLOCK_TASKS keys must be among {TASK_BLOCKS}")
    for block, ids in cfg.items():
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError(f"STUDY_BLOCK_TASKS[{block!r}] must be a list of task ids")
        tasks[block] = list(ids)
    return tasks


# Ids reserved for study-only challenges (study_challenges.py). Instructor-made
# and seeded challenges get uuid4 ids, which can never start with this.
STUDY_CHALLENGE_PREFIX = "study-"


def not_participant(user_id_column):
    """A WHERE clause that leaves study participants out, for every place the
    normal site counts, lists, ranks or exports data across users. Study data
    is reached only through the study's own admin endpoints.

    Applied whether or not the flag is on, so the data stays out after a study
    ends. With no participants the subquery is empty and the result is exactly
    what it was before."""
    return user_id_column.not_in(select(StudyParticipant.user_id))


async def is_participant_user(user_id: str | None) -> bool:
    """Whether this account is a study participant, flag or no flag: for the
    places that must keep study accounts and their data out of the normal site
    (admin drill-downs, joining a classroom)."""
    if not user_id:
        return False
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(StudyParticipant.id).where(
            StudyParticipant.user_id == user_id))).scalar_one_or_none() is not None


def is_study_challenge(challenge_id: str | None) -> bool:
    """A study-only challenge, hidden from everyone but the participants whose
    block holds it. A string check, no flag and no query, so the challenges
    stay hidden even if the flag is turned off after they were seeded."""
    return isinstance(challenge_id, str) and challenge_id.startswith(STUDY_CHALLENGE_PREFIX)


# Latin-square orders of the three tasks across pretest, training, posttest.
# Tasks are named by their slot in STUDY_BLOCK_TASKS: A is the pretest task,
# B the training task, C the posttest task.
#   1: A, B, C    2: B, C, A    3: C, A, B
LATIN_SQUARE_ORDERS = (1, 2, 3)


def latin_square_tasks(tasks: dict[str, list[str]], order: int | None) -> dict[str, list[str]] | None:
    """The blocks' tasks rotated into Latin-square `order`, or None when the
    config is not one distinct task per block (then the per-block shuffle
    applies as before)."""
    ids = [tasks.get(b) or [] for b in TASK_BLOCKS]
    if order not in LATIN_SQUARE_ORDERS or any(len(i) != 1 for i in ids) \
            or len({i[0] for i in ids}) != len(ids):
        return None
    k = order - 1
    return {b: [ids[(n + k) % len(ids)][0]] for n, b in enumerate(TASK_BLOCKS)}


def task_order(seed: int, block: str, task_ids: list[str]) -> list[str]:
    """The participant's order for one block. Deterministic for (seed, block).

    The block is mixed into the seed so two blocks of the same length are not
    shuffled into the same permutation. A str seed is hashed by SHA-512 inside
    random.Random, so the result does not depend on PYTHONHASHSEED."""
    if block not in TASK_BLOCKS:
        raise ValueError(f"unknown block {block!r}")
    order = list(task_ids)
    random.Random(f"{seed}:{block}").shuffle(order)
    return order


# --- Participants ------------------------------------------------------------

def _balanced_conditions(n: int, conditions: tuple[str, ...]) -> list[str]:
    """Every consecutive group of len(conditions) codes holds each condition
    once, shuffled within the group; a short last group is a random subset.
    Shuffled with the OS RNG so the assignment is not predictable from code order."""
    rng = secrets.SystemRandom()
    out: list[str] = []
    while len(out) < n:
        group = list(conditions)
        rng.shuffle(group)
        out.extend(group)
    return out[:n]


def _balanced_orders(assigned: list[str]) -> list[int]:
    """A Latin-square order for each assigned condition, balanced within each
    condition: every consecutive three participants of one condition hold each
    order once, shuffled, so per-condition counts differ by at most one."""
    rng = secrets.SystemRandom()
    pools: dict[str, list[int]] = {}
    out: list[int] = []
    for condition in assigned:
        pool = pools.setdefault(condition, [])
        if not pool:
            pool.extend(LATIN_SQUARE_ORDERS)
            rng.shuffle(pool)
        out.append(pool.pop())
    return out


# --- Lucy's design: six tasks, assigned round-robin (study_challenges.LUCY_SETS) ---
# The design that runs unless STUDY_BLOCK_TASKS names another config. Each
# participant gets one of 36 cells: condition x set order (her Williams square)
# x error order. Cells are taken in enrollment order, so any 36 consecutive
# enrollments fill every cell once. Tasks 1-3 are the training block, 4-6 the
# post-test block; the pretest block is empty.

LUCY_DESIGN = "lucy6"
CELL_COUNT = 36
CONDITION_LABELS = {"feedback": "huskyai", "no_feedback": "standard"}


def lucy_design_active() -> bool:
    """Lucy's design is the study unless STUDY_BLOCK_TASKS configures the older
    block layout (kept for the retired data challenges)."""
    return not os.getenv("STUDY_BLOCK_TASKS", "").strip()


def cell_assignment(seq: int) -> dict:
    """Enrollment number -> the participant's cell and everything it fixes:
    cell = seq mod 36, condition = cell mod 2, set order = (cell // 2) mod 6 + 1,
    error order = cell // 12 + 1."""
    from study_challenges import LUCY_ERROR_ORDERS, LUCY_SET_ORDERS, set_challenge_id

    cell = seq % CELL_COUNT
    set_order, error_order = (cell // 2) % 6 + 1, cell // 12 + 1
    sets = LUCY_SET_ORDERS[set_order]
    ids = [set_challenge_id(letter) for letter in sets]
    errors = LUCY_ERROR_ORDERS[error_order]
    return {
        "condition": STUDY_CONDITIONS[cell % 2],
        "task_order": {
            "design": LUCY_DESIGN, "enroll_seq": seq, "cell": cell,
            "set_order": set_order, "error_order": error_order, "sets": list(sets),
            "pretest": [], "training": ids[:3], "posttest": ids[3:],
            # Post-test tasks only: training tasks never carry an error.
            "errors": dict(zip(ids[3:], errors)),
        },
    }


async def _next_enroll_seq(db) -> int:
    """max + 1. Two enrollments that read the same max collide on the unique
    enroll_seq at commit, and the loser retries with a fresh read."""
    top = (await db.execute(select(func.max(StudyParticipant.enroll_seq)))).scalar()
    return 0 if top is None else top + 1


def is_lucy_participant(participant: StudyParticipant | None) -> bool:
    return participant is not None \
        and (participant.task_order or {}).get("design") == LUCY_DESIGN


def assignment_of(participant: StudyParticipant) -> dict:
    """What Qualtrics and the exports get: the condition label, set order,
    error order, cell and the set letter at each task. Empty for a participant
    outside Lucy's design."""
    t = participant.task_order or {}
    if t.get("design") != LUCY_DESIGN:
        return {}
    out = {"condition": CONDITION_LABELS[participant.condition], "set_order": t["set_order"],
           "error_order": t["error_order"], "cell": t["cell"], "enroll_seq": t["enroll_seq"]}
    out.update({f"set_{n}": letter for n, letter in enumerate(t["sets"], start=1)})
    return out


def error_type_for(participant: StudyParticipant, challenge_id: str | None) -> str | None:
    """The scripted error this participant's task carries: one of the three
    types on a post-test task, None on a training task (or outside the design)."""
    return ((participant.task_order or {}).get("errors") or {}).get(challenge_id)


def phase_of(participant: StudyParticipant, challenge_id: str | None) -> str | None:
    """"training" or "posttest" for a task of Lucy's design, else None."""
    if not is_lucy_participant(participant) or not challenge_id:
        return None
    t = participant.task_order
    if challenge_id in (t.get("training") or ()):
        return "training"
    if challenge_id in (t.get("posttest") or ()):
        return "posttest"
    return None


def study_system_prompt(participant: StudyParticipant, challenge_id: str | None,
                        session_data: dict | None) -> str | None:
    """The system prompt for a task of Lucy's design, or None to keep
    main._build_system_prompt's (any other challenge):
      training, HuskyAI condition    -> the study tutor prompt
      training, standard condition   -> the plain prompt
      post-test, both conditions     -> the plain prompt + the scripted error"""
    from study_challenges import (
        PLAIN_TASK_PROMPT_TEMPLATE, TUTOR_TASK_PROMPT_TEMPLATE, scripted_error_script,
        set_letter_of,
    )

    phase = phase_of(participant, challenge_id)
    if phase is None or not session_data:
        return None
    fields = dict(title=session_data.get("title", ""), goal=session_data.get("goal", ""),
                  brief=session_data.get("brief", ""))
    if phase == "training" and participant.condition == "feedback":
        return TUTOR_TASK_PROMPT_TEMPLATE.format(**fields)
    plain = PLAIN_TASK_PROMPT_TEMPLATE.format(**fields)
    if phase == "training":
        return plain
    error_type = error_type_for(participant, challenge_id)
    letter = set_letter_of(challenge_id)
    if error_type is None or letter is None:
        # A post-test task without its error would silently drop the
        # manipulation: say so, and run it plain rather than tutored.
        log.error("participant %s: post-test task %s has no scripted error",
                  participant.id[:8], challenge_id)
        return plain
    return f"{plain}\n\n{scripted_error_script(letter, error_type)}"


def task_time_limit(participant: StudyParticipant) -> int | None:
    """The per-task cap snapshotted onto a participant's session: none in
    Lucy's design (Qualtrics records time on task; nothing is enforced),
    STUDY_TASK_MINUTES otherwise."""
    return None if is_lucy_participant(participant) else task_minutes()


async def mint_codes(n: int, conditions: tuple[str, ...] = STUDY_CONDITIONS) -> list[dict]:
    """Create n participants and return their plaintext codes.

    This is the only time a code exists in plaintext: only its hash is stored,
    so a lost code cannot be recovered, only replaced. Each participant gets a
    User row with a placeholder email and the bcrypt hash of a random secret
    that is immediately discarded, so the normal email login can never succeed
    for it. All n rows are written in one transaction.

    In Lucy's design the cells (condition included) come from the enrollment
    sequence, exactly as for a Qualtrics enrollment, so `conditions` cannot
    narrow them.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    conditions = tuple(conditions)
    if not conditions or len(set(conditions)) != len(conditions) \
            or set(conditions) - set(STUDY_CONDITIONS):
        raise ValueError(f"conditions must be distinct values among {STUDY_CONDITIONS}")
    if lucy_design_active():
        if set(conditions) != set(STUDY_CONDITIONS):
            raise ValueError("conditions are assigned round-robin by the study design")
        minted = await _mint_in_sequence(n)
    else:
        minted = await _mint_legacy(n, conditions)
    log.info("minted %d study participants", n)
    return minted


def _fresh_code(seen_hashes: set[str]) -> str:
    code = _new_code()
    while hash_code(code) in seen_hashes:
        code = _new_code()
    seen_hashes.add(hash_code(code))
    return code


# A burst of enrollments that read the same max enroll_seq collide on its
# unique constraint; each loser retries with a fresh read.
ENROLL_ATTEMPTS = 20


async def _mint_in_sequence(n: int) -> list[dict]:
    """n participants on the next n enrollment numbers, in one transaction."""
    for _attempt in range(ENROLL_ATTEMPTS):
        seen: set[str] = set()
        minted: list[dict] = []
        async with AsyncSessionLocal() as db:
            seq = await _next_enroll_seq(db)
            try:
                # A collision can surface at any flush, not only the commit.
                for i in range(n):
                    a = cell_assignment(seq + i)
                    minted.append(await _add_participant(
                        db, _fresh_code(seen), a["condition"], a["task_order"],
                        enroll_seq=seq + i))
                await db.commit()
                return minted
            except IntegrityError:
                await db.rollback()
        await asyncio.sleep(secrets.randbelow(50) / 1000)
    raise RuntimeError("could not reserve enrollment numbers; try again")


async def _mint_legacy(n: int, conditions: tuple[str, ...]) -> list[dict]:
    """The older block layout (STUDY_BLOCK_TASKS): balanced random conditions
    and, with STUDY_COUNTERBALANCE, Latin-square task orders."""
    tasks = block_tasks()
    assigned = _balanced_conditions(n, conditions)
    orders = _orders_for(assigned)
    minted: list[dict] = []
    seen: set[str] = set()
    async with AsyncSessionLocal() as db:
        for condition, order in zip(assigned, orders):
            minted.append(await _add_participant(
                db, _fresh_code(seen), condition, legacy_task_order(tasks, order)))
        await db.commit()
    return minted


def _orders_for(assigned: list[str]) -> list[int]:
    """Latin-square orders for the assigned conditions when counterbalancing is
    on; otherwise every participant gets order 1, the fixed task order
    1 -> 2 -> 3 (pretest, training, posttest as configured)."""
    if counterbalance_enabled():
        return _balanced_orders(assigned)
    return [1] * len(assigned)


def legacy_task_order(tasks: dict[str, list[str]], order: int) -> dict:
    """The older layout's task_order: one task per block gets the Latin-square
    rotation, anything else the per-block shuffle. The order number is kept
    either way, so a config filled in after minting still rotates
    (block_task_ids). The seed rides along so _add_participant stores it."""
    seed = secrets.randbits(31)
    blocks = latin_square_tasks(tasks, order) \
        or {b: task_order(seed, b, tasks[b]) for b in TASK_BLOCKS}
    return {**blocks, "order": order, "_seed": seed}


async def _add_participant(db, code: str, condition: str, layout: dict,
                           enroll_seq: int | None = None) -> dict:
    """Add one participant (and its User row) to the caller's transaction.
    The one creation path, shared by admin minting and Qualtrics enrollment.
    `layout` is the task_order to store (cell_assignment or legacy_task_order)."""
    from auth import pwd_context  # auth imports this module

    participant_id = str(uuid4())
    # bcrypt is deliberately slow; keep it off the event loop.
    unusable = await asyncio.to_thread(pwd_context.hash, secrets.token_urlsafe(32))
    user = User(
        email=f"p-{participant_id}@study.invalid",
        name="Participant",
        password_hash=unusable,
    )
    db.add(user)
    await db.flush()

    layout = dict(layout)
    seed = layout.pop("_seed", None)
    if seed is None:
        seed = secrets.randbits(31)
    # The first block that holds tasks: Lucy's design starts in training.
    start = next((b for b in TASK_BLOCKS if layout.get(b)), "pretest")
    participant = StudyParticipant(
        id=participant_id,
        user_id=user.id,
        code_hash=hash_code(code),
        condition=condition,
        current_block=start,
        seed=seed,
        enroll_seq=enroll_seq,
        task_order=layout,
    )
    db.add(participant)
    # assignment_of's "condition" is the label Qualtrics gets; the stored
    # value wins here.
    return {
        **assignment_of(participant),
        "code": code,
        "participant_id": participant_id,
        "user_id": user.id,
        "condition": condition,
        "order": layout.get("order"),
    }


async def participant_for(user_id: str) -> StudyParticipant | None:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(StudyParticipant).where(StudyParticipant.user_id == user_id)
        )).scalar_one_or_none()


async def participant_by_code(code: str) -> StudyParticipant | None:
    if not normalize_code(code):
        return None
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(StudyParticipant).where(StudyParticipant.code_hash == hash_code(code))
        )).scalar_one_or_none()


def feedback_visible(participant: StudyParticipant | None, block: str) -> bool:
    """Whether PEI feedback may be shown. Says nothing about scoring, which
    always runs; only the display is gated."""
    return (participant is not None
            and participant.condition == "feedback"
            and block == "training")


async def advance_block(participant: StudyParticipant) -> str:
    """Move to the next block and return it.

    A conditional UPDATE on the block the caller saw, so two concurrent
    advances (two tabs, two workers) move the participant one block, not two;
    the loser gets a ValueError instead of a silent double step."""
    current = participant.current_block
    if current not in TASK_BLOCKS:
        raise ValueError(f"participant is already {current!r}")
    nxt = STUDY_BLOCKS[STUDY_BLOCKS.index(current) + 1]
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(StudyParticipant)
            .where(StudyParticipant.id == participant.id,
                   StudyParticipant.current_block == current)
            .values(current_block=nxt)
        )
        await db.commit()
    if res.rowcount != 1:
        raise ValueError("participant's block changed concurrently; reload and retry")
    participant.current_block = nxt
    return nxt


# --- Participants in the running app ---------------------------------------------
# Everything below is what the app's existing handlers call. Each entry point
# returns "not a participant" without touching the database when the flag is
# off, so a normal deploy runs exactly the code it ran before.

# A study task is session 1 of its challenge; later sessions are not played.
STUDY_SESSION_NUMBER = 1
SNAPSHOT_ACTION = "study.block_started"


async def active_participant(user_id: str | None) -> StudyParticipant | None:
    """The caller's participant row, or None. No query at all when the flag is
    off, and only ever a lookup by the current user's id."""
    if not user_id or not study_mode_enabled():
        return None
    return await participant_for(user_id)


def block_task_ids(participant: StudyParticipant) -> list[str]:
    """The participant's tasks for their current block, in their order.

    The order stored at minting wins. A block that was minted empty (the task
    config was still a stub) falls back to the config, shuffled with the same
    seed, so filling the config in later still gives each participant a fixed,
    reproducible order (their Latin-square rotation, when it has that shape)."""
    return _block_ids(participant, participant.current_block)


def _block_ids(participant: StudyParticipant, block: str) -> list[str]:
    """block_task_ids for any block, not only the current one."""
    if block not in TASK_BLOCKS:
        return []
    stored = (participant.task_order or {}).get(block) or []
    if stored:
        return list(stored)
    tasks = block_tasks()
    square = latin_square_tasks(tasks, (participant.task_order or {}).get("order"))
    if square:
        return square[block]
    return task_order(participant.seed, block, tasks[block])


async def _completed_task_ids(db, participant: StudyParticipant, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return set((await db.execute(
        select(UserChallengeSession.challenge_id).where(
            UserChallengeSession.user_id == participant.user_id,
            UserChallengeSession.session_number == STUDY_SESSION_NUMBER,
            UserChallengeSession.status == "completed",
            UserChallengeSession.challenge_id.in_(ids),
        )
    )).scalars().all())


async def current_task_id(db, participant: StudyParticipant) -> str | None:
    """The one task the participant may play now: the first in their order
    that is not completed. Study order replaces "finish the previous session"."""
    ids = block_task_ids(participant)
    done = await _completed_task_ids(db, participant, ids)
    return next((t for t in ids if t not in done), None)


async def may_play(db, participant: StudyParticipant, challenge_id: str,
                   session_number: int | None) -> bool:
    return (session_number == STUDY_SESSION_NUMBER
            and challenge_id == await current_task_id(db, participant))


def _snapshot_key(ucs_id: str) -> str:
    return f"study-block:{ucs_id}"


def condition_fields(participant: StudyParticipant, block: str | None) -> dict:
    """Added to the existing study condition, so every event a participant's
    session writes names its arm without a join."""
    return {"study_condition": participant.condition, "study_block": block}


async def snapshot_block(participant: StudyParticipant, session_record) -> bool:
    """Record the participant's block on the session, once. True when the
    snapshot is in the log (written now or by an earlier start).

    A fixed idempotency key makes the FIRST start win, enforced by the unique
    index rather than a read-then-write, so a later start, a second worker or
    an advance mid-session cannot replace it. Visibility for the whole session
    is read from this row, never from the participant's live block."""
    from events import record_event

    block = participant.current_block
    result = await record_event(
        action=SNAPSHOT_ACTION, target="feed", actor_kind="system",
        user_challenge_session_id=session_record.id, actor_user_id=participant.user_id,
        challenge_id=session_record.challenge_id,
        payload={"block": block, "feedback_visible": feedback_visible(participant, block)},
        idempotency_key=_snapshot_key(session_record.id),
        condition=condition_fields(participant, block),
    )
    await _record_consent_once(participant, session_record)
    return result.recorded


async def _record_consent_once(participant: StudyParticipant, session_record) -> None:
    """study.consent_recorded, for a participant enrolled through Qualtrics.

    Consent is set at enrollment (StudyEnrollment.consent_recorded_at), but
    every event lives in a session scope and a participant has none until a
    task starts, so the event is written on the first session, once (a fixed
    idempotency key), carrying the enrollment time. Best effort: the consent
    itself is already on the User row and the enrollment."""
    from events import record_event

    async with AsyncSessionLocal() as db:
        enrollment = (await db.execute(
            select(StudyEnrollment).where(StudyEnrollment.participant_id == participant.id)
        )).scalar_one_or_none()
    if enrollment is None:
        return
    await record_event(
        action="study.consent_recorded", target="feed", actor_kind="system",
        user_challenge_session_id=session_record.id, actor_user_id=participant.user_id,
        challenge_id=session_record.challenge_id,
        payload={"source": "qualtrics",
                 "consent_recorded_at": enrollment.consent_recorded_at.isoformat()},
        idempotency_key=f"study-consent:{participant.id}",
        condition=condition_fields(participant, participant.current_block),
    )


async def session_block(ucs_id: str | None) -> str | None:
    """The block snapshotted when this session started, or None."""
    if not ucs_id:
        return None
    async with AsyncSessionLocal() as db:
        ev = (await db.execute(
            select(StudyEvent).where(StudyEvent.idempotency_key == _snapshot_key(ucs_id))
        )).scalar_one_or_none()
    block = (ev.payload or {}).get("block") if ev else None
    return block if block in STUDY_BLOCKS else None


@dataclass(frozen=True)
class StudyGate:
    participant: StudyParticipant
    block: str | None
    visible: bool

    def condition_fields(self) -> dict:
        return condition_fields(self.participant, self.block)


async def solo_gate(user_id: str, challenge_id: str | None,
                    session_num: int | None) -> StudyGate | None:
    """None for anyone who is not a participant (and always when the flag is
    off). For a participant: the session's snapshotted block and whether it
    shows feedback. Fails closed: no session or no snapshot means hidden."""
    participant = await active_participant(user_id)
    if participant is None:
        return None
    ucs_id = None
    if challenge_id and session_num:
        async with AsyncSessionLocal() as db:
            ucs_id = (await db.execute(
                select(UserChallengeSession.id).where(
                    UserChallengeSession.user_id == user_id,
                    UserChallengeSession.challenge_id == challenge_id,
                    UserChallengeSession.session_number == session_num,
                )
            )).scalar_one_or_none()
    block = await session_block(ucs_id)
    return StudyGate(participant, block,
                     block is not None and feedback_visible(participant, block))


async def feedback_hidden_for(user_id: str, ucs_id: str | None) -> bool:
    """For endpoints that hold a session: True only for a participant whose
    session snapshot hides feedback (or who has no snapshot for it)."""
    participant = await active_participant(user_id)
    if participant is None:
        return False
    block = await session_block(ucs_id)
    return not (block is not None and feedback_visible(participant, block))


async def feedback_hidden_now(user_id: str) -> bool:
    """For endpoints that name no session (/prompt/stronger): judged by the
    participant's in-progress study session, so it agrees with what that
    session's socket shows even if the block has since advanced."""
    participant = await active_participant(user_id)
    if participant is None:
        return False
    async with AsyncSessionLocal() as db:
        ucs_id = (await db.execute(
            select(UserChallengeSession.id).where(
                UserChallengeSession.user_id == user_id,
                UserChallengeSession.status == "in_progress",
            ).order_by(UserChallengeSession.started_at.desc()).limit(1)
        )).scalar_one_or_none()
    return await feedback_hidden_for(user_id, ucs_id)


async def advance_if_block_done(user_id: str, challenge_id: str | None) -> str | None:
    """After a session is marked completed: if it finished the last open task
    of the participant's CURRENT block, move them to the next block. Returns
    the new block, or None when nothing moved.

    Only ever called on a completion, so a participant never changes block
    mid-session. Safe to repeat and to race:
    - a task outside the current block (a repeated complete after the advance,
      or a stale tab) moves nothing;
    - the last of two concurrent completions to commit sees every task done,
      and advance_block's conditional UPDATE lets at most one caller move the
      participant off a given block, so no block is ever skipped.
    Never raises: a study bookkeeping failure must not fail the completion
    the student just made, which is already committed."""
    try:
        participant = await active_participant(user_id)
        if participant is None or not challenge_id:
            return None
        # Every completion of a post-test task queues its exposure judge
        # (study_exposure.py), in the background; repeats are no-ops there.
        if phase_of(participant, challenge_id) == "posttest":
            from study_exposure import schedule_judgment
            schedule_judgment(participant.id, challenge_id)
        ids = block_task_ids(participant)
        if challenge_id not in ids:
            return None
        async with AsyncSessionLocal() as db:
            done = await _completed_task_ids(db, participant, ids)
        if set(ids) - done:
            return None
        try:
            new_block = await advance_block(participant)
        except ValueError:
            return None     # another completion already moved them on
        log.info("participant %s advanced to %s", participant.id[:8], new_block)
        return new_block
    except Exception as e:
        log.error("could not check block advancement for %s: %s", user_id[:8], e)
        return None


def strip_scores(item: dict) -> dict:
    """A challenge listing or detail payload, for a participant: no best_pei."""
    item.pop("best_pei", None)
    for s in item.get("sessions") or ():
        s.pop("best_pei", None)
    return item


# --- GET /study/tasks -------------------------------------------------------------

study_router = APIRouter(prefix="/study", tags=["study"])


async def _require_flag() -> None:
    if not study_mode_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


async def _current_user_id(authorization: Optional[str] = Header(None)) -> str:
    from auth import resolve_token_user_id  # auth imports this module

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    user_id = await resolve_token_user_id(authorization.removeprefix("Bearer ").strip())
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


async def _current_participant(user_id: str = Depends(_current_user_id)) -> StudyParticipant:
    participant = await active_participant(user_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return participant


@study_router.get("/tasks", include_in_schema=False, dependencies=[Depends(_require_flag)])
async def study_tasks(participant: StudyParticipant = Depends(_current_participant)):
    """The current block's tasks in this participant's order. Deliberately
    nothing about condition or scores: a participant must not be able to learn
    their arm from the API."""
    ids = block_task_ids(participant)
    async with AsyncSessionLocal() as db:
        done = await _completed_task_ids(db, participant, ids)
        titles, started = {}, set()
        if ids:
            titles = dict((await db.execute(
                select(Challenge.id, Challenge.title).where(Challenge.id.in_(ids))
            )).all())
            started = set((await db.execute(
                select(UserChallengeSession.challenge_id).where(
                    UserChallengeSession.user_id == participant.user_id,
                    UserChallengeSession.session_number == STUDY_SESSION_NUMBER,
                    UserChallengeSession.status == "in_progress",
                    UserChallengeSession.challenge_id.in_(ids),
                )
            )).scalars().all())
    current = next((t for t in ids if t not in done), None)
    return {
        "current_block": participant.current_block,
        "progress": {"completed": len(done), "total": len(ids)},
        "tasks": [
            {"challenge_id": t, "title": titles.get(t), "session_number": STUDY_SESSION_NUMBER,
             "completed": t in done, "started": t in started, "current": t == current}
            for t in ids
        ],
    }


@study_router.get("/me", include_in_schema=False, dependencies=[Depends(_require_flag)])
async def study_me(user_id: str = Depends(_current_user_id)):
    """Just enough for the frontend to route: whether this account is a
    participant and which block it is in. Never the condition."""
    participant = await active_participant(user_id)
    return {
        "is_participant": participant is not None,
        "current_block": participant.current_block if participant else None,
    }


# =============================================================================
# Qualtrics integration
# =============================================================================
# The survey (Qualtrics) owns consent and the questionnaires; HuskyAI is
# embedded on each task page at /study?code=...&task=N. In Lucy's design there
# are six tasks: 1-3 the training block, 4-6 the post-test block, and HuskyAI
# assigns the condition. In the older layout task N is block N (1 pretest,
# 2 training, 3 posttest) and the survey sends the condition.

STUDY_ENDED_DETAIL = "This study session has ended."
# The most tasks any layout has: request validation and the export's columns.
MAX_TASKS = 6

# Qualtrics' randomizer values -> the study's conditions.
QUALTRICS_CONDITIONS = {"feedback": "feedback", "control": "no_feedback"}

# Qualtrics ResponseIDs look like R_1a2B3c4D5e6F7g8; anything in this charset
# and length range is accepted so a format change on their side cannot break
# enrollment, and nothing else is.
RESPONSE_ID_PATTERN = r"^[A-Za-z0-9_-]{6,64}$"

_COMPLETION_LENGTH = 8
_MIN_SECRET_LENGTH = 32


def _utcnow() -> datetime:
    return datetime.utcnow()


# --- Keys ------------------------------------------------------------------------

def _strong_secret(value: str) -> bool:
    """At least 32 characters and not a repeated handful (e.g. 'aaaa...')."""
    return len(value) >= _MIN_SECRET_LENGTH and len(set(value)) >= 10


def _server_key() -> bytes | None:
    """STUDY_SECRET_KEY: the root of the completion-code HMAC and of the key
    that encrypts enrollment codes. None when unset or weak."""
    raw = os.getenv("STUDY_SECRET_KEY", "").strip()
    return raw.encode("utf-8") if _strong_secret(raw) else None


def _qualtrics_secret() -> bytes | None:
    raw = os.getenv("QUALTRICS_SHARED_SECRET", "").strip()
    return raw.encode("utf-8") if _strong_secret(raw) else None


class StudyConfigError(RuntimeError):
    """A required study secret is missing or weak."""


def _subkey(label: str) -> bytes:
    """Separate keys per use, derived from STUDY_SECRET_KEY, so the completion
    HMAC and the code encryption never share key material."""
    root = _server_key()
    if root is None:
        raise StudyConfigError("STUDY_SECRET_KEY is unset or weak")
    return hmac.new(root, f"huskyai-study:{label}".encode(), hashlib.sha256).digest()


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(_subkey("enrollment-code")))


def _encrypt_code(code: str) -> str:
    return _fernet().encrypt(code.encode("utf-8")).decode("ascii")


def _decrypt_code(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def completion_code(participant_id: str, task: int) -> str:
    """The code a participant pastes into the survey after task N.

    HMAC-SHA256 of (participant, task) under a server key, written in the
    sign-in alphabet (no 0/O, 1/I/L): deterministic, so a reload shows the same
    code; unique per participant and task; and not computable without the key.
    8 symbols of 31 is ~40 bits, against a verify endpoint that needs the
    Qualtrics secret and is rate limited."""
    digest = hmac.new(_subkey("completion"), f"{participant_id}:{task}".encode(),
                      hashlib.sha256).digest()
    n = int.from_bytes(digest, "big")
    out = []
    for _ in range(_COMPLETION_LENGTH):
        n, r = divmod(n, len(_CODE_ALPHABET))
        out.append(_CODE_ALPHABET[r])
    return "".join(out)


def _require_server_key() -> None:
    if _server_key() is None:
        log.error("study request refused: STUDY_SECRET_KEY is unset or weak")
        raise HTTPException(status_code=503, detail="The study is not available right now.")


def link_base(code: str) -> str:
    """The participant's link without the task: Qualtrics appends &task=N."""
    base = os.getenv("STUDY_LINK_BASE_URL", "").strip().rstrip("/") or "http://localhost:5173"
    return f"{base}/study?code={code}"


_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


def embed_origins() -> list[str]:
    """STUDY_EMBED_ORIGINS: comma-separated origins allowed to receive the
    completion postMessage when HuskyAI is embedded. Anything that is not a
    plain scheme://host[:port] (including "*") is dropped."""
    out = []
    for item in os.getenv("STUDY_EMBED_ORIGINS", "").split(","):
        item = item.strip().rstrip("/")
        if item and _ORIGIN_RE.match(item):
            out.append(item)
        elif item:
            log.warning("STUDY_EMBED_ORIGINS: ignoring %r (not an origin)", item)
    return out


# --- Tasks by number -------------------------------------------------------------

def participant_task_ids(participant: StudyParticipant) -> list[str | None]:
    """The participant's tasks by number (index 0 is task 1). Lucy's design:
    the three training tasks, then the three post-test tasks. The older
    layout: block N's task, or None where block N does not hold exactly one."""
    if is_lucy_participant(participant):
        t = participant.task_order
        return list(t.get("training") or []) + list(t.get("posttest") or [])
    out: list[str | None] = []
    for block in TASK_BLOCKS:
        ids = _block_ids(participant, block)
        out.append(ids[0] if len(ids) == 1 else None)
    return out


def task_count(participant: StudyParticipant) -> int:
    return len(participant_task_ids(participant))


def task_challenge_id(participant: StudyParticipant, task: int) -> str | None:
    """The challenge that is task N for this participant, or None."""
    ids = participant_task_ids(participant)
    return ids[task - 1] if 1 <= task <= len(ids) else None


def task_number_for(participant: StudyParticipant, challenge_id: str | None) -> int | None:
    if not challenge_id:
        return None
    ids = participant_task_ids(participant)
    return ids.index(challenge_id) + 1 if challenge_id in ids else None


def current_task_number(participant: StudyParticipant,
                        sessions: dict[str, UserChallengeSession]) -> int | None:
    """The task the participant may do now; None once every block is done.
    In Lucy's design: the first task, in order, that is not finished (blocks
    hold three tasks each). In the older layout: block N is task N."""
    block = participant.current_block
    if block not in TASK_BLOCKS:
        return None
    if not is_lucy_participant(participant):
        return TASK_BLOCKS.index(block) + 1
    for n, cid in enumerate(participant_task_ids(participant), start=1):
        s = sessions.get(cid)
        if s is None or s.status != "completed":
            return n
    return None


async def _study_sessions(db, participant: StudyParticipant) -> dict[str, UserChallengeSession]:
    """The participant's study sessions (session 1 of each of their tasks), by challenge."""
    ids = [cid for cid in participant_task_ids(participant) if cid]
    if not ids:
        return {}
    rows = (await db.execute(
        select(UserChallengeSession).where(
            UserChallengeSession.user_id == participant.user_id,
            UserChallengeSession.session_number == STUDY_SESSION_NUMBER,
            UserChallengeSession.challenge_id.in_(ids),
        )
    )).scalars().all()
    return {r.challenge_id: r for r in rows}


# --- End-of-task questions (study_challenges.END_QUESTIONS) ----------------------
# Two pages, in order, each locked once submitted. Page 1 under the finished
# task: the total and the corrections. Page 2, with the task and chat gone:
# confidence, and on a post-test task trust and checking. The completion code
# comes only after page 2.

def inapp_questions_enabled() -> bool:
    """STUDY_INAPP_QUESTIONS (default on): HuskyAI asks the end-of-task
    questions itself and holds back the completion code until they are
    answered. Off when the survey asks them instead (answer, corrections,
    confidence/trust in Qualtrics): every task's code is released as soon as
    the task ends, and nothing is stored in study_task_answers."""
    return os.getenv("STUDY_INAPP_QUESTIONS", "1").strip().lower() not in ("0", "false", "no", "off")


def end_questions(challenge_id: str | None) -> dict | None:
    """Page 1 as the page renders it, or None for a task without questions
    (its completion code is not gated). Never the answer key."""
    from study_challenges import END_QUESTIONS, set_letter_of
    if set_letter_of(challenge_id) is None or not inapp_questions_enabled():
        return None
    return {"total": END_QUESTIONS["total"], "corrections": END_QUESTIONS["corrections"]}


def ratings_questions(participant: StudyParticipant, challenge_id: str | None) -> dict | None:
    """Page 2: confidence, plus trust and checking on a post-test task."""
    from study_challenges import END_QUESTIONS, POSTTEST_RATINGS
    if end_questions(challenge_id) is None:
        return None
    out = {"confidence": END_QUESTIONS["confidence"],
           "confidence_low": END_QUESTIONS["confidence_low"],
           "confidence_high": END_QUESTIONS["confidence_high"]}
    if phase_of(participant, challenge_id) == "posttest":
        out["agreement"] = dict(POSTTEST_RATINGS)
    return out


def _answers_done(row: StudyTaskAnswer | None) -> bool:
    return row is not None and row.confidence is not None


def answers_stage(row: StudyTaskAnswer | None) -> str:
    """Where a finished task's questions stand: "answers" (page 1 owed),
    "ratings" (page 2 owed) or "done"."""
    if row is None:
        return "answers"
    return "done" if _answers_done(row) else "ratings"


def answers_required_payload(participant: StudyParticipant, task: int, challenge_id: str,
                             row: StudyTaskAnswer | None) -> dict:
    """What the page needs to show the next owed page of questions."""
    stage = answers_stage(row)
    out = {"task": task, "challenge_id": challenge_id, "answers_required": True,
           "stage": stage, "questions": end_questions(challenge_id)}
    if stage == "ratings":
        out["ratings"] = ratings_questions(participant, challenge_id)
    return out


async def _answer_row(db, participant: StudyParticipant, task: int) -> StudyTaskAnswer | None:
    return (await db.execute(select(StudyTaskAnswer).where(
        StudyTaskAnswer.participant_id == participant.id, StudyTaskAnswer.task == task,
    ))).scalar_one_or_none()


async def _awaiting_answers(db, participant: StudyParticipant,
                            sessions: dict[str, UserChallengeSession]) -> frozenset[str]:
    """Challenge ids of finished tasks whose end-of-task questions (either
    page) are still unanswered."""
    finished = [cid for cid, s in sessions.items()
                if s.status == "completed" and end_questions(cid) is not None]
    if not finished:
        return frozenset()
    done = set((await db.execute(select(StudyTaskAnswer.challenge_id).where(
        StudyTaskAnswer.participant_id == participant.id,
        StudyTaskAnswer.challenge_id.in_(finished),
        StudyTaskAnswer.confidence.is_not(None),
    ))).scalars().all())
    return frozenset(set(finished) - done)


async def answers_owed(participant: StudyParticipant, task: int, challenge_id: str) -> bool:
    """Whether task N's completion code is still held back for its questions."""
    if end_questions(challenge_id) is None:
        return False
    async with AsyncSessionLocal() as db:
        return not _answers_done(await _answer_row(db, participant, task))


# A dollar amount: digits with an optional "$" and thousands commas, and at
# most two decimals ("378", "$1,040.00", "2650.8").
_TOTAL_RE = re.compile(r"^\$?\s*(\d{1,3}(?:,\d{3})+|\d{1,9})(\.\d{1,2})?$")


def normalize_total(raw) -> str | None:
    """The dollar answer as a canonical 2-decimal string ("$1,040.5" ->
    "1040.50"), or None when it is not an amount with at most 2 decimals."""
    text = str(raw).strip() if isinstance(raw, (str, int, float)) and not isinstance(raw, bool) \
        else ""
    m = _TOTAL_RE.match(text)
    if not m:
        return None
    from decimal import Decimal
    return f"{Decimal(m.group(1).replace(',', '') + (m.group(2) or '')):.2f}"


def session_deadline(ucs) -> datetime | None:
    if ucs is None or not ucs.started_at or not ucs.time_limit_minutes:
        return None
    return ucs.started_at + timedelta(minutes=ucs.time_limit_minutes)


def remaining_seconds(deadline: datetime | None) -> int | None:
    """Seconds to the deadline, rounded UP. Rounding down (int()) made the
    browser's countdown hit zero up to a second before the server's deadline,
    so its automatic finish arrived early and was recorded as manual."""
    if deadline is None:
        return None
    return max(0, math.ceil((deadline - _utcnow()).total_seconds()))


# --- Timer: auto-finish ----------------------------------------------------------
# The server owns the deadline. A session past it is finished with end reason
# timer_expired by whichever comes first: the socket's watchdog (main.py), the
# next message or connect, or any study request that reads the participant's
# state (here), so a closed tab cannot leave a task open forever.

_finalizer = None


def register_finalizer(fn) -> None:
    """main._finalize_session: finishes a conversation's session the same way
    the timer always has (average PEI, analysis, block advance)."""
    global _finalizer
    _finalizer = fn


async def finalize_overdue(participant: StudyParticipant) -> int:
    """Finish every in-progress study session of this participant that is past
    its deadline. Returns how many were finished. Safe to repeat and to race
    with the socket's own finalize: both only ever complete a session once."""
    now = _utcnow()
    async with AsyncSessionLocal() as db:
        overdue = [s for s in (await _study_sessions(db, participant)).values()
                   if s.status == "in_progress" and (d := session_deadline(s)) and now >= d]
    for ucs in overdue:
        deadline = session_deadline(ucs)
        if ucs.conversation_id and _finalizer is not None:
            await _finalizer(ucs.conversation_id)
        else:
            # Started but never connected: no conversation to close or score.
            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    update(UserChallengeSession)
                    .where(UserChallengeSession.id == ucs.id,
                           UserChallengeSession.status != "completed")
                    .values(status="completed", completed_at=deadline,
                            end_reason="timer_expired")
                )
                await db.commit()
            if res.rowcount == 1:
                await advance_if_block_done(participant.user_id, ucs.challenge_id)
        # Noticed late (a closed tab): record when it really ended.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(UserChallengeSession)
                .where(UserChallengeSession.id == ucs.id,
                       UserChallengeSession.end_reason == "timer_expired",
                       UserChallengeSession.completed_at > deadline)
                .values(completed_at=deadline)
            )
            await db.commit()
    return len(overdue)


async def _heal_block(participant: StudyParticipant) -> StudyParticipant:
    """If the current block's task is done but the advance after it failed
    (advance_if_block_done never raises), move on now. Returns a fresh row."""
    ids = block_task_ids(participant)
    if ids:
        async with AsyncSessionLocal() as db:
            done = await _completed_task_ids(db, participant, ids)
        if not set(ids) - done:
            await advance_if_block_done(participant.user_id, ids[-1])
    return await participant_for(participant.user_id) or participant


# --- Session window (first sign-in + STUDY_SESSION_MINUTES) ----------------------

async def _open_window(participant_id: str) -> None:
    """Start the window at the first sign-in. Idempotent and race-safe: the
    first writer wins and later ones leave first_login_at alone."""
    now = _utcnow()
    async with AsyncSessionLocal() as db:
        st = await db.get(StudyParticipantStatus, participant_id)
        if st is None:
            db.add(StudyParticipantStatus(participant_id=participant_id, first_login_at=now))
        elif st.first_login_at is None:
            await db.execute(
                update(StudyParticipantStatus)
                .where(StudyParticipantStatus.participant_id == participant_id,
                       StudyParticipantStatus.first_login_at.is_(None))
                .values(first_login_at=now))
        else:
            return
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()     # a concurrent first sign-in got there first


def window_end(status: StudyParticipantStatus | None) -> datetime | None:
    if status is None or status.first_login_at is None:
        return None
    return status.first_login_at + timedelta(minutes=session_minutes())


def _tail_open(sessions, end: datetime, now: datetime,
               awaiting_answers: frozenset[str] = frozenset()) -> bool:
    """After the window: a task started inside it may run to its own deadline
    (plus the tail, so its finish and completion code still get through).

    A finished task whose end-of-task questions are unanswered (challenge ids
    in `awaiting_answers`) gets the longer answer tail instead, even if it
    finished before the window closed: its completion code is only shown once
    they are answered, so the plain tail would strand the participant."""
    for s in sessions:
        if not s.started_at or s.started_at >= end:
            continue
        awaiting = s.challenge_id in awaiting_answers
        stop = session_deadline(s) or (s.started_at + timedelta(minutes=task_minutes()))
        if s.status == "completed" and s.completed_at and s.completed_at < stop:
            stop = s.completed_at
        if awaiting:
            stop = max(stop, end)
        elif s.status == "completed" and stop < end:
            continue
        tail = timedelta(minutes=answer_minutes()) if awaiting \
            else timedelta(seconds=EXPIRY_TAIL_SECONDS)
        if now < stop + tail:
            return True
    return False


async def participant_access(participant: StudyParticipant) -> str | None:
    """None when the participant may make a request now; otherwise why not:
    "revoked" or "expired". A valid token is not enough on its own.

    The window opens at first sign-in (study-login does it; a request with no
    window yet opens one, which only happens for tokens minted outside
    study-login, e.g. in tests)."""
    async with AsyncSessionLocal() as db:
        st = await db.get(StudyParticipantStatus, participant.id)
    if st is not None and st.revoked_at is not None:
        return "revoked"
    end = window_end(st)
    if end is None:
        await _open_window(participant.id)
        return None
    now = _utcnow()
    if now < end:
        return None
    async with AsyncSessionLocal() as db:
        by_challenge = await _study_sessions(db, participant)
        awaiting = await _awaiting_answers(db, participant, by_challenge)
    if _tail_open(list(by_challenge.values()), end, now, awaiting):
        return None
    if st.expired_at is None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(StudyParticipantStatus)
                .where(StudyParticipantStatus.participant_id == participant.id,
                       StudyParticipantStatus.expired_at.is_(None))
                .values(expired_at=now))
            await db.commit()
        log.info("participant %s: study session ended", participant.id[:8])
    return "expired"


async def window_closed(participant: StudyParticipant) -> bool:
    """Whether the study session window is over (tail or not). No new task may
    start then: the tail only lets an already-running task finish."""
    async with AsyncSessionLocal() as db:
        st = await db.get(StudyParticipantStatus, participant.id)
    end = window_end(st)
    return end is not None and _utcnow() >= end


async def token_allowed(user_id: str) -> bool:
    """Called by auth.resolve_token_user_id for every token when the flag is
    on: a participant's token works only inside their study session."""
    participant = await active_participant(user_id)
    if participant is None:
        return True
    return await participant_access(participant) is None


async def login_refusal(participant: StudyParticipant) -> str | None:
    """At study-login with a correct code: open the window on the first
    sign-in, then refuse a revoked or expired participant."""
    async with AsyncSessionLocal() as db:
        st = await db.get(StudyParticipantStatus, participant.id)
    if st is not None and st.revoked_at is not None:
        return "revoked"
    await _open_window(participant.id)
    return await participant_access(participant)


# --- The task's conversation ---------------------------------------------------------

async def link_conversation(db, ucs, conversation_id: str) -> str:
    """Link a new conversation to the participant's session, unless another
    connection linked one first, and return the conversation to use.

    Two first connects that both find the session unlinked (React's dev
    double-mount, or a reconnect racing the first socket) used to each create
    and link a conversation, the second overwriting nothing but keeping its
    own: its turns were then saved to a conversation the session does not
    point at, and finishing it completed nothing. A conditional UPDATE lets
    exactly one win; the loser adopts the winner's."""
    res = await db.execute(
        update(UserChallengeSession)
        .where(UserChallengeSession.id == ucs.id,
               UserChallengeSession.conversation_id.is_(None))
        .values(conversation_id=conversation_id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if res.rowcount == 1:
        return conversation_id
    winner = (await db.execute(
        select(UserChallengeSession.conversation_id)
        .where(UserChallengeSession.id == ucs.id))).scalar_one()
    log.info("study session %s: adopted the conversation another connection linked",
             ucs.id[:8])
    return winner


# --- Finishing a task ------------------------------------------------------------

async def in_end_grace(user_id: str, ucs) -> bool:
    """A participant's finish within END_GRACE_SECONDS of the deadline is the
    timer's (see END_GRACE_SECONDS). False for everyone else."""
    if ucs is None or await active_participant(user_id) is None:
        return False
    deadline = session_deadline(ucs)
    return deadline is not None and (deadline - _utcnow()).total_seconds() <= END_GRACE_SECONDS


async def require_a_turn(db, user_id: str, ucs, past_deadline: bool) -> None:
    """A participant may finish a task by hand only after sending at least one
    message. The timer always finishes it."""
    if past_deadline or ucs is None or await active_participant(user_id) is None:
        return
    turns = 0
    if ucs.conversation_id:
        turns = int((await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == ucs.conversation_id, Message.role == "user")
        )).scalar() or 0)
    if turns < 1:
        raise HTTPException(status_code=400,
                            detail="Send at least one message before finishing the task.")


# --- Participant endpoints -------------------------------------------------------

@study_router.post("/tasks/{task}/enter", include_in_schema=False,
                   dependencies=[Depends(_require_flag)])
async def enter_task(task: int, participant: StudyParticipant = Depends(_current_participant)):
    """Open task N from its survey link. The server decides: N must be the
    participant's current task. A finished task re-shows its completion code
    and can never be redone; a later task is refused until the current one is
    done. Starting (or resuming) the session happens here, so any per-task
    deadline is set before the workspace opens."""
    _require_server_key()
    if not 1 <= task <= MAX_TASKS:
        raise HTTPException(status_code=404, detail="Not Found")
    await finalize_overdue(participant)
    participant = await _heal_block(participant)
    if task > task_count(participant):
        raise HTTPException(status_code=404, detail="Not Found")
    cid = task_challenge_id(participant, task)
    if cid is None:
        log.error("study task %d is not configured as one task for participant %s",
                  task, participant.id[:8])
        raise HTTPException(status_code=503, detail="The study is not available right now.")
    async with AsyncSessionLocal() as db:
        sessions = await _study_sessions(db, participant)
        awaiting = await _awaiting_answers(db, participant, sessions)
        # An earlier task's questions come before anything later: a
        # participant cannot skip them by opening the next task's link.
        owed = next((n for n in range(1, task + 1)
                     if task_challenge_id(participant, n) in awaiting), None)
        owed_row = await _answer_row(db, participant, owed) if owed else None
    if owed is not None:
        return {"status": "answers_required",
                **answers_required_payload(participant, owed,
                                           task_challenge_id(participant, owed), owed_row)}
    ucs = sessions.get(cid)
    if ucs is not None and ucs.status == "completed":
        return {"status": "completed", "task": task,
                "completion_code": completion_code(participant.id, task)}
    current = current_task_number(participant, sessions)
    if current != task:
        return {"status": "locked", "task": task, "current_task": current}

    from challenges import start_session  # challenges imports this module
    try:
        async with AsyncSessionLocal() as db:
            await start_session(cid, STUDY_SESSION_NUMBER, user_id=participant.user_id, db=db)
    except IntegrityError:
        # Two copies of the task page entered at once (the survey preview's
        # desktop and mobile frames, a quick reload, a second tab) and both
        # found no session to resume, so the loser's insert hit the unique key.
        # Again: it now finds the winner's session and resumes it.
        async with AsyncSessionLocal() as db:
            await start_session(cid, STUDY_SESSION_NUMBER, user_id=participant.user_id, db=db)
    return {"status": "ready", "task": task, "challenge_id": cid,
            "session_number": STUDY_SESSION_NUMBER}


@study_router.get("/completion", include_in_schema=False, dependencies=[Depends(_require_flag)])
async def task_completion(challenge_id: str,
                          participant: StudyParticipant = Depends(_current_participant)):
    """The completion code for one of the participant's finished tasks, for
    the workspace to show when the task ends, or the page of questions still
    owed before it. 404 until the task is finished."""
    _require_server_key()
    await finalize_overdue(participant)
    task = task_number_for(participant, challenge_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not Found")
    async with AsyncSessionLocal() as db:
        ucs = (await _study_sessions(db, participant)).get(challenge_id)
        row = await _answer_row(db, participant, task)
    if ucs is None or ucs.status != "completed":
        raise HTTPException(status_code=404, detail="Not Found")
    if end_questions(challenge_id) is not None and not _answers_done(row):
        return answers_required_payload(participant, task, challenge_id, row)
    return {"task": task, "completion_code": completion_code(participant.id, task),
            "embed_origins": embed_origins()}


class TaskAnswersRequest(BaseModel):
    total: str = Field(max_length=32)
    corrections: str = Field(max_length=5000)


class TaskRatingsRequest(BaseModel):
    confidence: int = Field(ge=0, le=100)
    trust: Optional[int] = Field(None, ge=1, le=6)
    check: Optional[int] = Field(None, ge=1, le=6)


async def _finished_task(db, participant: StudyParticipant, task: int) -> tuple[str, Any]:
    """(challenge id, its finished session) for a task with questions, or the
    HTTP error: 404 for a task without them, 409 before it is finished."""
    cid = task_challenge_id(participant, task)
    if cid is None or end_questions(cid) is None:
        raise HTTPException(status_code=404, detail="Not Found")
    ucs = (await _study_sessions(db, participant)).get(cid)
    if ucs is None or ucs.status != "completed":
        raise HTTPException(status_code=409, detail="Finish the task first.")
    return cid, ucs


def _completion(participant: StudyParticipant, task: int) -> dict:
    return {"task": task, "stage": "done",
            "completion_code": completion_code(participant.id, task),
            "embed_origins": embed_origins()}


def _after_answers(participant: StudyParticipant, task: int, row: StudyTaskAnswer) -> dict:
    """After page 1: page 2 if it is still owed, else the completion code."""
    if _answers_done(row):
        return _completion(participant, task)
    return {"task": task, "stage": "ratings",
            "ratings": ratings_questions(participant, row.challenge_id)}


@study_router.post("/tasks/{task}/answers", include_in_schema=False,
                   dependencies=[Depends(_require_flag)])
async def submit_task_answers(task: int, body: TaskAnswersRequest,
                              participant: StudyParticipant = Depends(_current_participant)):
    """Page 1 of a finished task's questions: the total and the corrections.
    Accepted once, then locked (a repeat gets 409 with where things stand).
    Returns page 2."""
    _require_server_key()
    total = normalize_total(body.total)
    if total is None:
        raise HTTPException(status_code=422,
                            detail="Enter a dollar amount with at most 2 decimal places.")
    corrections = body.corrections.strip()
    if not corrections:
        raise HTTPException(status_code=422, detail="Please list the corrections you made.")
    async with AsyncSessionLocal() as db:
        cid, ucs = await _finished_task(db, participant, task)
        existing = await _answer_row(db, participant, task)
        if existing is not None:
            raise HTTPException(status_code=409, detail={
                "message": "Already submitted.", **_after_answers(participant, task, existing)})
        row = StudyTaskAnswer(
            participant_id=participant.id, task=task, challenge_id=cid,
            user_challenge_session_id=ucs.id, total=total, corrections=corrections,
            submitted_at=_utcnow())
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent submit won; it is the one locked in.
            await db.rollback()
            existing = await _answer_row(db, participant, task)
            raise HTTPException(status_code=409, detail={
                "message": "Already submitted.", **_after_answers(participant, task, existing)})
    log.info("participant %s answered task %d (page 1)", participant.id[:8], task)
    return _after_answers(participant, task, row)


@study_router.post("/tasks/{task}/ratings", include_in_schema=False,
                   dependencies=[Depends(_require_flag)])
async def submit_task_ratings(task: int, body: TaskRatingsRequest,
                              participant: StudyParticipant = Depends(_current_participant)):
    """Page 2: confidence, plus trust and checking on a post-test task.
    Accepted once, after page 1; a repeat gets 409 with the code, since the
    first submit already earned it. Returns the completion code."""
    _require_server_key()
    async with AsyncSessionLocal() as db:
        cid, _ucs = await _finished_task(db, participant, task)
        posttest = phase_of(participant, cid) == "posttest"
        if posttest and (body.trust is None or body.check is None):
            raise HTTPException(status_code=422, detail="Please answer every question.")
        row = await _answer_row(db, participant, task)
        if row is None:
            raise HTTPException(status_code=409, detail="Answer the first questions first.")
        if _answers_done(row):
            raise HTTPException(status_code=409, detail={
                "message": "Already submitted.", **_completion(participant, task)})
        # Conditional on page 2 still being empty, so two racing submits lock
        # in exactly one.
        res = await db.execute(
            update(StudyTaskAnswer)
            .where(StudyTaskAnswer.id == row.id, StudyTaskAnswer.confidence.is_(None))
            .values(confidence=body.confidence,
                    ai_trust=body.trust if posttest else None,
                    self_check=body.check if posttest else None,
                    rated_at=_utcnow())
        )
        await db.commit()
    if res.rowcount != 1:
        raise HTTPException(status_code=409, detail={
            "message": "Already submitted.", **_completion(participant, task)})
    log.info("participant %s answered task %d (page 2)", participant.id[:8], task)
    return _completion(participant, task)


# --- Qualtrics web-service endpoints ---------------------------------------------

_qualtrics_limiter = None


def _qualtrics_rate_max() -> int:
    if os.getenv("HUSKY_TESTING") == "1":
        return int(os.getenv("QUALTRICS_RATE_TEST_MAX", "1000000"))
    return int(os.getenv("QUALTRICS_RATE_MAX", "120"))


async def _require_qualtrics(request: Request,
                             x_huskyai_secret: Optional[str] = Header(None)) -> None:
    """Shared-secret auth for the survey's Web Service calls (header
    X-HuskyAI-Secret). 503 when the server is not configured; 429 past the
    per-IP budget; 401, one message, for a missing or wrong secret."""
    global _qualtrics_limiter
    from rate_limit import SlidingWindowLimiter, _allowed, _client_ip

    expected = _qualtrics_secret()
    if expected is None or _server_key() is None:
        log.error("Qualtrics request refused: QUALTRICS_SHARED_SECRET or STUDY_SECRET_KEY "
                  "is unset or weak")
        raise HTTPException(status_code=503, detail="Study enrollment is not available.")
    if _qualtrics_limiter is None:
        _qualtrics_limiter = SlidingWindowLimiter(60.0)
    ip = _client_ip(request)
    if not await _allowed("qualtrics", _qualtrics_limiter, ip, _qualtrics_rate_max()):
        log.warning("rate limited: Qualtrics request from %s", ip)
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    given = (x_huskyai_secret or "").strip().encode("utf-8")
    if not hmac.compare_digest(given, expected):
        log.warning("Qualtrics request with a bad secret from %s", ip)
        raise HTTPException(status_code=401, detail="Unauthorized")


async def clear_qualtrics_rate_buckets() -> None:
    """Test helper."""
    from rate_limit import _shared_window
    if _qualtrics_limiter is not None:
        _qualtrics_limiter.clear()
    shared = _shared_window("qualtrics", 60.0)
    if shared is not None:
        try:
            await shared.clear()
        except Exception as e:
            log.warning("could not clear shared qualtrics rate buckets: %s", e)


class EnrollRequest(BaseModel):
    response_id: str = Field(pattern=RESPONSE_ID_PATTERN)
    # Lucy's design assigns the condition itself: `cond` is accepted (an older
    # survey may still send it) and ignored. The older layout requires it.
    cond: Optional[Literal["feedback", "control"]] = None


class VerifyCompletionRequest(BaseModel):
    response_id: str = Field(pattern=RESPONSE_ID_PATTERN)
    task: int = Field(ge=1, le=MAX_TASKS)
    code: str = Field(min_length=1, max_length=32)


async def _next_order(db, condition: str) -> int:
    """With counterbalancing on: the Latin-square order this condition has
    used least so far (ties broken at random), so orders stay balanced within
    each condition as enrollments arrive one at a time."""
    rows = (await db.execute(
        select(StudyParticipant.task_order).where(StudyParticipant.condition == condition)
    )).scalars().all()
    counts = {o: 0 for o in LATIN_SQUARE_ORDERS}
    for t in rows:
        o = (t or {}).get("order")
        if o in counts:
            counts[o] += 1
    low = min(counts.values())
    return secrets.choice([o for o, c in counts.items() if c == low])


def _enroll_result(code: str, participant: StudyParticipant) -> dict:
    """{code, link_base}, plus, in Lucy's design, the assignment Qualtrics
    uses to show the matching task text and the HuskyAI-only notes."""
    return {"code": code, "link_base": link_base(code), **assignment_of(participant)}


def _log_cond_mismatch(cond: str | None, participant: StudyParticipant) -> None:
    if cond is not None and QUALTRICS_CONDITIONS[cond] != participant.condition:
        log.info("enroll: survey sent cond=%s; participant %s was assigned %s (ignored)",
                 cond, participant.id[:8], participant.condition)


async def _existing_enrollment(db, enrollment: StudyEnrollment, cond: str | None) -> dict:
    participant = await db.get(StudyParticipant, enrollment.participant_id)
    if is_lucy_participant(participant):
        _log_cond_mismatch(cond, participant)
    elif participant.condition != QUALTRICS_CONDITIONS.get(cond or ""):
        # The survey re-sent this response with the other condition: refuse
        # rather than return a code for an arm the survey does not think it is.
        log.error("enroll: response already enrolled with a different condition "
                  "(participant %s)", participant.id[:8])
        raise HTTPException(status_code=409,
                            detail="This response is already enrolled with a different condition.")
    try:
        code = _decrypt_code(enrollment.code_ciphertext)
    except Exception:
        log.error("enroll: stored code for participant %s cannot be decrypted "
                  "(STUDY_SECRET_KEY changed?)", participant.id[:8])
        raise HTTPException(status_code=503, detail="Study enrollment is not available.")
    return _enroll_result(code, participant)


async def _enrollment_for(db, response_id: str) -> StudyEnrollment | None:
    return (await db.execute(
        select(StudyEnrollment).where(StudyEnrollment.response_id == response_id)
    )).scalar_one_or_none()


async def enroll(response_id: str, cond: str | None) -> dict:
    """Create (or return) the participant for one survey response.

    Idempotent on response_id: a repeat returns the same code and creates
    nothing. The participant, its User row (consent_research on: consent was
    given in the survey) and the enrollment are one transaction, so a race
    between two identical calls leaves exactly one participant and the loser
    returns the winner's code.

    Lucy's design: the next enrollment number picks the cell (condition, set
    order, error order). Two enrollments that read the same number collide on
    enroll_seq's unique constraint at commit; the loser retries."""
    lucy = lucy_design_active()
    if not lucy and cond is None:
        raise HTTPException(status_code=422, detail="cond is required.")
    for _attempt in range(ENROLL_ATTEMPTS):
        async with AsyncSessionLocal() as db:
            existing = await _enrollment_for(db, response_id)
            if existing is not None:
                return await _existing_enrollment(db, existing, cond)
            code = _new_code()
            try:
                # Inside the try: a collision can surface at any flush (the
                # User lookup below autoflushes), not only at the commit.
                if lucy:
                    seq = await _next_enroll_seq(db)
                    a = cell_assignment(seq)
                    minted = await _add_participant(db, code, a["condition"], a["task_order"],
                                                    enroll_seq=seq)
                else:
                    condition = QUALTRICS_CONDITIONS[cond]
                    order = await _next_order(db, condition) if counterbalance_enabled() else 1
                    minted = await _add_participant(db, code, condition,
                                                    legacy_task_order(block_tasks(), order))
                user = await db.get(User, minted["user_id"])
                user.consent_research = True
                db.add(StudyEnrollment(
                    participant_id=minted["participant_id"], response_id=response_id,
                    code_ciphertext=_encrypt_code(code), consent_recorded_at=_utcnow()))
                await db.commit()
            except IntegrityError:
                # A concurrent call for the same response won, another
                # enrollment took this number, or (vanishingly rarely) the
                # random code collided: look again.
                await db.rollback()
                await asyncio.sleep(secrets.randbelow(50) / 1000)
                continue
            participant = await db.get(StudyParticipant, minted["participant_id"])
        log.info("enrolled study participant %s via Qualtrics", minted["participant_id"][:8])
        if lucy:
            _log_cond_mismatch(cond, participant)
        return _enroll_result(code, participant)
    raise HTTPException(status_code=503, detail="Could not enroll. Try again.")


@study_router.post("/enroll", include_in_schema=False,
                   dependencies=[Depends(_require_flag), Depends(_require_qualtrics)])
async def study_enroll(body: EnrollRequest):
    """Qualtrics Web Service: {response_id} -> {code, link_base} and, in Lucy's
    design, the assignment: condition ("huskyai" | "standard"), set_order,
    error_order, cell, enroll_seq and set_1..set_6."""
    from fastapi.responses import JSONResponse
    result = await enroll(body.response_id, body.cond)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@study_router.post("/verify-completion", include_in_schema=False,
                   dependencies=[Depends(_require_flag), Depends(_require_qualtrics)])
async def verify_completion(body: VerifyCompletionRequest):
    """Qualtrics (optional): is this the completion code for that response's
    task N, and is the task actually finished? {valid: bool}, nothing else."""
    async with AsyncSessionLocal() as db:
        enrollment = await _enrollment_for(db, body.response_id)
        participant = await db.get(StudyParticipant, enrollment.participant_id) \
            if enrollment else None
    if participant is None:
        return {"valid": False}
    await finalize_overdue(participant)
    cid = task_challenge_id(participant, body.task)
    async with AsyncSessionLocal() as db:
        ucs = (await _study_sessions(db, participant)).get(cid) if cid else None
    expected = completion_code(participant.id, body.task)
    matches = hmac.compare_digest(normalize_code(body.code).encode(), expected.encode())
    finished = ucs is not None and ucs.status == "completed" \
        and not await answers_owed(participant, body.task, cid)
    return {"valid": bool(matches and finished)}


# --- Study admin (endpoints in admin.py) -----------------------------------------

def _task_rows(participant: StudyParticipant, sessions: dict) -> list[dict]:
    rows = []
    for n in range(1, task_count(participant) + 1):
        cid = task_challenge_id(participant, n)
        s = sessions.get(cid) if cid else None
        status = "not_started" if s is None or s.status == "not_started" else s.status
        rows.append({
            "task": n,
            "challenge_id": cid,
            "status": status,
            "started_at": s.started_at.isoformat() if s and s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s and s.completed_at else None,
            "end_reason": s.end_reason if s else None,
        })
    return rows


def _status_of(participant, st, tasks: list[dict], sessions: dict, now: datetime,
               awaiting_answers: frozenset[str] = frozenset()) -> dict:
    """One participant's admin status: not_used, in_progress (task N, time
    left), completed, expired or revoked."""
    out = {"status": "not_used", "current_task": None, "task_seconds_left": None,
           "session_seconds_left": None}
    if st is not None and st.revoked_at is not None:
        out["status"] = "revoked"
        return out
    if tasks and all(t["status"] == "completed" for t in tasks):
        out["status"] = "completed"
        return out
    end = window_end(st)
    if end is not None and now >= end \
            and not _tail_open(list(sessions.values()), end, now, awaiting_answers):
        out["status"] = "expired"
        return out
    running = next((t for t in tasks if t["status"] == "in_progress"), None)
    if st is None or (st.first_login_at is None and running is None):
        return out
    out["status"] = "in_progress"
    out["current_task"] = running["task"] if running \
        else current_task_number(participant, sessions)
    if running:
        out["task_seconds_left"] = remaining_seconds(
            session_deadline(sessions.get(running["challenge_id"])))
    if end is not None:
        out["session_seconds_left"] = max(0, math.ceil((end - now).total_seconds()))
    return out


async def admin_status(include_conditions: bool = False) -> list[dict]:
    """Every participant's status for /study-admin. The condition and the rest
    of the assignment are included only when asked for; codes never are (they
    are not stored in plaintext, and the encrypted enrollment code is never
    read here)."""
    from study_challenges import set_letter_of

    async with AsyncSessionLocal() as db:
        participants = (await db.execute(
            select(StudyParticipant).order_by(StudyParticipant.created_at))).scalars().all()
    for p in participants:
        await finalize_overdue(p)
    async with AsyncSessionLocal() as db:
        participants = (await db.execute(
            select(StudyParticipant).order_by(StudyParticipant.created_at))).scalars().all()
        statuses = {s.participant_id: s for s in (await db.execute(
            select(StudyParticipantStatus))).scalars().all()}
        responses = dict((await db.execute(
            select(StudyEnrollment.participant_id, StudyEnrollment.response_id))).all())
        now = _utcnow()
        out = []
        for p in participants:
            sessions = await _study_sessions(db, p)
            st = statuses.get(p.id)
            tasks = _task_rows(p, sessions)
            awaiting = await _awaiting_answers(db, p, sessions)
            row = {
                "participant_id": p.id,
                "response_id": responses.get(p.id),
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "first_login_at": st.first_login_at.isoformat() if st and st.first_login_at else None,
                "revoked_at": st.revoked_at.isoformat() if st and st.revoked_at else None,
                "tasks": tasks,
                **_status_of(p, st, tasks, sessions, now, awaiting),
            }
            if include_conditions:
                # The set and error orders are assignment too: hidden with
                # the condition.
                a = assignment_of(p)
                row["condition"] = p.condition
                row["condition_label"] = CONDITION_LABELS.get(p.condition)
                for k in ("enroll_seq", "cell", "set_order", "error_order"):
                    row[k] = a.get(k)
                for t in tasks:
                    t["set"] = set_letter_of(t["challenge_id"])
                    t["phase"] = phase_of(p, t["challenge_id"])
                    t["error_type"] = error_type_for(p, t["challenge_id"])
            out.append(row)
    return out


async def revoke(participant_id: str) -> bool:
    """Revoke a participant: every request is refused from now on (their
    tokens stop working at once: token_version is bumped too). Data is kept."""
    async with AsyncSessionLocal() as db:
        p = await db.get(StudyParticipant, participant_id)
        if p is None:
            return False
        st = await db.get(StudyParticipantStatus, participant_id)
        if st is None:
            db.add(StudyParticipantStatus(participant_id=participant_id, revoked_at=_utcnow()))
        elif st.revoked_at is None:
            st.revoked_at = _utcnow()
        user = await db.get(User, p.user_id)
        if user is not None:
            user.token_version = int(user.token_version or 0) + 1
        await db.commit()
    log.info("participant %s revoked", participant_id[:8])
    return True


# Lucy's appendix flags tasks over 12 minutes for sensitivity analyses
# (nothing is enforced). Measured here from the chat's start to its finish.
LONG_TASK_MINUTES = 12

_EXPORT_BASE = ["participant_id", "response_id", "condition", "condition_label", "enroll_seq",
                "cell", "set_order", "error_order", "status", "created_at", "first_login_at",
                "revoked_at"]
_EXPORT_TASK_FIELDS = ("set", "phase", "errtype", "challenge_id", "status", "started_at",
                       "completed_at", "end_reason", "chat_minutes", "over_12_min")
_EXPORT_ANSWER_FIELDS = ("answer_total", "answer_correct", "answer_match", "answer_tier",
                         "answer_exc_corrected", "answer_decoys_changed",
                         "answer_error_accepted", "answer_error_detected",
                         "answer_corrections", "answer_confidence", "answer_trust",
                         "answer_check", "answer_submitted_at", "ratings_submitted_at")
# The exposure judge's first-pass signal (study_exposure.py). exposed_source
# says it is unvalidated model output, to be spot-checked before use.
_EXPORT_EXPOSURE_FIELDS = ("exposed_ai_judge", "exposed_ai_judge_case",
                           "exposed_ai_judge_reasoning", "exposed_source",
                           "exposed_judge_status", "exposed_judge_version")
EXPOSED_SOURCE = "ai_judge_unvalidated"
EXPORT_COLUMNS = (
    _EXPORT_BASE
    + [f"task{n}_{k}" for n in range(1, MAX_TASKS + 1)
       for k in _EXPORT_TASK_FIELDS + _EXPORT_ANSWER_FIELDS + _EXPORT_EXPOSURE_FIELDS]
)


def _chat_minutes(task: dict) -> tuple[float | None, bool | None]:
    if not task.get("started_at") or not task.get("completed_at"):
        return None, None
    minutes = (datetime.fromisoformat(task["completed_at"])
               - datetime.fromisoformat(task["started_at"])).total_seconds() / 60
    return round(minutes, 2), minutes > LONG_TASK_MINUTES


def score_answer(challenge_id: str | None, total: str | None, error_type: str | None) -> dict:
    """A submitted total, read through its set's wrong-answer map (Appendix A3):
    which TIER state, whether EXC was corrected, which decoys changed, and on a
    post-test task whether the scripted error was accepted or detected (A2):
      commission   accepted if BOUND changed, detected if BOUND left alone
      omission     accepted if EXC not corrected, detected if EXC corrected
      calculation  accepted if TIER is the AI's slip value, detected if TIER
                   is the correct value (neither when TIER was not corrected)
    A total in no row is "unmatched", with the map fields left empty."""
    from study_challenges import LUCY_SETS, answer_map, set_letter_of

    out = {"answer_correct": None, "answer_match": None, "answer_tier": None,
           "answer_exc_corrected": None, "answer_decoys_changed": None,
           "answer_error_accepted": None, "answer_error_detected": None}
    letter = set_letter_of(challenge_id)
    if letter is None or total is None:
        return out
    out["answer_correct"] = total == LUCY_SETS[letter]["correct_total"]
    row = answer_map(letter).get(total)
    if row is None:
        out["answer_match"] = "unmatched"
        return out
    out.update(answer_match="matched", answer_tier=row["tier"],
               answer_exc_corrected=row["exc_corrected"],
               answer_decoys_changed=row["decoys_changed"])
    bound_changed = "BOUND" in row["decoys_changed"]
    if error_type == "commission":
        out["answer_error_accepted"], out["answer_error_detected"] = bound_changed, not bound_changed
    elif error_type == "omission":
        out["answer_error_accepted"] = not row["exc_corrected"]
        out["answer_error_detected"] = row["exc_corrected"]
    elif error_type == "calculation":
        out["answer_error_accepted"] = row["tier"] == "slip"
        out["answer_error_detected"] = row["tier"] == "corrected"
    return out


def _answer_fields(answer: StudyTaskAnswer | None, error_type: str | None) -> dict:
    """One task's end-of-task answers for the export, scored against the
    set's map. Blank, not False, when unanswered."""
    if answer is None:
        return dict.fromkeys(_EXPORT_ANSWER_FIELDS)
    return {
        "answer_total": answer.total,
        **score_answer(answer.challenge_id, answer.total, error_type),
        "answer_corrections": answer.corrections,
        "answer_confidence": answer.confidence,
        "answer_trust": answer.ai_trust,
        "answer_check": answer.self_check,
        "answer_submitted_at": answer.submitted_at.isoformat() if answer.submitted_at else None,
        "ratings_submitted_at": answer.rated_at.isoformat() if answer.rated_at else None,
    }


def _exposure_fields(judgment) -> dict:
    if judgment is None:
        return dict.fromkeys(_EXPORT_EXPOSURE_FIELDS)
    return {
        "exposed_ai_judge": None if judgment.exposed is None else int(judgment.exposed),
        "exposed_ai_judge_case": judgment.exposure_case,
        "exposed_ai_judge_reasoning": judgment.reasoning,
        "exposed_source": EXPOSED_SOURCE,
        "exposed_judge_status": judgment.status,
        "exposed_judge_version": judgment.judge_version,
    }


# --- Model and evaluator versions ----------------------------------------------
# Recorded on every participant turn (the turn event's condition), so the
# export shows what produced each reply and score. Read-only: the chat model
# and evaluator code are not changed for the study.

# The model main.py's solo socket streams from. Kept in step by a test that
# reads main.py (test_study_message_export).
STUDY_CHAT_MODEL = "gemini-2.5-pro"

_eval_version: str | None = None


def eval_version() -> str:
    """A fingerprint of the PEI evaluator: every judge's model, instructions,
    sampling settings and output schema, and the rubric store. Same code and
    config give the same value on any machine; any change to the evaluator
    gives a new one. Computed once per process from evaluator_v3, read-only."""
    global _eval_version
    if _eval_version is None:
        import evaluator_v3 as ev

        parts = []
        for agent in (ev.domain_detector, ev.psq_judge, ev.ccm_judge, ev.tsi_judge,
                      ev.clm_judge, ev.ras_judge, ev.feedback_writer):
            ms = agent.model_settings
            parts.append({
                "name": agent.name, "model": agent.model, "instructions": agent.instructions,
                "temperature": ms.temperature, "top_p": ms.top_p, "max_tokens": ms.max_tokens,
                "output": getattr(agent.output_type, "__name__", None),
            })
        parts.append({"rubric_store": ev._VECTOR_STORE_ID, "guard": ev._JUDGE_GUARD})
        digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()
        _eval_version = f"v3-{digest[:12]}"
    return _eval_version


MESSAGE_EXPORT_COLUMNS = [
    "participant_id", "response_id", "condition", "condition_label", "set_order",
    "error_order", "task", "challenge_id", "block", "phase", "mode", "task_set", "error_type",
    "turn", "user_message_at", "ai_response_at", "user_message",
    "ai_response", "pei", "psq", "ccm", "tsi", "clm", "ras", "score_status", "feedback_shown",
    "feedback_summary", "feedback_suggestions", "feedback_strengths", "feedback_red_flags",
    "chat_model", "eval_version",
]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def admin_message_rows() -> list[dict]:
    """One row per participant message, in every task and condition: what was
    said, the AI's reply, the turn's PEI and five dimension scores, and the
    feedback text, which is filled only for a turn whose feedback was actually
    shown (a feed.shown event, on time or late). `mode` is what the session
    ran as: "huskyai" (tutor and live feedback) or "standard", from its block
    snapshot; `task_set` is the task's set letter (A-F).

    A turn the evaluator failed on has NULL scores (score_status "pending" or
    "failed"): they stay None here, so the CSV cell is empty and the JSON value
    null, never 0. Lists (suggestions etc.) stay lists; the CSV writer joins
    them."""
    from study_challenges import set_letter_of

    async with AsyncSessionLocal() as db:
        participants = (await db.execute(
            select(StudyParticipant).order_by(StudyParticipant.created_at))).scalars().all()
        responses = dict((await db.execute(
            select(StudyEnrollment.participant_id, StudyEnrollment.response_id))).all())
        rows: list[dict] = []
        for p in participants:
            sessions = await _study_sessions(db, p)
            a = assignment_of(p)
            for n in range(1, task_count(p) + 1):
                cid = task_challenge_id(p, n)
                ucs = sessions.get(cid) if cid else None
                if ucs is None or not ucs.conversation_id:
                    continue
                snapshot = (await db.execute(select(StudyEvent).where(
                    StudyEvent.idempotency_key == _snapshot_key(ucs.id)))).scalar_one_or_none()
                snap = (snapshot.payload or {}) if snapshot else {}
                events = (await db.execute(select(StudyEvent).where(
                    StudyEvent.user_challenge_session_id == ucs.id,
                    StudyEvent.action.in_(("feed.shown", "turn"))))).scalars().all()
                shown_turns = {(e.payload or {}).get("turn") for e in events
                               if e.action == "feed.shown"}
                turn_conditions = {(e.payload or {}).get("turn"): (e.condition or {})
                                   for e in events if e.action == "turn"}
                msgs = (await db.execute(
                    select(Message).where(Message.conversation_id == ucs.conversation_id)
                    .order_by(Message.created_at))).scalars().all()
                users = [m for m in msgs if m.role == "user"]
                replies = [m for m in msgs if m.role == "assistant"]
                evals = {e.turn_number: e for e in (await db.execute(
                    select(EvalResult).where(
                        EvalResult.conversation_id == ucs.conversation_id))).scalars().all()}
                for i, um in enumerate(users):
                    turn = i + 1
                    reply = replies[i] if i < len(replies) else None
                    ev = evals.get(turn)
                    full = (ev.full_result or {}) if ev else {}
                    shown = turn in shown_turns
                    rows.append({
                        "participant_id": p.id,
                        "response_id": responses.get(p.id),
                        "condition": p.condition,
                        "condition_label": CONDITION_LABELS.get(p.condition),
                        "set_order": a.get("set_order"),
                        "error_order": a.get("error_order"),
                        "task": n,
                        "challenge_id": cid,
                        "block": snap.get("block"),
                        "phase": phase_of(p, cid),
                        "mode": None if not snap else
                        ("huskyai" if snap.get("feedback_visible") else "standard"),
                        "task_set": set_letter_of(cid),
                        "error_type": error_type_for(p, cid),
                        "turn": turn,
                        "user_message_at": _iso(um.created_at),
                        "ai_response_at": _iso(reply.created_at) if reply else None,
                        "user_message": um.content,
                        "ai_response": reply.content if reply else None,
                        "pei": ev.pei if ev else None,
                        "psq": ev.psq if ev else None,
                        "ccm": ev.ccm if ev else None,
                        "tsi": ev.tsi if ev else None,
                        "clm": ev.clm if ev else None,
                        "ras": ev.ras if ev else None,
                        "score_status": (ev.score_status or "scored") if ev else None,
                        "feedback_shown": shown,
                        "feedback_summary": full.get("turn_summary") if shown else None,
                        "feedback_suggestions": full.get("suggestions") if shown else None,
                        "feedback_strengths": full.get("strengths") if shown else None,
                        "feedback_red_flags": full.get("red_flags") if shown else None,
                        "chat_model": turn_conditions.get(turn, {}).get("chat_model"),
                        "eval_version": turn_conditions.get(turn, {}).get("eval_version"),
                    })
    return rows


async def admin_export_rows() -> list[dict]:
    """The CSV rows: ids, the assignment (condition, set order, error order),
    per-task set, phase, error type and timing, the end-of-task answers read
    through the wrong-answer map, and the exposure judge's first pass. No
    codes of any kind."""
    async with AsyncSessionLocal() as db:
        answers = {(a.participant_id, a.task): a for a in (await db.execute(
            select(StudyTaskAnswer))).scalars().all()}
        judgments = {(j.participant_id, j.task): j for j in (await db.execute(
            select(StudyExposureJudgment))).scalars().all()}
    rows = []
    for r in await admin_status(include_conditions=True):
        row = {k: r.get(k) for k in _EXPORT_BASE}
        for t in r["tasks"]:
            n = t["task"]
            t = {**t, "errtype": t.get("error_type")}
            t["chat_minutes"], t["over_12_min"] = _chat_minutes(t)
            for k in _EXPORT_TASK_FIELDS:
                row[f"task{n}_{k}"] = t.get(k)
            for k, v in _answer_fields(answers.get((r["participant_id"], n)),
                                       t.get("error_type")).items():
                row[f"task{n}_{k}"] = v
            for k, v in _exposure_fields(judgments.get((r["participant_id"], n))).items():
                row[f"task{n}_{k}"] = v
        rows.append(row)
    return rows


# --- Local seed command ---------------------------------------------------------
# python -m study_mode seed-challenges [--allow-postgres]
# Never run on startup: SEED_CHALLENGES would publish these to every user of a
# deploy. Refuses anything but a local SQLite database with the flag on, unless
# --allow-postgres is passed: a deliberate, by-hand seed of a deployed database.
# The rows are safe there because every list hides study- ids from
# non-participants (is_study_challenge).

def resolved_database() -> str:
    """The database this process would write to, password hidden."""
    from database import engine
    return engine.url.render_as_string(hide_password=True)


def _seed_refusal(allow_postgres: bool = False) -> str | None:
    from database import engine
    if not study_mode_enabled():
        return "STUDY_MODE_ENABLED is not true"
    backend = engine.url.get_backend_name()
    if backend == "sqlite" or (allow_postgres and backend == "postgresql"):
        return None
    if backend == "postgresql":
        return (f"the resolved database is {backend!r}, not SQLite "
                "(pass --allow-postgres to seed it on purpose)")
    return f"the resolved database is {backend!r}, not SQLite"


async def seed_study_challenges(allow_postgres: bool = False) -> dict[str, list[str]]:
    """Write the study challenges to the local database, keyed by their fixed
    ids. Idempotent: a missing challenge is added, an existing one is brought
    back in line with study_challenges.py, and nothing is ever duplicated."""
    reason = _seed_refusal(allow_postgres)
    if reason:
        raise RuntimeError(f"refusing to seed study challenges: {reason}")
    from study_challenges import ALL_STUDY_CHALLENGES

    result: dict[str, list[str]] = {"added": [], "updated": [], "unchanged": []}
    async with AsyncSessionLocal() as db:
        for data in ALL_STUDY_CHALLENGES:
            assert is_study_challenge(data["id"])
            fields = {k: v for k, v in data.items() if k != "id"}
            ch = await db.get(Challenge, data["id"])
            if ch is None:
                db.add(Challenge(id=data["id"], is_active=True, status="published", **fields))
                result["added"].append(data["id"])
            elif any(getattr(ch, k) != v for k, v in fields.items()):
                for k, v in fields.items():
                    setattr(ch, k, v)
                result["updated"].append(data["id"])
            else:
                result["unchanged"].append(data["id"])
        await db.commit()
    return result


def _main(argv: list[str]) -> int:
    if argv not in (["seed-challenges"], ["seed-challenges", "--allow-postgres"]):
        print("usage: python -m study_mode seed-challenges [--allow-postgres]")
        return 2
    print(f"database: {resolved_database()}")
    try:
        result = asyncio.run(seed_study_challenges(allow_postgres="--allow-postgres" in argv))
    except RuntimeError as e:
        print(e)
        return 1
    for k, ids in result.items():
        print(f"{k}: {', '.join(ids) or '-'}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
