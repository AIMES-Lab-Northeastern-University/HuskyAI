# Decisions needed before the first real study run

> **DRAFT for team review.** The recommendations below are a starting point for
> the team to confirm or change before this goes to the PI.

**To:** Prof. John P. Wihbey (PI)
**From:** HuskyAI engineering team
**Re:** Collaborative study, items 2, 3 and 4 of `docs/collab-study-pending.md`
**Reading time:** about 10 minutes. Each item ends with a question you can answer with one letter.

---

## What is blocked, and why now

The collaborative study (branch `feature/collab-study-phase-1`) is built and
tested, but three research decisions are still open. Each one already has a
safe default in the code. The defaults are deliberately conservative; they are
not choices the team has made on your behalf.

These need answering **before the first real session**, not after:

- **Changing a definition mid-study splits the dataset.** Sessions run under one
  setting are not comparable with sessions run under another, and nothing in
  the data can repair that afterwards.
- **Some data can't be collected after the fact.** If team-chat timing is not
  recorded during a session, it is gone for that session (item 3).
- **The consent wording depends on item 3.** See the dependency below.

| # | Decision | Default shipped today | Team recommendation |
|---|---|---|---|
| 2 | Role taxonomy for role-scoped coaches | No roles (every coach identical) | **A**: no roles for the first run |
| 3 | Does team chat enter the research record? | Not recorded | **B**: who and when only, no text |
| 4 | What is a team's PEI? | Both a team mean and per-student averages are shown | **B**: no team PEI; student is the unit |

### Dependency: item 1 (consent copy and IRB amendment)

Item 1 is not decided in this memo, but it gates the first run and has the
longest lead time. The consent notice students see today
(`frontend/src/components/ConsentGate.jsx`) does not describe most of what the
collaborative study records: shared-document text, read events, peer reviews,
contested-answer choices. `docs/consent-draft-for-pi.md` has the full list,
proposed wording, and seven questions for you and the IRB.

**Your answer to item 3 changes the consent text.** The draft has one paragraph
for each team-chat option, so the wording can't be finalised until item 3 is
answered. Items 2 and 4 don't change the consent text as drafted. Whether the
IRB protocol needs to mention roles or team-level scores is for you to confirm.

### Reply template

Copy, fill in, and send back. A letter is enough; add a note only if you want
something different from the options.

```
Item 2 (roles):        [A / B / C / D]   notes:
Item 3 (team chat):    [A / B / C]       notes:
Item 4 (team PEI):     [A / B / C / D]   notes:
Item 4 follow-up (show teammates' scores to each other?):  [yes / no]
Item 1: IRB amendment owner and expected filing date:
```

---

## Item 2: Role taxonomy for role-scoped coaches

### Background

The study design calls for each student on a team to hold a role, such as a
particular responsibility within the task. That student's private AI coach would
be told the role and would coach them in it. Roles are a way of structuring
collaboration: they can make contributions more distinct and change who reads
whose work. Roles are also an experimental manipulation in their own right. If
roles are used, a difference between students or teams could come from the role
rather than from the coaching condition being studied.

### What the system does today

**No roles.** Every student's coach gets the same instructions. The event log
has a `role_label` field on every event, but it is always empty. There is
nowhere yet to store a student's role (no column on team membership), nothing
assigns one, and no coach prompt mentions roles.

**Why this default.** Inventing a taxonomy would build a study decision into the
code. An empty field is honest: an exported log that says "no role" is accurate.
A placeholder role would mislabel every event.

### Options

| | Option | Research consequences | Engineering cost |
|---|---|---|---|
| **A** | **No roles for the first run.** Run the role-free version first and add roles in a later wave as a separate condition. | Simplest to interpret: coaching condition is the only manipulation. Role-free sessions are a clean baseline. Later role sessions are a *different condition*, not comparable without modelling roles. Departs from the original design, which calls for role-scoped coaches. | None |
| **B** | **Fixed roles, assigned by the instructor.** You define a role list per assignment; the instructor assigns each student before the session. | Roles are controlled and recorded on every event, so analysis can stratify by role. Assignment can be randomised or balanced. Instructor workload per session. Role list must be defined by you. | 2–3 days: storage plus migration, instructor assignment UI, role injected into that student's coach, role stamped on every event, tests |
| **C** | **Fixed roles, chosen by students.** Same role list; each student picks before starting. | Self-selection confounds role with student traits (confident students pick the lead role). Weaker for causal claims about roles, but more natural for students. | B plus about 1 day (student picker, rules for duplicates and late joiners) |
| **D** | **Roles assigned automatically and rotated each session.** System assigns at random or in rotation across a multi-session challenge. | Strongest design for separating role effects from student effects: each student holds several roles over time. Needs enough sessions per team for rotation to complete. Students lose continuity in a role. | B plus 0.5–1 day (assignment and rotation logic) |

