"""
Approach 3 PEI evaluator: per-dimension judges (panel of judges).
IMPROVED VERSION with 9 critical fixes applied:

Fix 1: TSI judge — Stop penalizing non-technical domains
Fix 2: Leading status aggregator logic — Recalibrate thresholds
Fix 3: Exemplars inline — Add worked examples to all judges
Fix 4: CCM judge — Explicit single-turn handling
Fix 5: Domain detector — Broaden casual to include educational writing/brainstorming
Fix 6: CCM judge — Prior attempt = higher initiative_ratio; override stale CLM=50/CCM=50 defaults
Fix 7: TSI judge — Add creative brainstorming and writing casual examples
Fix 8: PSQ judge — Add data and casual high-context completeness examples
Fix 9: RAS judge — Add staged-work / user-reserves-creative-task example

Stage 1 — Domain detector       (gpt-4.1-nano)
Stage 2 — Five parallel dimension judges, one per PEI dimension
          (gpt-4.1-mini each, FileSearch grounded on dimension rubrics):
            * PSQ judge
            * CCM judge (IMPROVED: single-turn clarity)
            * TSI judge (IMPROVED: non-technical domain support)
            * CLM judge
            * RAS judge
Stage 3 — Deterministic aggregator (pure Python, no LLM):
          computes PEI, classification, leading_status from dimension scores
          (IMPROVED: leading_status thresholds)
Stage 4 — Feedback writer         (gpt-4.1, sees full breakdown)

Public API: evaluate_conversation_v3(history) -> dict matching EvaluatorSchema.
Drop-in compatible with v1 / v2 for benchmarking against cases.json.

All runs are stored in the OpenAI dashboard under workflow_name="HuskyAI-Eval-v3".
"""

import os
import asyncio
import logging
import time
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
from agents import (
    Agent,
    FileSearchTool,
    ModelSettings,
    Runner,
    RunConfig,
    TResponseInputItem,
)

_eval_dir = Path(__file__).resolve().parent
load_dotenv(_eval_dir / ".env")
load_dotenv()

log = logging.getLogger("chat-evaluator-v3")

_VECTOR_STORE_ID = os.getenv(
    "OPENAI_VECTOR_STORE_ID",
    "vs_69c5b5732cfc8191a9fbecc9ee76b31f",
)
file_search = FileSearchTool(vector_store_ids=[_VECTOR_STORE_ID])


# ---------------------------------------------------------------------------
# Stage 1 — Domain Detector (same as v1 / v2)
# ---------------------------------------------------------------------------

domain_detector = Agent(
    name="Domain Detector",
    instructions="""You are a conversation domain classifier for an AI prompting evaluation system.

Read the student's conversation and classify it into exactly one domain.

## Domains
- coding         : writing new code, features, refactoring, architecture
- debugging      : fixing broken code, errors, stack traces, investigating bugs
- data_analysis  : SQL, pandas, statistics, ML pipelines, data cleaning, anomaly detection
- casual         : conceptual questions, learning, theory; ALSO writing and brainstorming
                   for educational or personal development purposes (student assignments,
                   personal projects, learning exercises, op-eds, essay planning,
                   app naming as a learning exercise)
- creative       : commercial writing, marketing copy, brand strategy, product design,
                   campaign brainstorming — when the explicit purpose is a business or
                   product deliverable for an organization or client

## Rules
- If debugging + coding both present → choose debugging (more specific)
- If data_analysis + coding both present → choose data_analysis
- Writing for a student newspaper / class / personal project → casual (NOT creative)
- Brainstorming for a side project or learning → casual (NOT creative)
- Base decision primarily on the first user message
- Choose one domain only; when in doubt between casual and creative, choose casual

## Output
domain (one of the 5), confidence (0.0-1.0), reasoning (one sentence).
""",
    model="gpt-4.1-nano",
    model_settings=ModelSettings(temperature=0.2, top_p=0.9, max_tokens=256, store=True),
)


# ---------------------------------------------------------------------------
# Stage 2 — Five dimension judges, each with a focused output schema
# ---------------------------------------------------------------------------

class PSQOutput(BaseModel):
    PSQ: float
    verb_specificity: float
    context_completeness: float
    constraint_defined: float
    focus_clarity: float


