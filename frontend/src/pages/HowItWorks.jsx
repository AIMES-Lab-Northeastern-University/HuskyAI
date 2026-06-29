import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'

const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');

  :root {
    --red: #C8102E;
    --red-deep: #9E0B24;
    --cream: #F7F3EE;
    --warm: #EDEAE4;
    --ink: #16120E;
    --ink-2: #4A4440;
    --ink-3: #9A948E;
    --white: #FDFCFB;
    --border: rgba(22,18,14,0.1);
  }

  body { font-family: 'DM Sans', sans-serif; }

  .hiw-reveal {
    opacity: 0;
    transform: translateY(20px);
    transition: opacity 0.55s ease, transform 0.55s ease;
  }
  .hiw-reveal.visible {
    opacity: 1;
    transform: translateY(0);
  }

  .hiw-card:hover { background: var(--warm) !important; }
  .hiw-dim-card:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(22,18,14,0.08) !important; }
  .hiw-stage:hover { border-color: var(--red) !important; }
  .hiw-nav-link:hover { color: var(--ink) !important; }
  .hiw-back:hover { color: var(--red) !important; }
  .hiw-pill-btn:hover { background: var(--red) !important; color: #fff !important; }
  .hiw-toc-link:hover { color: var(--red) !important; }
`

const PawIcon = ({ size = 18, color = '#C8102E' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="4" r="2"/>
    <circle cx="18" cy="8" r="2"/>
    <circle cx="20" cy="16" r="2"/>
    <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
  </svg>
)

const ArrowRight = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12h14M12 5l7 7-7 7"/>
  </svg>
)

const CheckIcon = ({ color = '#C8102E' }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
)

const DIMENSIONS = [
  {
    key: 'PSQ', weight: '25%',
    name: 'Prompt Structural Quality',
    color: '#C8102E',
    bg: '#FDE8EC',
    desc: 'Measures verb clarity, context completeness, defined constraints, focus, and alignment. A high-PSQ prompt is precise, scoped, and tells the AI exactly what "done" looks like.',
    sub: [
      { label: 'Verb Specificity (30%)', eg: '"Refactor" vs "help me with"' },
      { label: 'Context Completeness (25%)', eg: 'Language, env, errors, what was tried' },
      { label: 'Constraint Defined (20%)', eg: 'Performance, scope, compatibility bounds' },
      { label: 'Focus Clarity (15%)', eg: 'Precise desired output or success criteria' },
      { label: 'Alignment Specified (10%)', eg: 'How will success be verified?' },
    ],
  },
  {
    key: 'CCM', weight: '25%',
    name: 'Conversation Control Metrics',
    color: '#7C3AED',
    bg: '#EDE9FE',
    desc: 'Tracks who steers the conversation. A leading student redirects errors, challenges assumptions, and drives the AI - rather than accepting whatever it produces.',
    sub: [
      { label: 'Initiative Ratio', eg: 'User-initiated direction changes / total turns' },
      { label: 'Verification Frequency', eg: 'Times user verified AI output' },
      { label: 'Course Correction Rate', eg: 'Redirections after AI errors' },
      { label: 'Assumption Challenge Rate', eg: 'User challenged AI assumptions' },
    ],
  },
  {
    key: 'TSI', weight: '20%',
    name: 'Technical Sophistication Index',
    color: '#0891B2',
    bg: '#E0F2FE',
    desc: 'Evaluates problem decomposition depth, tool/technique awareness, error anticipation, and iteration quality. In debugging, decomposition is weighted +10%.',
    sub: [
      { label: 'Decomposition Depth', eg: 'Sub-problems identified before asking' },
      { label: 'Tool/Technique Awareness', eg: 'References to specific patterns or libraries' },
      { label: 'Error Anticipation', eg: 'Proactive edge-case mentions' },
      { label: 'Solution Iteration', eg: 'User-initiated refinement cycles' },
    ],
  },
  {
    key: 'CLM', weight: '15%',
    name: 'Cognitive Load Management',
    color: '#059669',
    bg: '#D1FAE5',
    desc: 'Assesses whether the student chunks requests appropriately, builds incrementally, and seeks clarification before acting on ambiguity.',
    sub: [
      { label: 'Chunk Size Appropriate', eg: 'Message length matches request complexity' },
      { label: 'Incremental Building', eg: 'Step-by-step vs. monolithic requests' },
      { label: 'Clarification Seeking', eg: 'Questions before acting on ambiguity' },
      { label: 'Mental Model Indicators', eg: 'Numbered steps, explicit assumptions' },
    ],
  },
  {
    key: 'RAS', weight: '15%',
    name: 'Reliance Appropriateness Score',
    color: '#D97706',
    bg: '#FEF3C7',
    desc: 'Distinguishes healthy AI reliance from over- or under-reliance. Red flag: accepting AI output without any verification across 5+ code generation turns.',
    sub: [
      { label: 'Correct Reliance Rate', eg: '(correct self + correct AI) / decisions' },
      { label: 'Over-Reliance Events', eg: 'Accepting incorrect AI output without question' },
      { label: 'Under-Reliance Events', eg: 'Rejecting clearly correct output without reason' },
      { label: 'Trust Calibration', eg: 'Matches task difficulty to reliance level' },
    ],
  },
]

const KB_FILES = [
  { path: 'CORE/', color: '#C8102E', items: ['framework_core.pdf - full PEI definitions, leading/led-by paradigm', 'scoring_rules.md - exact thresholds, red flag triggers, edge cases'] },
  { path: 'RUBRICS/', color: '#7C3AED', items: ['rubric_coding.md - verb specificity in code, CCM in code review', 'rubric_debugging.md - isolation, context requirements, TSI signals', 'rubric_data_analysis.md - SQL, pandas, business question framing', 'rubric_casual.md - TSI down-weighted, CLM and RAS signals'] },
  { path: 'EXEMPLARS/', color: '#0891B2', items: ['exemplars_novice.md - PEI 10–35, annotated why-low breakdowns', 'exemplars_intermediate.md - PEI 40–65, partial improvement patterns', 'exemplars_advanced.md - PEI 70–90, annotated why-high breakdowns'] },
  { path: 'RESEARCH/', color: '#059669', items: ['appropriate_reliance_2024.pdf - Zhang et al. over-reliance in code gen', 'prompting_patterns_2025.pdf - Mahmoud et al. decomposition → quality', 'ai_literacy_frameworks.pdf - NEU AI Literacy Lab, 2025', 'llm_overreliance_studies.pdf - Chen et al., skill stagnation study'] },
]

import { useEffect, useRef } from 'react'

export default function HowItWorks() {
  const navigate = useNavigate()
  const styleRef = useRef(false)
  const isLoggedIn = typeof window !== 'undefined' && !!localStorage.getItem('token')

  useEffect(() => {
    if (!styleRef.current) {
      const el = document.createElement('style')
      el.textContent = STYLES
      document.head.appendChild(el)
      styleRef.current = true
    }

    const obs = new IntersectionObserver(
      (entries) => entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('visible') }),
      { threshold: 0.08 }
    )
    document.querySelectorAll('.hiw-reveal').forEach(el => obs.observe(el))
    return () => obs.disconnect()
  }, [])

  return (
    <div style={{ background: 'var(--cream)', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif" }}>

      {isLoggedIn && <Sidebar />}

      <div style={{ marginLeft: isLoggedIn ? '220px' : 0 }}>

      {!isLoggedIn && (
        /* ── Navbar (public only) ── */
        <nav style={{
          position: 'sticky', top: 0, zIndex: 100,
          background: 'rgba(253,252,251,0.92)', backdropFilter: 'blur(12px)',
          borderBottom: '1.5px solid var(--border)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 40px', height: '58px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}
            onClick={() => navigate('/')}>
            <div style={{
              width: 32, height: 32, background: 'var(--red)', borderRadius: 9,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <PawIcon size={16} color="white" />
            </div>
            <span style={{ fontFamily: "'Instrument Serif', serif", fontSize: 20, color: 'var(--ink)' }}>Husky AI</span>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="hiw-back" onClick={() => navigate('/')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 5, transition: 'color 0.15s' }}>
              ← Back to Home
            </button>
            <button onClick={() => navigate('/login')}
              style={{ background: 'var(--red)', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              Get Started
            </button>
          </div>
        </nav>
      )}

      {/* ── Hero ── */}
      <section style={{ maxWidth: 820, margin: '0 auto', padding: '80px 24px 48px', textAlign: 'center' }}>
        <div className="hiw-reveal" style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          background: '#FDE8EC', borderRadius: 20, padding: '5px 14px',
          fontSize: 12, fontWeight: 600, color: 'var(--red)', marginBottom: 24, letterSpacing: '0.04em',
        }}>
          <PawIcon size={12} color="var(--red)" />
          AIMES LAB · NORTHEASTERN UNIVERSITY
        </div>

        <h1 className="hiw-reveal" style={{
          fontFamily: "'Instrument Serif', serif",
          fontSize: 'clamp(36px, 5vw, 58px)', fontWeight: 400,
          color: 'var(--ink)', lineHeight: 1.12, marginBottom: 20,
        }}>
          How the Evaluation<br />
          <span style={{ color: 'var(--red)', fontStyle: 'italic' }}>Agent Works</span>
        </h1>

        <p className="hiw-reveal" style={{ fontSize: 17, color: 'var(--ink-2)', lineHeight: 1.7, maxWidth: 620, margin: '0 auto 32px' }}>
          Every message you send is analyzed by a two-stage AI pipeline that scores your prompting behavior
          across five research-grounded dimensions - producing a live Prompting Effectiveness Index (PEI).
        </p>

        {/* Attribution card */}
        <div className="hiw-reveal" style={{
          background: 'var(--white)', border: '1.5px solid var(--border)',
          borderRadius: 16, padding: '24px 28px', display: 'inline-block', textAlign: 'left',
          boxShadow: '0 2px 12px rgba(22,18,14,0.06)', maxWidth: 620,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 14 }}>
            Research Team
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>

            {/* Prof. Wihbey */}
            <a href="https://aimeslab.org/" target="_blank" rel="noopener noreferrer"
              style={{ textDecoration: 'none', flex: 1, minWidth: 200 }}>
              <div style={{
                border: '1.5px solid var(--border)', borderRadius: 12, padding: '14px 16px',
                transition: 'border-color 0.15s, box-shadow 0.15s', cursor: 'pointer',
              }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = '#C8102E'; e.currentTarget.style.boxShadow = '0 4px 14px rgba(200,16,46,0.1)' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(22,18,14,0.1)'; e.currentTarget.style.boxShadow = 'none' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <div style={{ width: 34, height: 34, borderRadius: '50%', background: '#FDE8EC', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: '#C8102E' }}>JW</span>
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>Prof. John P. Wihbey</div>
                    <div style={{ fontSize: 11, color: '#C8102E', fontWeight: 600 }}>Principal Investigator</div>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.55 }}>
                  Professor &amp; Director, AIMES Lab<br />
                  Northeastern University
                </div>
                <div style={{ marginTop: 8, fontSize: 10, color: '#C8102E', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}>
                  aimeslab.org
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#C8102E" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
                  </svg>
                </div>
              </div>
            </a>

            {/* Yash Phalle */}
            <div style={{ flex: 1, minWidth: 180, border: '1.5px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <div style={{ width: 34, height: 34, borderRadius: '50%', background: '#EDE9FE', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: '#7C3AED' }}>YP</span>
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>Yash Phalle</div>
                  <div style={{ fontSize: 11, color: '#7C3AED', fontWeight: 600 }}>Research Assistant</div>
                </div>
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.55 }}>
                AIMES Lab, Northeastern University<br />
                MS Artificial Intelligence<br />
                Khoury College of Computer Sciences
              </div>
            </div>

          </div>
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)', fontSize: 12, color: 'var(--ink-3)', fontStyle: 'italic' }}>
            A research initiative building AI-ready professionals through real-time prompting feedback and evidence-based skill evaluation
          </div>
        </div>
      </section>

      {/* ── Architecture Overview ── */}
      <section id="architecture" style={{ maxWidth: 900, margin: '0 auto', padding: '0 24px 72px' }}>
        <div className="hiw-reveal" style={{ textAlign: 'center', marginBottom: 40 }}>
          <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 36, fontWeight: 400, color: 'var(--ink)', marginBottom: 10 }}>
            The Pipeline at a Glance
          </h2>
          <p style={{ fontSize: 15, color: 'var(--ink-3)', maxWidth: 520, margin: '0 auto' }}>
            One message triggers two sequential LLM calls and a vector store retrieval - all within ~2.5 seconds.
          </p>
        </div>

        {/* Pipeline diagram */}
        <div className="hiw-reveal" style={{
          background: 'var(--ink)', borderRadius: 20, padding: '36px 32px',
          display: 'flex', flexDirection: 'column', gap: 0,
        }}>
          {/* Row: User message */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
            <div style={{
              background: '#2A2420', border: '1px solid #3A3430',
              borderRadius: 12, padding: '12px 20px', flex: 1,
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#9A8E88', letterSpacing: '0.08em', marginBottom: 4 }}>STUDENT</div>
              <div style={{ fontSize: 13, color: '#F7F3EE', fontFamily: 'monospace' }}>"Debug this auth middleware - JWT token expires but session persists..."</div>
            </div>
            <div style={{ color: '#C8102E', fontSize: 22 }}>→</div>
            <div style={{
              background: '#C8102E', borderRadius: 12, padding: '12px 20px',
              fontSize: 13, fontWeight: 600, color: '#fff', whiteSpace: 'nowrap',
            }}>
              Gemini 2.5 Pro<br />
              <span style={{ fontWeight: 400, fontSize: 11, opacity: 0.8 }}>streaming response</span>
            </div>
          </div>

          {/* Divider */}
          <div style={{ height: 1, background: '#2A2420', margin: '4px 0 24px' }} />

          {/* Eval pipeline label */}
          <div style={{ fontSize: 10, fontWeight: 700, color: '#9A8E88', letterSpacing: '0.1em', marginBottom: 16 }}>EVALUATION PIPELINE (runs in parallel with response delivery)</div>

          {/* Stage 1 */}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 14 }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%', background: '#7C3AED',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 13, fontWeight: 700, color: '#fff', flexShrink: 0, marginTop: 2,
            }}>1</div>
            <div style={{
              background: '#1E1A18', border: '1px solid #2A2420',
              borderRadius: 12, padding: '14px 18px', flex: 1,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#E8E4E0' }}>Stage 1 - Domain Detector</div>
                <span style={{ fontSize: 11, background: '#7C3AED22', color: '#A78BFA', borderRadius: 6, padding: '2px 8px' }}>~500ms</span>
              </div>
              <div style={{ fontSize: 12, color: '#9A8E88', marginBottom: 8 }}>gpt-4.1-nano · temperature 1 · structured output</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {['coding', 'debugging', 'data_analysis', 'casual', 'creative'].map(d => (
                  <span key={d} style={{ fontSize: 11, background: '#2A2420', color: '#C8C0B8', borderRadius: 6, padding: '3px 8px', fontFamily: 'monospace' }}>{d}</span>
                ))}
              </div>
            </div>
          </div>

          <div style={{ marginLeft: 14, width: 1, height: 16, background: '#2A2420' }} />

          {/* Stage 2 */}
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%', background: '#C8102E',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 13, fontWeight: 700, color: '#fff', flexShrink: 0, marginTop: 2,
            }}>2</div>
            <div style={{
              background: '#1E1A18', border: '1px solid #2A2420',
              borderRadius: 12, padding: '14px 18px', flex: 1,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#E8E4E0' }}>Stage 2 - PEI Evaluator</div>
                <span style={{ fontSize: 11, background: '#C8102E22', color: '#FCA5A5', borderRadius: 6, padding: '2px 8px' }}>~2000ms</span>
              </div>
              <div style={{ fontSize: 12, color: '#9A8E88', marginBottom: 8 }}>gpt-4.1 · FileSearchTool · 8 KB chunks retrieved per call</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {['PSQ', 'CCM', 'TSI', 'CLM', 'RAS', 'PEI', 'classification', 'suggestions', 'red_flags'].map(f => (
                  <span key={f} style={{ fontSize: 11, background: '#C8102E18', color: '#FCA5A5', borderRadius: 6, padding: '3px 8px', fontFamily: 'monospace' }}>{f}</span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stage 1 Deep Dive ── */}
      <section id="stage1" style={{ maxWidth: 900, margin: '0 auto', padding: '0 24px 72px' }}>
        <div className="hiw-reveal" style={{ marginBottom: 32 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: '#7C3AED', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: '#fff', flexShrink: 0 }}>1</div>
            <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 32, fontWeight: 400, color: 'var(--ink)' }}>Stage 1 - Domain Detector</h2>
          </div>
          <p style={{ fontSize: 15, color: 'var(--ink-2)', lineHeight: 1.7, maxWidth: 700 }}>
            Before scoring, the pipeline must know <em>what kind</em> of work the student is doing.
            A fast, cheap model classifies the conversation into one of five domains so that
            Stage 2 retrieves the right rubric from the knowledge base.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14 }}>
          {[
            { domain: 'coding', color: '#7C3AED', bg: '#EDE9FE', signal: 'User is creating something new in code', eg: 'Features, architecture, code review' },
            { domain: 'debugging', color: '#C8102E', bg: '#FDE8EC', signal: 'Something exists and is not working', eg: 'Error messages, stack traces, broken behavior' },
            { domain: 'data_analysis', color: '#0891B2', bg: '#E0F2FE', signal: 'Subject is data - querying or understanding it', eg: 'SQL, pandas, statistics, ML pipelines' },
            { domain: 'casual', color: '#059669', bg: '#D1FAE5', signal: 'No code written - learning or discussing', eg: 'Concept questions, theory, explanations' },
            { domain: 'creative', color: '#D97706', bg: '#FEF3C7', signal: 'Output is words, ideas, or strategy', eg: 'Writing, design thinking, brainstorming' },
          ].map(({ domain, color, bg, signal, eg }) => (
            <div key={domain} className="hiw-reveal hiw-card" style={{
              background: 'var(--white)', border: '1.5px solid var(--border)',
              borderRadius: 14, padding: '18px 20px', transition: 'background 0.15s',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <div style={{ background: bg, color, borderRadius: 8, padding: '3px 10px', fontSize: 12, fontWeight: 700, fontFamily: 'monospace' }}>{domain}</div>
              </div>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)', marginBottom: 4 }}>{signal}</div>
              <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>{eg}</div>
            </div>
          ))}
        </div>

        <div className="hiw-reveal" style={{
          marginTop: 20, background: '#FDE8EC', borderRadius: 14, padding: '16px 20px',
          display: 'flex', gap: 12, alignItems: 'flex-start',
        }}>
          <div style={{ fontSize: 16, marginTop: 1 }}>💡</div>
          <div>
            <strong style={{ fontSize: 13, color: 'var(--ink)' }}>Priority rule:</strong>
            <span style={{ fontSize: 13, color: 'var(--ink-2)' }}> If both <code style={{ background: 'var(--warm)', padding: '1px 5px', borderRadius: 4 }}>debugging</code> and <code style={{ background: 'var(--warm)', padding: '1px 5px', borderRadius: 4 }}>coding</code> are present, Stage 1 always picks <strong>debugging</strong> - the more specific context. Fallback: if Stage 1 fails, domain defaults to <code style={{ background: 'var(--warm)', padding: '1px 5px', borderRadius: 4 }}>general</code> and Stage 2 proceeds without domain filtering.</span>
          </div>
        </div>
      </section>

      {/* ── Stage 2 Deep Dive ── */}
      <section id="stage2" style={{ maxWidth: 900, margin: '0 auto', padding: '0 24px 72px' }}>
        <div className="hiw-reveal" style={{ marginBottom: 32 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: '#C8102E', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700, color: '#fff', flexShrink: 0 }}>2</div>
            <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 32, fontWeight: 400, color: 'var(--ink)' }}>Stage 2 - PEI Evaluator</h2>
          </div>
          <p style={{ fontSize: 15, color: 'var(--ink-2)', lineHeight: 1.7, maxWidth: 700 }}>
            The evaluator agent receives the domain label from Stage 1, queries the vector knowledge base
            for the right rubric and exemplars, builds a student historical profile from the database,
            then scores the full conversation on five dimensions.
          </p>
        </div>

        {/* Eval prompt structure */}
        <div className="hiw-reveal" style={{
          background: 'var(--ink)', borderRadius: 16, padding: '28px 28px', marginBottom: 20,
          fontFamily: 'monospace', fontSize: 13, color: '#C8C0B8', lineHeight: 1.8,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#9A8E88', letterSpacing: '0.08em', marginBottom: 16, fontFamily: 'sans-serif' }}>EVALUATOR INPUT PROMPT STRUCTURE</div>
          <div><span style={{ color: '#A78BFA' }}>CONVERSATION DOMAIN:</span> debugging</div>
          <div style={{ marginTop: 12 }}><span style={{ color: '#A78BFA' }}>STUDENT HISTORICAL PROFILE:</span></div>
          <div style={{ paddingLeft: 16, color: '#9A8E88' }}>
            Sessions completed: 7<br/>
            Average PEI (recent 5): 54.2<br/>
            Strongest dimension: TSI (avg 68)<br/>
            Weakest dimension:   RAS (avg 34)<br/>
            Trend: improving (+8.1 PEI over last 4 sessions)<br/>
            Recurring red flags: ["accepts code without verification", "vague error context"]
          </div>
          <div style={{ marginTop: 12 }}><span style={{ color: '#A78BFA' }}>INSTRUCTIONS:</span></div>
          <div style={{ paddingLeft: 16, color: '#9A8E88' }}>
            1. Retrieve the debugging rubric and exemplars from knowledge base<br/>
            2. Score using PEI framework - scores are absolute, not relative to history<br/>
            3. Personalize suggestions using student's historical weak areas<br/>
            4. Flag if student is repeating a known red flag pattern<br/>
            5. Note if student shows improvement vs historical baseline
          </div>
          <div style={{ marginTop: 12 }}><span style={{ color: '#A78BFA' }}>CURRENT SESSION</span> <span style={{ color: '#9A8E88' }}>(3 user turns so far):</span></div>
          <div style={{ paddingLeft: 16, color: '#9A8E88' }}>
            [Turn 1] USER: ...<br/>
            [Turn 2] USER: ...<br/>
            [Turn 3] USER: (latest - weight most heavily for PSQ)
          </div>
        </div>

        <div className="hiw-reveal" style={{
          background: 'var(--white)', border: '1.5px solid var(--border)',
          borderRadius: 14, padding: '20px 24px', marginBottom: 20,
        }}>
          <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--ink)', marginBottom: 12 }}>Vector Store Retrieval - What gets pulled in</div>
          <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 14 }}>
            The domain-hinted prompt causes semantic retrieval of the right files naturally - no manual routing.
          </div>
          {[
            { score: '0.94', file: 'rubric_debugging.md', section: 'isolation & hypothesis section' },
            { score: '0.91', file: 'exemplars_advanced.md', section: 'debugging exemplar (PEI 84)' },
            { score: '0.88', file: 'framework_core.pdf', section: 'PSQ formula & definitions' },
            { score: '0.85', file: 'exemplars_novice.md', section: 'debugging exemplar (PEI 18)' },
            { score: '0.83', file: 'rubric_debugging.md', section: 'RAS verification section' },
            { score: '0.81', file: 'scoring_rules.md', section: 'red flag trigger conditions' },
          ].map(({ score, file, section }) => (
            <div key={file + section} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
              <div style={{ width: 38, fontSize: 12, fontWeight: 700, color: '#059669', fontFamily: 'monospace', flexShrink: 0 }}>{score}</div>
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', fontFamily: 'monospace' }}>{file}</span>
                <span style={{ fontSize: 12, color: 'var(--ink-3)' }}> - {section}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── PEI Formula ── */}
      <section id="pei" style={{ background: 'var(--ink)', padding: '72px 24px' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div className="hiw-reveal" style={{ textAlign: 'center', marginBottom: 48 }}>
            <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 40, fontWeight: 400, color: '#F7F3EE', marginBottom: 14 }}>
              The PEI Formula
            </h2>
            <div style={{ fontSize: 22, fontFamily: 'monospace', color: '#F7F3EE', background: '#2A2420', borderRadius: 12, padding: '16px 28px', display: 'inline-block', marginBottom: 16 }}>
              <span style={{ color: '#FCA5A5' }}>PEI</span>
              <span style={{ color: '#9A8E88' }}> = </span>
              <span style={{ color: '#A78BFA' }}>0.25</span><span style={{ color: '#9A8E88' }}>×PSQ </span>
              <span style={{ color: '#9A8E88' }}>+ </span>
              <span style={{ color: '#A78BFA' }}>0.25</span><span style={{ color: '#9A8E88' }}>×CCM </span>
              <span style={{ color: '#9A8E88' }}>+ </span>
              <span style={{ color: '#A78BFA' }}>0.20</span><span style={{ color: '#9A8E88' }}>×TSI </span>
              <span style={{ color: '#9A8E88' }}>+ </span>
              <span style={{ color: '#A78BFA' }}>0.15</span><span style={{ color: '#9A8E88' }}>×CLM </span>
              <span style={{ color: '#9A8E88' }}>+ </span>
              <span style={{ color: '#A78BFA' }}>0.15</span><span style={{ color: '#9A8E88' }}>×RAS</span>
            </div>
            <p style={{ fontSize: 14, color: '#9A8E88', maxWidth: 560, margin: '0 auto' }}>
              Each dimension scores 0–100. The weighted sum yields a single PEI from 0–100,
              classified as Novice (&lt;40), Intermediate (40–70), or Advanced (&gt;70).
            </p>
          </div>

          {/* Classification bands */}
          <div className="hiw-reveal" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 48 }}>
            {[
              { label: 'Novice', range: 'PEI < 40', color: '#F97316', desc: 'Predominantly led-by AI. Low structure, minimal verification. Student accepts first output.' },
              { label: 'Intermediate', range: 'PEI 40–70', color: '#EAB308', desc: 'Mixed control. Improving structure, occasional verification, inconsistent self-direction.' },
              { label: 'Advanced', range: 'PEI > 70', color: '#22C55E', desc: 'Leading the AI. Sophisticated prompting, consistent verification, deliberate conversation control.' },
            ].map(({ label, range, color, desc }) => (
              <div key={label} style={{
                background: '#1E1A18', border: '1px solid #2A2420',
                borderRadius: 14, padding: '20px 20px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#F7F3EE' }}>{label}</div>
                  <div style={{ marginLeft: 'auto', fontSize: 12, color: '#9A8E88', fontFamily: 'monospace' }}>{range}</div>
                </div>
                <div style={{ fontSize: 12, color: '#9A8E88', lineHeight: 1.6 }}>{desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Five Dimensions ── */}
      <section id="dimensions" style={{ maxWidth: 900, margin: '0 auto', padding: '72px 24px' }}>
        <div className="hiw-reveal" style={{ textAlign: 'center', marginBottom: 48 }}>
          <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 38, fontWeight: 400, color: 'var(--ink)', marginBottom: 12 }}>
            Five Dimensions, Explained
          </h2>
          <p style={{ fontSize: 15, color: 'var(--ink-3)', maxWidth: 520, margin: '0 auto' }}>
            Each dimension targets a distinct, research-grounded aspect of effective human-AI collaboration.
          </p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {DIMENSIONS.map(({ key, weight, name, color, bg, desc, sub }) => (
            <div key={key} className="hiw-reveal hiw-dim-card" style={{
              background: 'var(--white)', border: '1.5px solid var(--border)',
              borderRadius: 18, padding: '28px 32px',
              boxShadow: '0 2px 8px rgba(22,18,14,0.04)',
              transition: 'transform 0.2s, box-shadow 0.2s',
            }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20 }}>
                {/* Badge */}
                <div style={{
                  background: bg, border: `2px solid ${color}20`,
                  borderRadius: 14, padding: '10px 14px', textAlign: 'center',
                  flexShrink: 0, minWidth: 72,
                }}>
                  <div style={{ fontSize: 20, fontWeight: 800, color, fontFamily: "'Instrument Serif', serif" }}>{key}</div>
                  <div style={{ fontSize: 11, fontWeight: 700, color, marginTop: 2 }}>{weight}</div>
                </div>
                {/* Content */}
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--ink)', marginBottom: 8 }}>{name}</div>
                  <p style={{ fontSize: 14, color: 'var(--ink-2)', lineHeight: 1.65, marginBottom: 16, margin: '0 0 16px' }}>{desc}</p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
                    {sub.map(({ label, eg }) => (
                      <div key={label} style={{
                        display: 'flex', gap: 8, alignItems: 'flex-start',
                        background: 'var(--cream)', borderRadius: 10, padding: '10px 12px',
                      }}>
                        <div style={{ marginTop: 1, flexShrink: 0 }}><CheckIcon color={color} /></div>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)' }}>{label}</div>
                          <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2 }}>{eg}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Knowledge Base ── */}
      <section id="kb" style={{ background: 'var(--warm)', padding: '72px 24px' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div className="hiw-reveal" style={{ textAlign: 'center', marginBottom: 40 }}>
            <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 38, fontWeight: 400, color: 'var(--ink)', marginBottom: 12 }}>
              The Knowledge Base
            </h2>
            <p style={{ fontSize: 15, color: 'var(--ink-3)', maxWidth: 580, margin: '0 auto' }}>
              Stage 2 is not prompted with raw scoring rules - it retrieves them from a structured vector store
              at runtime. This grounds every evaluation in peer-reviewed rubrics and real exemplars.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
            {KB_FILES.map(({ path, color, items }) => (
              <div key={path} className="hiw-reveal" style={{
                background: 'var(--white)', border: '1.5px solid var(--border)',
                borderRadius: 16, padding: '20px 22px',
              }}>
                <div style={{
                  fontSize: 12, fontWeight: 700, color, fontFamily: 'monospace',
                  marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                  </svg>
                  {path}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {items.map(item => (
                    <div key={item} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                      <div style={{ width: 5, height: 5, borderRadius: '50%', background: color, marginTop: 6, flexShrink: 0 }} />
                      <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.5 }}>{item}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="hiw-reveal" style={{
            marginTop: 20, background: 'var(--white)', border: '1.5px solid var(--border)',
            borderRadius: 14, padding: '18px 22px',
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink)', marginBottom: 8 }}>File naming is part of the retrieval strategy</div>
            <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#059669', marginBottom: 4 }}>Good</div>
                {['rubric_coding.md', 'exemplars_advanced_debugging.md', 'research_reliance_zhang2024.pdf'].map(f => (
                  <div key={f} style={{ fontSize: 12, color: 'var(--ink-2)', fontFamily: 'monospace', marginBottom: 3 }}>✓ {f}</div>
                ))}
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#C8102E', marginBottom: 4 }}>Bad</div>
                {['doc1.pdf', 'rubric.md', 'data.txt'].map(f => (
                  <div key={f} style={{ fontSize: 12, color: 'var(--ink-3)', fontFamily: 'monospace', marginBottom: 3 }}>✗ {f} - too generic for semantic search</div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Red Flags ── */}
      <section id="redflags" style={{ maxWidth: 900, margin: '0 auto', padding: '72px 24px' }}>
        <div className="hiw-reveal" style={{ marginBottom: 32 }}>
          <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 36, fontWeight: 400, color: 'var(--ink)', marginBottom: 12 }}>
            Red Flags & Intervention Triggers
          </h2>
          <p style={{ fontSize: 15, color: 'var(--ink-2)', lineHeight: 1.7, maxWidth: 640 }}>
            The evaluator automatically surfaces patterns that indicate a student is developing
            unhealthy AI reliance habits - before they become entrenched.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
          {[
            { title: 'Persistent Over-Reliance', trigger: 'RAS < 0.3 across 3+ consecutive turns', risk: 'Student accepts AI output without any critical evaluation' },
            { title: 'Multi-Turn Degradation', trigger: 'PEI drops >50% from turn 1 to turn 5', risk: 'Student loses focus or structure as conversation deepens' },
            { title: 'Premature Acceptance', trigger: 'Incorrect AI suggestions accepted >40% of turns', risk: 'Student is not verifying - outputs go directly to production' },
            { title: 'Zero Verification', trigger: 'No verification attempts across 5+ code generations', risk: 'Critical - especially in debugging and coding domains' },
          ].map(({ title, trigger, risk }) => (
            <div key={title} className="hiw-reveal" style={{
              background: '#FFF5F5', border: '1.5px solid #FED7D7',
              borderRadius: 14, padding: '18px 20px',
            }}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C8102E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginTop: 1, flexShrink: 0 }}>
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                  <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#9B1C1C' }}>{title}</div>
              </div>
              <div style={{ fontSize: 12, color: '#C8102E', marginBottom: 6, fontFamily: 'monospace', background: '#FDE8EC', borderRadius: 6, padding: '4px 8px' }}>{trigger}</div>
              <div style={{ fontSize: 12, color: '#7F1D1D', lineHeight: 1.55 }}>{risk}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={{ background: 'var(--ink)', padding: '72px 24px', textAlign: 'center' }}>
        <div className="hiw-reveal">
          <div style={{
            width: 52, height: 52, background: 'var(--red)', borderRadius: 15,
            display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px',
          }}>
            <PawIcon size={24} color="white" />
          </div>
          <h2 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 40, fontWeight: 400, color: '#F7F3EE', marginBottom: 14 }}>
            Ready to see your PEI?
          </h2>
          <p style={{ fontSize: 16, color: '#9A8E88', maxWidth: 460, margin: '0 auto 32px', lineHeight: 1.65 }}>
            Every prompt you write is a data point. Start a challenge and watch your scores evolve in real time.
          </p>
          <button onClick={() => navigate(isLoggedIn ? '/challenges' : '/login')} style={{
            background: 'var(--red)', color: '#fff', border: 'none',
            borderRadius: 10, padding: '14px 32px', fontSize: 15, fontWeight: 600,
            cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8,
          }}>
            {isLoggedIn ? 'Try a challenge' : 'Get Started'} <ArrowRight size={15} />
          </button>
        </div>

        {/* Footer attribution */}
        <div style={{ marginTop: 64, paddingTop: 32, borderTop: '1px solid #2A2420' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, marginBottom: 16 }}>
            <div style={{ width: 28, height: 28, background: '#2A2420', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <PawIcon size={14} color="#C8102E" />
            </div>
            <span style={{ fontFamily: "'Instrument Serif', serif", fontSize: 18, color: '#F7F3EE' }}>Husky AI</span>
          </div>
          <div style={{ fontSize: 13, color: '#9A8E88', lineHeight: 1.9 }}>
            Built by the{' '}
            <a href="https://aimeslab.org/" target="_blank" rel="noopener noreferrer"
              style={{ color: '#C8C0B8', textDecoration: 'underline', textUnderlineOffset: 3 }}>
              AIMES Lab
            </a>
            {' '}at Northeastern University<br />
            <strong style={{ color: '#C8C0B8' }}>Prof. John P. Wihbey</strong>
            <span style={{ color: '#6A6460' }}> - Associate Professor &amp; Director, AIMES Lab · Special Advisor for Strategic AI Initiatives</span><br />
            <strong style={{ color: '#C8C0B8' }}>Yash Phalle</strong>
            <span style={{ color: '#6A6460' }}> - Research Assistant, AIMES Lab · MS AI, Khoury College of Computer Sciences</span><br />
            <span style={{ fontStyle: 'italic' }}>A research initiative building AI-ready professionals through real-time prompting feedback and evidence-based skill evaluation</span>
          </div>
        </div>
      </section>

      </div>
    </div>
  )
}
