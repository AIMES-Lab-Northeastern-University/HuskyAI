# Collaborative study — pending work

Status as of 2026-09-21. Branch `feature/collab-study-phase-1` (10 commits,
159 tests passing, pushed, not merged).

**What exists already.** Every student in a team has their own private coach;
the team shares one sectioned document; and every action — including who read
whose work — lands in a single ordered event log. On top of that: turn-taking
metrics, the solo control arm, a per-assignment reference corpus with grounding
scores, routed peer review, contested-answer choices, a de-identified export,
and UIs for most of it.

**The principle to preserve.** Anything about *behaviour* is derived from the
event log, never self-reported. A reviewer who submits a verdict without opening
the work, or a student who picks a side without reading either option, is
recorded as exactly that. If you add a feature that asks a student "did you read
this?", you have replaced a measurement with a claim. Read
`docs/event-schema.md` and `docs/metrics-codebook.md` before touching anything
that writes to `study_events`.

---

## Blocked on the PI

Nothing below can be built correctly without a decision. Do not guess: each has
a default already shipped, and guessing differently mid-study makes the affected
sessions incomparable.

### 1. Consent copy and IRB amendment — *gates the first real run*

**What.** The study now records data types the current research notice does not
describe: the content students write in the shared artifact, every read and
dwell event, peer-review verdicts, and contested-input choices.

**Why it blocks.** `frontend/src/components/ConsentGate.jsx` shows students what
they are consenting to. Collecting the above under the present wording is very
likely outside the approved protocol.

**Done looks like.** Updated consent copy in `ConsentGate.jsx`, an IRB amendment
filed and approved, and a decision on whether existing consents need re-taking.

**Owner.** PI plus whoever handles IRB. Longest lead time of anything here —
start it first, in parallel with everything else.

---

### 2. Role taxonomy for role-scoped coaches

**What.** The design calls for each student to hold a role (the plan's example
shape: one role per member, injected into that student's coach prompt so the
coach addresses them in that role).

**Current state — more missing than it looks.** `study_events.role_label` exists
as a column, and `role_label` is threaded as an optional parameter through
`backend/artifacts.py`. **There is no `group_members.role_label` column**, so
there is nowhere to store a student's role. Nothing populates it and no coach
prompt mentions roles.

**Decisions needed.** What the roles are; who assigns them (instructor, student
self-select, automatic); whether they rotate between sessions.

**Done looks like.** A `role_label` column on `group_members` plus a migration;
instructor UI to assign roles; the label injected into `_build_system_prompt` for
that student's coach; `role_label` populated on every event that student
generates. Default taxonomy configurable per assignment.

**Depends on.** Nothing technical. Purely the decision.

---

### 3. Does the team backchannel enter the research record?

**What.** Students can talk to each other in a pane that is deliberately
firewalled from every coach prompt and from the evaluator.

**Current state.** Messages are stored in `group_chat_messages`. **No study event
is emitted**, so team discussion is invisible in the log and in the export.

**Decision needed.** Three options, and they are materially different: content
enters the research record; metadata only (who spoke, when, how long — no text);
or it stays excluded entirely.

**Done looks like.** Whichever is chosen, implemented behind the existing
`target = "group_chat"` value already in the event vocabulary. Because the
messages are already stored, choosing "content" later loses nothing — but
choosing "metadata only" later cannot recover timing that was never logged, so
this is worth deciding early.

---

### 4. What does a team's PEI mean?

**What.** In the collaborative arm each student has their own coach and their own
per-turn score. There is no single number that is obviously "the team's score".

**Current state.** `_end_coach_session` in `backend/main.py` reports **both** a
team mean across all members' turns and each member's own average, and sets
`GroupSession.session_avg_pei` to the mean purely so existing instructor views
render something truthful. It deliberately does not touch `best_pei`.

**Decision needed.** Whether a team-level score should exist at all, and if so
whether it is the mean, the max, the score on the shared artifact, or something
else.

