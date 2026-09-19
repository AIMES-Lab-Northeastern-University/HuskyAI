# HuskyAI Collaborative-Study Build Plan

Implementation plan for the study architecture specified by the PI.

The build is two things: a private coach conversation per student plus one shared
artifact the team reads and writes, and a single ordered event log that records
every action including **reads** of that artifact. Everything else specified —
the reference corpus, contested input, routed verification, turn-taking indices,
prominence conditions — is either a reading of that log or a small addition on
the same architecture, and can follow.

Status: draft for review. Open questions in the final section block parts of
Phases 1, 4 and 5; question 8 decides whether Phases 1 and 2 can be built in
this order.

---

## 0. What already exists (the starting point)

Knowing this matters, because roughly half the directive is a modification of
working code rather than new construction.

| Capability | Where it lives today | Fit with the target design |
|---|---|---|
| Solo student <-> coach chat + per-turn PEI feed | `backend/main.py:647` (`/ws`), `frontend/src/pages/Workspace.jsx` (`EvalSidebar`) | This *is* Design A. Becomes the control arm. |
| Group mode: one team, one **shared** coach conversation, turn lock | `backend/main.py:1232` (`/ws/group`), `backend/group_room.py` | Must be replaced by per-student private coaches. Room manager is reusable. |
| Human-only team backchannel | `GroupChatMessage`, deliberately firewalled from prompts, eval and export | Stays. Becomes a third log target. See open question 7. |
| Per-message authorship | `Message.sender_user_id` | Option B in embryo. Needs to become a full event log. |
| Participation share per student | `backend/groups.py::_team_analytics` | Superseded by the turn-taking index, which is strictly richer. |
| Rubric retrieval at eval time | `backend/evaluator_v3.py`, one global `OPENAI_VECTOR_STORE_ID` | Must become per-assignment. This is Phase 2. |
| Per-assignment configuration surface | `ClassroomChallenge` (`mode`, `team_min`, `team_max`) | The natural home for every new study flag. |
| Migrations | `backend/alembic/versions/` plus a defensive `ALTER TABLE IF NOT EXISTS` block in `database.py::init_db` | Every new table needs both paths. |

Two standing constraints:

- **Single Uvicorn worker.** `group_room.py` holds room state in process memory.
  The new design adds more live state (per-student sockets plus artifact state),
  so this constraint hardens. Moving to multiple workers requires Redis pub/sub
  first. Documented, not addressed here.
- **Consent is snapshotted per row.** `EvalResult.consent_research` captures
  consent at scoring time so the export is immune to later toggles. Every new
  research table must follow this pattern.

---

## Build order: the spine and the tickets

The PI's own collapse of this: engineers need two things. Every student gets
their own coach conversation plus one shared document the team can read and
write, and every action lands in a timestamped event log carrying who did it and
what they touched, **including reads of the shared document**. Contested input,
routed verification, turn-taking indices and prominence conditions are all either
readings of that log or small additions on the same architecture. If the log is
right they are follow-on tickets. If the log is wrong they are not recoverable,
because who consulted whose work cannot be reconstructed from a database of final
states.

So the phases below are ordered by **irrecoverability**, not by feature value.
Build what cannot be reconstructed after the fact first.

| | Must be right the first time | Recoverable later |
|---|---|---|
| **Spine (Phase 1)** | Per-student coach conversations, shared artifact, event log with reads | |
| **Tickets (Phases 2, 4, 5, 6)** | | Reference corpus, contested input, routed verification, prominence conditions |

### This reorders one thing from the original directive

Option D (the corpus) was named first, on the grounds that every measurement
needs ground truth to score against. That reasoning holds, but it does not force
the corpus to be built first, because **the corpus is retrofittable and the log
is not**. `evaluate_conversation_v3` scores a stored conversation history, so a
corpus attached in week 6 can re-score every archived transcript from week 1. A
read that went unlogged in week 1 is gone permanently.

