"""Team submissions: what a team hands in when a group session ends.

When a session ends, by whatever path (a member pressing End, the timer, the
lazy expiry check), record_submission freezes the team's shared document as it
stood, together with the AI's team score. The instructor sees every team's
submission for an assignment side by side, opens the document, downloads it as
a PDF, and can set their own score and feedback. The AI score is kept beside
the instructor's, never overwritten; the score that counts is the instructor's
when set, else the AI's.

Also home to the team-score definition (coach_session_summary), which main.py
uses for the end-of-session frame, so a submission's AI score and the figure
students saw at the end can never disagree.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import artifacts
from challenges import _assert_user_manages_classroom, _session_feed_enabled, get_current_user, get_db
from database import (
    Artifact,
    ArtifactRevision,
    Challenge,
    Conversation,
    EvalResult,
    GroupChallenge,
    GroupMember,
    GroupSession,
    TeamSubmission,
    User,
)
from groups import _members_payload, _teams_for
from pdf_render import pdf_safe, pei_rgb, render_document_body

log = logging.getLogger("submissions")

# Student-facing: a team member reads their own team's submission.
router = APIRouter(prefix="/groups", tags=["submissions"])
# Instructor-facing: every team's submission for an assignment in a section.
team_router = APIRouter(prefix="/classrooms", tags=["submissions"])

MAX_FEEDBACK_CHARS = 5000


# ---------------------------------------------------------------------------
# Team score
# ---------------------------------------------------------------------------

async def coach_session_summary(db, gs, private_conversations: list) -> tuple[dict, float | None]:
    """The end-of-session figures for the private-coach arm, and the unrounded
    team mean. Read-only, so the ender, every teammate's session_ended frame
    and a tab reopening a finished session all see the same numbers.

    The team score is an EQUAL-WEIGHT mean: the average of each student's own
    average PEI, so every student counts once no matter how many turns they
    took. The earlier placeholder pooled every turn (sum of all turns / turn
    count), which let the most active student dominate — a student with 20 turns
    outweighed a teammate with 3. It is returned with the range (min/max of the
    per-student averages) so a single number can never hide a split team, and
    each student's own average is still exposed in `per_student`. See
    docs/metrics-codebook.md ("Team PEI") for the definition.
    """
    per_student: dict[str, dict] = {}
    student_means: list[float] = []  # one value per student, unrounded — equal weight
    total_turns = 0
    user_ids = [c.user_id for c in private_conversations]
    names = {}
    if user_ids:
        names = {u.id: u.name for u in (await db.execute(
            select(User).where(User.id.in_(user_ids))
        )).scalars().all()}

    for conv in private_conversations:
        peis = (await db.execute(
            select(EvalResult.pei).where(
                EvalResult.conversation_id == conv.id, EvalResult.pei.is_not(None)
            )
        )).scalars().all()
        if peis:
            student_means.append(sum(float(p) for p in peis) / len(peis))
        total_turns += len(peis)
        per_student[conv.user_id] = {
            "avg_pei": round(sum(peis) / len(peis), 1) if peis else None,
            "turns": len(peis),
            # Teammates may be offline when the frame arrives, so the client
            # cannot always name them from presence.
            "name": names.get(conv.user_id),
        }

    # Equal-weight mean of the per-student averages (not of raw turns), plus the
    # spread. A student with no scored turn has no average and is simply not
    # counted — they do not drag the team mean toward zero.
    team_mean = round(sum(student_means) / len(student_means), 2) if student_means else None
    pei_range = (
        {"min": round(min(student_means), 1), "max": round(max(student_means), 1)}
        if student_means else None
    )
    return {
        "arm": "collab_coach_artifact",
        "session_avg_pei": round(team_mean, 1) if team_mean is not None else None,
        "pei_range": pei_range,
        "turns": total_turns,
        "per_student": per_student,
        "analysis_status": None,
        "end_reason": gs.end_reason,
    }, team_mean


async def private_coach_conversations(db, group_session_id: str) -> list:
    return (await db.execute(
        select(Conversation).where(
            Conversation.group_session_id == group_session_id,
            Conversation.kind == "coach_private",
        )
    )).scalars().all()


async def team_score(db, gs: GroupSession) -> tuple[float | None, dict | None, dict | None]:
    """(team PEI, its range, per-student averages) for a session. The private-
    coach arm uses the equal-weight mean above; a legacy shared-chat session
    only has the pooled figure stored on the session, and no per-student split."""
    private = await private_coach_conversations(db, gs.id)
    if private:
        summary, _ = await coach_session_summary(db, gs, private)
        return summary["session_avg_pei"], summary["pei_range"], summary["per_student"]
    avg = round(float(gs.session_avg_pei), 1) if gs.session_avg_pei is not None else None
    return avg, None, None


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

async def _find(db, group_session_id: str) -> TeamSubmission | None:
    return (await db.execute(
        select(TeamSubmission).where(TeamSubmission.group_session_id == group_session_id)
    )).scalar_one_or_none()


async def record_submission(db, gs: GroupSession) -> TeamSubmission | None:
    """Freeze this session's document and AI score as the team's submission.

    Idempotent: a session has at most one submission, and a second call (the
    timer firing on another teammate's socket, a backfill on read) returns the
    first. Only an ended session is recorded — before the end the document is
    still being written. Commits on `db`."""
    if gs.status != "completed":
        return None
    existing = await _find(db, gs.id)
    if existing is not None:
        return existing

    snap = await artifacts.snapshot(gs.id)
    sections = [
        {"key": s["key"], "title": s["title"], "content": s["content"],
         "updated_by_user_id": s["updated_by_user_id"]}
        for s in (snap or {}).get("sections", [])
    ]
    ai, ai_range, per_student = await team_score(db, gs)
    sub = TeamSubmission(
        group_session_id=gs.id, group_id=gs.group_id, challenge_id=gs.challenge_id,
        session_number=gs.session_number, sections=sections,
        ai_score=ai, ai_score_range=ai_range, per_student=per_student,
        submitted_at=gs.completed_at or datetime.utcnow(),
    )
    db.add(sub)
    try:
        await db.commit()
    except IntegrityError:
        # A teammate's end path recorded it between our check and our insert.
        await db.rollback()
        return await _find(db, gs.id)
    return sub


def final_score(sub: TeamSubmission) -> float | None:
    return sub.instructor_score if sub.instructor_score is not None else sub.ai_score


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

def _session_title(ch: Challenge | None, n: int) -> str | None:
    try:
        return (ch.sessions_data or [])[n - 1].get("title") or None
    except (IndexError, AttributeError, TypeError):
        return None


async def _names(db, ids) -> dict[str, str]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return {u.id: u.name for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()}


async def _section_writers(db, group_session_id: str) -> dict[str, list[str]]:
    """Section key -> everyone who saved text into it, in order of first save.
    Read from the revision history, so a section two students wrote shows both,
    not just whoever saved last."""
    artifact_id = (await db.execute(
        select(Artifact.id).where(Artifact.group_session_id == group_session_id)
    )).scalar_one_or_none()
    if artifact_id is None:
        return {}
    rows = (await db.execute(
        select(ArtifactRevision.section_key, ArtifactRevision.author_user_id)
        .where(ArtifactRevision.artifact_id == artifact_id)
        .order_by(ArtifactRevision.created_at, ArtifactRevision.id)
    )).all()
    out: dict[str, list[str]] = {}
    for key, uid in rows:
        seen = out.setdefault(key, [])
        if uid not in seen:
            seen.append(uid)
    return out


async def _team_label(db, team: GroupChallenge) -> str:
    """The team's name, or "Team N" by creation order — the same fallback the
    instructor's team manager shows."""
    if team.name:
        return team.name
    if team.classroom_id:
        teams = await _teams_for(db, team.classroom_id, team.challenge_id)
        for i, t in enumerate(teams, start=1):
            if t.id == team.id:
                return f"Team {i}"
    return "Team"


def _summary(sub: TeamSubmission, grader_names: dict[str, str]) -> dict:
    words = sum(len((s.get("content") or "").split()) for s in (sub.sections or []))
    return {
        "id": sub.id,
        "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
        "ai_score": sub.ai_score,
        "ai_score_range": sub.ai_score_range,
        "instructor_score": sub.instructor_score,
        "final_score": final_score(sub),
        "graded": sub.graded_at is not None,
        "graded_at": sub.graded_at.isoformat() if sub.graded_at else None,
        "graded_by_name": grader_names.get(sub.graded_by_user_id),
        "has_feedback": bool(sub.instructor_feedback),
        "word_count": words,
    }


async def _detail(db, sub: TeamSubmission, *, for_instructor: bool, viewer_id: str | None = None) -> dict:
    """Everything needed to show or print one submission. A student gets the
    team's score and their own average, never a teammate's (as on the progress
    page), and no AI score at all for a session run with the score feed off."""
    gs = await db.get(GroupSession, sub.group_session_id)
    team = await db.get(GroupChallenge, sub.group_id)
    ch = await db.get(Challenge, sub.challenge_id)
    members = await _members_payload(db, sub.group_id)
    writers = await _section_writers(db, sub.group_session_id)
    per_student = sub.per_student or {}
    names = await _names(db, [m["user_id"] for m in members]
                         + [uid for ws in writers.values() for uid in ws]
                         + list(per_student) + [sub.graded_by_user_id])

    scores_hidden = not for_instructor and not _session_feed_enabled(ch, sub.session_number)
    out = {
        **_summary(sub, names),
        "group_session_id": sub.group_session_id,
        "team_id": sub.group_id,
        "team_name": await _team_label(db, team) if team else "Team",
        "members": [m["name"] for m in members],
        "challenge_title": ch.title if ch else "Challenge",
        "session_number": sub.session_number,
        "session_title": _session_title(ch, sub.session_number),
        "end_reason": gs.end_reason if gs else None,
        "instructor_feedback": sub.instructor_feedback,
        "scores_hidden": scores_hidden,
        "sections": [
            {"key": s.get("key"), "title": s.get("title"), "content": s.get("content") or "",
             "writers": [names.get(uid, "Former member") for uid in writers.get(s.get("key"), [])]}
            for s in (sub.sections or [])
        ],
    }
    if for_instructor:
        out["per_student"] = sorted(
            ({"user_id": uid, "name": v.get("name") or names.get(uid, "Former member"),
              "avg_pei": v.get("avg_pei"), "turns": v.get("turns", 0)}
             for uid, v in per_student.items()),
            key=lambda p: p["name"] or "",
        )
    else:
        mine = per_student.get(viewer_id) or {}
        out["my_pei"] = mine.get("avg_pei")
    if scores_hidden:
        out.update(ai_score=None, ai_score_range=None, my_pei=None)
        # With the feed off the final score is the instructor's or nothing.
        out["final_score"] = sub.instructor_score
    return out


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _fmt(v) -> str:
    return "-" if v is None else f"{round(float(v), 1):g}"


def render_submission_pdf(d: dict) -> bytes:
    """One team's submission as a printable document: who, which session, the
    scores, the instructor's feedback, then the document itself section by
    section with who wrote each part."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    footer_text = pdf_safe(f"{d['team_name']}  -  {d['challenge_title']}, session {d['session_number']}")

    class PDF(FPDF):
        def footer(self):
            self.set_y(-14)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(160, 160, 160)
            self.cell(0, 8, f"{footer_text}   -   page {self.page_no()}", align="C")

    pdf = PDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()
    nl = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(200, 16, 46)
    pdf.cell(0, 5, "HUSKYAI  -  TEAM SUBMISSION", **nl)
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 19)
    pdf.set_text_color(22, 18, 14)
    pdf.multi_cell(0, 9, pdf_safe(d["challenge_title"]), **nl)
    sub = f"Session {d['session_number']}" + (f": {d['session_title']}" if d.get("session_title") else "")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 6, pdf_safe(sub), **nl)
    pdf.ln(3)

    def row(label: str, value: str):
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(30, 5.5, label, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 5.5, pdf_safe(value), **nl)

    row("Team", d["team_name"])
    row("Members", ", ".join(d["members"]) or "-")
    if d.get("submitted_at"):
        ended = {"timer_expired": " (time ran out)", "manual": " (ended by the team)",
                 "team_ready": " (the whole team marked it ready)"}.get(d.get("end_reason"), "")
        row("Submitted", datetime.fromisoformat(d["submitted_at"]).strftime("%Y-%m-%d %H:%M UTC") + ended)
    pdf.ln(3)

    # Scores
    pdf.set_fill_color(247, 243, 238)
    top = pdf.get_y()
    pdf.rect(pdf.l_margin, top, pdf.epw, 20, style="F")
    cols = []
    if not d.get("scores_hidden"):
        rng = d.get("ai_score_range")
        cols.append(("AI team score (PEI)", _fmt(d.get("ai_score")),
                     f"members {_fmt(rng['min'])}-{_fmt(rng['max'])}" if rng else "", d.get("ai_score")))
    cols.append(("Instructor score", _fmt(d.get("instructor_score")),
                 "not graded yet" if d.get("instructor_score") is None else
                 (f"by {d['graded_by_name']}" if d.get("graded_by_name") else ""), d.get("instructor_score")))
    cols.append(("Final score", _fmt(d.get("final_score")),
                 "instructor's" if d.get("instructor_score") is not None else
                 ("AI's" if d.get("final_score") is not None else ""), d.get("final_score")))
    w = pdf.epw / len(cols)
    for i, (label, value, note, raw) in enumerate(cols):
        x = pdf.l_margin + i * w + 4
        pdf.set_xy(x, top + 2.5)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(120, 115, 110)
        pdf.cell(w - 8, 4, label.upper())
        pdf.set_xy(x, top + 7)
        pdf.set_font("Helvetica", "B", 15)
        pdf.set_text_color(*pei_rgb(raw))
        pdf.cell(w - 8, 7, value)
        pdf.set_xy(x, top + 14)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(120, 115, 110)
        pdf.cell(w - 8, 4, pdf_safe(note))
    pdf.set_xy(pdf.l_margin, top + 24)

    if d.get("per_student"):
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 5.5, "Each member's own average", **nl)
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(30, 30, 30)
        for p in d["per_student"]:
            t = p.get("turns") or 0
            pdf.cell(0, 5, pdf_safe(f"{p['name']}: PEI {_fmt(p.get('avg_pei'))} over {t} turn{'' if t == 1 else 's'}"), **nl)
        pdf.ln(2)

    if d.get("instructor_feedback"):
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 5.5, "Instructor feedback", **nl)
        render_document_body(pdf, d["instructor_feedback"])
        pdf.ln(1)

    pdf.set_draw_color(220, 214, 206)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pdf.epw, pdf.get_y())
    pdf.ln(5)

    sections = d.get("sections") or []
    if not any((s.get("content") or "").strip() for s in sections):
        pdf.set_font("Helvetica", "I", 10.5)
        pdf.set_text_color(120, 115, 110)
        pdf.multi_cell(0, 5.5, "The team's shared document was empty when the session ended.", **nl)
    for s in sections:
        if s.get("title"):
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(22, 18, 14)
            pdf.multi_cell(0, 7, pdf_safe(s["title"]), **nl)
        if s.get("writers"):
            pdf.set_font("Helvetica", "I", 8.5)
            pdf.set_text_color(130, 125, 120)
            pdf.multi_cell(0, 4.5, pdf_safe("Written by " + ", ".join(s["writers"])), **nl)
        pdf.ln(1.5)
        if (s.get("content") or "").strip():
            render_document_body(pdf, s["content"])
        else:
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(150, 145, 140)
            pdf.cell(0, 5.5, "(left blank)", **nl)
        pdf.ln(4)

    return bytes(pdf.output())


def _pdf_filename(d: dict) -> str:
    raw = f"{d['team_name']} {d['challenge_title']} session {d['session_number']}"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in raw).strip().replace(" ", "_")[:80]
    return f"{safe or 'submission'}.pdf"


def _pdf_response(d: dict) -> Response:
    return Response(
        content=render_submission_pdf(d),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_pdf_filename(d)}"'},
    )


# ---------------------------------------------------------------------------
# Student endpoints
# ---------------------------------------------------------------------------

async def _my_submission(db, group_id: str, session_num: int, user_id: str) -> TeamSubmission:
    member = (await db.execute(
        select(GroupMember.id).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=403, detail="You are not a member of this group")
    gs = (await db.execute(
        select(GroupSession).where(GroupSession.group_id == group_id,
                                   GroupSession.session_number == session_num)
    )).scalar_one_or_none()
    if gs is None:
        raise HTTPException(status_code=404, detail="Group session not found")
    if gs.status != "completed":
        raise HTTPException(status_code=409, detail="The session has not ended yet, so nothing has been submitted")
    sub = await record_submission(db, gs)
    if sub is None:
        raise HTTPException(status_code=404, detail="No submission for this session")
    return sub


@router.get("/{group_id}/sessions/{session_num}/submission")
async def get_my_submission(
    group_id: str,
    session_num: int,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The team's submitted document for an ended session, with its scores and
    any instructor feedback."""
    sub = await _my_submission(db, group_id, session_num, user_id)
    return await _detail(db, sub, for_instructor=False, viewer_id=user_id)


@router.get("/{group_id}/sessions/{session_num}/submission/pdf")
async def get_my_submission_pdf(
    group_id: str,
    session_num: int,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = await _my_submission(db, group_id, session_num, user_id)
    return _pdf_response(await _detail(db, sub, for_instructor=False, viewer_id=user_id))


# ---------------------------------------------------------------------------
# Instructor endpoints
# ---------------------------------------------------------------------------

async def _submission_in(db, classroom_id: str, challenge_id: str, submission_id: str) -> TeamSubmission:
    sub = await db.get(TeamSubmission, submission_id)
    team = await db.get(GroupChallenge, sub.group_id) if sub else None
    if sub is None or team is None or sub.challenge_id != challenge_id or team.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Submission not found in this section/challenge")
    return sub


@team_router.get("/{classroom_id}/challenges/{challenge_id}/submissions")
async def list_submissions(
    classroom_id: str,
    challenge_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: every team on this assignment, one cell per session — not
    started, in progress, or submitted (with AI, instructor and final score).
    A session that ended before submissions existed is recorded on first view."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    ch = await db.get(Challenge, challenge_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Challenge not found")
    total = max(ch.total_sessions or 1, 1)
    teams = await _teams_for(db, classroom_id, challenge_id)

    by_team: dict[str, dict[int, GroupSession]] = {}
    if teams:
        for gs in (await db.execute(
            select(GroupSession).where(GroupSession.group_id.in_([t.id for t in teams]))
        )).scalars().all():
            by_team.setdefault(gs.group_id, {})[gs.session_number] = gs

    subs: dict[str, TeamSubmission] = {}
    for sessions in by_team.values():
        for gs in sessions.values():
            if gs.status == "completed":
                sub = await record_submission(db, gs)
                if sub is not None:
                    subs[gs.id] = sub
    graders = await _names(db, [s.graded_by_user_id for s in subs.values()])

    out_teams = []
    for idx, t in enumerate(teams, start=1):
        cells = []
        for n in range(1, total + 1):
            gs = by_team.get(t.id, {}).get(n)
            sub = subs.get(gs.id) if gs else None
            if sub is not None:
                status = "graded" if sub.graded_at else "submitted"
            elif gs is not None and gs.started_at is not None:
                status = "in_progress"
            else:
                status = "not_started"
            cells.append({"session_number": n, "status": status,
                          "submission": _summary(sub, graders) if sub else None})
        out_teams.append({
            "id": t.id,
            "name": t.name or f"Team {idx}",
            "members": [m["name"] for m in await _members_payload(db, t.id)],
            "sessions": cells,
        })

    all_subs = list(subs.values())
    return {
        "challenge": {"id": ch.id, "title": ch.title, "total_sessions": total,
                      "sessions": [{"session_number": n, "title": _session_title(ch, n)}
                                   for n in range(1, total + 1)]},
        "teams": out_teams,
        "counts": {"teams": len(teams), "submitted": len(all_subs),
                   "graded": sum(1 for s in all_subs if s.graded_at)},
    }


@team_router.get("/{classroom_id}/challenges/{challenge_id}/submissions/{submission_id}")
async def get_submission(
    classroom_id: str,
    challenge_id: str,
    submission_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    sub = await _submission_in(db, classroom_id, challenge_id, submission_id)
    return await _detail(db, sub, for_instructor=True)


class GradeBody(BaseModel):
    # None clears the override, so the AI score counts again.
    score: float | None = Field(None, ge=0, le=100)
    feedback: str | None = Field(None, max_length=MAX_FEEDBACK_CHARS)


@team_router.put("/{classroom_id}/challenges/{challenge_id}/submissions/{submission_id}/grade")
async def grade_submission(
    classroom_id: str,
    challenge_id: str,
    submission_id: str,
    body: GradeBody,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: set (or clear) the score that replaces the AI's, and the
    feedback the team sees. Clearing both returns the submission to ungraded."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    sub = await _submission_in(db, classroom_id, challenge_id, submission_id)
    feedback = (body.feedback or "").strip() or None
    sub.instructor_score = round(body.score, 1) if body.score is not None else None
    sub.instructor_feedback = feedback
    if sub.instructor_score is None and feedback is None:
        sub.graded_at = sub.graded_by_user_id = None
    else:
        sub.graded_at = datetime.utcnow()
        sub.graded_by_user_id = user_id
    await db.commit()
    return await _detail(db, sub, for_instructor=True)


@team_router.get("/{classroom_id}/challenges/{challenge_id}/submissions/{submission_id}/pdf")
async def get_submission_pdf(
    classroom_id: str,
    challenge_id: str,
    submission_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    sub = await _submission_in(db, classroom_id, challenge_id, submission_id)
    return _pdf_response(await _detail(db, sub, for_instructor=True))


@team_router.get("/{classroom_id}/challenges/{challenge_id}/submissions-zip")
async def download_all_submissions(
    classroom_id: str,
    challenge_id: str,
    session: int | None = None,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Instructor: every submitted PDF for the assignment (or one session of
    it) in one zip, one file per team and session."""
    await _assert_user_manages_classroom(db, user_id, classroom_id)
    team_ids = [t.id for t in await _teams_for(db, classroom_id, challenge_id)]
    q = select(TeamSubmission).where(TeamSubmission.challenge_id == challenge_id,
                                     TeamSubmission.group_id.in_(team_ids))
    if session is not None:
        q = q.where(TeamSubmission.session_number == session)
    subs = (await db.execute(q.order_by(TeamSubmission.session_number))).scalars().all() if team_ids else []
    if not subs:
        raise HTTPException(status_code=404, detail="No submissions yet")

    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in subs:
            d = await _detail(db, sub, for_instructor=True)
            name = _pdf_filename(d)
            while name in used:
                name = name[:-4] + "_.pdf"
            used.add(name)
            zf.writestr(name, render_submission_pdf(d))
    ch = await db.get(Challenge, challenge_id)
    label = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (ch.title if ch else "submissions"))
    label = label.strip().replace(" ", "_")[:60] or "submissions"
    suffix = f"_session{session}" if session is not None else ""
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{label}{suffix}_submissions.zip"'},
    )
