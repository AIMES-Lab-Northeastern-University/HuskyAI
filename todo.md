# HuskyAI roadmap and TODO

Work in priority order **P1 → P11**. Last updated: 2026-04-14.

---

## Current state (today)

- App skeleton works end to end (frontend, backend, DB, Eval Model).
- Instructor tools are working (create, edit, assign, reorder, rename section, manage challenges from Challenges page).
- Reporting is working for instructors and admins (section analytics, student drill-down, admin overview analytics, classroom + user drill-down modals).
- Session completion now fully wired: "Mark as complete" button calls POST /complete, unblocking progress tracking and sequential unlock.
- Admin section complete: user list, promote/demote, user activity modal, classroom detail modal.
- Auth registration flow fixed: instructor registration auto-creates a section and redirects to instructor dashboard; admin registration blocked with "reach out to team" message.
- 3 new seed challenges added: The Case Analyst, The Data Interpreter, The Presentation Outliner.
- Biggest remaining gaps: password reset, pre-pilot hardening (P9).

---

## Next actions items

- [ ] P4: password reset — students will get locked out without it
- [ ] P9: run full pre-pilot checklist (CORS, JWT_SECRET, log level, .gitignore)
- [ ] P8: add CSV or JSON export for instructor analytics
- [ ] P3: more challenge content + QA matrix

---

## P1 Demo vs real app

Goal: visitors can try the product without an account; logged-in users hit the real API.

- [x] Landing page: **Try demo** and **Log in**
- [x] Public `/demo/...` routes (same screens as the app, sample data)
- [x] Demo banner + links to sign up / sign in (`DemoLayout.jsx`)
- [x] Demo home redirects to `/demo/dashboard`
- [x] Logged-in routes use auth and real classroom / challenge data

---

## P2 Database and hosting

- [x] Core tables: users, conversations, messages, eval results, challenges, sessions
- [x] Classrooms (sections): join codes, memberships, link challenges to sections
- [x] Class APIs: create section, join, browse, update, summary, instructor challenge list
- [x] Works on SQLite (local) and Postgres (e.g. Railway)
- [ ] Choose and lock one production Postgres host
- [ ] Written data policy (PII, what instructors see, retention)
- [ ] Optional: research consent / export rules in product copy + code

---

## P3 Challenge content

- [x] Seed challenges in the repo (`seed_challenges`)
- [x] New instructor challenges get a default session template
- [ ] More syllabus-aligned challenges and richer `sessions_data`
- [ ] QA matrix: every challenge → start session → chat → eval saved (automate where you can)
- [ ] Build a small gold set of transcripts (50 to 200) with expected rubric outcomes (In progress)
- [ ] Create a study on annotation websites to compare eval by our LLM agent vs human graders

---

## P4 Auth, onboarding, tests

- [x] Register, login, JWT, `/auth/me`
- [x] Password rules on the server; rate limits on auth routes
- [x] Login supports dev admin shortcut (`admin` / seeded email)
- [x] Role hints on login page; clearer API errors in the UI
- [x] Student joins a section with a code (Classroom, Settings, Browse)
- [x] Challenges list respects section assignments + test-as-student
- [x] Automated tests (auth, classrooms, challenges, smoke, E2E HTTP, rate limit)
- [ ] Email verification
- [ ] Password reset
- [ ] Optional: match password rules in the signup form UI

---

## P5 Instructor tools

- [x] Only instructors (or section admins) can create / manage challenges for their section
- [x] Create challenge and assign to section; list section challenges
- [x] Edit challenge, activate / deactivate, remove from section, reorder
- [x] Test-as-student toggle; test section option when creating a section
- [x] Instructor dashboard: section picker, join code, challenge list, create form
- [x] “Test preview” on student Challenges when applicable
- [ ] Edit `sessions_data` per session in the UI
- [x] Draft vs published workflow for challenges
- [ ] Soft-delete challenge (optional)
- [ ] Clearer audit trail / `updated_at` usage

---

## P6 Platform admin

- [x] Platform admin flag on user; sync emails from env on startup
- [x] Admin overview API (counts, classrooms, join codes, DB analytics block)
- [x] Admin page + sidebar link; dev seed admin for local QA
- [x] User list: promote / demote platform admin
- [x] Drill into a section: members, challenges, session analytics
- [x] Drill into a user: workspace stats, challenge sessions, recent conversations (metadata only), sections
- [ ] Deactivate or archive sections from the UI
- [ ] Activity logs
- [ ] Data exports from admin (see P8)

---

## P7 Evaluation quality

- [x] Retries and backoff when evaluation fails
- [x] Sanitize model output (scores, lists)
- [x] Safe fallback when evaluation is unavailable (user still sees a message)
- [ ] Frozen transcript regression set in repo
- [ ] Runbook for common eval failures

---

## P8 Reporting and metrics

**Section-wide (instructor)**

- [x] API: section analytics (students, sessions, workspace + eval counts, averages, by challenge, last activity)
- [x] Instructor UI: **Section activity** cards and tables from that API

**Per student (instructor)**

- [x] API: roster for a section (name, email, joined)
- [x] API: one student’s activity (workspace stats, challenge sessions, by challenge, session rows, **no chat text**)
- [x] Instructor UI: **Students** table + **View activity** modal

**Admin**

- [x] Overview API includes extra analytics from the DB
- [x] Admin UI shows those totals

**Still to build**

- [ ] Export CSV or JSON (section or student)
- [ ] Optional charts or PDF report
- [x] Admin: drill into one section or user (parity with instructor)
- [ ] Short policy: what instructors may export or store

**Other pages**

- [ ] Double-check Dashboard, Progress, Challenges for loading and empty states everywhere

---

## P9 Pre-pilot hardening

- [x] Happy-path HTTP E2E in CI (register, section, challenge, join, session)
- [ ] Full script with WebSocket + eval + DB checks (where keys allow)
- [ ] CORS, secrets, log level, `.gitignore` production checklist
- [ ] Close blocking bugs from smoke tests

---

## P10 Pilot

- [ ] Run 2–3 real users; keep a short issue log
- [ ] Go / no-go decision
- [ ] Short feedback survey

---

## P11 Misc

- [ ] “How it works” matches the real stack
- [ ] Check lab / showcase links
- [ ] Handoff doc (Slack / deploy)
- [ ] After pilot: dataset / evaluator tuning (only if needed)

---

## How tracks depend on each other

- [x] P1 demo, P2 schema, and P7 eval basics can ship in parallel (done enough to use)
- [x] P4, P5, P6, P8 build on classrooms (core paths done). Exports and admin tools still open
- [ ] Finish P9 before a real pilot (**P10**)