One condition on that argument, and it is load-bearing: it holds only if the
corpus is evaluator-side. If grounding scores are shown to students in the feed,
the corpus becomes part of the intervention itself and must precede the first
real run, retrofitting or not. That is open question 8, which therefore decides
the build order rather than being a UI detail.

---

## The read requirement (the part to be firm about)

A student opening a teammate's contribution **is the measurement**. It is not
incidental traffic, and it is the single requirement most likely to be quietly
dropped, because every instinct in performance engineering says to sample
high-volume low-value events, batch them lossily, shed them under load, or infer
them from what was rendered. Each of those instincts destroys the dataset, and
the damage is silent and permanent.

Hard requirements, to be stated to whoever implements this:

1. **Reads share the write sequence space.** A read and a write in the same
   session draw from one monotonic `seq`. The ordering is the finding: whether a
   student read a teammate's contribution *before* or *after* writing their own
   is the whole question, and it is unanswerable if reads live in a side table
   with their own clock.
2. **No sampling, ever.** Delivery is at-least-once with an idempotency key and
   dedupe on ingest. Under-recording is not a tunable here.
3. **Buffer across disconnects.** Client-side read events survive a dropped
   socket and flush on reconnect with their original `client_ts` preserved. A
   flaky network must not silently eat reads.
4. **Rendered is not read.** Events fire on an actual open or expand by a person,
   never on background render, prefetch or an off-screen mount.
5. **Coach-mediated reads are logged distinctly** (`artifact.read_by_coach`) and
   never merged into human opens. They answer a different question, and whether
   they count as the student reading a teammate's work is open question 4.
6. **Asymmetric retention.** Dwell heartbeats may be downsampled or expired.
   `open`, `expand` and `read_by_coach` events are permanent.
7. **Load shedding, if it ever happens, drops heartbeats only** and records that
   it happened, so a gap is visible in analysis rather than invisible.
8. **A test enforces coverage.** An integration test asserts that every path
   capable of displaying a teammate's contribution emits a read event, including
   the coach-injection path. A new display surface fails that test until it is
   instrumented, which is what stops this eroding over the next six months of
   feature work.

`artifact_revision` answers who wrote what. Only the event log answers who looked
at whose work before writing, which is the question the study is actually asking.

## Phase 1 — The spine: private coaches, shared artifact, event log (Options C + B)

**Goal.** One private coach conversation per student, role-scoped, plus one
shared artifact any member can write to and any member's coach can read from,
with every action landing in a single ordered event log.

### 1.1 Data model — the architecture
- `Conversation.kind` — `solo` | `group_shared` | `coach_private`. The existing
  `Conversation` row already carries both `user_id` and a nullable
  `group_session_id`, so a private coach conversation inside a group session
  needs **no new table**: set both, and set `kind = coach_private`.
- `GroupMember.role_label` — the "role-scoped" part. Injected into that
  student's coach system prompt. Taxonomy is open question 1; ship it
  configurable per assignment with a default set.
- `artifact` — `id`, `group_session_id`, `content`, `version` (Integer,
  optimistic concurrency), `updated_at`, `updated_by_user_id`.
- `artifact_revision` — `id`, `artifact_id`, `version`, `content`,
  `author_user_id`, `origin` (`student_typed` | `coach_copied` |
  `verification_edit`), `bytes_added`, `bytes_removed`, `created_at`. Full
  revision history is a research record, not an undo buffer, so revisions are
  append-only and never pruned.

### 1.2 Backend — the architecture
- New endpoint `/ws/coach`: one socket per student per group session, driving
  that student's private conversation. Largely the solo `/ws` handler's logic
  with group context added, so extract the shared turn machinery
  (`_build_gemini_history`, `_save_turn`, eval dispatch) rather than forking it.
- Extend `group_room.py`: a room now holds N private histories plus one artifact
  state plus presence. The global `turn_lock` that serializes AI turns becomes
  **per-user** — private coaches must run concurrently, which is the point of the
  design. Artifact writes take a short room-level lock and a version check;
  a stale write is rejected with the current version so the client can rebase.
