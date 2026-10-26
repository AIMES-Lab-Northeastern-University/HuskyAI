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

