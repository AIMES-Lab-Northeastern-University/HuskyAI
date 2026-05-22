# Advanced Exemplars (PEI 70-90)

Use these as calibration anchors for high-scoring conversations.

---

DOMAIN: debugging | PEI: 84 | TURN: 2
USER: "The error only occurs when the user email contains a special character.
       I've already confirmed it's not the regex — the validation passes fine.
       I need to understand if this is a DB encoding issue or an API
       serializer issue. Here's the full stack trace: [...]
       I've already ruled out client-side encoding. The issue is server-side."
WHY HIGH:
  PSQ=91: clear scope (special chars), evidence provided (trace), constraint (already checked regex)
  CCM=85: user has done prior investigation, directs AI to specific layers
  TSI=88: problem isolated to two layers, ruled out third — clear decomposition
  CLM=78: appropriately sized message with all necessary context
  RAS=80: user is testing a hypothesis, not asking AI to guess blindly

---

DOMAIN: coding | PEI: 79 | TURN: 3
USER: "The implementation works but I'm not satisfied with the O(n²) complexity.
       I know we can do better because the data is always sorted.
       Don't give me the solution yet — first explain what patterns
       typically exploit sorted data for search/lookup optimization."
WHY HIGH:
  PSQ=88: specific problem (O(n²)), constraint (data is sorted), clear goal
  CCM=82: user explicitly controls the pace — "don't give me the solution yet"
  TSI=85: user identifies the optimization opportunity independently
  CLM=75: asks for conceptual step before implementation — incremental
  RAS=72: user wants to understand before accepting solution (under-reliance avoided)

---

DOMAIN: data_analysis | PEI: 76 | TURN: 2
USER: "The query returns 847 rows but I expected ~200 based on the business logic.
       I've checked for duplicates in the orders table — none.
       The join is on customer_id which is indexed. Could the issue be in
       how I'm filtering the date range? The business rule is 'orders in Q4'
       but our fiscal year ends March 31, not December 31."
WHY HIGH:
  PSQ=85: specific discrepancy (847 vs 200), evidence of investigation
  CCM=78: user has already debugged, presents a specific hypothesis
  TSI=82: considers indexing, date logic, fiscal year — sophisticated analysis
  CLM=72: well-structured message, not overwhelming
  RAS=75: user is verifying their own hypothesis, not asking AI to start from scratch

---

DOMAIN: casual | PEI: 81 | TURN: 1
USER: "I have a final interview tomorrow for a PM role at a Series B fintech startup.
They told me to expect a product strategy case: 'How would you grow payment volume by 20%
in the next year?' I've already mapped the problem space into three levers: acquisition,
retention, and ARPU increase. I'm not asking you to solve the case.
I want to pressure-test my framework: what is the most common mistake PMs make when
answering this type of growth case, and what is the one assumption in my
acquisition/retention/ARPU framing I'm most likely getting wrong for a payments product?"
WHY HIGH:
  PSQ=85: context rich (role, company stage, case prompt), prior work shown (own framework),
          explicit constraint ("not asking you to solve"), specific 2-part ask
  CCM=80: "not asking you to solve" = explicit scope-bound; user presents own framework
          for critique rather than asking AI to generate one; retains decision-making
  TSI=78: own analytical framework demonstrated before asking; asks for critique of
          specific assumptions; anticipates failure modes rather than seeking validation
  CLM=78: appropriate length — context, constraint, and ask each clearly delimited
  RAS=82: uses AI to stress-test own thinking rather than outsource it;
          prior framework built independently
WHAT MAKES IT ADVANCED:
  User brings a framework and asks AI to find its flaws — not to build one from scratch.
  Scope is bounded to two targeted questions, not "help me prep for my interview."

---

DOMAIN: casual | PEI: 82 | TURN: 1
USER: "I'm studying for my advanced econometrics final. I keep conflating 'unbiasedness'
and 'efficiency' when an OLS assumption is violated — I know the definitions but I can't
quickly reason through which property breaks under which violation.
Don't give me a summary table — I can find those anywhere.
Instead, walk me through the causal logic for exactly two cases:
(1) omitted variable bias and (2) heteroskedasticity.
For each: which property breaks and why in plain language, and what the practical
consequence is for inference. I'll build my own summary table from your explanations."
WHY HIGH:
  PSQ=86: specific confusion identified (unbiasedness vs efficiency), explicit constraint
          ("not a table"), exactly 2 cases scoped, 3-part ask per case
          (property / why / consequence), staged work ("I'll build my own table")
  CCM=82: "don't give me a table" = explicit refusal of default AI response;
          2-case scope = controlled output; "I'll build my own" = student retains synthesis
  TSI=80: meta-level thinking (which property breaks under which violation — not just
          definitions); asks for causal logic not recall; staged synthesis
  CLM=80: each component of ask clearly delimited; appropriate length
  RAS=82: "I'll build my own summary table" = authorship of synthesis retained;
          AI explains mechanism, student does pattern recognition and generalization