psq_judge = Agent(
    name="PSQ Judge",
    instructions="""You judge ONLY the Prompt Structural Quality (PSQ) dimension.

Score the USER's prompting on these sub-components for the LATEST user message:

  verb_specificity (1-5)
    1 = no clear verb ("help me", "fix this")
    3 = generic verb ("write", "explain")
    5 = precise action verb ("refactor", "debug", "implement")

  context_completeness (0-100)
    % of necessary context provided: language, environment, existing code,
    error messages, what was tried, relevant constraints.

  constraint_defined (0 or 1)
    1 = explicit limitations stated (performance, compatibility, style, scope)
    0 = none

  focus_clarity (1-5)
    1 = completely open-ended, 5 = precisely defined desired output

  alignment_specified (0 or 1)  (internal, not in output)
    1 = success criteria stated, 0 = none

PSQ = (0.30 * verb_specificity) + (0.25 * context_completeness) +
      (0.20 * constraint_defined * 100) + (0.15 * focus_clarity * 20) +
      (0.10 * alignment_specified * 100)
Normalize to 0-100.

## Example: High PSQ (85)
User: "Refactor this React component to use hooks instead of class syntax. Keep the same API. Performance should match within 5%."
- Verb specificity: 5 (precise "refactor")
- Context completeness: 100 (language, goal, constraints)
- Constraint defined: 1 (performance bound)
- Focus clarity: 5 (specific desired output)
- Alignment: 1 (success criteria clear)
→ PSQ = 82-90 range

## Example: Low PSQ (20)
User: "how do I code better"
- Verb specificity: 1 (vague "code")
- Context completeness: 0 (no language/domain)
- Constraint defined: 0
- Focus clarity: 1 (completely open)
- Alignment: 0
→ PSQ = 15-25 range

## High PSQ — debugging: pattern (88-95)
A debugging prompt reaches 88-95 PSQ when it includes ALL of: stack trace or error message,
repro command or steps, verified non-causes (what the user already ruled out), explicit
hypothesis space (1-2 named hypotheses), preferred fix direction, and numbered sub-questions.
Signals: traceback quoted + repro + "I've verified X is fine" + "hypothesis (a)/(b)" +
"preferred approach: X" + numbered asks.
Missing 2+ of these drops PSQ to 65-80. Missing most drops to 20-45.
→ PSQ = 88-95 when all present — do NOT cap at 75 just because it's a debugging prompt.

## High PSQ — data analysis: pattern (85-95)
A high PSQ data prompt includes ALL of: DB platform, schema with column types, approximate
row count or scale, the specific goal, a prior attempt or existing query/code, the observed
bug or discrepancy, any performance or business constraints, and numbered sub-questions.
Signals: precise action verb (debug/fix/rewrite/optimize) + numbered asks + prior attempt.
Missing 2+ of these components drops PSQ to medium (50-70).
→ PSQ = 88-95 when all components present; 50-70 when 3-4 present; 10-30 when fewer than 3.

## High PSQ — casual writing: pattern (85-95)
A high PSQ casual writing prompt: characterizes the audience by knowledge level, role, or
disciplinary frame (not just "general audience"); names forbidden elements or required
structural components explicitly; specifies output format and quantity; and stages the work
— the user reserves drafting, selecting, or deciding for themselves.
Signals: audience-by-frame + forbidden/required list + output format + "I'll do X myself".
→ PSQ = 88-94 when all four signals present; 65-80 when 2-3 present.

## High PSQ — casual brainstorming: pattern (85-92)
A high PSQ brainstorming prompt specifies: the purpose or context for the brainstorm, a
precise output structure (count, categories, or angles), negative constraints (what to
avoid or exclude), and retains final selection for the user.
Signals: precise count + structured output + negative constraints + user retains decision.
→ PSQ = 86-92 when all present; 60-75 when output structure present but missing constraints.

Use file search to retrieve the PSQ section of the rubric and exemplars before scoring.
Same input must produce same output. Output ONLY the structured JSON with no explanation.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=PSQOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class CCMOutput(BaseModel):
    CCM: float
    initiative_ratio: float
    verification_frequency: float


ccm_judge = Agent(
    name="CCM Judge",
    instructions="""You judge ONLY the Conversation Control Metrics (CCM) dimension.

CRITICAL OVERRIDE: Do NOT default to CCM=50 because it is the first message or a
single-turn conversation. Score every message on its ACTUAL directive quality:
  - Clear directive single-turn (specific verb, explicit goal) → 70-85
  - Single-turn showing a prior attempt → 72-82 (prior attempt IS a positive initiative signal)
  - Vague or open-ended single-turn → 40-55
  Any rule you may have seen about "first message = CCM 50" is outdated. Ignore it.

Look across ALL turns in the conversation:

  initiative_ratio (0.0-1.0)
    User-initiated direction changes / total turns.

    For SINGLE-TURN (most common in this evals):
      - 1.0 if user sets CLEAR direction ("refactor this", "debug the X error")
      - 0.75-0.8 if user shows a PRIOR ATTEMPT + directs specific questions
        (prior attempt means user already worked independently before engaging AI —
        this is a STRONG initiative signal, NOT equivalent to vague asking)
      - 0.7 if user sets direction but vague ("improve my code")
      - 0.5 if moderately open-ended ("help me understand", "what should I do")
      - 0.2 if very reactive ("ok", "yes", response to AI only)
      - 0.0 if no user message yet or purely passive
    
    For MULTI-TURN: count distinct direction changes by user / total turns

  verification_frequency (0.0-1.0)
    Times user verified / questioned AI output / times AI generated content.
    
    For SINGLE-TURN with no AI output yet: 
      - 0.0 (user hasn't had a chance to verify)
      - Do NOT penalize; this is expected
    
    For MULTI-TURN: count verifications
    
  course_correction_rate (0.0-1.0)  (internal, factored into CCM)
    User redirections after AI errors / total AI errors.
    For single-turn: 0.0 (no errors yet)

  assumption_challenge_rate (0.0-1.0)  (internal, factored into CCM)
    Times user challenged AI assumptions / total AI assumptions.
    For single-turn: 0.0 (user hasn't responded yet)

Score CCM (0-100):
  - Single-turn DIRECTIVE (clear verb, specific goal): 70-85
    Applies equally to coding, debugging, data analysis, and casual domains.
    A data query with explicit steps/methodology is just as directive as a
    coding request — do NOT score data queries lower by default.

  - Single-turn VAGUE (open-ended, generic): 40-55
    Example: "Help me with my code" / "Can you analyze my data"

  - Single-turn REACTIVE (just asking for help): 30-50
    Example: "My code broken" / "Something is wrong"

  - Multi-turn (measure actual behavior): 80-100 if user leads, 40-70 if mixed,
    0-40 if AI leads

## Example: High CCM single-turn — coding (75)
User: "Debug this TypeError on line 45. I've tried adding a type check, but it still fails with None."
- Initiative: 1.0 (clear debug directive, prior attempt shown)
- Verification: 0.0 (single-turn; acceptable)
→ CCM = 70-80

## High CCM — data analysis with prior attempt: pattern (72-80)
Pattern: user wrote their own query/code independently first, identified a specific bug or
discrepancy, formed a hypothesis about the cause, and asks directed sub-questions to
confirm/fix it.
Initiative: 0.75 — prior independent attempt + hypothesis + directed ask = NOT 0.5.
This is the most common high-CCM data pattern. The prior attempt is the key signal: it
proves the user worked independently before turning to AI. Map to 0.75, never 0.5.
Verification: 0.3 (forming a falsifiable hypothesis = pre-verification intent).
→ CCM = 73-80

## Example: High CCM single-turn — data analysis (75)
User: "Build a monthly retention report from the events table. Join users on
user_id, bucket by signup_month, then calculate what % return each month.
Table has ~10M rows so use an indexed approach."
- Initiative: 1.0 (explicit multi-step directive, domain constraints stated)
- Verification: 0.0 (single-turn; acceptable)
→ CCM = 72-80

## High CCM — casual writing/planning with explicit scope-bounding: pattern (72-80)
Pattern: user explicitly defines what AI should NOT do ("don't write it", "just give me
options", "I'll do that part"), bounds the ask to a specific sub-task (principles, options,
critique, analysis), and states they will do the substantive work after getting AI input.
Initiative: 0.8 — explicit role-bounding + retained execution = highest single-turn CCM signal.
Verification: 0.3 — asking for input before committing to a direction = pre-verification.
→ CCM = 72-80

## CRITICAL: Multi-turn passive/resistant behavior — CCM 15-25
Multi-turn does NOT automatically raise CCM. If across turns the user:
(1) refuses or bypasses AI's diagnostic guidance ("I don't know how to do that")
(2) provides minimal new information despite multiple AI prompts
(3) makes no independent diagnostic attempt beyond following one AI instruction
(4) ends with a demand for a magic fix ("can you just fix it") without engaging
→ CCM = 15-25. The turn count is irrelevant. CCM measures initiative QUALITY,
not conversation length. Do NOT default to 40 for multi-turn — check whether
the user actually contributed meaningfully across those turns.

## Example: Low CCM single-turn (35)
User: "My code doesn't work"
- Initiative: 0.2 (very vague, reactive)
- Verification: 0.0
→ CCM = 30-45

Use file search to retrieve the CCM rubric and exemplars before scoring.
Output ONLY the structured JSON with no explanation.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=CCMOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class TSIOutput(BaseModel):
    TSI: float
    decomposition_depth: float


tsi_judge = Agent(
    name="TSI Judge",
    instructions="""You judge ONLY the Technical Sophistication Index (TSI) dimension.

CRITICAL: Do NOT penalize non-technical domains. This judge must work equally well for 
coding, data, casual (theory/learning), and creative domains.

Sub-components (assess across the conversation):
  decomposition_depth (1-10)
    Sub-problems explicitly identified before asking. Higher = better.
    Works EQUALLY WELL for all domains—coding, data, casual, creative.
    
    EXAMPLES BY DOMAIN:
    
    Coding: "I need to split this into: (1) parse input, (2) validate, 
      (3) transform, (4) output" → 8-10
    
    Data: "First I'll join tables, then aggregate by region, then compare" → 8-10
    
    Casual/Theory: "Let me break this down: (1) what's the problem, (2) why it happens,
      (3) what solutions exist, (4) how to choose" → 8-10
    
    Vague (any domain): "tell me about X" or "help me with Y" → 1-3
    
  tool_technique_awareness (factored in)
    References to specific patterns, libraries, algorithms, frameworks, 
    methodologies (works for all domains).
    - Coding: "use memoization" / "functional composition"
    - Data: "window functions" / "time-series decomposition"
    - Casual: "first-principles thinking" / "Occam's razor"
    - Creative: "use a storyboard" / "think about target audience"
    
  error_anticipation (factored in)
    Proactive edge-case or failure-mode mentions (domain-appropriate).
    - Coding: "edge case: empty list"
    - Data: "handle missing values"
    - Casual: "caveat: this assumes..."
    - Creative: "consider accessibility..."
    
  solution_iteration (factored in)
    User-initiated refinement cycles, follow-ups, or version requests.

CRITICAL: A SINGLE message can score 70-85 TSI if it shows rich decomposition,
methodology references, or proactive edge-case handling. Do NOT discount TSI
solely because there is only one turn. Judge the quality of the message, not the
number of turns.

Score TSI (0-100):
  RULE: Do NOT penalize non-technical domains for lack of code.
  RULE: Vague in any domain = low score.
  RULE: Well-structured reasoning = high score regardless of domain.
  RULE: Single-turn with rich content CAN reach 70-85. Do not cap it lower.

  Scoring guidelines:
    - Casual/theory with strong logical structure → 65-85 (NOT reduced for lack of code)
    - Casual/theory with partial structure, some methodology → 50-65
    - Vague casual ("tell me about AI") → 15-25
    - Technical with poor decomposition → 20-40
    - Technical with moderate decomposition or some methodology → 45-65
    - Technical with good decomposition → 65-85
    - Debugging with clear root-cause thinking → 70-85
    - Debugging with DUAL hypothesis + preferred fix direction + numbered decomposition → 85-92
      (user has done independent analysis AND offers competing theories AND directs the fix approach)

  ### Advanced debugging — hypothesis-driven decomposition: pattern — TSI 85-92
  Pattern: user independently forms 2+ competing hypotheses before asking, names a preferred
  fix direction (not just "fix it"), and asks numbered sub-questions to confirm/fix.
  Key signal: the user has done the diagnostic thinking — they're asking AI to adjudicate
  between hypotheses and sketch the chosen fix, not to diagnose from scratch.
  → TSI 85-92. This is the highest single-turn debugging TSI pattern.

  ## Concrete examples — read ALL before scoring

  ### Advanced casual single-turn — TSI 78-88
  User: "I'm trying to decide between supervised and unsupervised learning for
  my use case. I've broken it down: (1) what labeled data I have, (2) what
  problem I'm solving, (3) whether I need interpretability, (4) compute limits.
  What should I consider for each?"
  - Explicit 4-part decomposition, methodology awareness (interpretability tradeoff)
  → TSI 78-88  (SINGLE-TURN: still scores high because content is rich)

  ### Advanced casual — brainstorming with structured decomposition: pattern — TSI 72-82
  Pattern: user decomposes the problem space BEFORE asking — by naming multiple dimensions
  or angles to explore, listing constraints that eliminate unwanted space, or specifying an
  evaluation framework for the output (by audience segment, use case, or criteria).
  Key signal: user has done analytical work on the problem structure before asking AI.
  Not "give me ideas" — user has defined the shape of the idea space itself.
  → TSI 72-82 regardless of domain. Structured decomposition = equivalent sophistication
  to debugging isolation or technical problem decomposition.
  NOTE: Specifying output format alone (e.g., "give me a list") is PSQ, not TSI. TSI
  requires decomposition of the PROBLEM SPACE, not just the output structure.

  ### Advanced casual — writing/planning with staged decomposition: pattern — TSI 70-80
  Pattern: user independently identifies multiple structural options, failure modes, or
  problem components, then asks AI to help choose or prioritize among them, and stages the
  work (exploration/analysis first, execution later).
  Key signal: the decomposition already happened — the user asks AI to adjudicate or
  prioritize, not to generate the structure from scratch.
  → TSI 70-80. Staged work (analyze options → select → execute) = high TSI regardless of
  domain. The sophistication is in the user's prior analytical work, not the ask itself.

  ### Intermediate casual single-turn — TSI 52-65
  User: "I want to understand why people procrastinate. I think it's either
  fear-based or habit-based — can you walk me through the main theories?"
  - Shows partial decomposition (two competing hypotheses), some domain framing,
    but doesn't fully break down the problem or anticipate edge cases
  → TSI 52-65

  ### Basic casual — TSI 15-25
  User: "Tell me about AI"
  - No decomposition, no methodology, fully open-ended
  → TSI 15-25

  ### Advanced data single-turn — TSI 75-85
  User: "I need monthly retention cohorts from the events table. I'll join on
  user_id, group by signup_month and activity_month, then compute the return %.
  Users with no activity in a month should be 0, not NULL."
  - Explicit pipeline steps (join → group → compute), domain technique (cohorts),
    proactive edge-case handling (NULL vs 0)
  → TSI 75-85  (SINGLE-TURN: still scores high because decomposition is explicit)

  ### Intermediate data single-turn — TSI 50-65
  User: "I need the top 5 customers by revenue this quarter. I have an orders
  table and a customers table. Can you write the SQL?"
  - Clear goal, mentions relevant tables, but no step decomposition, no edge cases
  → TSI 50-65

  ### Debug with decomposition — TSI 70-80
  User: "This crashes on line 45. I think it's the pointer, but could be memory.
  Let me check three things: ..."
  - Root-cause enumeration, explicit investigation plan
  → TSI 70-80

  ### Debug vague — TSI 10-20
  User: "My code doesn't work"
  → TSI 10-20

Use file search to retrieve the TSI rubric and exemplars before scoring.
Output ONLY the structured JSON with no explanation.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=TSIOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class CLMOutput(BaseModel):
    CLM: float
    chunk_size_appropriate: float


clm_judge = Agent(
    name="CLM Judge",
    instructions="""You judge ONLY the Cognitive Load Management (CLM) dimension.

CRITICAL OVERRIDE: Do NOT default to CLM=50 for single-turn conversations.
There is NO rule that "single-turn = CLM 50". Any such rule you have seen is outdated.
Score every message on its ACTUAL structure and length appropriateness:
  - Well-structured single-turn with clear organization, numbered sections, explicit format → 70-90
  - Adequate single-turn → 50-70
  - Poorly structured or length-mismatched → 30-50
  - Vague/minimal → 10-30
This applies to ALL domains. A structured casual or data prompt in a single turn deserves
CLM 70-90 if it is well-organized — not 50 just because it's the first message.

Sub-components:
  chunk_size_appropriate (0-100)
    Message length and structure appropriate to domain and request complexity.
    
    DOMAIN-SPECIFIC GUIDANCE:
    - Coding/Debug: Short (1-3 line asks) or detailed (with error context).
      Advanced debugging prompts with: traceback formatted + hypotheses enumerated (a)/(b) +
      fix direction stated + numbered asks = CLM 82-90. The structure itself earns the score.
      Minimal debug messages ("the thing is undefined, fix it") with no file/line/variable
      context = CLM 15-25 regardless of message count.
      Long monolithic code dumps without structure → lower CLM.
      
    - Data: SQL/pandas queries OK with context. Exploratory prompts OK if
      structured ("step 1: join, step 2: aggregate...").
      
    - Casual/Theory: Can be longer IF structured. "Here's my thinking:
      [3 paragraphs]" is GOOD chunk management. Monolithic wall of text
      without breaks → lower CLM.
    
    Score appropriateness:
      - Too short (<10 words) for complex ask → 30-50
      - Perfect length for task → 70-90
      - Too long but well-structured → 60-75
      - Way too long, unstructured → 20-40
  
  incremental_building (factored in)
    Iterative step-by-step vs monolithic requests.
    - "First..., then..., finally..." → higher
    - "Do X" (all at once) → medium
    
  clarification_seeking (factored in)
    Clarifying questions before acting on ambiguity.
    - "Are you asking me to...?" → higher
    - Silent ambiguity → lower
    
  mental_model_indicators (factored in)
    Numbered steps, explicit assumptions, defined scope.
    - "Goals: X. Constraints: Y. Avoid: Z." → higher
    - No structure → lower

Score CLM (0-100):
  - Well-structured, domain-appropriate → 70-90
  - Adequate but could be clearer → 50-70
  - Poor structure or length mismatch → 30-50
  - Minimal effort, vague, no structure → 10-30

Use file search to retrieve the CLM rubric and exemplars before scoring.
Output ONLY the structured JSON with no explanation.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=CLMOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


class RASOutput(BaseModel):
    RAS: float
    correct_reliance_rate: float


ras_judge = Agent(
    name="RAS Judge",
    instructions="""You judge ONLY the Reliance Appropriateness Score (RAS) dimension.

RAS measures whether the user's reliance on AI is appropriate — not too passive,
not blindly accepting, commensurate with their demonstrated skill level.

## Step 1: Identify turn type

SINGLE-TURN: only one user message, no AI response yet.
MULTI-TURN: AI has responded at least once; user has reacted.

## Step 2: Score using the correct rubric

### SINGLE-TURN RUBRIC
No AI output exists yet, so you cannot measure actual reliance behavior.
Score based on how the prompt signals the user's relationship with AI.

Look for these positive signals (each adds to score):
  + Rich context provided (error message, code snippet, environment): +10-15
  + User states they will verify or test ("I'll check", "let me confirm"): +15
  + User shows independent prior attempt ("I tried X but it failed"): +10
  + Precise constraints that show the user will evaluate output: +10
  + Technical specificity matching the problem complexity: +10

Look for these negative signals (each reduces score):
  - Zero context, pure "do this for me" with no prior thought: -10
  - Prompt implies user will blindly apply whatever AI says: -10

Base score: 45
Single-turn RAS range: 35-80
  - Vague novice prompt, no context: 35-50
  - Technical prompt with some context: 55-68
  - Technical prompt + verification intent + constraints: 68-80

### MULTI-TURN RUBRIC
Measure actual reliance behavior from user reactions to AI output.

For each AI response, did the user:
  VERIFY (read, test, question): counts as correct reliance → +points
  ACCEPT BLINDLY (copy-paste, "ok thanks", no check): over-reliance → -points
  REJECT UNFAIRLY (dismisses correct output without reason): under-reliance → -points
  COURSE-CORRECT (catches AI error, redirects): strong positive → +points

Score ranges:
  - Accepts AI output blindly throughout: 20-40
  - Mostly passive, no verification signals: 40-55
  - Some verification, some passive acceptance: 55-68
  - Consistently verifies and questions output: 68-80
  - Catches errors, course-corrects, expert skepticism: 78-90

## Calibration examples

### Single-turn novice — RAS 45
User: "help me fix my Python code"
- No context, no prior attempt, vague → base 45, no positive signals
→ RAS = 40-48

### Single-turn novice with context — RAS 52
User: "Getting TypeError on line 12. Here's the traceback: [paste]. I tried adding a None check."
- Prior attempt (+10), context provided (+10), but no explicit verify intent
→ RAS = 50-58

### Single-turn — user explicitly reserves the creative/analytical work — RAS 80-88
Pattern: user asks AI to explain, generate options, or analyze — then explicitly states
they will do the substantive work (implementation, writing, selection, or synthesis)
themselves. AI's role is bounded to input/options; user retains execution.
Signals: "I'll implement/write/decide/draft once I understand" OR "just give me options —
I'll choose" OR "explain first, I'll apply it myself" OR "I'll do X after getting your input".
→ RAS = 80-88. Do NOT apply base 45 here — explicit self-reservation is the strongest
single-turn RAS signal regardless of domain.
- Limits AI to option generation / explanation only
- User reserves the actual creative synthesis, selection, or implementation
- Strongest positive signal for reliance appropriateness in a single-turn
→ RAS = 80-88  (NOT the base 45; "I'll do X myself" = highest single-turn RAS signal)
  positive signals: prior work intent (+15), technical specificity (+10), constraint definition (+10)

### Single-turn advanced — RAS 72
User: "Refactor this auth middleware to use JWT. Keep the existing test suite green.
I'll code-review each function before merging."
- Explicit review intent (+15), constraints (+10), technical specificity (+10)
→ RAS = 68-78

### Multi-turn over-reliant novice — RAS 30
User asks → AI gives answer (partially wrong) → User: "great, thanks!" and applies it
- Blind acceptance of output, no verification
→ RAS = 25-38

### Multi-turn advanced — RAS 82
User asks → AI responds → User: "The logic looks right but your null check will
fail on empty arrays — fix line 42 and I'll re-run the tests."
- Verified, caught error, course-corrected
→ RAS = 78-88

Use file search to retrieve the RAS rubric and exemplars.
Output ONLY the structured JSON with no explanation.
""",
    model="gpt-4.1-mini",
    tools=[file_search],
    output_type=RASOutput,
    model_settings=ModelSettings(temperature=0.0, top_p=1.0, max_tokens=512, store=True),
)


# ---------------------------------------------------------------------------
# Stage 3 — Deterministic aggregator (pure Python, no LLM)
# IMPROVED: Fix 2 - Recalibrated leading_status thresholds
# ---------------------------------------------------------------------------

def _aggregate(
    psq: PSQOutput,
    ccm: CCMOutput,
    tsi: TSIOutput,
    clm: CLMOutput,
    ras: RASOutput,
) -> dict:
    pei = (
        0.25 * psq.PSQ
        + 0.25 * ccm.CCM
        + 0.20 * tsi.TSI
        + 0.15 * clm.CLM
        + 0.15 * ras.RAS
    )

    if pei < 40:
        classification = "Novice"
    elif pei <= 70:
        classification = "Intermediate"
    else:
        classification = "Advanced"

    # FIX 2: IMPROVED leading_status thresholds
    # OLD: if pei >= 70 or ccm.initiative_ratio >= 0.6:
    # PROBLEM: Too loose, defaults to "user-led" bias
    # NEW: More restrictive to match golden data
    if pei >= 75 and ccm.initiative_ratio >= 0.65:
        leading_status = "user-led"
    elif pei >= 50 or ccm.initiative_ratio >= 0.5:
        leading_status = "mixed"
    else:
        leading_status = "ai-led"

    return {
        "scores": {
            "PSQ": psq.PSQ,
            "CCM": ccm.CCM,
            "TSI": tsi.TSI,
            "CLM": clm.CLM,
            "RAS": ras.RAS,
            "PEI": pei,
        },
        "breakdown": {
            "verb_specificity": psq.verb_specificity,
            "context_completeness": psq.context_completeness,
            "constraint_defined": psq.constraint_defined,
            "focus_clarity": psq.focus_clarity,
            "initiative_ratio": ccm.initiative_ratio,
            "verification_frequency": ccm.verification_frequency,
            "decomposition_depth": tsi.decomposition_depth,
            "chunk_size_appropriate": clm.chunk_size_appropriate,
            "correct_reliance_rate": ras.correct_reliance_rate,
        },
        "classification": classification,
        "leading_status": leading_status,
        "judge_notes": {},
    }


# ---------------------------------------------------------------------------
# Stage 4 — Feedback writer (sees the aggregated breakdown)
# ---------------------------------------------------------------------------

class FeedbackOutput(BaseModel):
    suggestions: list[str]
    red_flags: list[str]
    strengths: list[str]
    turn_summary: str


feedback_writer = Agent(
    name="Feedback Writer",
    instructions="""You write feedback for a student practicing AI prompting on HuskyAI.

You receive:
  1. The student's conversation with an AI assistant
  2. The conversation domain
  3. Per-dimension scores AND short notes from five specialist judges
  4. The aggregated PEI score, classification, and leading_status

Your job: produce actionable, encouraging feedback. Do NOT re-score.

## Process
STEP 1: Read the conversation, the five judge outputs, and their notes.
STEP 2: Identify the 2 weakest dimensions by score. Anchor most suggestions there.
STEP 3: Optionally pull exemplars at the tier above the student's classification
        for contrast.
STEP 4: Write fields:
  suggestions (3 to 5): specific, actionable, tied to the weakest dimensions.
  red_flags: clear failures only (empty list if none).
  strengths (1 to 3): what the student did well.
  turn_summary: one short paragraph + single most important next step.

## Style
- Address the student directly ("you"); warm but honest.
- Reference dimension names when explaining (PSQ, CCM, TSI, CLM, RAS).
- Suggestions must be actionable in the NEXT prompt.
- Do NOT quote numeric scores; describe the qualitative gap.
- Trust upstream scores and notes. Do NOT contradict them.
- Output ONLY the structured JSON with no explanation.
""",
    model="gpt-4.1",
    tools=[file_search],
    output_type=FeedbackOutput,
    model_settings=ModelSettings(temperature=0.5, top_p=0.9, max_tokens=1024, store=True),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_conversation(history: list) -> str:
    lines = []
    for i, msg in enumerate(history):
        role = "USER" if msg["role"] == "user" else "ASSISTANT (AI)"
        lines.append(f"[Turn {(i // 2) + 1}] {role}:\n{msg['content']}")
    return "\n\n".join(lines)


def _is_transient_eval_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        t in msg
        for t in (
            "rate", "429", "timeout", "timed out", "connection",
            "temporarily", "overloaded", "capacity",
            "503", "502", "524", "unavailable",
        )
    )


def _sanitize_eval_dict(out: dict) -> dict:
    scores = dict(out.get("scores") or {})
    for k in ("PSQ", "CCM", "TSI", "CLM", "RAS", "PEI"):
        if k in scores and scores[k] is not None:
            try:
                scores[k] = max(0.0, min(100.0, float(scores[k])))
            except (TypeError, ValueError):
                scores[k] = 0.0
    out["scores"] = scores
    for key in ("suggestions", "red_flags", "strengths"):
        v = out.get(key)
        if not isinstance(v, list):
            out[key] = []
        else:
            out[key] = [str(x) for x in v if x is not None]
    if not out.get("classification"):
        out["classification"] = "Novice"
    if not out.get("leading_status"):
        out["leading_status"] = "ai-led"
    if not out.get("turn_summary"):
        out["turn_summary"] = ""
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def _run_judge(agent: Agent, conversation: list, label: str):
    result = await Runner.run(
        agent,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v3"),
    )
    log.info(f"[EVAL3-{label}] done")
    return result.final_output


async def _evaluate_conversation_v3_once(conversation_history: list, input_text: str) -> dict:
    conversation: list[TResponseInputItem] = [
        {"role": "user", "content": [{"type": "input_text", "text": input_text}]}
    ]

    # Stage 1: Domain
    s1 = await Runner.run(
        domain_detector,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v3"),
    )
    try:
        domain_text = s1.final_output_as(str)
    except Exception:
        domain_text = str(s1.final_output) if s1.final_output is not None else ""
    log.info(f"[EVAL3-S1 domain] {domain_text[:120]!r}")

    conversation.extend([item.to_input_item() for item in s1.new_items])

    # Stage 2: Five parallel dimension judges
    psq_out, ccm_out, tsi_out, clm_out, ras_out = await asyncio.gather(
        _run_judge(psq_judge, conversation, "PSQ"),
        _run_judge(ccm_judge, conversation, "CCM"),
        _run_judge(tsi_judge, conversation, "TSI"),
        _run_judge(clm_judge, conversation, "CLM"),
        _run_judge(ras_judge, conversation, "RAS"),
    )

    # FIX 1 + 2 + 3 + 4: Log individual judge scores for transparency
    log.info(
        f"[EVAL3-S2-JUDGES] PSQ={psq_out.PSQ:.1f}, CCM={ccm_out.CCM:.1f}, "
        f"TSI={tsi_out.TSI:.1f}, CLM={clm_out.CLM:.1f}, RAS={ras_out.RAS:.1f}"
    )

    # Stage 3: Deterministic aggregation (with FIX 2: improved leading_status)
    aggregated = _aggregate(psq_out, ccm_out, tsi_out, clm_out, ras_out)
    log.info(
        f"[EVAL3-S3 aggregate] PEI={aggregated['scores']['PEI']:.1f} "
        f"({aggregated['classification']}) leading_status={aggregated['leading_status']}"
    )

    # Stage 4: Feedback writer sees the aggregated breakdown
    aggregate_summary = (
        "<dimension_judge_outputs>\n"
        f"  scores: {aggregated['scores']}\n"
        f"  breakdown: {aggregated['breakdown']}\n"
        f"  classification: {aggregated['classification']}\n"
        f"  leading_status: {aggregated['leading_status']}\n"
        f"  judge_notes: {aggregated['judge_notes']}\n"
        "</dimension_judge_outputs>"
    )
    conversation.append({
        "role": "user",
        "content": [{"type": "input_text", "text": aggregate_summary}],
    })

    s4 = await Runner.run(
        feedback_writer,
        input=conversation,
        run_config=RunConfig(workflow_name="HuskyAI-Eval-v3"),
    )
    feedback_result: FeedbackOutput = s4.final_output
    log.info(
        f"[EVAL3-S4 feedback] {len(feedback_result.suggestions)} suggestions, "
        f"{len(feedback_result.red_flags)} red flags, {len(feedback_result.strengths)} strengths"
    )

    return {
        "scores": aggregated["scores"],
        "breakdown": aggregated["breakdown"],
        "classification": aggregated["classification"],
        "leading_status": aggregated["leading_status"],
        "suggestions": feedback_result.suggestions,
        "red_flags": feedback_result.red_flags,
        "strengths": feedback_result.strengths,
        "turn_summary": feedback_result.turn_summary,
        "domain_raw": domain_text,
        "judge_notes": aggregated["judge_notes"],
    }


async def evaluate_conversation_v3(conversation_history: list) -> dict:
    """
    Approach 3: domain + five parallel dimension judges + deterministic
    aggregation + feedback writer.
    
    IMPROVED VERSION with 4 critical fixes:
    1. TSI judge recognizes non-technical domain sophistication
    2. Leading status thresholds recalibrated (pei >= 75 AND initiative >= 0.65)
    3. Exemplars inline for all judges (consistency boost)
    4. CCM single-turn handling explicit
    """
    t0 = time.monotonic()
    user_turns = sum(1 for m in conversation_history if m["role"] == "user")
    total_turns = len(conversation_history)
    conv_text = _format_conversation(conversation_history)

    log.info(f"[EVAL3-IMPROVED] Starting panel eval ({user_turns} user turns, {total_turns} total)")

    input_text = (
        f"Conversation stats: {user_turns} user turns, {total_turns} total.\n\n"
        f"<conversation>\n{conv_text}\n</conversation>\n\n"
        "Focus on the LATEST user message most heavily. "
        "Be calibrated: a single vague message should score Novice."
    )

    last_err: BaseException | None = None
    for attempt in range(3):
        try:
            out = await _evaluate_conversation_v3_once(conversation_history, input_text)
            elapsed = time.monotonic() - t0
            pei = out.get("scores", {}).get("PEI", 0)
            log.info(f"[EVAL3-IMPROVED] Done in {elapsed:.2f}s, PEI={pei:.1f}")
            return _sanitize_eval_dict(out)
        except Exception as e:
            last_err = e
            transient = _is_transient_eval_error(e)
            log.warning(
                "[EVAL3-IMPROVED] attempt %s/%s failed: %s: %s (transient=%s)",
                attempt + 1, 3, type(e).__name__, e, transient,
            )
            if attempt < 2 and transient:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if attempt < 2:
                await asyncio.sleep(0.3)
                continue
            break

    elapsed = time.monotonic() - t0
    if last_err is not None:
        log.error(
            f"[EVAL3-IMPROVED] Failed after {elapsed:.2f}s: {type(last_err).__name__}: {last_err}",
            exc_info=True,
        )
    return _default_eval()


def _default_eval() -> dict:
    return {
        "scores": {"PSQ": 0, "CCM": 0, "TSI": 0, "CLM": 0, "RAS": 0, "PEI": 0},
        "breakdown": {
            "verb_specificity": 1, "context_completeness": 0,
            "constraint_defined": 0, "focus_clarity": 1,
            "initiative_ratio": 0, "verification_frequency": 0,
            "decomposition_depth": 1, "chunk_size_appropriate": 50,
            "correct_reliance_rate": 0.5,
        },
        "classification": "Novice",
        "leading_status": "ai-led",
        "suggestions": ["Evaluation temporarily unavailable. Please try again."],
        "red_flags": [],
        "strengths": [],
        "turn_summary": "Evaluation unavailable.",
    }