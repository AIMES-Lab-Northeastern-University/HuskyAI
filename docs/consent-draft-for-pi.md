# Consent copy and IRB amendment — draft for the PI

**Status: DRAFT. Not shown to students.** Nothing in this document is live. The
wording students see is still the old text in
`frontend/src/components/ConsentGate.jsx` and the Research & Data toggle in
`frontend/src/pages/Settings.jsx`. It changes only after the PI approves new
wording and the IRB approves the amendment. This covers
`docs/collab-study-pending.md` items #1 (consent/IRB) and #3 (team chat); the
team-chat paragraph below depends on the #3 decision.

---

## 1. What the current notice covers, and what it does not

The notice today says: *"Your conversations and prompt scores help us improve
the platform and train models that teach better prompting."*

The collaborative study now records the following. None of it is described:

| Data | Where it is stored | In the research export? |
|---|---|---|
| Text each student writes in the shared team document, every version | `artifact_revisions` | Yes, scrubbed |
| Every time a student opens the document or expands a teammate's section, and how long it stayed open | `study_events` (`open`, `section_expand`, `dwell`) | Yes |
| When a student's own coach was shown the team document | `study_events` (`read_by_coach`) | Yes |
| Peer-review verdicts and written rationales | `verification_responses` | Yes, scrubbed |
| Which of two answers a student picked in a contested pair, and whether they opened each one | `contested_responses` | Yes, scrubbed |
| Derived behaviour measures: contribution share, turn-taking equality, alternation, reliance on the coach | computed from `study_events` | Yes |
| Team chat between students | `group_chat_messages` | **Only if the PI turns it on** (section 3) |

## 2. Questions for the PI and IRB beyond the new data types

These came up while reading the code. Each one is a statement the notice makes,
or a behaviour it doesn't mention, that the IRB may want addressed. Items 1 and
5 are already built behind settings that change nothing until turned on.

1. **There is no way to decline.** The gate has only "Continue", and the
   platform can't be used without clicking it. A student can turn research use
   off afterwards in Settings. Most protocols require that research
   participation be voluntary and separate from using a course tool. Decide
   whether the gate needs a "Use HuskyAI without taking part" option.
   **Built, off:** setting `RESEARCH_NOTICE_ALLOW_DECLINE=1` shows that button.
   Clicking it counts as seeing the notice and leaves research consent off.
2. **"Anonymized" overstates what happens.** Ids are *pseudonymised* with a
   keyed hash that stays stable across exports, so one student's rows can be
   linked over time. Free text is scrubbed by pattern (emails, phone numbers,
   NUIDs, SSNs, URLs, and known names). The code itself calls this
   *best-effort* (`backend/anonymize.py`): a street address or an unusual
   identifier can get through. Suggested wording: "de-identified".
3. **Team metrics include students who declined.** Consented-only exports leave
   out a declining student's rows. But team-level measures such as contribution
   share are still computed over the *whole* team, including that student
   (`backend/research_export.py`, "Metrics, computed from the FULL log"). This
   is deliberate: a share computed over part of a team is wrong. Still, the IRB
   should know that a declining student's activity shapes their teammates'
   numbers.
4. **"Train models."** Confirm that the approved protocol covers training
   models on student data, not only research analysis. If it doesn't, remove the
   phrase from both the gate and Settings.