- Artifact message types on the socket: `artifact_open`, `artifact_write`,
  `artifact_patch`, `artifact_close`, plus a broadcast to teammates on change.
- **Coach reads artifact**: before each private coach turn, inject the current
  artifact snapshot into that student's prompt, subject to the prominence policy
  from Phase 6, and emit a read event attributed to that student with
  `actor_kind = coach`.

### 1.3 Option B — the event log
- `study_event` — `id`, `group_session_id` or `user_challenge_session_id`,
  `classroom_id`, `challenge_id`, `seq` (monotonic per session, assigned
  server-side under a per-session lock, guaranteeing total order),
  `actor_user_id`, `actor_kind` (`student` | `coach` | `system`), `role_label`,
  `target` (`coach` | `artifact` | `group_chat` | `feed` | `contested` |
  `verification`), `action`, `ref_id`, `payload` (JSON), `client_ts` (recorded
  for latency analysis, never trusted for ordering), `server_ts`,
  `consent_research` (snapshot), `condition` (JSON: arm, prominence, corpus id).
- `backend/events.py::log_event(...)` — the single write path. Call sites:
  `_save_turn`, `_save_group_turn`, `_save_team_chat`, every artifact operation,
  every feed render in Design A, and Phases 4 and 5 wholesale.
- **Reads are first-class.** Proposed taxonomy, pending open question 5:
  `artifact.open` (panel opened), `artifact.dwell` (heartbeat with duration,
  batched client-side), `artifact.section_expand`, `artifact.read_by_coach`
  (snapshot injected into a prompt). Client-emitted read events go through a
  batched `POST /events` endpoint, are rate-limited, and are re-stamped
  server-side.

### 1.4 The turn-taking index
Treated as a primary research output, not telemetry, which means it gets
versioned definitions, unit tests over synthetic logs and a written codebook.
- `backend/analysis/turn_taking.py`, computing per session: per-actor
  contribution share, entropy or Gini of that share, alternation rate, median
  latency from a teammate's write to the next read by anyone else,
  read-before-write ratio, and coach-reliance ratio (coach-sourced adoptions
  over teammate-sourced adoptions).
- `GET /research/sessions/{id}/turn-taking`, instructor and admin scoped.
- `docs/event-schema.md` and `docs/metrics-codebook.md`, both versioned. A
  metric definition change bumps a version field on the response.
- Determinism test: replaying a fixed log must reproduce identical metrics.
- `groups.py::_team_analytics` becomes a thin wrapper over this module, so the
  existing instructor analytics page keeps working and gains the new numbers.

### 1.5 Frontend
- Group workspace becomes a two-pane layout: private coach chat on one side, the
  shared artifact on the other, with presence and a live teammate-edit indicator.
- Read instrumentation must be honest: an event fires when a panel is actually
  opened or a section actually expanded, never on background render.

### 1.6 Acceptance
- Three students in one team hold three concurrent, mutually invisible coach
  conversations, all reading and writing one artifact.
- The event log for that session, ordered by `seq`, reconstructs the whole
  session with no gaps, and a replay reproduces the turn-taking metrics exactly.
- A stale artifact write is rejected and rebased without data loss.

---

## Phase 2 — Option D: per-assignment reference corpus

**Goal.** An instructor attaches ground-truth material to an assignment, and the
evaluator scores student work against it.

Built second rather than first, because it is retrofittable: see the build-order
section above, and open question 8, which decides whether that is true here.

### 2.1 Data model
- `reference_corpus` — `id`, `classroom_challenge_id` (FK, the per-section
  assignment, so the same challenge can carry different corpora in different
  sections), `name`, `openai_vector_store_id`, `status` (`building` | `ready` |
  `failed`), `created_by_user_id`, `created_at`.
- `corpus_document` — `id`, `corpus_id`, `filename`, `mime_type`, `size_bytes`,
  `data` (LargeBinary, mirroring the `Attachment` table's inline-bytes decision,
  which exists because the deploy target has an ephemeral filesystem),
  `openai_file_id`, `status`, `uploaded_by_user_id`, `created_at`.
