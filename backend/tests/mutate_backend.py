"""Mutation harness for the backend invariants that must not silently rot.

Same idea as frontend/tests/mutate.py: a test that only checks code shape still
passes when the behaviour is broken, so each entry here re-introduces a specific
defect and asserts at least one test goes red.

Covers the three invariants where "looks correct in code" is not sufficient:
  - the artifact_events actor CHECK constraint (a coach event carrying a student
    must be refused by the DATABASE, not merely by the Python helpers)
  - a GroupSession's study arm never changing after assignment
  - the alternation-rate arithmetic

Not collected by pytest (the filename is not test_*). Run it directly:

    python tests/mutate_backend.py            # backs the sources up itself
    python tests/mutate_backend.py <dir>      # or reuse an existing backup
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
BACKUP = (
    Path(sys.argv[1]) if len(sys.argv) > 1
    else Path(tempfile.mkdtemp(prefix="husky-backend-mutate-"))
)

DATABASE = BACKEND / "database.py"
MAIN = BACKEND / "main.py"
TURN_TAKING = BACKEND / "turn_taking.py"
TOUCHED = [DATABASE, MAIN]
if TURN_TAKING.exists():
    TOUCHED.append(TURN_TAKING)

# Spelled this way because the shell heredocs used to author this file mangle
# backslash escapes; chr(10) is unambiguous.
NL = chr(10)

ACTOR_CHECK = """        CheckConstraint(
            "(actor_kind = 'student' AND actor_user_id IS NOT NULL) OR "
            "(actor_kind IN ('coach', 'system') AND actor_user_id IS NULL)",
            name="ck_artifact_event_actor",
        ),