5. **Re-consent.** Decide whether students who already accepted must accept
   the new wording. **Built, inactive:** each account now records which notice
   version it accepted. Raising `RESEARCH_NOTICE_VERSION` from 1 to 2 when the
   new wording ships shows the gate again to everyone who accepted version 1.
   Their first acceptance time is kept for audit. Limit to know: until a student
   accepts the new notice, their existing consent setting stays as it is. The
   gate blocks the app, so they can't generate new data until they respond,
   *except* that the gate lets students through if it can't reach the server
   (so a network blip doesn't lock anyone out). If the IRB needs consent to be
   off until re-accepted, that's a further small change.
6. **Everyone was once opted in automatically.** When the consent notice was
   first introduced, a one-time step marked **every existing student and every
   past score as research-consented**, whether or not the student had seen a
   notice (`backend/database.py`, "One-time backfill: make ALL pre-existing
   data research-usable"). Confirm that the protocol covers data collected
   before the notice existed. If it doesn't, those rows need excluding from
   research exports.
7. **Consent is captured per row, at the time of the action.** Turning research
   use off in Settings applies from that moment on and doesn't delete earlier
   rows. "To remove data already collected, contact your instructor" is the
   only removal path. Confirm that this matches the protocol's withdrawal
   procedure.

## 3. Team chat: the decision needed (#3)

Team chat is already stored so teammates can scroll back. Until now it was never
part of the research record. That is now a per-assignment setting in the
instructor's **Study settings** panel ("Team chat in research"). It defaults to
**Not recorded**, and it stays that way until the PI picks one of these:

| Option | What is recorded | Notes |
|---|---|---|
| **Not recorded** (current) | Nothing | No change needed to the consent text. |
| **Who and when only** | For each message: sender (pseudonymised), time, length in characters and words. No text. | Supports "who talked, how much, when" analysis. |
| **Full messages** | The above, plus the message text in the export, scrubbed of emails, phone numbers, ids and **every teammate's name** | Most useful. Also the most sensitive: students speak informally to each other. |

Two behaviours the PI should know:
- **Each message keeps the setting it was sent under.** Switching from "who and
  when" to "full messages" mid-study only adds text for messages sent *after*
  the switch.
- **Timing picks up late.** If the choice is "who and when", every session run
  while it is still "Not recorded" never gets that timing. The text is stored,
  so "full messages" chosen later does not lose text. "Who and when" chosen
  later cannot recover the timing of messages sent while it was off. So decide
  before the first real session.

## 4. Proposed wording

Replaces the body of `ConsentGate.jsx`. Keep it short: the full detail goes in
the IRB information sheet, linked from the gate. Pick the team-chat paragraph
that matches the decision in section 3.

> **How we use your data**
>
> HuskyAI is a research project at the AIMES Lab, Northeastern University. If
> you agree, we use what you do here to study how students learn to work with
> AI, alone and in teams.
>
> **What we record.** Your conversations with the coach and their scores. In
> team assignments, also: what you write in the shared team document, when you
> open or read your teammates' work, peer reviews you write, and choices you
> make between suggested answers. We use these to measure how teams share work.
> For example, whether students read each other's contributions before writing
> their own.
>
> *[Team chat: choose one]*
> - *(Not recorded)* Messages you send your teammates in team chat are **not**
>   part of the research.
> - *(Who and when)* For team chat we record who sent a message, when, and how
>   long it was, but **not** what it said.
> - *(Full messages)* Messages you send your teammates in team chat are included,
>   with names, emails and similar details removed.
>
> **How it is protected.** Research data is de-identified: your name, email and
> account id are replaced with a code, and we remove personal details we can
> detect in what you write. Only the research team sees it.
>
> **Your choice.** Taking part in the research is voluntary and does not affect
> your grade. *[If a decline option is added:]* You can use HuskyAI without
> taking part. You can stop anytime in **Settings**; this applies from then on.
> To remove data already collected, contact *[name / email from the protocol]*.
>
> ☐ I agree to take part in the research as described.
>
> *[Continue]*   *[Use HuskyAI without taking part]*

Update the Settings toggle text (`Settings.jsx`, "Research & Data") to match:
the same list of what is recorded, and "de-identified" in place of "anonymized".

## 5. Checklist

- [ ] PI picks the team-chat option (section 3).
- [ ] PI answers the questions in section 2.
- [ ] PI approves the wording in section 4, with the chosen team-chat paragraph.
- [ ] IRB amendment filed with the table from section 1 and the approved wording.
- [ ] IRB approval received.
- [ ] Engineering: put the approved wording into `ConsentGate.jsx` and
      `Settings.jsx`.
- [ ] Engineering: in the same deploy, set `RESEARCH_NOTICE_VERSION=2` so
      everyone sees the new wording, and `RESEARCH_NOTICE_ALLOW_DECLINE=1` if
      a decline option was approved (edit the button label if the approved
      wording differs).
- [ ] Engineering: set "Team chat in research" on each study assignment to the
      chosen option.
- [ ] All of the above live **before** the first real study session.