**Done looks like.** A documented definition in `docs/metrics-codebook.md` and
the aggregation implemented in one place.

---

## Instructor cannot run the study without these

Each is a small UI on an endpoint that already works and is already tested.

### 5. Per-session feed on/off — *no UI*

**What.** The control arm runs early sessions with the PEI feed visible and a
later session without it, to see what carries over.

**Current state.** Works end to end server-side. The flag lives at
`Challenge.sessions_data[n]["feed_enabled"]` (absent means `true`). Setting it
requires editing the database directly.

**Done looks like.** A per-session toggle in the instructor's challenge editor
(`frontend/src/pages/Instructor.jsx`). Note it is **per session**, not per
assignment, so it belongs next to the session's title/goal fields, not in the
Study settings panel.

**Verify with.** `backend/tests/test_control_arm.py` —
`test_feed_disabled_still_scores_the_turn_server_side`.

---

### 6. Consequential revision policy — *no UI*

**What.** After the feedback is shown for a designated turn, the student must
submit one revision that counts as the scored artifact of record. The session
cannot be completed without it (server returns 409).

**Current state.** Works end to end. Configured via
`ClassroomChallenge.revision_policy`, shape `{"require_revision_on_turn": N}`.
No UI sets it.

**Done looks like.** A field in the Study settings panel
(`StudySettings` in `frontend/src/pages/Instructor.jsx`) — a turn number, or off.
Extend `PATCH /classrooms/assignments/{id}/study`, which already handles the
other three settings.

---

### 7. Contested-pair authoring — *no UI*

**What.** The instructor writes two divergent answers to the same subproblem in
advance; one is surfaced to a student mid-session and their choice is recorded.

**Current state.** `POST /contested/sessions/{group_session_id}/pairs` works and
is tested. The student side is built — pairs appear as a purple card in the
collaborative workspace. Creating one requires curl.

**Done looks like.** An instructor form: pick a session, pick a section key, type
option A (the teammate's answer) and option B (the coach's answer), pick which
student sees it, optionally mark which option the ground truth supports.

**Two constraints the UI must respect.** Option A is *always* the human
contribution and B *always* the coach output — if that varies, "adopted A" means
different things in different rows and the adoption rate becomes uninterpretable.
And the student-facing API deliberately does not label which is which; do not
add labels in the UI.

---

### 8. `instructor_assigned` reviewer policy is a lie — *bug, not a gap*

**What.** `ClassroomChallenge.verification_policy` accepts
`instructor_assigned`, and the Study settings dropdown offers "I assign
manually".

**Current state.** `choose_reviewer` in `backend/verification.py` only
special-cases `"random"`; every other value falls through to load-balanced
round-robin. **Selecting "I assign manually" silently does round-robin instead.**

**Done looks like.** Either implement manual assignment (an instructor UI that
creates `VerificationAssignment` rows directly, with `choose_reviewer` returning
`None` for this policy so nothing is auto-routed), or remove the option from the
dropdown until it exists. Do not leave it as-is — a setting that claims one
behaviour and performs another will corrupt a study arm silently.

---

## Nothing to look at yet

### 9. Turn-taking dashboard

`GET /research/sessions/{group_session_id}/turn-taking` returns contribution
share, equality (Gini and normalised entropy), alternation rate, write→read
latency, **read-before-write ratio** and coach reliance. Instructor and admin
scoped. Nothing in the frontend consumes it.

**Read `docs/metrics-codebook.md` first.** Several values are deliberately
`null` rather than `0` — "no eligible writes" and "nobody did it" are different
findings, and rendering `null` as zero would misreport the result. Students must
not see these numbers live: showing contribution share during a session turns
the measurement into an incentive.

### 10. Export download

`GET /research/sessions/{id}/export?format=json|jsonl` returns the
de-identified bundle. No download button anywhere.