- `ClassroomChallenge.reference_corpus_id` — nullable FK. Null means today's
  behavior: rubric store only.

### 2.2 Backend
- New router `backend/corpus.py`: create corpus, upload document, list, delete,
  poll status. Reuse the existing attachment size and count caps and the
  `python-docx` text extraction already in `main.py`.
- Ingestion: upload to the OpenAI Files API, attach to a vector store created
  per corpus, poll until indexed, write `status`.
- `evaluator_v3.py` refactor: `file_search` is currently a module-level
  `FileSearchTool` bound to one global store, and the judge agents are
  module-level singletons. Replace with a factory keyed by corpus id
  (`_agents_for(corpus_store_id)`) that memoizes per corpus, and thread an
  optional `corpus_vector_store_id` argument through `evaluate_conversation_v3`.
  Callers in `main.py` resolve it from the session's assignment.
- New scored dimension, **grounding**: does the student's work cover and stay
  faithful to the corpus. Add `EvalResult.grounding` (Float, nullable) and keep
  the judge's detail in `full_result`. Null when no corpus is attached, so
  existing rows and corpus-free assignments are unaffected.

### 2.3 Frontend
- Corpus manager on the instructor assignment view: drag-drop upload, per-file
  index status, delete, and an explicit "the evaluator scores against these
  files" statement.
- Student-facing visibility is an open question (9). Build the API so the corpus
  can be exposed read-only later without a schema change.

### 2.4 Acceptance
- Instructor uploads three documents, status reaches `ready`, and a subsequent
  student turn produces an eval whose grounding rationale cites corpus content.
- Detaching the corpus mid-assignment degrades to rubric-only scoring with no
  errors and no orphaned rows.
- An assignment with no corpus behaves exactly as it does today (regression test).


---

## Phase 3 — Design A as the control arm

**Goal.** Preserve the existing solo feed experience as a comparison condition,
with the two specified changes.

### 3.1 Arm and policy configuration
- `ClassroomChallenge.study_arm` — `control_solo_feed` | `collab_coach_artifact`.
- `ClassroomChallenge.revision_policy` (JSON) and per-session `feed_enabled`,
  stored in the existing `Challenge.sessions_data` structure so it varies by
  session number without a new table.
- The solo `/ws` path is modified additively. No destructive refactor of the
  control arm, so control-arm behavior stays comparable across the study.

### 3.2 Consequential post-feed revision
- After the feed is shown for a designated turn, the student must submit one
  revision that **counts**: it is the scored artifact of record for that session.
- `EvalResult.is_graded_revision` (Boolean) marks it; the session cannot be
  completed without it; the pre-revision score is retained for the delta.
- Events: `feed.shown`, `revision.opened`, `revision.submitted`, with the score
  before and after in the payload.

### 3.3 Feed-disabled task
- A later session runs with `feed_enabled = false`: the client shows no feed, and
  the server **still scores every turn**. Removing the intervention must not
  remove the measurement.
- Events: `feed.suppressed` on each turn, so the arm is legible in the log
  rather than inferred from a config table at analysis time.

### 3.4 Acceptance
- One student, one challenge, sessions 1 and 2 with feed, session 3 without, all
  three fully scored server-side, all three distinguishable in the log.
- The consequential revision is enforced server-side, not only in the UI.

---

## Phase 4 — Contested input

**Goal.** Surface a teammate contribution and a coach output that diverge on the
same subproblem, and record which the student adopts and whether they checked
either.

### 4.1 Data model
- `contested_pair` — `id`, `group_session_id`, `subproblem_key`, `option_a_ref`
  (artifact revision or event), `option_b_ref` (coach message), `origin`
  (`instructor_scripted` | `auto_detected`), `surfaced_to_user_id`,
  `surfaced_at`.
- `contested_response` — `pair_id`, `user_id`, `adopted` (`a` | `b` | `neither` |
  `merged`), `inspected_a`, `inspected_b` (both derived from real read events,
  never assumed), `dwell_ms_a`, `dwell_ms_b`, `rationale_text`, `responded_at`.

