# Study event schema

**Schema version: 1.0.0** — echoed as `schema_version` in API responses. Any
change to a field's meaning is a version bump, not a silent edit.

One table, `study_events`, holds every action in a collaborative-study session
in a single total order. It is append-only. Nothing in it is ever updated or
deleted, including during a session.

## Why a single ordered log

`artifact_revisions` answers *who wrote what*. Only this log answers *who looked
at whose work before writing*, which is what the study is asking. That question
is unanswerable from a database of final states, so a read that goes unrecorded
is lost permanently — unlike, say, a grounding score, which can be recomputed
from an archived transcript at any time.

Three properties follow, and they are structural rather than conventional:

- **Reads and writes share one sequence space.** `seq` is monotonic per session
  and assigned server-side. Whether a student read a teammate's contribution
  *before* or *after* writing their own is read straight off `seq`. Reads in a
  side table with their own clock could not answer it.
- **No sampling.** `idempotency_key` is unique, so client delivery is
  at-least-once with dedupe on ingest. Under-recording is not a tunable.
- **`client_ts` is never used for ordering.** It is kept for latency analysis
  and preserved across a buffered reconnect flush; `seq` and `server_ts` are
  authoritative.

## Fields

| Field | Meaning |
|---|---|
| `id` | UUID |
| `group_session_id` | Set for collaborative sessions. Exactly one scope column is set. |
| `user_challenge_session_id` | Set for the solo control arm. |
| `classroom_id`, `challenge_id` | Denormalised for analysis-time filtering. |
| `seq` | Monotonic per session, server-assigned under a per-session lock. **The ordering is the finding.** |
| `actor_user_id` | Whose action. For `read_by_coach`, the student whose prompt the artifact entered. |
| `actor_kind` | `student` \| `coach` \| `system` |
| `role_label` | The actor's role-scoped label. Currently always NULL — the role taxonomy is an open question for the PI. |
| `target` | `coach` \| `artifact` \| `group_chat` \| `feed` \| `contested` \| `verification` |
| `action` | See the vocabulary below. |
| `ref_id` | The row this event points at (a `Message.id`, an `artifact_sections.id`, …). Untyped: targets live in different tables. |
| `payload` | Action-specific JSON. |
| `client_ts` | Client-supplied, preserved across a buffered flush. Latency analysis only. |
| `server_ts` | Authoritative wall-clock. |
| `idempotency_key` | Unique. NULL for server-emitted events, which cannot be double-delivered. |
| `consent_research` | Snapshotted per row at write time, so the export is immune to a later toggle. |
| `condition` | Resolved experimental condition (`arm`, `prominence`, `corpus`), written onto every row so an exported log is self-describing. |

## Action vocabulary

### `target = artifact`

| Action | Emitted when | Payload | Retention |
|---|---|---|---|
| `write` | A section write is **accepted**. A rejected (conflicting) write emits nothing — it is not a contribution. | `section_key`, `version`, `origin`, `bytes_added`, `bytes_removed` | permanent |
| `open` | A person opens the artifact panel. Not on initial render. | — | permanent |
| `close` | A person closes the panel. Bounds an `open`. | — | permanent |
| `section_expand` | A person expands one section. **The finest-grained read, and the one that makes "did they look at Sam's step 2?" answerable.** | `section_key` | permanent |
| `dwell` | Time a section was expanded. | `section_key`, `duration_ms` | **may be downsampled or expired** |
| `read_by_coach` | The artifact was injected into a student's coach prompt. `actor_kind = coach`, attributed to that student. Never merged into human opens. | `section_keys` | permanent |

### `target = coach`

| Action | Emitted when | Payload |
|---|---|---|
| `turn` | A completed coach turn is persisted. | `turn`, `pei` |

### `target = verification` (Phase 5)

| Action | Emitted when | Payload |
|---|---|---|
| `assigned` | A contribution is routed to a teammate. Written *before* the write is acked, so a client that closes immediately cannot leave a contribution unrouted. | `section_key`, `author`, `policy` |
| `responded` | A reviewer submits a verdict. Whether they actually read the work is **not** recorded here — it is derived from their `section_expand` events. | `verdict`, `section_key` |

Outcomes (`happened`, `skipped_unread`, `skipped_no_response`, `duplicated`,
`expired`) are computed by `verification.classify`, never stored. A reviewer who
answers without reading has told you they were willing to claim a check, not
that they performed one; that distinction only survives because reads are
first-class events sharing one sequence with writes.