**Done looks like.** A button on the instructor's session view. It must surface
the `consent_filtered` flag in the filename or UI — an archived file that was
exported with `include_unconsented=true` must never be mistakable for a
consented one.

---

## Deferred, deliberately

### 11. Auto-detected contested pairs

Only instructor-scripted pairs are built. Auto-detection means an LLM judge
comparing a teammate's contribution against the student's coach output on the
same subproblem and scoring both against the reference corpus — which is what
turns adoption into a measure of *accuracy* rather than preference. Needs real
corpora in use first, so there is ground truth to label against. Build behind a
flag; scripted pairs stay the default for study v1 because they are
deterministic and comparable across teams.

### 12. Multi-worker support — *built, unverified against a real Redis*

**Done.** The in-process `asyncio.Lock` is gone from `backend/events.py`: `seq`
is `MAX(seq)+1` guaranteed by `UNIQUE(scope, seq)`, retried up to 8 times, so
two workers racing produce a gapless sequence rather than duplicates
(`test_two_event_loops_still_produce_one_gapless_sequence` stages it with two
threads and two event loops). The artifact write path is covered the same way:
`UNIQUE(section_id, version)` turns a cross-worker version race into the
ordinary conflict, returning the current text to rebase against, instead of
silently dropping a revision.

`backend/group_room.py` now has two modes. With `REDIS_URL` unset it is the
in-process room, correct on one worker, unchanged. With it set, presence
(ZSET + HASH with a heartbeat), broadcast (pub/sub with origin suppression) and
the per-student coach-turn lock (`SET NX PX` + compare-and-delete release) move
to Redis, so any number of workers can serve one team. A configured but
unreachable Redis refuses sessions with close code 4005 rather than degrading to
per-worker rooms, which would look live while teammates were invisible to each
other. Shared rate-limit counters moved to Redis on the same switch.

**Still to do before running multiple workers.** Nothing has been exercised
against a real Redis server: `backend/tests/test_group_room_redis.py` drives the
fan-out through an injected fake shared by two instances (key naming, envelope
shape, echo suppression, presence merging and eviction, lock semantics,
heartbeat) and one case checks a real unreachable client fails loudly, but the
wire behaviour of `redis.asyncio` is untested here. Bring up a Redis, set
`REDIS_URL`, run with `--workers 2`, and put two teammates on one team.

### 13. Disconnect-buffer verification — *still needs a human and a real drop*

**Changed since this was written.** The buffer was memory-only and nothing
acked, so delivery was at-most-once in practice: a send accepted by a socket
that was OPEN but already dead was lost, and a page reload — what a student
actually does when the app looks stuck — discarded everything held.

Now `frontend/src/lib/readBuffer.js` writes every read to localStorage *before*
sending and keeps it until the server names it back with `read_ack` (added to
`/ws/coach`; sent for a handled read whether or not the row was new, so a
replayed duplicate is acked rather than replayed forever). Buffers are scoped
per student per session, and logout wipes them, so nothing one student left
behind can be flushed under the next student's identity on a shared machine.
13 tests in `frontend/tests/readBuffer.test.js` cover the loss paths, including
the reload case; three in `test_coach_socket.py` cover the ack contract.

**Still to do.** Kill wifi mid-session, expand several artifact sections,
reload the page for good measure, reconnect. Every read should appear exactly
once, each keeping the timestamp from when it happened rather than when it
arrived. No amount of unit testing substitutes for one real drop.

---

## Suggested order

1. **Item 1** (consent/IRB) — start immediately, longest lead time, blocks the run.
2. **Items 5, 6, 7** — an instructor hits these within five minutes of trying to run a session.
3. **Item 8** — small, and it is actively misleading right now.
4. **Items 2, 3** — chase the decisions; the implementations are small once made.
5. **Items 9, 10** — needed before anyone can read results.
6. **Items 11, 12, 13** — after a first real run.