### 4.2 Two detection strategies, shipped in order
1. **Instructor-scripted pairs** (study v1). The instructor authors divergent
   option pairs per subproblem in advance. Deterministic, reliably triggered,
   and comparable across teams, which matters more than realism for a first run.
2. **Auto-detected divergence** (behind a flag). An LLM judge compares a
   teammate's contribution against the student's coach output on the same
   subproblem, scoring both against the Phase 1 corpus. This is where Option D
   pays off directly: with ground truth you can label which option was actually
   better, so adoption becomes measurable as accuracy rather than mere
   preference.

### 4.3 Dependency
Both strategies need a notion of subproblem. Either the instructor decomposes
the assignment into subproblems (an addition to `sessions_data`) or the system
segments contributions automatically. This is open question 2 and blocks the
phase.

### 4.4 Acceptance
- A scripted contested pair surfaces at the intended point, the student's choice
  is recorded, and inspection flags come from actual read events. A student who
  adopts without expanding either option is recorded as an uninspected adoption.

---

## Phase 5 — Routed verification

**Goal.** Assign one student's output to a teammate for review, and record
whether the check happened, was duplicated or was skipped.

### 5.1 Data model
- `verification_assignment` — `id`, `group_session_id`, `target_ref`
  (artifact revision or event), `author_user_id`, `reviewer_user_id`,
  `assigned_at`, `due_at` or `due_turn`, `status` (`pending` | `completed` |
  `skipped` | `expired` | `duplicated`), `routing_policy`.
- `verification_response` — `assignment_id`, `reviewer_user_id`, `verdict`
  (`correct` | `incorrect` | `unsure`), `comment`, `checked_against_corpus`,
  `evidence_refs`, `opened_at`, `submitted_at`.

### 5.2 Routing and outcome classification
- `ClassroomChallenge.verification_policy` — `none` | `round_robin` | `random` |
  `instructor_assigned`. Round-robin excluding self is the default.
- Outcomes are derived, not self-reported:
  - **happened** — a response exists and read events show the target was opened.
  - **skipped** — no response, or a response with no preceding read event, which
    is the more interesting case and is only detectable because Phase 2 logs
    reads as first-class events.
  - **duplicated** — two or more reviewers responded to the same target.

### 5.3 Frontend
- A review inbox in the workspace ("Review Sam's step 2"), a verdict form, and a
  verified or unverified badge on the relevant artifact section.

### 5.4 Acceptance
- A four-person team produces a full round-robin of assignments, and the three
  outcome classes are each reproducible in a seeded test.

---

## Phase 6 — Coach prominence as a configuration flag

**Goal.** Make coach prominence an experimental condition rather than a
hardcoded product choice.

- `ClassroomChallenge.coach_prominence` — `ambient` | `on_request` | `isolated`.
  - **ambient** — the coach reacts to artifact changes unprompted, and its output
    is visible in the shared space.
  - **on_request** — the coach responds only when addressed. This is today's
    behavior and the natural default.
  - **isolated** — the coach is reachable but its output never flows into the
    shared artifact automatically. Importing it requires an explicit, logged copy
    action.
- Implementation: one `CoachPolicy` object resolved once per session, controlling
  artifact injection, unsolicited turns, shared-space posting rights and UI
  placement. Every handler reads the policy object. No `if prominence ==` checks
  scattered through the websocket handlers, because that is how conditions drift
  apart mid-study.
- The resolved policy is written onto the session row **and** onto every event's
  `condition` field, so an exported log is self-describing.

### Acceptance
- The same assignment run under all three settings produces materially different
  logs from an identical script of student actions, and the setting is
  recoverable from the export alone.

---

## Phase 7 — Research outputs and data hygiene

- **Export bundle** (instructor and admin): per session, a JSONL event log,
  artifact revision history, eval results, computed turn-taking metrics and
  condition metadata, consent-filtered per row and pseudonymized through the
  existing `anonymize.py` path, which must be extended to cover every new table.
