"""The research export bundle.

One session in, one de-identified, self-describing archive out: the ordered
event log, the artifact's full revision history, per-turn evaluations, the
computed turn-taking metrics, verification and contested-input outcomes, and
the condition that produced all of it.

Three rules, each of which exists because the alternative silently corrupts or
leaks:

- **Consent is filtered per row, from the snapshot each row captured at write
  time** — never from the user's current setting. A student who withdraws
  consent today must not retroactively remove turns that were exported under
  consent last month, and a student who grants it today must not have last
  month's unconsented turns swept in.
- **Every id is pseudonymised and every free-text field is scrubbed.** Ids are
  stable across exports (HMAC + salt), so longitudinal analysis works without
  anyone being identifiable.
- **The bundle states its own versions.** Schema and metrics versions travel
  with the data, so a number in a paper stays traceable to the definitions that
  produced it.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.turn_taking import METRICS_VERSION, compute_turn_taking, events_for_group_session
from anonymize import pseudonymize, scrub
from challenges import get_current_user, get_db
from database import (Artifact, ArtifactRevision, ContestedPair, ContestedResponse,
                      Conversation, EvalResult, GroupChallenge, GroupMember,
                      GroupSession, StudyEvent, User, VerificationAssignment,
                      VerificationResponse)

log = logging.getLogger("research_export")

router = APIRouter(prefix="/research", tags=["research"])

SCHEMA_VERSION = "1.0.0"


def _anon(user_id: str | None) -> str | None:
    return pseudonymize(user_id, "anon") if user_id else None


async def build_session_bundle(db: AsyncSession, group_session_id: str,
                               consent_only: bool = True) -> dict:
    """Assemble the de-identified bundle for one collaborative session."""
    gs = await db.get(GroupSession, group_session_id)
    if gs is None:
        raise HTTPException(status_code=404, detail="Group session not found")
    team = await db.get(GroupChallenge, gs.group_id)

    members = [
        uid for (uid,) in (await db.execute(
            select(GroupMember.user_id).where(GroupMember.group_id == gs.group_id)
        )).all()
    ]
    users = {
        u.id: u for u in (await db.execute(
            select(User).where(User.id.in_(members or [""]))
        )).scalars().all()
    }

    def ident(uid):
        """Scrub terms for this author: their own name and email."""
        u = users.get(uid)
        return (u.name if u else None, u.email if u else None)

    # ── Events ──────────────────────────────────────────────────────────────
    raw_events = (await db.execute(
        select(StudyEvent).where(StudyEvent.group_session_id == group_session_id)
        .order_by(StudyEvent.seq)
    )).scalars().all()
    events = [
        {
            "seq": e.seq,
            "actor": _anon(e.actor_user_id),
            "actor_kind": e.actor_kind,
            "role_label": e.role_label,
            "target": e.target,
            "action": e.action,
            "payload": e.payload,
            "client_ts": e.client_ts.isoformat() if e.client_ts else None,
            "server_ts": e.server_ts.isoformat() if e.server_ts else None,
            "condition": e.condition,
        }
        for e in raw_events
        if not consent_only or e.consent_research
    ]

    # ── Artifact revisions ──────────────────────────────────────────────────
    artifact = (await db.execute(
        select(Artifact).where(Artifact.group_session_id == group_session_id)
    )).scalar_one_or_none()
    revisions = []
    if artifact is not None:
        rows = (await db.execute(
            select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact.id)
            .order_by(ArtifactRevision.created_at, ArtifactRevision.section_key,
                      ArtifactRevision.version)
        )).scalars().all()
        for r in rows:
            if consent_only and not r.consent_research:
                continue
            name, email = ident(r.author_user_id)
            revisions.append({
                "section_key": r.section_key,
                "version": r.version,
                "author": _anon(r.author_user_id),
                "origin": r.origin,
                "bytes_added": r.bytes_added,
                "bytes_removed": r.bytes_removed,
                "content": scrub(r.content, name, email),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

    # ── Evaluations, across every member's private coach conversation ───────
    convs = (await db.execute(
        select(Conversation).where(Conversation.group_session_id == group_session_id)
    )).scalars().all()
    evaluations = []
    for conv in convs:
        rows = (await db.execute(
            select(EvalResult).where(EvalResult.conversation_id == conv.id)
            .order_by(EvalResult.turn_number)
        )).scalars().all()
        for ev in rows:
            if consent_only and not ev.consent_research:
                continue
            evaluations.append({
                "conversation": pseudonymize(conv.id, "conv"),
                "conversation_kind": conv.kind,
                "owner": _anon(conv.user_id),
                "turn": ev.turn_number,
                "pei": ev.pei, "psq": ev.psq, "ccm": ev.ccm,
                "tsi": ev.tsi, "clm": ev.clm, "ras": ev.ras,
                "grounding": ev.grounding,
                "classification": ev.classification,
                "leading_status": ev.leading_status,
                "is_graded_revision": bool(ev.is_graded_revision),
            })

    # ── Verification ────────────────────────────────────────────────────────
    from verification import outcomes_for_session

    verification_rows = []
    responded_consent = {
        r.assignment_id: r.consent_research
        for r in (await db.execute(
            select(VerificationResponse).join(
                VerificationAssignment,
                VerificationAssignment.id == VerificationResponse.assignment_id,
            ).where(VerificationAssignment.group_session_id == group_session_id)
        )).scalars().all()
    }
    for row in await outcomes_for_session(db, group_session_id):
        # An assignment with no response has no consent snapshot of its own;
        # it carries no student-authored content, only the routing fact.
        if consent_only and row["assignment_id"] in responded_consent \
                and not responded_consent[row["assignment_id"]]:
            continue
        verification_rows.append({
            **{k: v for k, v in row.items() if k != "assignment_id"},
            "author": _anon(row["author_user_id"]),
            "reviewer": _anon(row["reviewer_user_id"]),
            "author_user_id": None, "reviewer_user_id": None,
        })

    # ── Contested input ─────────────────────────────────────────────────────
    pairs = (await db.execute(
        select(ContestedPair).where(ContestedPair.group_session_id == group_session_id)
    )).scalars().all()
    responses = {
        r.pair_id: r for r in (await db.execute(
            select(ContestedResponse).where(
                ContestedResponse.pair_id.in_([p.id for p in pairs] or [""])
            )
        )).scalars().all()
    }
    contested_rows = []
    for p in pairs:
        r = responses.get(p.id)
        if consent_only and r is not None and not r.consent_research:
            continue
        name, email = ident(p.surfaced_to_user_id)
        contested_rows.append({
            "subproblem_key": p.subproblem_key,
            "origin": p.origin,
            "surfaced_to": _anon(p.surfaced_to_user_id),
            "better_option": p.better_option,
            "adopted": r.adopted if r else None,
            "inspected_a": bool(r.inspected_a) if r else None,
            "inspected_b": bool(r.inspected_b) if r else None,
            "uninspected_adoption": bool(r) and not (r.inspected_a or r.inspected_b),
            "rationale": scrub(r.rationale_text, name, email) if r else None,
        })

    # ── Metrics, computed from the FULL log ─────────────────────────────────
    # Deliberately not from the consent-filtered subset: a contribution share
    # computed over a subset of a team is not that team's contribution share,
    # and publishing one would be wrong in a way no reader could detect. The
    # metrics describe the session; the exported rows are what may be shared.
    metrics = compute_turn_taking(
        await events_for_group_session(db, group_session_id), members
    )
    metrics["actors"] = [_anon(a) for a in metrics["actors"]]
    for key in ("contribution_share", "writes_by_user", "coach_turns_by_user"):
        metrics[key] = {_anon(k): v for k, v in metrics[key].items()}

    return {
        "schema_version": SCHEMA_VERSION,
        "metrics_version": METRICS_VERSION,
        "session": {
            "id": pseudonymize(group_session_id, "sess"),
            "session_number": gs.session_number,
            "status": gs.status,
            "started_at": gs.started_at.isoformat() if gs.started_at else None,
            "completed_at": gs.completed_at.isoformat() if gs.completed_at else None,
            "end_reason": gs.end_reason,
            "team": pseudonymize(gs.group_id, "team"),
            "classroom": pseudonymize(team.classroom_id, "room") if team and team.classroom_id else None,
        },
        "consent_filtered": consent_only,
        "members": [_anon(m) for m in members],
        "events": events,
        "artifact_revisions": revisions,
        "evaluations": evaluations,
        "verification": verification_rows,
        "contested": contested_rows,
        "turn_taking": metrics,
    }


@router.get("/sessions/{group_session_id}/export")
async def export_session(
    group_session_id: str,
    fmt: str = Query("json", alias="format", pattern="^(json|jsonl)$"),
    include_unconsented: bool = Query(False),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """De-identified bundle for one session. Instructor and admin only.

    `include_unconsented` exists for an instructor reviewing their own section's
    activity, not for research use — it is off by default and the bundle records
    which mode produced it in `consent_filtered`, so an archived file cannot be
    mistaken for a consented one.
    """
    from main import _assert_can_read_research

    gs = await db.get(GroupSession, group_session_id)
    if gs is None:
        raise HTTPException(status_code=404, detail="Group session not found")
    team = await db.get(GroupChallenge, gs.group_id)
    await _assert_can_read_research(db, user_id, team.classroom_id if team else None)

    bundle = await build_session_bundle(db, group_session_id,
                                        consent_only=not include_unconsented)
    if fmt == "json":
        return bundle

    # JSONL: one object per line, each tagged with its kind, for streaming into
    # analysis tools without loading the whole bundle.
    lines = [json.dumps({"kind": "meta", **{k: v for k, v in bundle.items()
                                            if not isinstance(v, list)}})]
    for kind in ("events", "artifact_revisions", "evaluations", "verification", "contested"):
        for row in bundle[kind]:
            lines.append(json.dumps({"kind": kind, **row}))
    return PlainTextResponse("\n".join(lines), media_type="application/x-ndjson")