### `target = contested` (Phase 4)

| Action | Emitted when | Payload |
|---|---|---|
| `surfaced` | A scripted divergent pair is shown to a student. | `subproblem_key` |
| `adopted` | The student picks a side. | `adopted` (a/b/neither/merged), `inspected_a`, `inspected_b`, `uninspected`, `subproblem_key` |

The subproblem is the artifact section key — choosing a sectioned artifact is
what answered the plan's blocking question about how two contributions are
known to address the same subproblem.

`inspected_a` / `inspected_b` are **derived from the log**, never asked of the
student, and the windows start when the pair was surfaced: reading the section
before the pair existed is not inspecting this contested option. `uninspected:
true` is the case the phase exists to catch — a student taking a side without
opening either answer.

Option A is always the human contribution and option B always the coach output,
fixed so "adopted A" means the same thing in every row. The API does not label
which is which, because labelling the source would measure trust in labels
rather than in the work.

### `target = feed` (control arm)

Whether the PEI feed appeared **is** the intervention, so it is recorded per
turn rather than inferred at analysis time from a config table that may have
been edited since. All are written *before* the client is notified, so a client
that disconnects the instant it receives its score cannot cancel the record.

| Action | Emitted when | Payload |
|---|---|---|
| `feed.shown` | The score was sent to the student. | `turn`, `pei` |
| `feed.suppressed` | The turn was scored and stored but **not** shown (a feed-disabled session). Written explicitly on every such turn: absence of `feed.shown` is indistinguishable from a logging bug. | `turn`, `pei` (the unseen score) |
| `revision.opened` | The feed was shown for the turn that requires a consequential revision. | `after_turn`, `pei_before` |
| `revision.submitted` | The student submitted the revision that counts. Its `EvalResult.is_graded_revision` is true; the pre-revision score is kept as its own row so the delta stays measurable. | `turn`, `pei_after` |

## What is deliberately *not* an event

- **Rendering.** Delivering the artifact on connect, and a teammate's screen
  updating from an `artifact_updated` broadcast, emit nothing. Counting either
  would manufacture reads for someone who never looked, and would inflate every
  read measure from the first session onwards.
- **Rejected writes.** A conflict is not a write. Logging it would inflate
  contribution share for a student whose text never landed.
- **The team backchannel.** `group_chat` is in the `target` vocabulary but
  nothing emits it yet: whether human-to-human discussion enters the research
  record as content, as metadata only, or not at all is an open question for the
  PI. The messages themselves are stored in `group_chat_messages` regardless, so
  deciding later loses nothing.

## Known limits

- **Single worker.** `seq` is allocated under an in-process lock
  (`backend/events.py`). Two Uvicorn workers would allocate the same number; the
  unique `(scope, seq)` constraint turns that into a retry rather than silent
  corruption, but multi-worker needs a DB sequence or Redis first.
- **`role_label` is unpopulated** pending the role taxonomy decision.

## Export

`GET /research/sessions/{id}/export?format=json|jsonl` — instructor and admin
only. Returns the ordered event log, artifact revision history, evaluations,
verification and contested-input outcomes, and the computed turn-taking
metrics, with schema and metrics versions travelling alongside the data.

Three rules the bundle enforces:

- **Consent is filtered per row from the snapshot each row captured at write
  time**, never from the user's current setting. Withdrawing consent today must
  not retroactively unexport turns shared last month; granting it must not
  sweep in rows written without it. Every research table carries
  `consent_research`: `eval_results`, `study_events`, `artifact_revisions`,
  `verification_responses`, `contested_responses`.
- **Turn-taking metrics are computed over the FULL session, not the
  consent-filtered subset.** A contribution share computed over part of a team
  is not that team's contribution share, and a reader could not detect the
  difference. Metrics describe the session; the rows are what may be shared.
- **`include_unconsented=true` is recorded in the bundle** as
  `consent_filtered: false`, so an archived file can never be mistaken for a
  consented one. It exists for an instructor reviewing their own section, not
  for research use.

Ids are pseudonymised with HMAC + `ANONYMIZE_SALT` (stable across exports, so
longitudinal analysis works), and every student-authored free-text field goes
through `anonymize.scrub()`. Scrubbing is best-effort pattern matching, not a
guarantee — see `docs/data-anonymization.md` before sharing anything externally.
