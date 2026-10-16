# Turn-taking metrics codebook

**Metrics version: 1.2.0** (`METRICS_VERSION` in `backend/analysis/turn_taking.py`,
echoed as `metrics_version` in every response.)

Changes in 1.2.0:
- `read_before_write`: a read only qualifies if a teammate's text was in that
  section **when it was read**. Before, any earlier expand of a section that was
  teammate-authored at write time counted, including expanding it while it was
  still empty or held only the reader's own text. 1.2.0 ratios can only be
  lower than or equal to 1.1.0 ratios on the same log.
- `coach_reliance`: writes with `origin` `coach_pasted` (coach text pasted
  into the editor) now count as coach adoption alongside `coach_copied`
  ("Copy to document"). Before, a paste counted as `student_typed`.

Changes in 1.1.0: `coach_reliance.ratio` draws both of its terms from eligible
writes only (see below).

Every other definition is unchanged since 1.0.0. Compare a metric across
versions only if its definition did not change between them.

Changing any definition here is a **version bump plus a codebook edit**, never a
silent fix. A number in a paper must be traceable to the definition that
produced it.

Computed by `compute_turn_taking(events, members)`, a pure function over an
ordered event list. It touches no database and no clock, so replaying an
exported log reproduces identical metrics — there is a test asserting exactly
that.

## Definitions

### `contribution_share[user]`
Accepted artifact writes by that user ÷ total accepted artifact writes.

Writes, not coach turns, because the shared artifact is the team's actual joint
output. Rejected (conflicting) writes are never logged, so a member cannot
inflate their share with text that did not land. A member who wrote nothing
appears as `0.0` rather than being absent — silence is a finding, not missing
data.

### `equality.gini`
Gini coefficient of the write counts. `0` = perfectly equal, approaching `1` =
one member did everything. `null` when there are no writes.

### `equality.normalised_entropy`
Shannon entropy of the share distribution ÷ `log(n_actors)`, giving `[0, 1]`.
`1.0` = every member contributed equally, `0.0` = one member contributed
everything. `null` with fewer than two actors.

Reported alongside Gini because they disagree usefully: entropy is more
sensitive to *how many* members participated at all, Gini to *how unequal* the
participants were.

### `alternation_rate`
Over artifact writes in `seq` order, the proportion of consecutive pairs whose
author differs. `1.0` = the writer changed hands every time; `0.0` = one member
wrote an uninterrupted block. `null` with fewer than two writes.

### `median_write_to_read_ms`
For each write, the time until the first `section_expand`/`dwell` **of that same
section by a different member**. Median across all such pairs.

Section-scoped deliberately: the question is how long a specific contribution
sat unread, not how long until the panel was next opened for any reason.
Excludes `read_by_coach` — see below.

### `writes_never_read_by_a_teammate`
Count of section writes with no subsequent read by anyone else.

Reported separately because a median hides it entirely: a team where half the
contributions were never opened can show a perfectly healthy latency.

### `read_before_write.ratio`
**The study's central measure.** Of writes that were *eligible*, the proportion
where the author had already expanded a section **while it held a teammate's
text**, earlier in the session. Reading an earlier version of a teammate's text
still counts; expanding a section that was empty, or held only the reader's own
text, does not (since 1.2.0).

`eligible_writes` counts only writes made when a teammate-authored section
actually existed to be read. A write cannot be "informed by a teammate" if no
teammate had written anything yet, so those are excluded from the denominator
rather than counted as failures — a convenient denominator would make early
turns look like students ignoring each other. `null` when nothing was eligible.

### `coach_reliance.ratio`
`coach_copied_eligible_writes ÷ (coach_copied_eligible_writes + teammate_informed_writes)`.

Both terms are adoption; the question is adoption of *whose* work. `origin` on
each write distinguishes text a student typed from text they took from their
coach: `coach_copied` (the "Copy to document" button) and, since 1.2.0,
`coach_pasted` (coach text pasted into the editor) both count as the coach's.
`null` when neither occurred.

