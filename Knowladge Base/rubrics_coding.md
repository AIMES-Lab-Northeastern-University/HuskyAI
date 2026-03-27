# Coding Domain Rubric

Apply this rubric when the conversation involves writing code, implementing features,
architecture decisions, or code review.

## PSQ in Coding Conversations

HIGH PSQ (80-100):
- "Refactor this Express auth middleware to use JWT instead of sessions.
   It needs to work with our existing Redis store. Here's the current code: [...]"
- Clear action verb (refactor), tech stack specified, constraint (Redis), context provided

LOW PSQ (0-25):
- "Help me with my login code"
- "Can you write authentication for me"
- No language, no framework, no constraints, no current state provided

MEDIUM PSQ (40-65):
- "Write a login function in Python using FastAPI"
- Has verb and language but missing: what auth method, what's already built, success criteria

## CCM in Coding Conversations

HIGH CCM signals (user is leading):
- User specifies what they DON'T want before seeing the solution
- User defines acceptance criteria: "it must handle 10k concurrent users"
- User redirects after seeing solution: "that approach won't work because..."
- User asks the AI to explain before implementing

LOW CCM signals (user is led-by):
- User asks "is this correct?" after every generated function
- User copies solution without reading it
- User asks AI to "just finish it" after partial implementation
- User accepts the first approach suggested without questioning alternatives

## TSI in Coding Conversations

HIGH TSI signals:
- User decomposes feature before asking: "I need to handle: (1) auth, (2) session, (3) token refresh"
- User references specific patterns: "I want to use the repository pattern"
- User anticipates edge cases: "what happens if the token expires mid-request?"
- User initiates refinement: "the solution works but I want to optimize the DB query"

LOW TSI signals:
- "Build me a full e-commerce site"
- No decomposition of complex problems
- No mention of edge cases, scale, or technical constraints

## RAS in Coding Conversations

HIGH RAS (appropriate reliance):
- User runs the generated code locally before accepting
- User reads the code before saying it looks good
- User questions unusual patterns: "why are you using X instead of Y here?"
- User provides test results back to AI

LOW RAS (over-reliance):
- User copies AI output directly into production without testing
- User says "looks good" without evidence of reading
- User asks AI to write tests for code the AI wrote (without reviewing first)
- User reports error message without any attempt to debug first
