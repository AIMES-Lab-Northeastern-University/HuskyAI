"""Team submissions: the shared document a team hands in when a session ends.

Ending a session freezes the document and the AI's team score as a submission.
The instructor sees every team's submission side by side, can open it as a PDF,
and can set their own score and feedback; the AI score is kept beside it, and
the final score is the instructor's when set.
"""

import asyncio
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from test_collab_visibility import _coach_turn, _h, _section_with_team, app_ready, stub_model  # noqa: F401


async def _write(team_id, uid, content, title="Plan"):
    import artifacts
    from database import AsyncSessionLocal, GroupSession
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        gs = (await db.execute(select(GroupSession).where(
            GroupSession.group_id == team_id, GroupSession.session_number == 1))).scalar_one()
    snap = await artifacts.snapshot(gs.id)
    key = snap["sections"][0]["key"]
    r = await artifacts.write_section(group_session_id=gs.id, section_key=key, content=content,
                                      author_user_id=uid, expected_version=snap["sections"][0]["version"])
    assert r["ok"], r


@pytest.fixture
def submitted(app_ready, stub_model):
    room, ch, team, inst, students = asyncio.run(_section_with_team(2))
    client = TestClient(app_ready)
    _coach_turn(client, team, students[0])
    _coach_turn(client, team, students[1])
    asyncio.run(_write(team, students[0], "# Our answer\n\n- first point\n- second point\n\nA closing paragraph."))
    r = client.post(f"/groups/{team}/sessions/1/end", headers=_h(students[0]))
    assert r.status_code == 200, r.text
    return client, room, ch, team, inst, students


def _list(client, room, ch, inst):
    r = client.get(f"/classrooms/{room}/challenges/{ch}/submissions", headers=_h(inst))
    assert r.status_code == 200, r.text
    return r.json()


def test_ending_a_session_hands_the_document_in(submitted):
    client, room, ch, team, inst, students = submitted
    data = _list(client, room, ch, inst)
    assert data["counts"] == {"teams": 1, "submitted": 1, "graded": 0}
    (t,) = data["teams"]
    (cell,) = t["sessions"]
    assert cell["status"] == "submitted"
    sub = cell["submission"]
    assert sub["ai_score"] == 60.0 and sub["final_score"] == 60.0
    assert sub["instructor_score"] is None and sub["word_count"] > 0

    d = client.get(f"/classrooms/{room}/challenges/{ch}/submissions/{sub['id']}", headers=_h(inst)).json()
    assert "first point" in d["sections"][0]["content"]
    assert d["sections"][0]["writers"] == ["Stu0"]
    assert {p["name"] for p in d["per_student"]} == {"Stu0", "Stu1"}


def test_the_instructor_score_replaces_the_ai_score_and_can_be_cleared(submitted):
    client, room, ch, team, inst, students = submitted
    sid = _list(client, room, ch, inst)["teams"][0]["sessions"][0]["submission"]["id"]
    url = f"/classrooms/{room}/challenges/{ch}/submissions/{sid}/grade"

    r = client.put(url, json={"score": 85, "feedback": "Clear structure."}, headers=_h(inst))
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["ai_score"], d["instructor_score"], d["final_score"]) == (60.0, 85.0, 85.0)
    assert d["graded"] and d["graded_by_name"] == "Inst"

    mine = client.get(f"/groups/{team}/sessions/1/submission", headers=_h(students[1])).json()
    assert mine["final_score"] == 85.0 and mine["instructor_feedback"] == "Clear structure."
    assert mine["my_pei"] == 60.0
    # A student never sees a teammate's own average.
    assert "per_student" not in mine

    d = client.put(url, json={"score": None, "feedback": ""}, headers=_h(inst)).json()
    assert d["final_score"] == 60.0 and not d["graded"]


def test_only_the_sections_instructor_can_grade_or_list(submitted):
    client, room, ch, team, inst, students = submitted
    assert client.get(f"/classrooms/{room}/challenges/{ch}/submissions",
                      headers=_h(students[0])).status_code == 403
    sid = _list(client, room, ch, inst)["teams"][0]["sessions"][0]["submission"]["id"]
    r = client.put(f"/classrooms/{room}/challenges/{ch}/submissions/{sid}/grade",
                   json={"score": 100}, headers=_h(students[0]))
    assert r.status_code == 403
    r = client.put(f"/classrooms/{room}/challenges/{ch}/submissions/{sid}/grade",
                   json={"score": 101}, headers=_h(inst))
    assert r.status_code == 422


def test_the_submission_downloads_as_a_pdf_and_as_a_zip(submitted):
    client, room, ch, team, inst, students = submitted
    r = client.get(f"/groups/{team}/sessions/1/submission/pdf", headers=_h(students[0]))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"

    sid = _list(client, room, ch, inst)["teams"][0]["sessions"][0]["submission"]["id"]
    r = client.get(f"/classrooms/{room}/challenges/{ch}/submissions/{sid}/pdf", headers=_h(inst))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")

    r = client.get(f"/classrooms/{room}/challenges/{ch}/submissions-zip", headers=_h(inst))
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 1 and names[0].endswith(".pdf")


def test_a_running_session_has_nothing_submitted(app_ready, stub_model):
    room, ch, team, inst, students = asyncio.run(_section_with_team(2))
    client = TestClient(app_ready)
    _coach_turn(client, team, students[0])
    (cell,) = _list(client, room, ch, inst)["teams"][0]["sessions"]
    assert cell["status"] == "in_progress" and cell["submission"] is None
    r = client.get(f"/groups/{team}/sessions/1/submission", headers=_h(students[0]))
    assert r.status_code == 409


def test_a_session_ended_before_submissions_existed_is_recorded_on_view(submitted):
    """Sessions that ended before this feature have no row; the instructor's
    list records them from the document as it stands."""
    client, room, ch, team, inst, students = submitted

    async def drop():
        from database import AsyncSessionLocal, TeamSubmission
        from sqlalchemy import delete
        async with AsyncSessionLocal() as db:
            await db.execute(delete(TeamSubmission).where(TeamSubmission.group_id == team))
            await db.commit()
    asyncio.run(drop())

    (cell,) = _list(client, room, ch, inst)["teams"][0]["sessions"]
    assert cell["status"] == "submitted" and cell["submission"]["ai_score"] == 60.0


def test_with_the_feed_off_students_get_no_ai_score(submitted):
    client, room, ch, team, inst, students = submitted

    async def feed_off():
        from database import AsyncSessionLocal, Challenge
        async with AsyncSessionLocal() as db:
            c = await db.get(Challenge, ch)
            c.sessions_data = [{**c.sessions_data[0], "feed_enabled": False}]
            await db.commit()
    asyncio.run(feed_off())

    mine = client.get(f"/groups/{team}/sessions/1/submission", headers=_h(students[0])).json()
    assert mine["scores_hidden"] and mine["ai_score"] is None and mine["my_pei"] is None
    assert mine["final_score"] is None
    sid = mine["id"]
    # The instructor still sees it.
    d = client.get(f"/classrooms/{room}/challenges/{ch}/submissions/{sid}", headers=_h(inst)).json()
    assert d["ai_score"] == 60.0