**Both terms are restricted to eligible writes** — writes made when a
teammate-authored section already existed — so the ratio answers "when a
teammate's work was there to adopt, how often was the coach's taken instead?".
`teammate_informed_writes` can only ever be drawn from eligible writes, so a
numerator drawn from *every* write would compare two different populations: a
session whose only coach-copied write landed before anyone else had written
would report total coach reliance, when there was no teammate work available to
adopt. That is the same artefact `eligible_writes` exists to avoid. In 1.0.0 the
numerator was unrestricted; `coach_copied_writes` still reports that
unrestricted count for description, but it is not what the ratio divides.

`teammate_informed_writes` counts only `student_typed` writes that were preceded
by a teammate read — it is **not** the same number as
`read_before_write.informed_writes`, which is origin-agnostic. A student who has
read a teammate and then pastes coach output has adopted the coach's work, not
the teammate's; counting that write on both sides of the ratio would understate
coach reliance exactly where it matters most.

## Standing methodological notes

**Coach reads are never merged into human reads.** `read_by_coach` fires when
the artifact enters a student's prompt without them necessarily looking at it.
Whether that counts as the student having read their teammate's work is an open
question for the PI, and it stays answerable either way only because the two are
kept apart. Every metric above uses human reads only; coach reads are reported
as a raw count in `totals`.

**`dwell` may be downsampled or expired** under a future retention policy, while
`open`/`section_expand`/`read_by_coach` are permanent. No metric here depends on
`dwell` alone — `section_expand` carries the read signal — so an expired
heartbeat degrades precision, not validity.

**Null is not zero.** Every ratio returns `null` when its denominator is empty,
rather than `0.0`. "No eligible writes" and "nobody read anything" are different
findings and must not be collapsed.


## `grounding` (Phase 2)

Not a turn-taking metric, but scored per turn and stored on
`EvalResult.grounding`, so it belongs in the same codebook.

`grounding = (0.5 * coverage) + (0.5 * faithfulness)`, judged against the
assignment's reference corpus by a sixth judge that searches **only** that
corpus. Mixing the rubric store in would let a rhetorically well-formed answer
score well on grounding without matching the source material, which is the exact
confusion the dimension exists to avoid.

`NULL` whenever no corpus is attached, the corpus is not `ready`, or the corpus
contains nothing relevant to what the student is doing. An absent corpus match
is not a student failure, so it must not be recorded as a low score.

**Grounding is not part of the PEI.** PEI keeps its five weighted dimensions
exactly as defined above, so scores from corpus-bearing and corpus-free
assignments remain directly comparable — and so every score computed before
Phase 2 stays valid.

## Team PEI (collaborative-coach arm)

In the collaborative-coach arm each student has their own coach and their own
per-turn PEI, so there is no single number that is self-evidently "the team's
score". We do **not** blend one. Three things are reported separately:

1. **Each student's own average PEI** — in `per_student[user].avg_pei`.
2. **The team's collaboration measures** — the turn-taking metrics defined above
   (contribution share, equality, alternation, read-before-write, coach
   reliance). These describe *how* the team worked, not how well any one student
   scored.
3. **Team PEI** — a single convenience figure for instructor views, defined
   below. It is a summary of (1), never a substitute for reading the parts.

### `session_avg_pei` (team PEI) — equal-weight mean

`session_avg_pei` on a `GroupSession` is the **mean of the per-student average
PEIs**: each student contributes their own average once, regardless of how many
turns they took.

```
session_avg_pei = mean( avg_pei(student) for each student with ≥1 scored turn )
```

A student who produced no scored turn has no average and is **not counted** —
they neither raise nor lower the team figure.

It is always reported with its spread, `pei_range = {min, max}`, the lowest and
highest per-student average on the team. A lone number can hide a split team
(one strong student, one struggling); the range makes that visible.

**Why not pool every turn.** The previous placeholder averaged *all turns* across
the team (`sum of every turn's PEI / total turn count`). That weights a student
by how talkative they were: a student with 20 turns outweighed a teammate with
3, so the team score tracked participation volume, not shared performance.
Equal-weight means one student, one vote.

**This is a definition change (bump the metrics version when releasing).** Team
scores produced by the old pooled formula are **not** comparable with
equal-weight ones; do not mix them in the same analysis.

Computed once in `_coach_session_summary` (`backend/main.py`). It deliberately
does **not** touch `best_pei`, which remains the shared-coach arm's concept.
