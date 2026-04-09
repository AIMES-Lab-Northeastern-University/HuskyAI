# HuskyAI roadmap and TODO

Work in priority order **P1 → P11**. Last updated: 2026-04-08.

---

## Current state (today)

- App skeleton works end to end (frontend, backend, DB, Eval Model).
- Instructor tools are working (create, edit, assign, reorder challenges; test as student).
- Reporting is working for instructors and admins (section analytics, student drill-down, admin overview analytics).
- Biggest missing pieces are admin management UI (P6), and production hardening checklist (P9), Benchmarking for llm eval agent.

---

## Next actions items

☐ P2: lock production database confirm all backend changes 
☐ P8: add CSV or JSON export for instructor analytics
☐ P6: admin UI to manage users and sections
☐ P5: edit per-session content in the UI; draft / publish
☐ P9: run full pre-pilot checklist (E2E + ops)

---

## P1 Demo vs real app

Goal: visitors can try the product without an account; logged-in users hit the real API.

☑ Landing page: **Try demo** and **Log in**
☑ Public `/demo/...` routes (same screens as the app, sample data)
☑ Demo banner + links to sign up / sign in (`DemoLayout.jsx`)
☑ Demo home redirects to `/demo/dashboard`
☑ Logged-in routes use auth and real classroom / challenge data

---

## P2 Database and hosting

☑ Core tables: users, conversations, messages, eval results, challenges, sessions  
☑ Classrooms (sections): join codes, memberships, link challenges to sections  
☑ Class APIs: create section, join, browse, update, summary, instructor challenge list  
☑ Works on SQLite (local) and Postgres (e.g. Railway)  
☐ Choose and lock one production Postgres host  
☐ Written data policy (PII, what instructors see, retention)  
☐ Optional: research consent / export rules in product copy + code

---

## P3 Challenge content

☑ Seed challenges in the repo (`seed_challenges`)
☑ New instructor challenges get a default session template
☐ More syllabus-aligned challenges and richer `sessions_data`
☐ QA matrix: every challenge → start session → chat → eval saved (automate where you can)
☐ Build a small gold set of transcripts (50 to 200) with expected rubric outcomes (In progress)
☐ Create a study on annotation websites to compare eval by our LLM agent vs human graders

---

## P4 Auth, onboarding, tests

☑ Register, login, JWT, `/auth/me`
☑ Password rules on the server; rate limits on auth routes
☑ Login supports dev admin shortcut (`admin` / seeded email)
☑ Role hints on login page; clearer API errors in the UI
☑ Student joins a section with a code (Classroom, Settings, Browse)
☑ Challenges list respects section assignments + test-as-student
☑ Automated tests (auth, classrooms, challenges, smoke, E2E HTTP, rate limit)
☐ Email verification
☐ Password reset
☐ Optional: match password rules in the signup form UI

---

## P5 Instructor tools

☑ Only instructors (or section admins) can create / manage challenges for their section
☑ Create challenge and assign to section; list section challenges
☑ Edit challenge, activate / deactivate, remove from section, reorder
☑ Test-as-student toggle; test section option when creating a section
☑ Instructor dashboard: section picker, join code, challenge list, create form
☑ “Test preview” on student Challenges when applicable
☐ Edit `sessions_data` per session in the UI
☐ Draft vs published workflow for challenges
☐ Soft-delete challenge (optional)
☐ Clearer audit trail / `updated_at` usage

---

## P6 Platform admin

☑ Platform admin flag on user; sync emails from env on startup
☑ Admin overview API (counts, classrooms, join codes, DB analytics block)
☑ Admin page + sidebar link; dev seed admin for local QA
☐ User list: promote / demote platform admin
☐ Deactivate or archive sections from the UI
☐ Activity logs
☐ Data exports from admin (see P8)

---

## P7 Evaluation quality

☑ Retries and backoff when evaluation fails
☑ Sanitize model output (scores, lists)
☑ Safe fallback when evaluation is unavailable (user still sees a message)
☐ Frozen transcript regression set in repo
☐ Runbook for common eval failures

---

## P8 Reporting and metrics

**Section-wide (instructor)**

☑ API: section analytics (students, sessions, workspace + eval counts, averages, by challenge, last activity)
☑ Instructor UI: **Section activity** cards and tables from that API

**Per student (instructor)**

☑ API: roster for a section (name, email, joined)
☑ API: one student’s activity (workspace stats, challenge sessions, by challenge, session rows, **no chat text**)
☑ Instructor UI: **Students** table + **View activity** modal

**Admin**

☑ Overview API includes extra analytics from the DB
☑ Admin UI shows those totals

**Still to build**

☐ Export CSV or JSON (section or student)
☐ Optional charts or PDF report
☐ Admin: drill into one section or user (if you want parity with instructor)
☐ Short policy: what instructors may export or store

**Other pages**

☐ Double-check Dashboard, Progress, Challenges for loading and empty states everywhere

---

## P9 Pre-pilot hardening

☐ Happy-path HTTP E2E in CI (register, section, challenge, join, session)
☐ Full script with WebSocket + eval + DB checks (where keys allow)
☐ CORS, secrets, log level, `.gitignore` production checklist
☐ Close blocking bugs from smoke tests

---

## P10 Pilot

☐ Run 2–3 real users; keep a short issue log
☐ Go / no-go decision
☐ Short feedback survey

---

## P11 Misc

☐ “How it works” matches the real stack
☐ Check lab / showcase links
☐ Handoff doc (Slack / deploy)
☐ After pilot: dataset / evaluator tuning (only if needed)

---

## How tracks depend on each other

☐ P1 demo, P2 schema, and P7 eval basics can ship in parallel (done enough to use)
☐ P4, P5, P6, P8 build on classrooms (core paths done). Exports and admin tools still open
☐ Finish P9 before a real pilot (**P10**)