- **Codebook and schema versioning**: `docs/event-schema.md`,
  `docs/metrics-codebook.md`, both with a version field echoed in API responses.
- **Consent and IRB**: the new data types (artifact content, read and dwell
  events, verification verdicts, contested-input choices) go beyond what the
  current research notice in `ConsentGate.jsx` describes. The consent copy needs
  updating and, most likely, an IRB amendment. This should start early, in
  parallel with Phase 1, because it can gate the first real run.
- **Volume control**: dwell and read events are the chatty ones. Batch on the
  client, rate-limit on the server, index on `(session, seq)`, and set a
  retention policy for heartbeats distinct from the one for semantic events.

---

## Dependency order

```
Phase 1  SPINE — private coaches + shared artifact + event log (reads included)
   |     Must be right the first time. Nothing below is recoverable without it.
   |
   +--> Phase 2  Reference corpus — retrofittable; can re-score archived transcripts
   |        |
   |        +--> feeds Phase 4: labels which contested option was actually better
   |
   +--> Phase 4  Contested input      [also blocked on subproblem decomposition]
   +--> Phase 5  Routed verification  [derives its outcomes from Phase 1 read events]
   +--> Phase 6  Prominence flag      [cheap if the policy object lands with Phase 1]
   |
   +--> Phase 3  Control arm — parallelizable, touches the solo path almost only
   |
   +--> Phase 7  Export, codebook, consent — starts now, closes last
```

Phase 3 is the piece that parallelizes cleanly. Phases 4, 5 and 6 are the
follow-on tickets the PI describes: each is a reading of the log or a small
addition to the same architecture.

## Rough effort

| Phase | Size | Main risk |
|---|---|---|
| 1 Spine: coaches + artifact + log | L | Concurrency (per-user locks, artifact versioning, event ordering) and read fidelity |
| 2 Reference corpus | M | Vector-store indexing latency and the evaluator agent refactor |
| 3 Control arm | S | Low. Additive config plus one UI step |
| 4 Contested input | M | Blocked on the subproblem decomposition decision |
| 5 Routed verification | M | Outcome classification is only as good as read-event fidelity |
| 6 Prominence | S | Small only if the policy object lands with Phase 1 rather than after |
| 7 Research outputs | M | Consent and IRB timing, not engineering |

## Open questions for the PI

These are the decisions that change what gets built, ordered by how early they
bite.

1. **Roles.** What is the role taxonomy for role-scoped coaches, who assigns
   them, and do they rotate between sessions? Blocks Phase 1.
2. **Subproblems.** How does the system know two contributions address the same
   subproblem: instructor-authored decomposition, or automatic segmentation?
   Blocks Phase 4 and shapes the artifact's structure.
3. **Artifact shape.** Free-form document, fixed sections per subproblem, or
   code? This determines the write-conflict model and how granular a read event
   can be. Blocks Phase 1's UI.
4. **What counts as a read.** Panel open, dwell past a threshold, section
   expand? And does a coach-mediated read, where the artifact enters the
   student's prompt without the student looking at it, count as that student
   reading a teammate's work? This is a measurement definition, not an
   implementation detail, and the turn-taking index depends on it.
5. **Condition assignment.** Is the unit of randomization the section, the team
   or the session, and can one student experience both arms?
6. **The human backchannel.** Group chat is currently firewalled by design from
   prompts, evaluation and export. Does it now enter the research record as
   content, as metadata only, or stay excluded?
7. **Consequential revision.** Consequential in what sense: it replaces the
   score, it is the only graded artifact, or the session cannot be completed
   without it?
8. **Corpus visibility.** Is the reference corpus evaluator-only ground truth, or
   is it also readable by students? This is a large fork in what the study
   measures.
9. **Verification and prominence interaction.** When a reviewer checks a
   teammate's output, do they see what the coach said about it? Under `ambient`
   they plausibly would, and under `isolated` they would not, which makes the two
   mechanisms interact.
