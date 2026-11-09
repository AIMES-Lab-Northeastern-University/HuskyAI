# Collaborative study — pending work

Status as of 2026-11-09. Branch `feature/student-progress` (PR #18): backend
316 tests passing with `REDIS_URL` set, on SQLite and on Postgres (306 + 10
skipped without Redis), frontend 26 passing.

**Since 2026-10-04.** Item 4 is decided and built (equal-weight team PEI).
Item 8 has its tests. Team sessions now end through a final review where every
member who took part marks the document ready, and every ended session is
frozen as a `TeamSubmission` that the instructor grades (see the README,
"Finishing a team session" and "Submissions"). A two-worker end-to-end dry run
and the server half of item 13 were run on 2026-11-02; see items 12 and 13.

**What exists already.** Every student in a team has their own private coach;
the team shares one sectioned document; and every action — including who read
whose work — lands in a single ordered event log. On top of that: turn-taking
metrics, the solo control arm, a per-assignment reference corpus with grounding
scores, routed peer review, contested-answer choices, a de-identified export,
and an instructor UI for every one of those. Multi-worker deployment behind
Redis has been verified with real processes.

**What is left.** Three PI decisions (items 1–3) plus one on late reads (see
item 13), a capacity check on the real database (item 12), and the deliberately
deferred auto-detection (item 11). Everything an
instructor needs to configure and read out a session (items 5–10) is built.

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

**Still needs.** The PI and IRB. Nothing technical is outstanding: the copy
change and a `RESEARCH_NOTICE_VERSION` bump ship together once approved.

**Owner.** PI plus whoever handles IRB. Longest lead time of anything here —
start it first, in parallel with everything else.

**Prepared.** `docs/consent-draft-for-pi.md` has a table of everything now
recorded for the IRB amendment, proposed wording (with a variant for each
team-chat option), and seven questions found in the code: there is no decline
option, "anonymized" overstates what the scrubbing does, team metrics include
students who declined, the "train models" claim, how re-consent would work,
the one-time step that opted in all existing data, and how withdrawal works.

**Built, inactive until the wording is approved.** `RESEARCH_NOTICE_VERSION`
(default 1): raise it in the same deploy as the new wording, and everyone who
accepted an older notice sees the gate again. `RESEARCH_NOTICE_ALLOW_DECLINE`
(default off): adds a "Use HuskyAI without taking part" button that counts as
seeing the notice, with consent off. See `backend/tests/test_research_notice.py`.

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

**Current state — built, waiting on the decision.** Now a per-assignment setting,
`ClassroomChallenge.team_chat_logging`, set under "Team chat in research" in the
instructor's Study settings panel: `off` (the default, and the previous
behaviour), `metadata` (a `group_chat.message` event per message: who, when,
length, no text), or `content` (as metadata, plus the scrubbed text in the
export's `team_chat` section). Each event records the mode its message was sent
under, so a later switch never adds text for earlier messages. The mode is
resolved once per session into `CoachPolicy.team_chat_logging`
(`backend/study_policy.py`) and acted on in one place, `_log_team_chat` in
`backend/main.py`; the event payload carries length only, never text, in both
modes. See `docs/event-schema.md` (`target = group_chat`) and
`backend/tests/test_team_chat_logging.py`.

**Decision needed.** Which of the three options to use. Draft consent wording for
each is in `docs/consent-draft-for-pi.md`. Decide before the first real session:
if the choice is `metadata`, the timing of messages sent while the setting is
still `off` can't be recovered.

---

### 4. What does a team's PEI mean? — *decided and built*

**Decision.** The equal-weight mean of each student's own average PEI, always
shown with its range; defined in `docs/metrics-codebook.md` ("Team PEI") and
computed in one place, `coach_session_summary` in `backend/submissions.py`.
It is also the AI score on a team's submission. The text below is the original
framing, kept for context.

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

## Instructor controls — done

Items 5–10 used to be "an endpoint that works, and no UI". Each now has one.
They are kept here, briefly, because each carries a constraint that is easy to
undo by accident when the UI is next touched.

All of the per-team panels hang off **Manage teams** on a group-mode challenge
in the instructor view, in `frontend/src/components/GroupTeamManager.jsx`. The
per-assignment settings are in `StudySettings` in
`frontend/src/pages/Instructor.jsx` (the **Study settings** button), saved
through `PATCH /classrooms/assignments/{id}/study` (`backend/classrooms.py`).

### 5. Per-session feed on/off — *done*

**Where.** The challenge editor in `Instructor.jsx` ("Show score feed to
students in", one checkbox per session), next to the session fields rather than
in Study settings, because the flag is per *session*, not per assignment. It
sends `feed_enabled_by_session` on `PATCH /challenges/{id}`;
`_apply_feed_flags` in `backend/challenges.py` writes
`sessions_data[n]["feed_enabled"]`, dropping the key when the session is on so
"absent means true" stays the only representation of on.

**Behaviour.** Turns are still scored server-side when the feed is hidden, and
the event log records `feed.suppressed` rather than leaving the absence to be
inferred. Applies to sessions started after saving.

**Tests.** `backend/tests/test_control_arm.py` covers the server-side gating
(`test_feed_disabled_still_scores_the_turn_server_side` and neighbours). The
`feed_enabled_by_session` field on the PATCH has no test of its own.

### 6. Consequential revision policy — *done*

**Where.** "Required revision" in `StudySettings`, shown only for the solo
control arm: a checkbox plus a turn number (1–50), sent as
`require_revision_on_turn` (`null` turns it off). The endpoint rebuilds
`ClassroomChallenge.revision_policy` rather than mutating it, and keeps any
other keys in it.

**Behaviour.** Not required in a session whose feed is hidden — the revision is
a response to the feedback, and there is none to respond to
(`backend/challenges.py`, the completion check). Completion without it is
refused with 409. See `test_completion_is_refused_until_the_revision_is_submitted`.

### 7. Contested-pair authoring — *done*

**Where.** `frontend/src/components/ContestedPairsAdmin.jsx`, opened with
**Contested answers** on a team. It lists, creates and deletes pairs through
`GET|POST /classrooms/{cid}/challenges/{chid}/teams/{tid}/contested-pairs` and
`DELETE …/contested-pairs/{pair_id}` (`backend/groups.py`), which create the
group session on demand and delegate to `create_scripted_pair` in
`backend/contested.py`.

**The two constraints are held by construction.** The form's fields are named
by source — `teammate_answer` and `coach_answer` — and the backend maps them to
`option_a_text` and `option_b_text`, so A is always the human contribution and
B always the coach output. The source labels appear only in the instructor
panel; the student card stays unlabelled
(`test_the_option_labels_do_not_reveal_which_side_is_the_coach`). Do not add
labels on the student side.

**Gap.** The team-scoped routes are untested; `backend/tests/test_contested.py`
exercises the original `/contested/sessions/{id}/pairs` path.

### 8. `instructor_assigned` reviewer policy — *fixed*

**What changed.** `choose_reviewer` in `backend/verification.py` now follows
the instructor's pairings (author → reviewer, stored in `review_pairings`) and
nothing else. No pairing, or a paired reviewer who has left the team, returns
`None`: the contribution is not routed, and — on a team of more than one — a
`verification.unrouted` event is logged with `reason` `no_pairing` or
`reviewer_not_on_team`, so the gap is visible in the record instead of silent.
It never falls through to round-robin.

**Where.** `ReviewPairingsEditor` in
`frontend/src/components/PeerReviewAdmin.jsx`, shown under each team when the
policy is `instructor_assigned`, saved with
`PUT /classrooms/{cid}/challenges/{chid}/teams/{tid}/review-pairings`. The
Study settings dropdown says the same thing the code does: "A student with no
reviewer picked gets no review — it never falls back to round robin."
`PeerReviewsPanel` (same file) lists each review's derived outcome and lets
the instructor reassign a pending one (`POST /verification/{id}/reassign`).

**Tests.** `backend/tests/test_review_pairings.py` covers the
`instructor_assigned` branch, the `unrouted` event and the review-pairings
route.

### 9. Turn-taking dashboard — *done*

**Where.** `frontend/src/components/TurnTakingPanel.jsx`, shown in each team's
analytics. It reads the classroom-scoped
`GET /classrooms/{cid}/challenges/{chid}/teams/{tid}/turn-taking`, which uses
the same pure function as `/research/sessions/{id}/turn-taking`
(`backend/analysis/turn_taking.py`); both are covered by
`backend/tests/test_turn_taking.py`.

**Constraints held.** A `null` renders as a dash with the reason it is missing,
never as zero or a drawn bar. Metrics are per session and deliberately not
averaged across sessions. The codebook version is shown at the foot of the
panel. It is instructor-only — keep it that way while a study is running (see
`docs/metrics-codebook.md`).

### 10. Export download — *done*

**Where.** `frontend/src/components/ResearchExportPanel.jsx`, one row per team
session with **Download JSON** and **Download JSONL**, from
`GET /research/sessions/{id}/export` (`backend/research_export.py`). An
"include students who did not consent" checkbox sets `include_unconsented`.

**The `consent_filtered` rule is held.** The filename is built from the
downloaded bundle's own `consent_filtered` flag, not from the checkbox:
`huskyai-<team>-session<n>-consented-<date>.json` or
`…-INCLUDES-UNCONSENTED-…`. A bundle whose flag cannot be read is labelled
`INCLUDES-UNCONSENTED`, the safe direction. The backend's `Content-Disposition`
filename uses the same rule.

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

## Deployment and reliability

### 12. Multi-worker support — *done, verified against a real Redis on 2026-10-04*

**What exists.** Event ordering never depended on Redis: `seq` in
`backend/events.py` is `MAX(seq)+1` guaranteed by `UNIQUE(scope, seq)` and
retried, and artifact writes are guarded by `UNIQUE(section_id, version)`, so a
cross-worker race becomes the ordinary conflict rather than a lost revision.

With `REDIS_URL` set, `backend/group_room.py` moves presence, broadcast, the
per-student coach lock and the legacy shared-room team turn lock to Redis;
`backend/coordination.py` gives background work (score retries, session
analyses, corpus ingests) short leases so it runs once rather than once per
worker; `backend/rate_limit.py` shares its counters; and
`database.startup_lock` serialises schema setup and seeding on Postgres. A
configured but unreachable Redis refuses group and coach sessions with close
code 4005 rather than degrading to per-worker rooms. Solo chat is unaffected.

**Verified.** Two real Uvicorn processes sharing one Redis and one database:

- presence is visible across workers;
- team turn lock: a second worker sees the team busy, and turn numbers are
  never duplicated;
- per-student coach lock holds across two tabs on different workers, while
  teammates' coaches are not blocked and one student's private coach output
  never reaches another;
- team chat and artifact writes cross workers;
- `session_ended` propagates to every worker;
- the per-account login limit is shared;
- a Redis restart recovers in about 5 s;
- a worker SIGKILLed mid-turn: the turn lock is held until its 300 s TTL, the
  dead worker's members age out after about 45 s, and the survivors' roster is
  now pushed by their heartbeat when that happens (commit 783de56; before it,
  survivors kept showing the dead members until something else changed).

All 10 real-Redis tests in `backend/tests` (`test_multiworker_redis.py`,
`test_rate_limit_shared.py`) pass against a real server (last run 2026-11-02).

**End-to-end dry run, 2026-11-02.** Two Uvicorn workers sharing one Redis and
one database, driven over HTTP and WebSocket with live Gemini: an instructor
created a section, a group challenge with section briefs, study settings
(`instructor_assigned`, team chat `metadata`), a team, review pairings and a
contested pair; two students on different workers took coach turns, wrote
sections (each write reached the other worker; a stale write came back as a
conflict), read, and used team chat; the final review ran (an edit withdrew a
ready mark, the last mark ended the session as `team_ready`, the other worker
got `session_ended`, later writes were refused); then the submission, student
and instructor PDFs, grading, zip, analytics, turn-taking, team progress and
the research export were read back (consent-filtered, no emails, strictly
increasing `seq`, team chat as metadata with no text). 54 of 54 checks passed.
Turn scoring could not be checked: the OpenAI key in `backend/.env` is
rejected (401), so every turn came back `eval_pending`. They are skipped in an
ordinary run, which is why the suite reports 10 skipped.

**How to deploy it.** `docs/multi-worker-deploy.md` — what `REDIS_URL` turns
on, what a worker crash costs a team, and a pre-deploy checklist.

**On Postgres, 2026-11-09.** The suite now runs against a real database
(`TEST_DATABASE_URL`, see `backend/tests/conftest.py`): 316 pass. Running it
there found that concurrent events for one session could be dropped (20 at once
kept 8–14), now fixed with a per-session advisory lock in `events.py`.
`backend/scripts/stress_team_sessions.py` then ran 12 and 30 concurrent teams
across two workers with every invariant checked; it also caught the session-row
lock added on 2026-11-02 failing under load (now a `FOR NO KEY UPDATE`).

**Capacity: open.** Through port 6543 (the transaction-pooler path, which the
deploy notes prefer) the app opens a new database connection for every
transaction, and recording one read takes two. Locally that made a read about
5x slower than with a pool (17 ms vs 3.3 ms). In a class-sized run (30 teams,
90 students at a human pace, two workers) reads were stored 6 s late on
average and up to 34 s late, and some sockets dropped on keepalive timeouts.
The same run with a normal pool had no problems (0.6 s average). Against
Supabase each new connection also costs a network round trip and TLS, so run
the stress script against a staging database on the production connection
settings before a full class uses the collaborative arm.

**Not covered.** A Redis outage *during* a session closes group and coach
sockets with 1011 and refuses reconnects with 4005 until Redis is back; the
coach workspace stops retrying on 4005, so students reload once it recovers.
That path was exercised by restarting Redis, not by a long outage in a class.

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

**Server half verified, 2026-11-02.** Reads sent on one worker, the TCP
connection aborted with no close frame before any ack, then the same reads
replayed twice on the other worker, as the buffer does after a reconnect and
again after a reload: each read was stored exactly once, every one was acked,
and each kept the client timestamp from when it happened (a minute earlier),
not when it arrived.

**Browser half verified, 2026-11-09.** In Chromium (Playwright), a student
went offline mid-session, expanded each of two sections twice, came back
online and reloaded at once. All four reads were stored exactly once, each with
the time it happened rather than when it arrived, and the localStorage buffer
was empty afterwards. Item 13 is done.

**Open: reads that happened during the session but arrive after it.** A read
is recorded only if it reaches the server before the session ends (apart from
the closing dwell). A student whose wifi drops in the last minutes of a timed
session and who reconnects after the deadline therefore loses those reads: they
are acked and discarded. Accepting them would mean trusting `client_ts`, which
the schema deliberately never does. A PI decision: keep the rule, or accept
late reads whose `client_ts` falls inside the session and that arrive within a
grace window. Every read should appear exactly
once, each keeping the timestamp from when it happened rather than when it
arrived. No amount of unit testing substitutes for one real drop.

---

## Suggested order

1. **Item 1** (consent/IRB) — still first. Longest lead time, blocks the run, and
   nothing technical is waiting on anything else.
2. **Items 3, 2** — chase the decisions. Item 3 is a dropdown once decided
   and must be decided before the first real session; item 2 still needs
   building (column, migration, UI, prompt) after the decision.
3. **A working OpenAI key** in every deployment's environment — without one no
   turn is scored (they queue as `eval_pending`). Check with
   `python scripts/verify_external_ai.py`.
4. **Capacity on the real database** — run
   `backend/scripts/stress_team_sessions.py` (class pace) against a Supabase
   staging database with production connection settings (item 12).
5. **A dry run on the deployed site** — the API dry run (item 12) and a
   three-browser run (2026-11-09: live edits across workers, a conflicting edit,
   a draft carried into the full-document view, an offline spell with a reload,
   the final review, the hand-in, PDFs, and instructor grading) both pass
   locally; what is left is the deployed site.
6. **Item 11** — after a first real run, once corpora are in use.
