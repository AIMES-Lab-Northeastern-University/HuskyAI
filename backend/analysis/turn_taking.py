"""Turn-taking metrics over the study event log.

A primary research output, not telemetry. That distinction drives three choices
here, and they should survive refactoring:

1. **`compute_turn_taking` is a pure function over an ordered list of events.**
   Nothing in it touches the database or the clock. Replaying the same log must
   produce byte-identical metrics, which is what makes a published number
   reproducible from an exported log months later.
2. **Definitions are versioned** (`METRICS_VERSION`). Every response carries the
   version, so a number in a paper can be tied to the definition that produced
   it. Changing any definition below is a version bump and a codebook edit, not
   a silent fix — see docs/metrics-codebook.md.
3. **Denominators are chosen deliberately, not conveniently.** The clearest case
   is read_before_write_ratio: a write cannot be "informed by a teammate" if no
   teammate had written anything yet, so those writes are excluded from the
   denominator rather than counted as failures. A convenient denominator would
   make early turns look like students ignoring each other.
"""

from __future__ import annotations

import math
from statistics import median

# Bumped whenever any definition in this module changes. Echoed in the API
# response and recorded alongside exported metrics.
METRICS_VERSION = "1.1.0"

# Reads performed by a person. Deliberately excludes read_by_coach: whether a
# coach-mediated read counts as the student having read their teammate's work is
# an open research question, so the two are never merged. Coach reads are
# reported separately below.
HUMAN_READ_ACTIONS = {"open", "section_expand", "dwell"}
# The subset that names a specific section, and so can be attributed to a
# teammate's contribution rather than to the artifact as a whole.
SECTION_READ_ACTIONS = {"section_expand", "dwell"}


def _gini(values: list[float]) -> float | None:
    """Gini coefficient of a contribution distribution. 0 = perfectly equal,
    approaching 1 = one member did everything. None when there is nothing to
    measure."""
    if not values or sum(values) <= 0:
        return None
    xs = sorted(values)
    n = len(xs)
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return round((2 * cum) / (n * sum(xs)) - (n + 1) / n, 4)


def _normalised_entropy(values: list[float]) -> float | None:
    """Shannon entropy of the share distribution, scaled to [0, 1] by the
    maximum possible for this number of actors. 1.0 = every member contributed
    equally; 0.0 = a single member contributed everything.

    Reported alongside Gini because they disagree in useful ways: entropy is
    more sensitive to how many members participated at all, Gini to how unequal
    the participants were."""
    total = sum(values)
    if total <= 0 or len(values) < 2:
        return None
    h = -sum((v / total) * math.log(v / total) for v in values if v > 0)
    return round(h / math.log(len(values)), 4)