WHAT MAKES IT ADVANCED:
  Explicitly refuses the default AI output (summary table) and asks for something harder.
  Staged: AI provides mechanism, student does the synthesis.

---

# Intermediate Exemplars (PEI 40-70)

Use the following as calibration anchors for mid-tier conversations.

---

DOMAIN: coding | PEI: 63 | TURN: 1
USER: "Build a React hook useLocalStorage(key, defaultValue) that syncs state with
localStorage. It should handle JSON serialization and fall back to defaultValue if the
stored value can't be parsed. TypeScript. Export the hook from its own file.
Don't worry about cross-tab sync."
WHY INTERMEDIATE:
  PSQ=74: hook name and signature, serialization requirement, fallback behavior, TypeScript,
          file structure specified. Missing: no test criteria, undefined behavior for
          null/undefined values, no SSR consideration flagged.
  CCM=60: directive single-turn, no staging, no explicit scope-bounding or pace control
  TSI=58: mentions serialization + fallback but stops short — doesn't decompose edge cases
          (stale reads, localStorage quota exceeded, SSR environments)
  CLM=65: appropriate length but reads as a flat spec rather than structured sections
  RAS=55: no prior attempt, no verification intent stated

---

DOMAIN: data | PEI: 68 | TURN: 1
USER: "I have a Redshift table pageviews(session_id, user_id, page_slug, viewed_at)
with about 40M rows, 6 months of data. I want to compute 7-day rolling retention:
of users who first visited on day D, what fraction returned on day D+7 (±1 day tolerance).
I tried grouping by first_seen date and joining back on viewed_at but the query runs
for 20 minutes. I haven't tried window functions yet.
Can you suggest the right window function pattern for this?"
WHY INTERMEDIATE:
  PSQ=74: table schema + row count + metric definition (7-day ±1 day tolerance), prior
          attempt mentioned, performance problem stated, specific ask (window function
          pattern). Missing: partition/sort key info, definition of 'first visit'.
  CCM=65: prior attempt shown, directs to specific solution space (window functions).
          Doesn't challenge alternatives or stage the output format.
  TSI=64: identified optimization opportunity (window functions), quantified tolerance,
          mentioned prior approach. Doesn't decompose the full pipeline or consider edge
          cases (users with gaps, timezone normalization).
  CLM=70: appropriate length, organized
  RAS=68: prior attempt made, performance issue self-diagnosed. Asks for a pattern rather
          than a full solution — some independent effort shown.

---

DOMAIN: debugging | PEI: 69 | TURN: 1
USER: "Our React table component re-renders on every keystroke in a sibling search input,
even though the table data hasn't changed. I confirmed it with React DevTools Profiler —
the table re-renders ~200ms after every keypress. I already wrapped the table in
React.memo() but it's still happening. My guess is the issue is the filter function we
pass as a prop — we define it inline in the parent component on every render.
Can you confirm whether that's the likely cause and show me the fix?"
WHY INTERMEDIATE:
  PSQ=76: specific symptom (re-renders on keypress), evidence provided (DevTools Profiler
          timing), prior fix attempted (React.memo), hypothesis stated (inline prop).
          Missing: no code shown, parent component structure not described.
  CCM=68: prior investigation + fix attempt shown, hypothesis formed before asking,
          directs AI to specific cause. Doesn't challenge alternatives.
  TSI=65: identified specific mechanism (inline function prop), ruled out one approach
          (React.memo), formed falsifiable hypothesis. Doesn't explore alternative causes
          (context subscription, selector memoization, state lifting).
  CLM=70: appropriate, well-structured
  RAS=65: prior fix attempted, profiler evidence gathered, hypothesis-driven ask.
          Doesn't state a verification plan after the fix is applied.

---

DOMAIN: casual | PEI: 69 | TURN: 1
USER: "Help me structure a 20-minute conference talk for a local Python meetup on migrating
a sync Django app to async FastAPI. Audience: mid-level devs who know Django well but have
never written async Python. Budget: 5 min motivation, 10 min live-code demo, 5 min Q&A.
The demo should start from a slow sync endpoint (simulated DB delay), refactor it async,
then show throughput improvement via a quick locust run. For each of the three sections
give me: the key narrative point, a specific code snippet or visual to use, and one thing
to avoid (common mistake or audience confusion). Also give me one backup plan in case the
live demo environment fails."
WHY INTERMEDIATE:
  PSQ=80: good constraints, section-level output requested (narrative + snippet + avoid),
          backup contingency included. Missing: specific audience experience range.
  CCM=62: detailed structure but AI is doing all the synthesis; user isn't staging the
          output or challenging the framework
  TSI=60: decomposed into sections and includes failure contingency, but no methodology
          awareness beyond structural requirements
  CLM=78: well-structured, appropriate length for a talk-prep request
  RAS=60: user will evaluate output but no explicit verification intent or prior draft
