# Collaborative study — pending work

Status as of 2026-10-04. Branch `feature/collab-study-phase-1` (backend: 232
tests passing, 10 skipped — the skips are the real-Redis tests, which need
`REDIS_URL`; see `docs/multi-worker-deploy.md`).

**What exists already.** Every student in a team has their own private coach;
the team shares one sectioned document; and every action — including who read
whose work — lands in a single ordered event log. On top of that: turn-taking
metrics, the solo control arm, a per-assignment reference corpus with grounding
scores, routed peer review, contested-answer choices, a de-identified export,
and an instructor UI for every one of those. Multi-worker deployment behind
Redis has been verified with real processes.

**What is left.** Four PI decisions (items 1–4), one real-network check
(item 13), and the deliberately deferred auto-detection (item 11). Everything an
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

**Gap.** Nothing in `backend/tests/` exercises the `instructor_assigned` branch,
the `unrouted` event, or the review-pairings route. `test_verification.py`
covers round-robin and outcome classification only. Add a test before relying
on this arm.

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
`test_rate_limit_shared.py`) pass against a real server. They are skipped in an
ordinary run, which is why the suite reports 10 skipped.

**How to deploy it.** `docs/multi-worker-deploy.md` — what `REDIS_URL` turns
on, what a worker crash costs a team, and a pre-deploy checklist.

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

**Still to do.** Kill wifi mid-session, expand several artifact sections,
reload the page for good measure, reconnect. Every read should appear exactly
once, each keeping the timestamp from when it happened rather than when it
arrived. No amount of unit testing substitutes for one real drop.

---

## Suggested order

1. **Item 1** (consent/IRB) — still first. Longest lead time, blocks the run, and
   nothing technical is waiting on anything else.
2. **Items 3, 4, 2** — chase the decisions. Item 3 is a dropdown once decided
   and must be decided before the first real session; item 4 changes what the
   instructor views report; item 2 is the only one that still needs building
   (column, migration, UI, prompt) after the decision.
3. **Tests for item 8** — the `instructor_assigned` routing, the `unrouted`
   event and the review-pairings route have no backend test. Add them before a
   study arm depends on manual pairing.
4. **Item 13** — one real network drop, in progress separately.
5. **A dry run** — one instructor configures an assignment end to end through
   the UI (items 5–10), a team runs a session on the multi-worker deployment
   (item 12, `docs/multi-worker-deploy.md`), and the export is read back.
6. **Item 11** — after a first real run, once corpora are in use.
