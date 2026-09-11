"""Group read endpoint + confirmation that student self-join is retired.

Team creation/assignment is covered by test_group_teams.py (instructor flow).
Here we check GET /groups/{id} membership gating and that the old student
self-join endpoints (POST /groups, POST /groups/join) no longer exist.
"""

from fastapi.testclient import TestClient

from group_helpers import make_group_team, register


def test_get_group_membership_gated():
    from main import app

    with TestClient(app) as c:
        gid, (t1, _t2) = make_group_team(c, n_students=2)

        # A member can read the team.
        g = c.get(f"/groups/{gid}", headers={"Authorization": f"Bearer {t1}"})
        assert g.status_code == 200, g.text
        assert len(g.json()["members"]) == 2

        # A non-member cannot.
        outsider = register(c)
        forbidden = c.get(f"/groups/{gid}", headers={"Authorization": f"Bearer {outsider}"})
        assert forbidden.status_code == 403


def test_student_self_join_is_retired():
    from main import app

    with TestClient(app) as c:
        # These endpoints were removed in the instructor-driven redesign.
        r_create = c.post("/groups", json={"challenge_id": "x"}, headers={"Authorization": "Bearer x"})
        assert r_create.status_code in (404, 405)
        r_join = c.post("/groups/join", json={"code": "ZZZZZZ"}, headers={"Authorization": "Bearer x"})
        assert r_join.status_code in (404, 405)
