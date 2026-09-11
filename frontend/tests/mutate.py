"""Mutation harness: re-break each fix and confirm the tests notice.

A test that only checks code shape still passes when the behaviour is broken.
Each entry below re-introduces a specific defect; the run asserts that at least
one test goes red, and prints which. Sources are restored from a backup copy
afterwards, pass or fail.

Not collected by vitest (it only picks up tests/**/*.test.{js,jsx}).

    python tests/mutate.py            # backs the sources up itself
    python tests/mutate.py <dir>      # or use an existing backup copy
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent
BACKUP = (
    Path(sys.argv[1]) if len(sys.argv) > 1
    else Path(tempfile.mkdtemp(prefix="husky-mutate-"))
)

TRACKING = FRONTEND / "src/lib/readTracking.js"
GROUPCHAT = FRONTEND / "src/pages/GroupChat.jsx"
PANEL = FRONTEND / "src/components/ArtifactPanel.jsx"
TOUCHED = (TRACKING, GROUPCHAT, PANEL)

LISTENER_IN_ATTACH = """  function attach() {
    if (typeof document !== 'undefined') {
      // Same function reference, so a double attach cannot double-register.
      document.addEventListener('visibilitychange', handleVisibility)
    }"""
LISTENER_AT_CONSTRUCTION = """  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibility)
  }
  function attach() {"""

# (label, [(file, find, replace), ...])
MUTATIONS = [
    (
        "the original bug, faithfully: listener registered during render (so "
        "StrictMode's double render builds two trackers) AND per-tracker "
        "episode maps (so the surviving listener sees an empty one)",
        [
            (TRACKING, LISTENER_IN_ATTACH, LISTENER_AT_CONSTRUCTION),
            (TRACKING, "  const episodes = episodesFor(key)", "  const episodes = new Map()"),
        ],
    ),
    (
        "half of it: listener at construction, but keep the shared episode "
        "registry. The dwell behaviour survives -- either half alone defeats "
        "the original bug -- so only the listener-registration test catches it",
        [(TRACKING, LISTENER_IN_ATTACH, LISTENER_AT_CONSTRUCTION)],
    ),
    (
        "unmount disposes instead of detaching (discards banked dwell)",
        [(TRACKING, "return () => tracker.detach()", "return () => tracker.dispose()")],
    ),
    (
        "stop banking visible time when the timer is paused",
        [(TRACKING, "ep.visibleMs += Date.now() - ep.startedAt", "ep.visibleMs += 0")],
    ),
    (
        "make unmount discard the episode instead of pausing it",
        [(
            TRACKING,
            "for (const sk of episodes.keys()) disarm(sk)",
            "for (const sk of [...episodes.keys()]) close(sk)",
        )],
    ),
    (
        "unwire the read tracker from GroupChat (re-break the dead ack path)",
        [(GROUPCHAT, "onTracker={handleArtifactTracker}", "")],
    ),
    (
        "let logout leave in-flight dwell timers running",
        [(
            TRACKING,
            "      if (ep.timer) clearTimeout(ep.timer)",
            "      if (ep.timer) { /* leak */ }",
        )],
    ),
    (
        "render section content whether or not it is expanded",
        [(PANEL, "{isOpen && (", "{true && (")],
    ),
]

# Mutations expected to survive. Every mutation here is currently caught, so
# any survivor is a hole in the tests.
TOLERATED = set()


def run_tests():
    subprocess.run(
        ["npx", "vitest", "run", "--reporter=json", "--outputFile=.mut.json"],
        cwd=FRONTEND, capture_output=True, text=True, shell=True,
    )
    data = json.loads((FRONTEND / ".mut.json").read_text(encoding="utf-8"))
    failed = [
        t["fullName"]
        for suite in data.get("testResults", [])
        for t in suite.get("assertionResults", [])
        if t["status"] == "failed"
    ]
    return data.get("numFailedTests", 0), data.get("numPassedTests", 0), failed


def restore():
    for path in TOUCHED:
        shutil.copy(BACKUP / path.name, path)


for path in TOUCHED:
    if not (BACKUP / path.name).exists():
        shutil.copy(path, BACKUP / path.name)
print(f"sources backed up to {BACKUP}")

problems = []
for i, (label, edits) in enumerate(MUTATIONS):
    for path, old, new in edits:
        text = path.read_text(encoding="utf-8")
        if old not in text:
            problems.append(f"anchor not found in {path.name}: {label}")
            break
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    else:
        try:
            n_failed, n_passed, failed = run_tests()
        finally:
            restore()

        expected_survivor = i in TOLERATED
        caught = n_failed > 0
        if caught:
            verdict = "CAUGHT   " if not expected_survivor else "CAUGHT(!)"
        else:
            verdict = "SURVIVED " if expected_survivor else "MISSED   "
        if caught == expected_survivor:
            problems.append(f"{verdict.strip()}: {label}")

        print(f"\n{verdict} {label}")
        print(f"          {n_failed} failed / {n_passed} passed")
        for name in failed[:6]:
            print(f"            - {name}")
        if len(failed) > 6:
            print(f"            ... and {len(failed) - 6} more")
        continue
    restore()

print()
if problems:
    print("UNEXPECTED RESULTS:")
    for p in problems:
        print(f"  {p}")
else:
    print("every mutation behaved as expected")
sys.exit(1 if problems else 0)