Whichever option is chosen, the role names themselves must come from you. The
repo has no proposed taxonomy, and the team won't invent one.

### Team's recommendation: A

Run the first real session without roles. It isolates the coaching and
shared-document conditions, which are already built and instrumented, and avoids
a manipulation whose effect we couldn't separate from them in a first run. If
roles are central to the research question, then **D** is the stronger design
and **B** is the practical one; choose and send the role list, and the work is
2–4 days.

### Question to answer

> **Item 2: For the first real run, should coaches be role-scoped? A (no roles),
> B (instructor assigns), C (students choose), or D (system assigns and rotates)?**
> If B, C or D, please also send the role names and say whether roles rotate
> between sessions.

---

## Item 3: Does the team chat enter the research record?

### Background

In the collaborative workspace, students have a team chat pane for talking to
each other. It is deliberately walled off: no coach ever sees it, and it is
never scored. The pane tells students it is "not seen by any coach". The
question is whether what students say to each other there becomes research
data. This matters for the study: a lot of real coordination ("I'll take
section 2", "read mine first") happens in that chat. It is also the most
sensitive data in the system, because students talk to each other informally.

### What the system does today

Already built as a per-assignment setting, "Team chat in research", in the
instructor's Study settings panel. Three modes:

- **Not recorded** (`off`, the default). Messages are saved only so teammates
  can scroll back. No research event is created. Nothing is exported.
- **Who and when only** (`metadata`). For each message, a research event records
  the sender (pseudonymised in the export), the time, and the length in
  characters and words. No text.
- **Full messages** (`content`). As above, plus the message text in the export,
  scrubbed of emails, phone numbers, ID numbers, URLs and **every teammate's
  name**.

Two behaviours that affect your choice:

1. **Each message keeps the mode it was sent under.** Switching an assignment
   from "who and when" to "full messages" mid-study adds text only for messages
   sent after the switch. Earlier messages never gain text in the export.
2. **Timing is not recoverable.** If a session runs under "Not recorded", there
   are no events for its messages, so choosing "who and when" later does not
   recover them. The raw text is still in the database for team replay, but the
   export does not include it, and using it would need a code change *and*
   consent that covers it.

**Why this default.** The current consent notice does not mention team chat, so
recording nothing is the only mode that is safe before the IRB amendment.

Scrubbing is best-effort. It catches patterns and known names, but a street
address or an unusual identifier can get through. This is why the consent draft
says "de-identified" rather than "anonymized".

### Options

| | Option | Research consequences | Consent / IRB | Engineering cost |
|---|---|---|---|---|
| **A** | **Not recorded** | No data on student-to-student coordination. Can't distinguish "they didn't talk" from "they talked in chat". Timing for these sessions can never be recovered. | No team-chat change to the notice; uses the "not recorded" paragraph. | None |
| **B** | **Who and when only** | Answers who talked, how much, and when, relative to writing and reading in the shared document (for example, "did a team talk before its first write?"). Says nothing about what was said. Keeps C open for later sessions. | One sentence in the notice. Low sensitivity: no student words leave the database. | Setting change only. No chat measures are computed yet: the turn-taking metrics use the shared document, not chat, so chat measures would be a codebook addition (about 1 day each, versioned). |
| **C** | **Full messages** | Richest data: allows analysis of what students said to each other (coordination, disagreement, delegation to the AI). Also includes everything in B. | Most sensitive. Students speak casually and may mention third parties or personal details that scrubbing misses. The IRB is likely to scrutinise this most. The export includes a message only if its sender had research consent at the time, but a consenting student's message can still be *about* a teammate who declined. | Setting change only. |

**Effect on student behaviour (B and C).** Once the notice says team chat is
recorded, some students will talk less freely, or move to channels nobody
records (Discord, texting, talking in person). B probably has less of this
effect than C, because no words are kept. No option captures off-platform
conversation, and analysis should treat chat volume as a lower bound. Under
B or C we also suggest changing the in-pane label from "not seen by any coach"
to say the chat is recorded, so the pane does not imply privacy it doesn't
have. That is about one hour of work, and the wording is for you to approve.

### Team's recommendation: B (who and when only)

B captures the one thing that can't be recovered later: the timing of the team's
coordination relative to its reads and writes, which is what the study's central
measures are about. It also has the lightest consent burden that still records
anything. If your research questions require the *content* of deliberation,
choose C, and choose it from the first session: text is exported only for
messages sent under C, so sessions run under B would have no text to compare.
Whichever you choose, apply it to every study assignment from the first real
session onwards.

### Question to answer

> **Item 3: Which team-chat mode for the study? A (not recorded), B (who and when
> only), or C (full messages, de-identified)?**
> Your answer selects the team-chat paragraph in the consent draft
> (`docs/consent-draft-for-pi.md`, section 4) and goes into the IRB amendment.

---

## Item 4: What does a team's PEI mean?

### Background

The PEI (Prompt Effectiveness Index) scores **one student's prompt** to the AI,
turn by turn, on five weighted dimensions (0.25 PSQ, 0.25 CCM, 0.20 TSI,
0.15 CLM, 0.15 RAS). It is a measure of prompting skill. In the collaborative
arm, each student has their own private coach, so each student gets their own
stream of PEI scores. There is no shared conversation, and no single number is
obviously "the team's score". PEI does not score the shared document. It scores
what each student asked their coach.

### What the system does today

When a team ends a session, the system reports **both**:

- a **team mean**: the average of every scored turn from every member, pooled,
  and
- **each member's own average** and turn count.

All teammates see both on the end-of-session banner, including each teammate's
average by name. The team mean is also saved as the team session's average so
existing instructor views have something to display. The system does not set a
"best score" for the team.

**Why this default.** Choosing one definition would quietly answer a research
question. Reporting both decides nothing and keeps every option open, because
every per-turn score is stored with its student either way.

**A detail you should know about the current team mean.** It pools all turns,
so it is *turn-weighted*. A student who sent 20 prompts counts four times as
much as one who sent 5. A team where one student dominates the coach gets a
team mean that mostly reflects that one student. That may or may not be what
you want "team PEI" to mean.

### Options

| | Option | Research consequences | Engineering cost |
|---|---|---|---|
| **A** | **Keep the team mean as now (pooled over all turns).** | Easy to explain, but weighted towards the most active student. Confounds prompting quality with participation, which the turn-taking metrics already measure separately. | About 2 hours (write the definition into `docs/metrics-codebook.md`) |
| **B** | **No team PEI. The student is the unit of analysis.** Report per-student averages only; team-level questions use the turn-taking metrics (contribution share, read-before-write, coach reliance). | Keeps PEI meaning one thing in both arms: one student's prompting. Directly comparable with the solo control arm, where PEI is also per student. Team effects are modelled statistically (students nested in teams) rather than baked into one number. | About half a day (codebook entry; stop presenting the team mean as a score; instructor views show per-student values) |
| **C** | **Team PEI as the mean of member averages** (each student weighted equally), optionally reported with the spread across members. | Avoids the turn-weighting problem in A. Still mixes several students' prompting into one number. Sessions using A and C are not comparable. | About half a day |
| **D** | **Score the shared document instead.** | A genuinely team-level outcome, but it is **not PEI**: PEI is defined over prompts, not documents. Would need a new rubric and judge, validation, and a new codebook entry. | 1–2 weeks plus validation. Not feasible before a first run. |

Max (the best member's average) is also possible, but it measures the team's
strongest prompter rather than the team. We don't recommend it.

**Related decision: should teammates see each other's scores?** Today every
teammate sees every member's average PEI by name at session end. Students can also
see their own PEI live during the session. Showing teammates' scores invites
social comparison and could change how students prompt or divide work in later
sessions. Hiding them is a small change (about 2 hours). This is your call; the
reply template has a line for it.

### Team's recommendation: B (no team PEI; the student is the unit)

PEI was designed as a measure of one student's prompting. Keeping
it that way makes the collaborative arm directly comparable with the solo
control arm, and leaves team-level questions to the turn-taking metrics, which
were built for them. If a single team number is needed for reporting to
instructors, use **C** (equal weight per student), labelled clearly as a summary
and not as a team score. We also lean towards *not* showing teammates' scores to
each other during the study, but that depends on the study design, which is for
you to decide.

### Question to answer

> **Item 4: How should a team's PEI be defined? A (pooled team mean, as now),
> B (no team PEI; per-student only), C (equal-weight mean of member averages),
> or D (score the shared document, deferred).**
> Also: should teammates see each other's PEI at session end? Yes or no.

---

## After you reply

- The team writes each definition into `docs/metrics-codebook.md`, versioned, so
  any number in a paper traces back to the definition that produced it.
- Item 3's answer goes into the consent wording and the IRB amendment (item 1),
  and is applied to every study assignment before the first real session.
- Engineering estimates above assume the decision arrives as answered here.
  Anything outside the options, such as a custom role scheme, will be re-estimated.

Sources for every statement about current behaviour: `docs/collab-study-pending.md`,
`docs/consent-draft-for-pi.md`, `docs/event-schema.md`, `docs/metrics-codebook.md`,
`backend/study_policy.py`, `backend/main.py` (`_log_team_chat`, `_end_coach_session`),
`backend/research_export.py`, `frontend/src/pages/CoachWorkspace.jsx`.
