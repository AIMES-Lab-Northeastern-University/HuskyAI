"""Resolved experimental condition for one session.

The plan is explicit about why this is an object and not a handful of checks:
"No `if prominence ==` checks scattered through the websocket handlers, because
that is how conditions drift apart mid-study." A condition that is read in six
places will eventually be honoured in five of them, and the resulting dataset
mixes two conditions under one label — which is not detectable after the fact.

So: resolve once per session, pass the object, and let every handler ask it a
question rather than re-derive the answer. The resolved policy is also written
onto every event's `condition` field, so an exported log says what condition
produced it without a join against a config table that may have changed since.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select

from database import AsyncSessionLocal, ClassroomChallenge, GroupChallenge, GroupSession

ARMS = ("control_solo_feed", "collab_coach_artifact")
PROMINENCE = ("ambient", "on_request", "isolated")


@dataclass(frozen=True)
class CoachPolicy:
    """What the coach may do in this session. Frozen: a condition that can be
    mutated mid-session is a condition that can be mutated mid-session."""

    arm: str = "control_solo_feed"
    prominence: str = "on_request"
    revision_policy: dict | None = None
    verification_policy: str = "none"
    corpus_vector_store_id: str | None = None

    # -- Questions the handlers ask -------------------------------------------

    @property
    def injects_artifact(self) -> bool:
        """Does the shared artifact enter this student's coach prompt?

        False under `isolated`: the coach is reachable, but the team's work does
        not reach it unless a student explicitly copies it in, which is logged."""
        return self.prominence != "isolated"

    @property
    def takes_unsolicited_turns(self) -> bool:
        """May the coach speak without being addressed? Only under `ambient`."""
        return self.prominence == "ambient"

    @property
    def posts_to_shared_space(self) -> bool:
        """May coach output appear in the shared artifact automatically?

        Only under `ambient`. Under `isolated` an import must be an explicit
        student action recorded with origin="coach_copied" — the difference
        between a student adopting AI output and the system inserting it."""
        return self.prominence == "ambient"

    @property
    def is_collab_arm(self) -> bool:
        return self.arm == "collab_coach_artifact"

    def as_condition(self) -> dict:
        """Stamped onto every study event, so the log is self-describing."""
        return {
            "arm": self.arm,
            "prominence": self.prominence,
            "corpus": self.corpus_vector_store_id,
        }

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(value: str | None, allowed: tuple[str, ...], fallback: str) -> str:
    """An unrecognised value falls back to the safe default rather than being
    honoured. A typo in a config row must not silently create a fourth
    condition that analysis will never look for."""
    return value if value in allowed else fallback


async def resolve_for_group_session(group_session_id: str) -> CoachPolicy:
    """Resolve the policy for a collaborative session from its assignment.

    Falls back to defaults when the session is not linked to a
    ClassroomChallenge — an unconfigured session behaves exactly as it does
    today rather than failing."""
    async with AsyncSessionLocal() as db:
        gs = await db.get(GroupSession, group_session_id)
        if gs is None:
            return CoachPolicy()
        team = await db.get(GroupChallenge, gs.group_id)
        if team is None or team.classroom_id is None:
            return CoachPolicy(arm="collab_coach_artifact")
        cc = (await db.execute(
            select(ClassroomChallenge).where(
                ClassroomChallenge.classroom_id == team.classroom_id,
                ClassroomChallenge.challenge_id == gs.challenge_id,
            )
        )).scalar_one_or_none()
        if cc is None:
            return CoachPolicy(arm="collab_coach_artifact")
        return CoachPolicy(
            # A team reaching /ws/coach IS in the collaborative arm; the column
            # records intent for the whole section, but the socket it connected
            # to is the ground truth for this session.
            arm="collab_coach_artifact",
            prominence=_clean(cc.coach_prominence, PROMINENCE, "on_request"),
            revision_policy=cc.revision_policy,
            verification_policy=cc.verification_policy or "none",
        )


async def resolve_for_classroom_challenge(classroom_id: str, challenge_id: str) -> CoachPolicy:
    """Resolve the policy for a solo/control session."""
    async with AsyncSessionLocal() as db:
        cc = (await db.execute(
            select(ClassroomChallenge).where(
                ClassroomChallenge.classroom_id == classroom_id,
                ClassroomChallenge.challenge_id == challenge_id,
            )
        )).scalar_one_or_none()
        if cc is None:
            return CoachPolicy()
        return CoachPolicy(
            arm=_clean(cc.study_arm, ARMS, "control_solo_feed"),
            prominence=_clean(cc.coach_prominence, PROMINENCE, "on_request"),
            revision_policy=cc.revision_policy,
            verification_policy=cc.verification_policy or "none",
        )