"""

# (label, [(file, find, replace), ...])
MUTATIONS = [
    (
        "drop the artifact_events actor CHECK constraint, so the database no "
        "longer refuses a coach event that carries a student",
        [(DATABASE, ACTOR_CHECK, "")],
    ),
    (
        "let the coach snapshot exceed its character budget (no truncation)",
        [(MAIN, "        body = content[:budget]", "        body = content")],
    ),
    (
        "let a team's later sessions draw a fresh arm instead of inheriting the "
        "team's (i.e. make it session-level, not team-level)",
        [(
            MAIN,
            "    if existing in STUDY_ARMS:" + NL + "        return existing",
            "    if existing in STUDY_ARMS:" + NL
            + "        return ARM_TREATMENT if existing == ARM_CONTROL else ARM_CONTROL",
        )],
    ),
    (
        "replace stratified minimisation with a fixed arm, proving the balance "
        "assertion is not vacuous (a pure coin flip would also fail it, but "
        "only ~77% of the time, which is why the mutation is deterministic)",
        [(
            MAIN,
            "    if counts[ARM_CONTROL] < counts[ARM_TREATMENT]:",
            "    return ARM_CONTROL" + NL
            + "    if counts[ARM_CONTROL] < counts[ARM_TREATMENT]:",
        )],
    ),
    (
        "back-fill an arm onto a session that predates the column, inventing a "
        "condition the team never ran under",
        [(
            MAIN,
            "        if gs.conversation_id is None:",
            "        if gs.arm is None:" + NL
            + "            gs.arm = await _assign_study_arm(db, group)" + NL
            + "        if gs.conversation_id is None:",
        )],
    ),
    (
        "divide the alternation rate by the number of TURNS instead of the "
        "number of adjacent pairs -- the classic off-by-one denominator",
        [(
            TURN_TAKING,
            "    return round(switches / len(pairs), 4)",
            "    return round(switches / len(actors), 4)",
        )],
    ),
    (
        "let a read of the SAME section satisfy the headline read-before-write, "
        "collapsing it into the loose variant",
        [(
            TURN_TAKING,
            "            other_read = any(s != skey for s in read_sections)",
            "            other_read = any_read",
        )],
    ),
    # The realistic version of this defect: credit the coach's pull to the
    # student named in meta.requested_by. Simply widening the actor_kind filter
    # does NOT misattribute, because a coach row's actor_user_id is NULL (the
    # CHECK constraint guarantees it), so the read keys to None and no student
    # gains anything. Reaching into meta is what actually breaks it -- which is
    # exactly the trap the comment on _log_coach_artifact_reads warns about.
    (
        "credit the coach's section pulls to the student in meta.requested_by, "
        "the misattribution that would drive read-before-write toward 1.0",
        [
            (
                TURN_TAKING,
                '            "section_key": e.section_key,',
                '            "section_key": e.section_key,' + NL
                + '            "meta": e.meta,',
            ),
            (
                TURN_TAKING,
                "        if kind == ACTOR_STUDENT and etype in STUDENT_READ_TYPES and uid:",
                "        if etype == 'section_read_by_coach':" + NL
                + "            uid = (ev.get('meta') or {}).get('requested_by')" + NL
                + "        if etype in STUDENT_READ_TYPES or etype == 'section_read_by_coach':"
                + NL + "            if not uid:" + NL + "                continue",
            ),
        ],
    ),
    (
        "drop the turn from the coach-read idempotency key, so every later "
        "turn's pull collapses onto the first turn's row",
        [(
            MAIN,
            "idempotency_key=f\"coach:{conversation_id}:{turn}:{item['section_key']}\",",
            "idempotency_key=f\"coach:{conversation_id}:{item['section_key']}\",",
        )],
    ),
]


def run_tests():
    out = BACKEND / ".mut_backend.json"
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q",
         "--json-report", f"--json-report-file={out}"],
        cwd=BACKEND, capture_output=True, text=True,
    )
    if out.exists():
        data = json.loads(out.read_text(encoding="utf-8"))
        failed = [
            t["nodeid"] for t in data.get("tests", [])
            if t.get("outcome") == "failed"
        ]
        summary = data.get("summary", {})
        return summary.get("failed", 0), summary.get("passed", 0), failed
    # pytest-json-report not installed: fall back to parsing the terminal tail.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
        cwd=BACKEND, capture_output=True, text=True,
    )
    tail = proc.stdout.strip().splitlines()
    failed_names = [
        ln.split(" ")[1] for ln in tail if ln.startswith("FAILED ")
    ]
    n_failed = sum(1 for ln in tail if ln.startswith("FAILED "))
    if not n_failed:
        import re
        m = re.search(r"(\d+) failed", proc.stdout)
        n_failed = int(m.group(1)) if m else 0
    import re
    mp = re.search(r"(\d+) passed", proc.stdout)
    return n_failed, int(mp.group(1)) if mp else 0, failed_names


def restore():
    for path in TOUCHED:
        backup = BACKUP / path.name
        if backup.exists():
            shutil.copy(backup, path)


for path in TOUCHED:
    if not (BACKUP / path.name).exists():
        shutil.copy(path, BACKUP / path.name)
print(f"sources backed up to {BACKUP}")

problems = []
for label, edits in MUTATIONS:
    applied = True
    for path, old, new in edits:
        text = path.read_text(encoding="utf-8")
        if old not in text:
            problems.append(f"anchor not found in {path.name}: {label}")
            applied = False
            break
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    if not applied:
        restore()
        continue
    try:
        n_failed, n_passed, failed = run_tests()
    finally:
        restore()

    verdict = "CAUGHT " if n_failed else "MISSED "
    if not n_failed:
        problems.append(f"MISSED: {label}")
    print(f"\n{verdict} {label}")
    print(f"         {n_failed} failed / {n_passed} passed")
    for name in failed[:6]:
        print(f"           - {name}")
    if len(failed) > 6:
        print(f"           ... and {len(failed) - 6} more")

print()
if problems:
    print("UNEXPECTED RESULTS:")
    for p in problems:
        print(f"  {p}")
else:
    print("every mutation behaved as expected")
sys.exit(1 if problems else 0)