def compute_turn_taking(events: list[dict], members: list[str] | None = None) -> dict:
    """Turn-taking metrics for one session.

    `events` must be ordered by `seq` and each item needs: seq, actor_user_id,
    actor_kind, target, action, payload, server_ts. `members` optionally lists
    every member so a participant who did nothing is reported as a zero rather
    than being absent — silence is a finding, not missing data.
    """
    events = sorted(events, key=lambda e: e["seq"])

    writes = [e for e in events if e["target"] == "artifact" and e["action"] == "write"]
    human_reads = [
        e for e in events
        if e["target"] == "artifact"
        and e["action"] in HUMAN_READ_ACTIONS
        and e["actor_kind"] == "student"
    ]
    coach_reads = [e for e in events if e["action"] == "read_by_coach"]
    coach_turns = [e for e in events if e["target"] == "coach" and e["action"] == "turn"]

    actors = set(members or [])
    actors |= {e["actor_user_id"] for e in events if e["actor_user_id"]}
    actors.discard(None)

    # -- Contribution share: accepted artifact writes, per member. -------------
    # Writes rather than coach turns, because the shared artifact is the team's
    # actual joint output. A rejected (conflicting) write is never logged, so a
    # member cannot inflate their share with writes that did not land.
    writes_by_user = {u: 0 for u in actors}
    for e in writes:
        if e["actor_user_id"]:
            writes_by_user[e["actor_user_id"]] = writes_by_user.get(e["actor_user_id"], 0) + 1
    total_writes = sum(writes_by_user.values())
    contribution_share = {
        u: (round(n / total_writes, 4) if total_writes else 0.0)
        for u, n in writes_by_user.items()
    }

    turns_by_user = {u: 0 for u in actors}
    for e in coach_turns:
        if e["actor_user_id"]:
            turns_by_user[e["actor_user_id"]] = turns_by_user.get(e["actor_user_id"], 0) + 1

    # -- Alternation: how often the writer changes hands. ----------------------
    # 1.0 = every write came from a different member than the one before it;
    # 0.0 = one member wrote a whole block uninterrupted.
    alternation_rate = None
    if len(writes) >= 2:
        switches = sum(
            1 for a, b in zip(writes, writes[1:])
            if a["actor_user_id"] != b["actor_user_id"]
        )
        alternation_rate = round(switches / (len(writes) - 1), 4)

    # -- Latency from a write to the first read of it by someone else. ---------
    # Section-scoped: the question is how long a specific contribution sat
    # unread, not how long until the panel was next opened for any reason.
    latencies: list[float] = []
    for w in writes:
        key = (w.get("payload") or {}).get("section_key")
        if key is None:
            continue
        follow = next(
            (
                r for r in human_reads
                if r["seq"] > w["seq"]
                and r["actor_user_id"] != w["actor_user_id"]
                and r["action"] in SECTION_READ_ACTIONS
                and (r.get("payload") or {}).get("section_key") == key
            ),
            None,
        )
        if follow is not None:
            latencies.append((follow["server_ts"] - w["server_ts"]).total_seconds() * 1000)
    median_write_to_read_ms = round(median(latencies)) if latencies else None
    # How many contributions were never read by anyone else at all. A high
    # number here means the team worked in parallel rather than together, which
    # no latency average would reveal.
    unread_writes = sum(
        1 for w in writes if (w.get("payload") or {}).get("section_key") is not None
    ) - len(latencies)

    # -- Read-before-write: did this member look at a teammate's contribution
    # before adding their own? The study's central question. -------------------
    # A write only counts in the denominator if a teammate-authored section
    # actually existed to be read at that point. Counting the unanswerable case
    # as a failure would make early turns look like students ignoring each other.
    informed, eligible = 0, 0
    # Tracked apart from `informed` for the coach-reliance ratio below: a write
    # whose text was lifted from the coach must not also count as adopting a
    # teammate's work, even when that student had read a teammate earlier in the
    # session. Otherwise one write lands on both sides of the same ratio.
    informed_typed = 0
    # Coach-copied writes made when a teammate-authored section already existed.
    # The ratio below uses this and NOT the count over all writes: `informed_typed`
    # can only ever be drawn from eligible writes, so pairing it with a numerator
    # drawn from every write compares two different populations. A session whose
    # only coach-copied write landed before anyone else had written would report
    # total coach reliance, when there was no teammate work available to adopt --
    # the same artefact the read_before_write denominator exists to avoid.
    coach_copied_eligible = 0
    section_author: dict[str, str] = {}
    for e in events:
        if e["target"] != "artifact":
            continue
        key = (e.get("payload") or {}).get("section_key")
        if e["action"] == "write":
            teammate_sections = {
                k for k, a in section_author.items() if a != e["actor_user_id"]
            }
            if teammate_sections:
                eligible += 1
                if (e.get("payload") or {}).get("origin") == "coach_copied":
                    coach_copied_eligible += 1
                read_a_teammate = any(
                    r["seq"] < e["seq"]
                    and r["actor_user_id"] == e["actor_user_id"]
                    and r["action"] in SECTION_READ_ACTIONS
                    and (r.get("payload") or {}).get("section_key") in teammate_sections
                    for r in human_reads
                )
                if read_a_teammate:
                    informed += 1
                    if (e.get("payload") or {}).get("origin") != "coach_copied":
                        informed_typed += 1
            if key:
                section_author[key] = e["actor_user_id"]
    read_before_write_ratio = round(informed / eligible, 4) if eligible else None

    # -- Coach reliance: text lifted from a coach vs text written after reading
    # a teammate. Both are "adoption"; the question is adoption of whose work. --
    # Both terms are restricted to eligible writes, so the ratio answers "when a
    # teammate's work was there to adopt, how often was the coach's taken
    # instead?". The unrestricted count is still reported for description.
    coach_copied = sum(1 for w in writes if (w.get("payload") or {}).get("origin") == "coach_copied")
    coach_reliance_ratio = (
        round(coach_copied_eligible / (coach_copied_eligible + informed_typed), 4)
        if (coach_copied_eligible + informed_typed) > 0 else None
    )

    shares = [writes_by_user[u] for u in sorted(actors)]

    return {
        "metrics_version": METRICS_VERSION,
        "actors": sorted(actors),
        "totals": {
            "artifact_writes": total_writes,
            "coach_turns": len(coach_turns),
            "human_reads": len(human_reads),
            "coach_reads": len(coach_reads),
            "events": len(events),
        },
        "contribution_share": contribution_share,
        "writes_by_user": writes_by_user,
        "coach_turns_by_user": turns_by_user,
        "equality": {
            "gini": _gini([float(v) for v in shares]),
            "normalised_entropy": _normalised_entropy([float(v) for v in shares]),
        },
        "alternation_rate": alternation_rate,
        "median_write_to_read_ms": median_write_to_read_ms,
        "writes_never_read_by_a_teammate": unread_writes,
        "read_before_write": {
            "ratio": read_before_write_ratio,
            "informed_writes": informed,
            "eligible_writes": eligible,
        },
        "coach_reliance": {
            "ratio": coach_reliance_ratio,
            # Every coach-copied write in the session, eligible or not.
            "coach_copied_writes": coach_copied,
            # The numerator of the ratio: coach-copied writes made when a
            # teammate's section already existed to be adopted instead.
            "coach_copied_eligible_writes": coach_copied_eligible,
            "teammate_informed_writes": informed_typed,
        },
    }


async def events_for_group_session(db, group_session_id: str) -> list[dict]:
    """Load one session's log in `seq` order, in the shape compute_turn_taking
    expects. Kept separate from the computation so the metrics stay replayable
    from an exported log with no database at all."""
    from sqlalchemy import select

    from database import StudyEvent

    rows = (
        await db.execute(
            select(StudyEvent)
            .where(StudyEvent.group_session_id == group_session_id)
            .order_by(StudyEvent.seq)
        )
    ).scalars().all()
    return [
        {
            "seq": e.seq,
            "actor_user_id": e.actor_user_id,
            "actor_kind": e.actor_kind,
            "target": e.target,
            "action": e.action,
            "payload": e.payload,
            "server_ts": e.server_ts,
        }
        for e in rows
    ]
