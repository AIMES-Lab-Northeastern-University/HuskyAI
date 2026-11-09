"""The final review: finishing a team session is a step, not a button.

A member asks to finish, everyone sees the whole document, and each member who
took part marks it ready. The last one to do so ends the session and submits
the document. An edit during review withdraws every ready mark, because they
approved text that has since changed.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from test_collab_visibility import _coach_turn, _h, _section_with_team, _token, _until, app_ready, stub_model  # noqa: F401

SECTIONS = [
    {"key": "answer", "title": "Recommendation", "prompt": "State your pick and two reasons.", "target_words": 150},
    {"key": "risks", "title": "Risks", "prompt": ""},
]


async def _with_sections(ch_id):
    from database import AsyncSessionLocal, Challenge
    async with AsyncSessionLocal() as db:
        ch = await db.get(Challenge, ch_id)
        ch.sessions_data = [{**ch.sessions_data[0], "artifact_sections": SECTIONS}]
        await db.commit()


@pytest.fixture
def team(app_ready, stub_model):
    """Three students; two take a coach turn, the third never opens the session."""
    room, ch, team_id, inst, students = asyncio.run(_section_with_team(3))
    asyncio.run(_with_sections(ch))
    client = TestClient(app_ready)
    _coach_turn(client, team_id, students[0])
    _coach_turn(client, team_id, students[1])
    return client, room, ch, team_id, inst, students


def _ready(client, team_id, uid, ready=True):
    r = client.post(f"/groups/{team_id}/sessions/1/ready", json={"ready": ready}, headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()


def test_students_get_each_sections_brief_and_target(team):
    client, room, ch, team_id, inst, students = team
    with client.websocket_connect(f"/ws/coach?token={_token(students[0])}&group_id={team_id}&session_num=1") as ws:
        init = _until(ws, {"session_init"})
        assert init["review"]["started_at"] is None
        guides = _until(ws, {"section_guides"})["data"]
    assert guides["answer"] == {"prompt": "State your pick and two reasons.", "target_words": 150}
    assert guides["risks"] == {"prompt": None, "target_words": None}


def test_the_session_ends_once_everyone_who_took_part_is_ready(team):
    client, room, ch, team_id, inst, students = team
    r = client.post(f"/groups/{team_id}/sessions/1/review", headers=_h(students[0]))
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["started_at"] is not None
    # The member who never opened the session does not hold the team up.
    assert {m["user_id"] for m in state["required"]} == set(students[:2])

    state = _ready(client, team_id, students[0])
    assert state["ready_user_ids"] == [students[0]] and not state.get("ended")

    done = _ready(client, team_id, students[1])
    assert done["ended"] and done["summary"]["end_reason"] == "team_ready"

    sub = client.get(f"/groups/{team_id}/sessions/1/submission", headers=_h(students[2])).json()
    assert sub["end_reason"] == "team_ready"
    # Ended means ended: no more review changes.
    r = client.post(f"/groups/{team_id}/sessions/1/ready", json={"ready": False}, headers=_h(students[0]))
    assert r.status_code == 409


def test_unmarking_ready_withdraws_it(team):
    client, room, ch, team_id, inst, students = team
    _ready(client, team_id, students[0])
    assert _ready(client, team_id, students[0], ready=False)["ready_user_ids"] == []


def test_an_edit_during_review_withdraws_every_ready_mark(team):
    client, room, ch, team_id, inst, students = team
    _ready(client, team_id, students[0])
    with client.websocket_connect(f"/ws/coach?token={_token(students[1])}&group_id={team_id}&session_num=1") as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_write", "section_key": "answer",
                                 "content": "Option 1, because it is cheaper.", "expected_version": 0}))
        _until(ws, {"artifact_write_ok"})
        reset = _until(ws, {"review_state"})
    assert reset["ready_user_ids"] == []
    assert reset["reset_by_name"] == "Stu1" and reset["reset_section"] == "answer"


def test_the_review_screen_is_logged_as_a_read(team):
    client, room, ch, team_id, inst, students = team
    with client.websocket_connect(f"/ws/coach?token={_token(students[0])}&group_id={team_id}&session_num=1") as ws:
        _until(ws, {"artifact"})
        ws.send_text(json.dumps({"type": "artifact_expand", "section_key": "answer",
                                 "via": "review", "event_id": "rv-1"}))
        _until(ws, {"read_ack"})

    async def payloads():
        from database import AsyncSessionLocal, StudyEvent
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            return [e.payload for e in (await db.execute(
                select(StudyEvent).where(StudyEvent.actor_user_id == students[0],
                                         StudyEvent.action == "section_expand"))).scalars().all()]
    assert {"section_key": "answer", "via": "review"} in asyncio.run(payloads())


def test_only_team_members_can_review(team):
    client, room, ch, team_id, inst, students = team
    r = client.post(f"/groups/{team_id}/sessions/1/review", headers=_h(inst))
    assert r.status_code == 403


def test_an_instructor_saves_each_sections_brief_and_target(team):
    client, room, ch, team_id, inst, students = team
    body = {"sections": [
        {"key": "answer", "title": "Recommendation", "prompt": "Pick one.", "target_words": 120},
        {"key": "risks", "title": "Risks", "prompt": ""},
    ]}
    r = client.patch(f"/challenges/{ch}", json=body, headers=_h(inst))
    assert r.status_code == 200, r.text
    got = client.get(f"/challenges/{ch}", headers=_h(inst)).json()["sections"]
    assert got[0]["target_words"] == 120 and "target_words" not in got[1]

    bad = {"sections": [{"key": "a", "title": "A", "target_words": 3}]}
    assert client.patch(f"/challenges/{ch}", json=bad, headers=_h(inst)).status_code == 422


def test_the_full_document_view_is_logged_as_a_read_and_other_vias_are_dropped(team):
    client, room, ch, team_id, inst, students = team
    with client.websocket_connect(f"/ws/coach?token={_token(students[1])}&group_id={team_id}&session_num=1") as ws:
        _until(ws, {"artifact"})
        for i, via in enumerate(("document", "made-up")):
            ws.send_text(json.dumps({"type": "artifact_expand", "section_key": "answer",
                                     "via": via, "event_id": f"dv-{i}"}))
            _until(ws, {"read_ack"})

    async def payloads():
        from database import AsyncSessionLocal, StudyEvent
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            return [e.payload for e in (await db.execute(
                select(StudyEvent).where(StudyEvent.actor_user_id == students[1],
                                         StudyEvent.action == "section_expand"))).scalars().all()]
    got = asyncio.run(payloads())
    assert {"section_key": "answer", "via": "document"} in got
    # An unknown via is recorded as a plain read, never stored as given.
    assert {"section_key": "answer"} in got


# --- Ending, submitting and editing must not race ----------------------------

async def _group_session(team_id):
    from database import AsyncSessionLocal, GroupSession
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(GroupSession).where(GroupSession.group_id == team_id))).scalar_one()


async def _ready_marks(gs_id):
    from database import AsyncSessionLocal, ReviewReadyMark
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        return set((await db.execute(select(ReviewReadyMark.user_id).where(
            ReviewReadyMark.group_session_id == gs_id))).scalars().all())


def test_marking_ready_twice_is_harmless(team):
    client, room, ch, team_id, inst, students = team
    _ready(client, team_id, students[0])
    # A double click, a second tab or a retried request: same answer, not a 500.
    assert _ready(client, team_id, students[0])["ready_user_ids"] == [students[0]]


def test_a_failed_hand_in_still_ends_the_session_and_tells_the_team(team, monkeypatch):
    client, room, ch, team_id, inst, students = team
    import main

    async def boom(db, gs):
        raise RuntimeError("snapshot failed")

    told = []
    real_notify = main._notify_session_ended

    async def spy(*a, **kw):
        told.append(a)
        return await real_notify(*a, **kw)

    monkeypatch.setattr(main, "record_submission", boom)
    monkeypatch.setattr(main, "_notify_session_ended", spy)
    r = client.post(f"/groups/{team_id}/sessions/1/end", headers=_h(students[0]))
    assert r.status_code == 200, r.text
    assert len(told) == 1
    assert asyncio.run(_group_session(team_id)).status == "completed"


def test_a_submission_recorded_by_a_teammate_mid_insert_is_returned(team, monkeypatch):
    client, room, ch, team_id, inst, students = team
    assert client.post(f"/groups/{team_id}/sessions/1/end", headers=_h(students[0])).status_code == 200
    import submissions
    from database import AsyncSessionLocal

    real_find = submissions._find
    calls = []

    async def first_miss(db, gs_id):
        calls.append(gs_id)
        return None if len(calls) == 1 else await real_find(db, gs_id)

    monkeypatch.setattr(submissions, "_find", first_miss)

    from database import GroupSession
    gs_id = asyncio.run(_group_session(team_id)).id

    async def go():
        async with AsyncSessionLocal() as db:
            gs = await db.get(GroupSession, gs_id)
            sub = await submissions.record_submission(db, gs)
            # The insert lost to the existing row; both the submission and the
            # session (expired by the rollback) must still be readable.
            return sub.group_session_id, gs.status
    assert asyncio.run(go()) == (gs_id, "completed")


def test_a_write_cannot_land_after_the_session_ends(team):
    client, room, ch, team_id, inst, students = team
    assert client.post(f"/groups/{team_id}/sessions/1/end", headers=_h(students[0])).status_code == 200
    import artifacts
    gs = asyncio.run(_group_session(team_id))
    # Straight to the write, past the socket's own ended check: the write
    # itself must refuse, or text can land after the snapshot was taken.
    res = asyncio.run(artifacts.write_section(
        group_session_id=gs.id, section_key="answer", content="too late",
        author_user_id=students[0], expected_version=0))
    assert res == {"ok": False, "error": "session_ended",
                   "message": "This session has ended, so the document can no longer be changed."}
    sub = client.get(f"/groups/{team_id}/sessions/1/submission", headers=_h(students[0])).json()
    assert "too late" not in json.dumps(sub)


def test_a_write_withdraws_ready_marks_in_its_own_transaction(team):
    client, room, ch, team_id, inst, students = team
    _ready(client, team_id, students[0])
    import artifacts
    gs = asyncio.run(_group_session(team_id))
    res = asyncio.run(artifacts.write_section(
        group_session_id=gs.id, section_key="answer", content="changed under review",
        author_user_id=students[1], expected_version=0))
    assert res["ok"] and res["ready_marks_cleared"] == 1
    # Already gone when the write returns, before any announcement: a teammate
    # marking ready now cannot complete the review on the old text.
    assert asyncio.run(_ready_marks(gs.id)) == set()
    assert not _ready(client, team_id, students[1]).get("ended")


def test_a_write_outside_review_clears_nothing(team):
    client, room, ch, team_id, inst, students = team
    import artifacts
    gs = asyncio.run(_group_session(team_id))
    res = asyncio.run(artifacts.write_section(
        group_session_id=gs.id, section_key="answer", content="draft",
        author_user_id=students[0], expected_version=0))
    assert res["ok"] and res["ready_marks_cleared"] == 0


def test_a_turn_scored_after_the_end_updates_the_submitted_ai_score(team):
    client, room, ch, team_id, inst, students = team
    assert client.post(f"/groups/{team_id}/sessions/1/end", headers=_h(students[0])).status_code == 200
    before = client.get(f"/groups/{team_id}/sessions/1/submission", headers=_h(students[0])).json()
    assert before["ai_score"] == 60.0

    import main
    from database import AsyncSessionLocal, Conversation, EvalResult
    from sqlalchemy import select

    async def pending_turn():
        async with AsyncSessionLocal() as db:
            conv = (await db.execute(select(Conversation).where(
                Conversation.user_id == students[0], Conversation.kind == "coach_private"))).scalar_one()
            ev = EvalResult(conversation_id=conv.id, turn_number=2, score_status="pending")
            db.add(ev)
            await db.commit()
            return ev.id
    eval_id = asyncio.run(pending_turn())
    asyncio.run(main._apply_late_score(eval_id, {"scores": {"PEI": 90.0}}))

    after = client.get(f"/groups/{team_id}/sessions/1/submission", headers=_h(students[0])).json()
    # Student 0 now averages (60 + 90) / 2 = 75, student 1 is 60: equal weight, 67.5.
    assert after["ai_score"] == 67.5


def test_the_team_score_is_rounded_once(team):
    """Rounding the mean to 2 places and then to 1 gave 72.7 here, while the
    Progress page, which rounds once, showed 72.6."""
    client, room, ch, team_id, inst, students = team
    from database import AsyncSessionLocal, Conversation, EvalResult
    from sqlalchemy import select, update
    from submissions import coach_session_summary, private_coach_conversations

    async def go():
        async with AsyncSessionLocal() as db:
            for uid, pei in zip(students, (72.646, 72.65)):
                conv_id = (await db.execute(select(Conversation.id).where(
                    Conversation.user_id == uid, Conversation.kind == "coach_private"))).scalar_one()
                await db.execute(update(EvalResult).where(EvalResult.conversation_id == conv_id).values(pei=pei))
            await db.commit()
            gs = await _group_session(team_id)
            summary, _ = await coach_session_summary(db, gs, await private_coach_conversations(db, gs.id))
            return summary["session_avg_pei"]
    assert asyncio.run(go()) == 72.6
