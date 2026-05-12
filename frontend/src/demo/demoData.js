/** Static demo content - no API keys or DB required */

export const DEMO_USER = { name: 'Demo Student', email: 'demo@husky.edu' }

export const SAMPLE_EVAL = {
  scores: { PSQ: 72, CCM: 64, TSI: 58, CLM: 70, RAS: 55, PEI: 64 },
  breakdown: {
    verb_specificity: 4,
    context_completeness: 72,
    constraint_defined: 1,
    focus_clarity: 4,
    initiative_ratio: 0.55,
    verification_frequency: 0.4,
    decomposition_depth: 6,
    chunk_size_appropriate: 75,
    correct_reliance_rate: 0.55,
  },
  classification: 'Intermediate',
  leading_status: 'Leading',
  suggestions: [
    'State the exact error text and what you already tried before asking for a fix.',
    'Ask the model to propose 2 approaches and compare trade-offs instead of accepting the first answer.',
    'Add acceptance criteria (what “done” looks like) so responses stay scoped.',
  ],
  red_flags: [],
  strengths: ['You asked a focused follow-up after the first reply.'],
  turn_summary: 'Demo turn - sample evaluation for product tour.',
}

export const DEMO_CHALLENGE_CONTEXTS = {
  'debug-app': {
    title: 'Session 1: Reproduce & Triage',
    goal: 'Identify the most likely root causes from symptoms alone.',
    brief:
      "You've received user reports about login failures and slow loads (sample brief).\n\nThis is illustrative data for the demo.",
    seed_question:
      'Based on these symptoms alone, what are the most likely root causes? Walk me through your reasoning.',
  },
  campaign: {
    title: 'Session 1: Audience & message',
    goal: 'Define who you are trying to reach and the core message.',
    brief: 'Sample creative brief for the demo - outline stakeholders and constraints.',
    seed_question: 'Who is the primary audience, and what behavior do you want to change?',
  },
  'data-story': {
    title: 'Session 1: Frame the question',
    goal: 'Turn a raw dataset into a sharp analytical question.',
    brief: 'Sample data narrative brief for the demo.',
    seed_question: 'What decision should this analysis inform, and what would convince a skeptic?',
  },
}

export function demoSlugForChallengeId(id) {
  const m = {
    'demo-debug-app': 'debug-app',
    'demo-campaign': 'campaign',
    'demo-data-story': 'data-story',
  }
  return m[id] || 'debug-app'
}

export const DEMO_CHALLENGE_LIST = [
  {
    id: 'demo-debug-app',
    title: 'Debug a Failing Web App',
    description:
      'A production web application is broken. Practice triaging symptoms and using AI as a partner - sample challenge.',
    category: 'Technical',
    difficulty: 'Beginner',
    week: 1,
    total_sessions: 3,
    sessions_completed: 1,
    best_pei: 62,
    is_active: true,
  },
  {
    id: 'demo-campaign',
    title: 'Design a Public Awareness Campaign',
    description:
      'Brainstorm and refine a multi-channel campaign with AI - sample creative challenge.',
    category: 'Creative & Strategy',
    difficulty: 'Beginner',
    week: 2,
    total_sessions: 3,
    sessions_completed: 0,
    best_pei: null,
    is_active: true,
  },
  {
    id: 'demo-data-story',
    title: 'Tell a Story with Data',
    description:
      'Turn a dataset into a clear narrative and visuals - sample data literacy challenge.',
    category: 'Data & Analysis',
    difficulty: 'Intermediate',
    week: 3,
    total_sessions: 4,
    sessions_completed: 0,
    best_pei: null,
    is_active: true,
  },
]

const SESSION_TMPL = (n, title, goal) => ({
  session_number: n,
  title,
  goal,
  brief: 'Sample session brief for the interactive demo.',
  seed_question: 'What is your first step, and what evidence will you ask the AI to help you gather?',
  status: n === 1 ? 'completed' : n === 2 ? 'in_progress' : 'not_started',
  best_pei: n === 1 ? 62 : null,
  conversation_id: null,
  started_at: n <= 2 ? '2026-04-01T12:00:00' : null,
  completed_at: n === 1 ? '2026-04-01T12:45:00' : null,
})

export function getDemoChallengeDetail(id) {
  const row = DEMO_CHALLENGE_LIST.find((c) => c.id === id)
  if (!row) return null
  const total = row.total_sessions
  const sessions = Array.from({ length: total }, (_, i) => {
    const n = i + 1
    return SESSION_TMPL(n, `Session ${n}`, `Demo goal for session ${n}`)
  })
  return {
    id: row.id,
    title: row.title,
    description: row.description,
    category: row.category,
    difficulty: row.difficulty,
    week: row.week,
    total_sessions: row.total_sessions,
    sessions,
  }
}

export function cannedAssistantReply(userMessage) {
  return (
    'Here is a **sample coach response** (demo mode - no live model):\n\n' +
    '- Restate what you are trying to achieve in one sentence.\n' +
    '- List what you already know vs. what is unknown.\n' +
    '- Ask yourself what evidence would change your next step.\n\n' +
    `You wrote: "${userMessage.slice(0, 200)}${userMessage.length > 200 ? '…' : ''}"`
  )
}
