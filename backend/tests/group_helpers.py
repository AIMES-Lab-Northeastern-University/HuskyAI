"""Shared helpers for group-challenge tests (sync TestClient).

Builds a prof-assigned team via the instructor flow — the post-2026-06-21 model,
where teams are created by an instructor from the section roster (no student
self-join). Importable from sibling test modules (pytest prepend mode puts the
tests dir on sys.path; there is no __init__.py here).
"""

import uuid


def register(c, name="u") -> str:
    email = f"{name}_{uuid.uuid4().hex[:10]}@example.com"
    r = c.post(
        "/auth/register",
        json={"email": email, "name": name, "password": "testpassword123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _uid(c, token) -> str:
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


def setup_group(c, n_students=2, team_min=2, team_max=4):
    """Create a group-mode challenge with one team holding n_students enrolled
    members, via the instructor flow. Returns a dict with everything a test might
    need: instructor_token/instructor_headers, classroom_id, challenge_id,
    group_id, and student_tokens."""
    it = register(c, "ins")
    hi = {"Authorization": f"Bearer {it}"}
    cr = c.post("/classrooms", json={"name": "Grp Sec"}, headers=hi)
    assert cr.status_code == 200, cr.text
    classroom_id, join_code = cr.json()["id"], cr.json()["join_code"]

    ch = c.post(
        "/challenges",
        json={
            "classroom_id": classroom_id,
            "title": "Group Challenge",
            "description": "d",
            "category": "Test",
            "difficulty": "Beginner",
            "total_sessions": 1,
            "mode": "group",
            "team_min": team_min,
            "team_max": team_max,
        },
        headers=hi,
    )
    assert ch.status_code == 201, ch.text
    challenge_id = ch.json()["id"]

    team = c.post(f"/classrooms/{classroom_id}/challenges/{challenge_id}/teams", json={}, headers=hi)
    assert team.status_code == 201, team.text
    group_id = team.json()["id"]

    tokens = []
    for _ in range(n_students):
        st = register(c, "stu")
        jr = c.post("/classrooms/join", json={"code": join_code}, headers={"Authorization": f"Bearer {st}"})
        assert jr.status_code == 200, jr.text
        ar = c.post(
            f"/classrooms/{classroom_id}/challenges/{challenge_id}/teams/{group_id}/members",
            json={"user_id": _uid(c, st)},
            headers=hi,
        )
        assert ar.status_code == 200, ar.text
        tokens.append(st)
    return {
        "instructor_token": it,
        "instructor_headers": hi,
        "classroom_id": classroom_id,
        "challenge_id": challenge_id,
        "group_id": group_id,
        "student_tokens": tokens,
    }


def make_group_team(c, n_students=2, team_min=2, team_max=4):
    """Backward-compatible shim: returns (group_id, [student_tokens])."""
    s = setup_group(c, n_students, team_min, team_max)
    return s["group_id"], s["student_tokens"]
