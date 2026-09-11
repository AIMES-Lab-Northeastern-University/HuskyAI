"""Contribution analytics for a team: per-student prompt share (participation)
plus team-level scoring. Gemini + evaluator are mocked. Drives real turns over
the group WebSocket so sender_user_id attribution is exercised end-to-end."""

from fastapi.testclient import TestClient

from group_helpers import setup_group, register as _register
from test_group_scoring import _patch_ai, _recv_until


def test_team_analytics_attributes_prompts_and_flags_idle(monkeypatch):
    import main

    _patch_ai(monkeypatch)
    with TestClient(main.app) as c:
        s = setup_group(c, n_students=3, team_min=2)
        gid = s["group_id"]
        t1, t2, t3 = s["student_tokens"]
        base = f"/classrooms/{s['classroom_id']}/challenges/{s['challenge_id']}/teams/{gid}"

        # All three live (so turns can run); only student 1 sends prompts — twice.
        with c.websocket_connect(f"/ws/group?token={t1}&group_id={gid}") as ws, \
             c.websocket_connect(f"/ws/group?token={t2}&group_id={gid}") as ws2, \
             c.websocket_connect(f"/ws/group?token={t3}&group_id={gid}") as ws3:
            _recv_until(ws, "session_init")
            _recv_until(ws2, "session_init")
            _recv_until(ws3, "session_init")
            ws.send_json({"type": "message", "content": "First"})
            _recv_until(ws, "eval")
            ws.send_json({"type": "message", "content": "Second"})
            _recv_until(ws, "eval")

        r = c.get(f"{base}/analytics", headers=s["instructor_headers"])
        assert r.status_code == 200, r.text
        d = r.json()

        assert d["total_turns"] == 2
        assert d["team_pei_avg"] == 82.0
        assert d["team_pei_best"] == 82.0

        by_turns = {m["turns"]: m for m in d["members"]}
        assert len(d["members"]) == 3
        # Student 1 sent both prompts -> 100% share; the other two sent none.
        top = max(d["members"], key=lambda m: m["turns"])
        assert top["turns"] == 2
        assert top["share_pct"] == 100.0
        idle = [m for m in d["members"] if m["turns"] == 0]
        assert len(idle) == 2
        assert all(m["share_pct"] == 0.0 for m in idle)
        assert all(m["on_team"] for m in d["members"])

        # Timeline has one entry per turn, each attributed to the sender.
        assert len(d["timeline"]) == 2
        assert all(t["pei"] == 82 for t in d["timeline"])


def test_team_analytics_empty_before_activity(monkeypatch):
    import main

    _patch_ai(monkeypatch)
    with TestClient(main.app) as c:
        s = setup_group(c, n_students=2)
        base = f"/classrooms/{s['classroom_id']}/challenges/{s['challenge_id']}/teams/{s['group_id']}"

        r = c.get(f"{base}/analytics", headers=s["instructor_headers"])
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_turns"] == 0
        assert d["team_pei_avg"] is None
        assert d["members"] == [] or all(m["turns"] == 0 for m in d["members"])


def test_team_analytics_instructor_only(monkeypatch):
    import main

    _patch_ai(monkeypatch)
    with TestClient(main.app) as c:
        s = setup_group(c, n_students=2)
        base = f"/classrooms/{s['classroom_id']}/challenges/{s['challenge_id']}/teams/{s['group_id']}"

        # A student (non-instructor) cannot read team analytics.
        student_headers = {"Authorization": f"Bearer {s['student_tokens'][0]}"}
        r = c.get(f"{base}/analytics", headers=student_headers)
        assert r.status_code in (403, 404), r.text

        # An unrelated user certainly cannot.
        outsider = _register(c)
        r2 = c.get(f"{base}/analytics", headers={"Authorization": f"Bearer {outsider}"})
        assert r2.status_code in (403, 404), r2.text
