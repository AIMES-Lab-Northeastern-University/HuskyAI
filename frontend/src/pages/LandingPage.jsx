import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

/* ─── Inline keyframes injected once ─── */
const GLOBAL_STYLES = `
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

  @keyframes lp-fadeUp {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  @keyframes lp-marquee {
    from { transform: translateX(0); }
    to   { transform: translateX(-50%); }
  }

  @keyframes lp-pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
  }

  .lp-reveal {
    opacity: 0;
    transform: translateY(24px);
    transition: opacity 0.6s ease, transform 0.6s ease;
  }
  .lp-reveal.visible {
    opacity: 1;
    transform: translateY(0);
  }

  .lp-step:hover  { background: var(--warm) !important; }
  .lp-feat:hover  { background: var(--warm) !important; }
  .lp-feat-dark:hover { background: #2A2420 !important; }
  .lp-dim:hover   { background: var(--warm) !important; transform: translateY(-3px); }

  .lp-nav-cta:hover { background: var(--red) !important; }
  .lp-nav-link:hover { color: var(--ink) !important; }

  .lp-btn-primary:hover  { background: var(--red-deep) !important; transform: translateY(-1px); }
  .lp-btn-secondary:hover { color: var(--red) !important; border-color: var(--red) !important; }

  .lp-footer-link:hover { color: var(--ink) !important; }
`

/* ─── SVG icons ─── */
const PawIcon = ({ size = 16, color = 'white' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="4" r="2"/>
    <circle cx="18" cy="8" r="2"/>
    <circle cx="20" cy="16" r="2"/>
    <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
  </svg>
)

const MonitorIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 20, height: 20, stroke: '#C8102E' }}>
    <rect x="2" y="3" width="20" height="14" rx="2"/>
    <path d="M8 21h8M12 17v4"/>
  </svg>
)

const EditIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 20, height: 20, stroke: '#C8102E' }}>
    <path d="M12 20h9"/>
    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
  </svg>
)

const UsersIcon = ({ dimColor }) => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round"
    style={{ width: 20, height: 20, stroke: dimColor || '#C8102E' }}>
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
  </svg>
)

const BoltIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 20, height: 20, stroke: '#C8102E' }}>
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
  </svg>
)

const BarsIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 20, height: 20, stroke: '#C8102E' }}>
    <line x1="18" y1="20" x2="18" y2="10"/>
    <line x1="12" y1="20" x2="12" y2="4"/>
    <line x1="6" y1="20" x2="6" y2="14"/>
  </svg>
)

const BookIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 20, height: 20, stroke: '#C8102E' }}>
    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
  </svg>
)

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16, stroke: '#C8102E' }}>
    <polyline points="20 6 9 17 4 12"/>
  </svg>
)

const InfoIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 13, height: 13, stroke: '#FCA5A5' }}>
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="16" x2="12" y2="12"/>
    <line x1="12" y1="8" x2="12.01" y2="8"/>
  </svg>
)

const ArrowIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 14, height: 14, stroke: 'currentColor' }}>
    <line x1="5" y1="12" x2="19" y2="12"/>
    <polyline points="12 5 19 12 12 19"/>
  </svg>
)

const ChevronDownIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" style={{ width: 14, height: 14, stroke: 'currentColor' }}>
    <polyline points="6 9 12 15 18 9"/>
  </svg>
)

/* ─── Marquee items ─── */
const MARQUEE_ITEMS = [
  'Prompt Structural Quality',
  'Conversation Control',
  'Technical Sophistication',
  'Cognitive Load Management',
  'Reliance Appropriateness',
  'Real-time Feedback',
  'Classroom Competition',
  'AI Literacy Scoring',
]

export default function LandingPage() {
  const navigate = useNavigate()

  /* Inject global styles once */
  useEffect(() => {
    const id = 'lp-global-styles'
    if (!document.getElementById(id)) {
      const tag = document.createElement('style')
      tag.id = id
      tag.textContent = GLOBAL_STYLES
      document.head.appendChild(tag)
    }
    return () => {
      // leave styles in place; harmless
    }
  }, [])

  /* Scroll-reveal via IntersectionObserver */
  useEffect(() => {
    const reveals = document.querySelectorAll('.lp-reveal')
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((e, i) => {
          if (e.isIntersecting) {
            setTimeout(() => e.target.classList.add('visible'), i * 80)
          }
        })
      },
      { threshold: 0.1 }
    )
    reveals.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  /* ── styles objects ── */
  const s = {
    page: {
      fontFamily: "'DM Sans', sans-serif",
      background: 'var(--cream)',
      color: 'var(--ink)',
      overflowX: 'hidden',
    },

    /* NAV */
    nav: {
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      display: 'flex', alignItems: 'center', padding: '0 48px', height: 60,
      background: 'rgba(247,243,238,0.92)', backdropFilter: 'blur(12px)',
      borderBottom: '1px solid var(--border)',
    },
    navLogo: {
      display: 'flex', alignItems: 'center', gap: 10,
      fontFamily: "'Instrument Serif', serif", fontSize: 20, color: 'var(--ink)',
      textDecoration: 'none', cursor: 'pointer',
    },
    navPaw: {
      width: 30, height: 30, background: 'var(--red)', borderRadius: 8,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    },
    navLinks: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 32 },
    navLink: { fontSize: 13, fontWeight: 500, color: 'var(--ink-2)', textDecoration: 'none', cursor: 'pointer', transition: 'color 0.15s' },
    navCta: {
      background: 'var(--ink)', color: 'var(--white)', padding: '8px 20px',
      borderRadius: 6, fontWeight: 600, fontSize: 13, cursor: 'pointer',
      textDecoration: 'none', transition: 'background 0.15s', border: 'none',
      fontFamily: "'DM Sans', sans-serif",
    },

    /* HERO */
    heroWrap: { background: 'var(--cream)' },
    hero: {
      minHeight: '100vh', padding: '140px 48px 80px',
      display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80,
      alignItems: 'center', maxWidth: 1280, margin: '0 auto',
    },
    heroLeft: { animation: 'lp-fadeUp 0.7s ease both' },
    heroEyebrow: {
      display: 'inline-flex', alignItems: 'center', gap: 8,
      fontSize: 11, fontWeight: 600, letterSpacing: 2,
      textTransform: 'uppercase', color: 'var(--red)', marginBottom: 24,
    },
    eyebrowLine: { width: 24, height: 1.5, background: 'var(--red)' },
    heroH1: {
      fontFamily: "'Instrument Serif', serif",
      fontSize: 'clamp(48px, 5.5vw, 76px)',
      lineHeight: 1.08, letterSpacing: -1,
      color: 'var(--ink)', marginBottom: 28,
    },
    heroH1Em: { fontStyle: 'italic', color: 'var(--red)' },
    heroSub: {
      fontSize: 17, fontWeight: 300, color: 'var(--ink-2)',
      lineHeight: 1.75, maxWidth: 440, marginBottom: 44,
    },
    heroActions: { display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' },
    btnPrimary: {
      background: 'var(--red)', color: 'white',
      fontFamily: "'DM Sans', sans-serif", fontSize: 14, fontWeight: 600,
      padding: '14px 28px', borderRadius: 8, border: 'none', cursor: 'pointer',
      textDecoration: 'none', display: 'inline-block',
      transition: 'background 0.15s, transform 0.1s',
    },
    btnSecondary: {
      fontFamily: "'DM Sans', sans-serif", fontSize: 14, fontWeight: 500,
      color: 'var(--ink-2)', textDecoration: 'none',
      display: 'inline-flex', alignItems: 'center', gap: 6,
      paddingBottom: 2,
      transition: 'color 0.15s, border-color 0.15s', cursor: 'pointer', background: 'none', border: 'none', borderBottom: '1px solid var(--border)',
    },
    heroStats: {
      display: 'flex', gap: 36, marginTop: 56, paddingTop: 40,
      borderTop: '1px solid var(--border)',
    },
    statN: { fontFamily: "'Instrument Serif', serif", fontSize: 36, color: 'var(--ink)', lineHeight: 1 },
    statNSpan: { color: 'var(--red)' },
    statLbl: { fontSize: 12, color: 'var(--ink-3)', marginTop: 4, fontWeight: 500 },

    /* HERO RIGHT */
    heroRight: { animation: 'lp-fadeUp 0.7s 0.15s ease both', position: 'relative', paddingBottom: 28, paddingRight: 28 },
    uiPreview: {
      background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 16,
      overflow: 'hidden',
      boxShadow: '0 24px 64px rgba(22,18,14,0.12), 0 4px 16px rgba(22,18,14,0.06)',
    },
    uiBar: {
      background: '#FDFCFB', borderBottom: '1px solid var(--border)',
      padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 8,
    },
    uiDots: { display: 'flex', gap: 5 },
    uiTitle: { fontSize: 12, fontWeight: 600, color: 'var(--ink-3)', marginLeft: 8 },
    uiBody: { padding: 20 },
    uiTaskCard: {
      background: 'var(--red)', borderRadius: 12, padding: '18px 20px',
      marginBottom: 14, color: 'white', position: 'relative', overflow: 'hidden',
    },
    uiTaskCardBg: { position: 'absolute', right: 16, top: '50%', transform: 'translateY(-50%)', opacity: 0.12 },
    uiWeek: { fontSize: 10, fontWeight: 600, opacity: 0.7, letterSpacing: 1, textTransform: 'uppercase', marginBottom: 5 },
    uiTaskName: { fontFamily: "'Instrument Serif', serif", fontSize: 17, marginBottom: 10 },
    uiTaskBtn: {
      display: 'inline-block', background: 'white', color: 'var(--red)',
      fontSize: 11, fontWeight: 700, padding: '6px 14px', borderRadius: 6,
    },
    uiGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 14 },
    uiStat: { background: 'var(--cream)', borderRadius: 8, padding: '10px 12px' },
    uiStatN: { fontFamily: "'Instrument Serif', serif", fontSize: 22, color: 'var(--ink)' },
    uiStatL: { fontSize: 10, color: 'var(--ink-3)', marginTop: 2, fontWeight: 500 },
    uiPromptRow: {
      background: 'var(--cream)', borderRadius: 10, padding: '10px 14px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    },
    uiPromptLabel: { fontSize: 11, color: 'var(--ink-3)', fontWeight: 500 },
    uiScorePill: {
      fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 20,
      background: '#DCFCE7', color: '#15803D',
    },
    floatingCard: {
      position: 'absolute', bottom: 0, right: 0,
      background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 12,
      padding: '14px 16px', boxShadow: '0 8px 24px rgba(22,18,14,0.1)', minWidth: 160,
    },
    fcLabel: { fontSize: 10, fontWeight: 600, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
    fcScore: { fontFamily: "'Instrument Serif', serif", fontSize: 28, color: 'var(--ink)', lineHeight: 1 },
    fcSub: { fontSize: 11, color: '#16A34A', fontWeight: 600, marginTop: 2 },

    /* MARQUEE */
    marqueeWrap: {
      borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)',
      background: 'var(--white)', padding: '14px 0', overflow: 'hidden',
    },
    marqueeTrack: {
      display: 'flex', gap: 48, width: 'max-content',
      animation: 'lp-marquee 28s linear infinite',
    },
    marqueeItem: {
      display: 'flex', alignItems: 'center', gap: 10,
      fontSize: 12, fontWeight: 600, color: 'var(--ink-3)',
      textTransform: 'uppercase', letterSpacing: 1, whiteSpace: 'nowrap',
    },
    marqueeDot: { width: 4, height: 4, borderRadius: '50%', background: 'var(--red)' },

    /* SECTIONS */
    section: { maxWidth: 1280, margin: '0 auto', padding: '100px 48px' },
    sectionLabel: {
      fontSize: 11, fontWeight: 600, letterSpacing: 2, textTransform: 'uppercase',
      color: 'var(--red)', marginBottom: 16,
      display: 'flex', alignItems: 'center', gap: 8,
    },
    sectionLabelLine: { width: 20, height: 1.5, background: 'var(--red)', flexShrink: 0 },
    sectionH2: {
      fontFamily: "'Instrument Serif', serif",
      fontSize: 'clamp(36px, 4vw, 52px)', lineHeight: 1.12,
      letterSpacing: -0.5, color: 'var(--ink)', maxWidth: 560, marginBottom: 64,
    },
    sectionH2Em: { fontStyle: 'italic', color: 'var(--red)' },

    /* STEPS */
    steps: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 2 },
    step: (i) => ({
      background: 'var(--white)', padding: '40px 36px',
      border: '1px solid var(--border)', position: 'relative',
      transition: 'background 0.2s',
      borderRadius: i === 0 ? '16px 0 0 16px' : i === 2 ? '0 16px 16px 0' : 0,
    }),
    stepNum: {
      fontFamily: "'Instrument Serif', serif", fontSize: 56,
      color: 'var(--warm)', lineHeight: 1, marginBottom: 20, userSelect: 'none',
    },
    stepIconWrap: {
      width: 44, height: 44, borderRadius: 10, border: '1px solid var(--border)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      marginBottom: 20, background: 'var(--cream)',
    },
    stepTitle: { fontSize: 18, fontWeight: 600, color: 'var(--ink)', marginBottom: 10 },
    stepText: { fontSize: 14, color: 'var(--ink-2)', lineHeight: 1.75, fontWeight: 300 },

    /* FEATURES */
    featGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 },
    feat: (i) => ({
      background: 'var(--white)', padding: 40, border: '1px solid var(--border)',
      transition: 'background 0.2s',
      borderRadius: i === 0 ? '16px 0 0 0' : i === 1 ? '0 16px 0 0' : i === 2 ? '0 0 0 16px' : '0 0 16px 0',
    }),
    featDark: (i) => ({
      background: 'var(--ink)', borderColor: 'var(--ink)', padding: 40,
      transition: 'background 0.2s', border: '1px solid var(--ink)',
      borderRadius: i === 0 ? '16px 0 0 0' : i === 1 ? '0 16px 0 0' : i === 2 ? '0 0 0 16px' : '0 0 16px 0',
    }),
    featIconWrap: {
      width: 44, height: 44, borderRadius: 10, border: '1px solid var(--border)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      marginBottom: 20, background: 'var(--cream)',
    },
    featIconDark: {
      width: 44, height: 44, borderRadius: 10,
      border: '1px solid rgba(255,255,255,0.1)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      marginBottom: 20, background: 'rgba(255,255,255,0.06)',
    },
    featTitle: { fontSize: 20, fontWeight: 600, color: 'var(--ink)', marginBottom: 10 },
    featTitleLight: { fontSize: 20, fontWeight: 600, color: 'var(--white)', marginBottom: 10 },
    featText: { fontSize: 14, color: 'var(--ink-2)', lineHeight: 1.75, fontWeight: 300 },
    featTextLight: { fontSize: 14, color: 'rgba(253,252,251,0.55)', lineHeight: 1.75, fontWeight: 300 },
    featTag: {
      display: 'inline-block', marginTop: 20, fontSize: 11, fontWeight: 600,
      letterSpacing: 1, textTransform: 'uppercase', color: 'var(--red)',
      borderBottom: '1px solid var(--red)', paddingBottom: 2,
    },
    featTagLight: {
      display: 'inline-block', marginTop: 20, fontSize: 11, fontWeight: 600,
      letterSpacing: 1, textTransform: 'uppercase', color: 'rgba(253,252,251,0.4)',
      borderBottom: '1px solid rgba(253,252,251,0.2)', paddingBottom: 2,
    },

    /* CLASSROOM */
    classroomSection: { background: 'var(--ink)', color: 'var(--white)', padding: '100px 48px' },
    classroomInner: {
      maxWidth: 1280, margin: '0 auto',
      display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80, alignItems: 'center',
    },
    clsLabel: {
      fontSize: 11, fontWeight: 600, letterSpacing: 2, textTransform: 'uppercase',
      color: 'var(--red)', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8,
    },
    clsH2: {
      fontFamily: "'Instrument Serif', serif",
      fontSize: 'clamp(32px, 3.5vw, 48px)', lineHeight: 1.12, marginBottom: 24,
    },
    clsH2Em: { fontStyle: 'italic', color: 'var(--red)' },
    clsText: { fontSize: 15, color: 'rgba(253,252,251,0.6)', lineHeight: 1.8, fontWeight: 300, marginBottom: 36 },
    clsPoints: { display: 'flex', flexDirection: 'column', gap: 16 },
    clsPoint: { display: 'flex', gap: 14, alignItems: 'flex-start' },
    clsPointIcon: { width: 20, height: 20, flexShrink: 0, marginTop: 1 },
    clsPointText: { fontSize: 14, color: 'rgba(253,252,251,0.65)', lineHeight: 1.7 },
    clsVisual: {
      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 16, padding: 28,
    },
    clsVisHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
    clsVisTitle: { fontSize: 13, fontWeight: 600, color: 'rgba(255,255,255,0.9)' },
    clsVisLive: { display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#4ADE80', fontWeight: 600 },
    liveDot: { width: 6, height: 6, borderRadius: '50%', background: '#4ADE80', animation: 'lp-pulse 2s infinite' },
    clsVsRow: { display: 'flex', gap: 16, alignItems: 'center', marginBottom: 20 },
    clsTeam: { flex: 1 },
    clsTeamLabel: { fontSize: 10, color: 'rgba(255,255,255,0.4)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 },
    clsVs: { fontSize: 13, color: 'rgba(255,255,255,0.3)', fontWeight: 700, flexShrink: 0 },
    clsDimRow: { marginBottom: 10 },
    clsDimLabel: { fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 5, display: 'flex', justifyContent: 'space-between' },
    clsDimBars: { display: 'flex', gap: 4, height: 8 },
    clsDimBar: { borderRadius: 2 },
    clsInsight: {
      marginTop: 16, padding: '12px 14px',
      background: 'rgba(200,16,46,0.15)', border: '1px solid rgba(200,16,46,0.3)', borderRadius: 10,
    },
    clsInsightHeader: { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 },
    clsInsightLabel: { fontSize: 11, fontWeight: 700, color: '#FCA5A5' },
    clsInsightText: { fontSize: 12, color: 'rgba(255,255,255,0.55)', lineHeight: 1.6 },

    /* DIMS */
    dimsSection: { maxWidth: 1280, margin: '0 auto', padding: '100px 48px' },
    dimsGrid: { display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 2 },
    dimCard: (i, total) => ({
      background: 'var(--white)', border: '1px solid var(--border)',
      padding: '28px 24px', transition: 'background 0.2s, transform 0.2s',
      borderRadius: i === 0 ? '16px 0 0 16px' : i === total - 1 ? '0 16px 16px 0' : 0,
    }),
    dimAbbr: { fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 4, display: 'inline-block', marginBottom: 16, letterSpacing: 0.5 },
    dimFull: { fontSize: 14, fontWeight: 600, color: 'var(--ink)', marginBottom: 8, lineHeight: 1.3 },
    dimSub: { fontSize: 12, color: 'var(--ink-3)', lineHeight: 1.6, fontWeight: 300 },
    dimMax: { fontFamily: "'Instrument Serif', serif", fontSize: 24, color: 'var(--ink)', marginTop: 16 },
    dimMaxSpan: { fontSize: 13, color: 'var(--ink-3)' },

    /* CTA */
    ctaSection: { maxWidth: 1280, margin: '0 auto', padding: '80px 48px 120px' },
    ctaBox: {
      background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 24, padding: 80,
      display: 'grid', gridTemplateColumns: '1fr auto', gap: 60, alignItems: 'center',
    },
    ctaH2: {
      fontFamily: "'Instrument Serif', serif",
      fontSize: 'clamp(32px, 3.5vw, 48px)', lineHeight: 1.12, color: 'var(--ink)',
    },
    ctaH2Em: { fontStyle: 'italic', color: 'var(--red)' },
    ctaSub: { fontSize: 15, color: 'var(--ink-2)', marginTop: 14, lineHeight: 1.7, fontWeight: 300 },
    ctaActions: { display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'flex-start' },
    ctaNote: { fontSize: 12, color: 'var(--ink-3)' },

    /* FOOTER */
    footer: {
      borderTop: '1px solid var(--border)', padding: '32px 48px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      background: 'var(--white)',
    },
    footerLogo: {
      fontFamily: "'Instrument Serif', serif", fontSize: 16, color: 'var(--ink)',
      display: 'flex', alignItems: 'center', gap: 8,
    },
    footerPaw: {
      width: 24, height: 24, background: 'var(--red)', borderRadius: 6,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    },
    footerLinks: { display: 'flex', gap: 28 },
    footerLink: { fontSize: 12, color: 'var(--ink-3)', textDecoration: 'none', fontWeight: 500, cursor: 'pointer' },
    footerCopy: { fontSize: 12, color: 'var(--ink-3)' },
  }

  /* Duplicate marquee items for seamless loop */
  const marqueeItems = [...MARQUEE_ITEMS, ...MARQUEE_ITEMS]

  return (
    <div style={s.page}>

      {/* ── NAV ── */}
      <nav style={s.nav}>
        <div style={s.navLogo} onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <div style={s.navPaw}><PawIcon size={16} color="white" /></div>
          Husky AI
        </div>
        <div style={s.navLinks}>
          <a onClick={() => navigate('/how-it-works')} style={{ ...s.navLink, cursor: 'pointer' }} className="lp-nav-link">How it works</a>
          <a href="#features" style={s.navLink} className="lp-nav-link">Features</a>
          <a href="#instructors" style={s.navLink} className="lp-nav-link">For Instructors</a>
          <a
            onClick={() => navigate('/login#educators-login-info')}
            style={{ ...s.navLink, cursor: 'pointer' }}
            className="lp-nav-link"
            title="Same sign-in page - how instructors and admins get in"
          >
            Instructor / Admin
          </a>
          <button
            style={s.navCta}
            className="lp-nav-cta"
            onClick={() => navigate('/login')}
          >
            Sign in
          </button>
        </div>
      </nav>

      {/* ── HERO ── */}
      <section style={s.heroWrap}>
        <div style={s.hero}>
          {/* Left */}
          <div style={s.heroLeft}>
            <div style={s.heroEyebrow}>
              <div style={s.eyebrowLine} />
              AIMES Lab, Northeastern University
            </div>
            <h1 style={s.heroH1}>
              Be an<br />
              <em style={s.heroH1Em}>AI-Ready</em><br />
              professional.
            </h1>
            <p style={s.heroSub}>
              Husky AI is your personal coach for learning how to think with AI - not just use it.
              Complete real challenges, get scored on your prompting, and see how your class stacks up.
            </p>
            <div style={{ ...s.heroActions, flexWrap: 'wrap', gap: '12px' }}>
              <button
                style={s.btnPrimary}
                className="lp-btn-primary"
                onClick={() => navigate('/login?tab=register')}
              >
                Get Started &rarr;
              </button>
              <button
                type="button"
                style={{
                  ...s.btnSecondary,
                  cursor: 'pointer',
                  border: '1.5px solid var(--red)',
                  color: 'var(--red)',
                  background: 'var(--white)',
                  borderRadius: '10px',
                  padding: '12px 22px',
                  fontSize: '14px',
                  fontWeight: 600,
                }}
                onClick={() => navigate('/demo/dashboard')}
              >
                Try interactive demo
              </button>
              <button
                style={{ ...s.btnSecondary, background: 'none', border: 'none', borderBottom: '1px solid var(--border)', cursor: 'pointer', paddingBottom: 2 }}
                className="lp-btn-secondary"
                onClick={() => navigate('/how-it-works')}
              >
                See how it works&nbsp;<ChevronDownIcon />
              </button>
            </div>
            <div style={s.heroStats}>
              <div>
                <div style={s.statN}>5<span style={s.statNSpan}>k+</span></div>
                <div style={s.statLbl}>Prompts evaluated</div>
              </div>
              <div>
                <div style={s.statN}>12</div>
                <div style={s.statLbl}>Weekly challenges</div>
              </div>
              <div>
                <div style={s.statN}>82<span style={s.statNSpan}>%</span></div>
                <div style={s.statLbl}>Avg. score improvement</div>
              </div>
            </div>
          </div>

          {/* Right – UI preview */}
          <div style={s.heroRight}>
            <div style={s.uiPreview}>
              {/* Title bar */}
              <div style={s.uiBar}>
                <div style={s.uiDots}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#FF5F57' }} />
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#FEBC2E' }} />
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#28C840' }} />
                </div>
                <div style={s.uiTitle}>husky-ai.northeastern.edu</div>
              </div>

              {/* Body */}
              <div style={s.uiBody}>
                {/* Active challenge card */}
                <div style={s.uiTaskCard}>
                  <div style={s.uiTaskCardBg}>
                    <svg width="72" height="72" viewBox="0 0 24 24" fill="none"
                      stroke="white" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 20h9"/>
                      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
                    </svg>
                  </div>
                  <div style={s.uiWeek}>Week 4 &middot; Active Challenge</div>
                  <div style={s.uiTaskName}>Design a Public Awareness Campaign</div>
                  <div style={s.uiTaskBtn}>Continue working &rarr;</div>
                </div>

                {/* Stats grid */}
                <div style={s.uiGrid}>
                  <div style={s.uiStat}>
                    <div style={s.uiStatN}>7.4</div>
                    <div style={s.uiStatL}>Prompt score</div>
                  </div>
                  <div style={s.uiStat}>
                    <div style={s.uiStatN}>#4</div>
                    <div style={s.uiStatL}>Class rank</div>
                  </div>
                  <div style={s.uiStat}>
                    <div style={s.uiStatN}>8</div>
                    <div style={s.uiStatL}>Completed</div>
                  </div>
                </div>

                {/* Prompt row */}
                <div style={s.uiPromptRow}>
                  <div style={s.uiPromptLabel}>"Design a campaign for 18&ndash;22 yr olds..."</div>
                  <div style={s.uiScorePill}>PEI 82</div>
                </div>
              </div>
            </div>

            {/* Floating PEI card */}
            <div style={s.floatingCard}>
              <div style={s.fcLabel}>Your PEI score</div>
              <div style={s.fcScore}>82</div>
              <div style={s.fcSub}>&#8593; +67 this session</div>
            </div>
          </div>
        </div>
      </section>

      {/* ── MARQUEE ── */}
      <div style={s.marqueeWrap}>
        <div style={s.marqueeTrack}>
          {marqueeItems.map((item, i) => (
            <div key={i} style={s.marqueeItem}>
              <div style={s.marqueeDot} />
              {item}
            </div>
          ))}
        </div>
      </div>

      {/* ── HOW IT WORKS ── */}
      <section style={s.section} id="how">
        <div className="lp-reveal">
          <div style={s.sectionLabel}>
            <div style={s.sectionLabelLine} />
            How it works
          </div>
          <h2 style={s.sectionH2}>
            Three steps to becoming <em style={s.sectionH2Em}>AI-fluent</em>
          </h2>
        </div>

        <div style={s.steps} className="lp-reveal">
          {/* Step 1 */}
          <div style={s.step(0)} className="lp-step">
            <div style={s.stepNum}>01</div>
            <div style={s.stepIconWrap}><MonitorIcon /></div>
            <div style={s.stepTitle}>Get a challenge</div>
            <div style={s.stepText}>
              Each week your class gets a real, open-ended project - design a campaign, analyze a dataset,
              build something. No multiple choice. No hand-holding.
            </div>
          </div>

          {/* Step 2 */}
          <div style={s.step(1)} className="lp-step">
            <div style={s.stepNum}>02</div>
            <div style={s.stepIconWrap}><EditIcon /></div>
            <div style={s.stepTitle}>Work with AI, get scored</div>
            <div style={s.stepText}>
              Use AI to complete the challenge. Every prompt you write is evaluated in real time across
              five dimensions - specificity, iteration, control, and more.
            </div>
          </div>

          {/* Step 3 */}
          <div style={s.step(2)} className="lp-step">
            <div style={s.stepNum}>03</div>
            <div style={s.stepIconWrap}><UsersIcon /></div>
            <div style={s.stepTitle}>Compete with another class</div>
            <div style={s.stepText}>
              Your class's aggregate prompting patterns are shared anonymously with a partner class.
              Watch the signal, adapt, and push your collective score higher.
            </div>
          </div>
        </div>
      </section>

      {/* ── FEATURES ── */}
      <section style={{ ...s.section, paddingTop: 0 }} id="features">
        <div className="lp-reveal">
          <div style={s.sectionLabel}>
            <div style={s.sectionLabelLine} />
            Features
          </div>
          <h2 style={s.sectionH2}>
            Built for how students <em style={s.sectionH2Em}>actually</em> learn
          </h2>
        </div>

        <div style={s.featGrid} className="lp-reveal">
          {/* Card 1 */}
          <div style={s.feat(0)} className="lp-feat">
            <div style={s.featIconWrap}><BoltIcon /></div>
            <div style={s.featTitle}>Live Prompt Evaluator</div>
            <div style={s.featText}>
              Every message you send to AI gets scored instantly. See exactly which dimensions improved and
              get a specific tip for your next prompt - not generic advice.
            </div>
            <div style={s.featTag}>Core feature</div>
          </div>

          {/* Card 2 – dark accent */}
          <div style={s.featDark(1)} className="lp-feat-dark">
            <div style={s.featIconDark}><UsersIcon dimColor="rgba(255,255,255,0.7)" /></div>
            <div style={s.featTitleLight}>Classroom Signal</div>
            <div style={s.featTextLight}>
              Two classrooms, anonymously paired. Your class sees the other's aggregate pattern - not
              individual scores, not raw prompts. Just a signal strong enough to learn from.
            </div>
            <div style={s.featTagLight}>Research-backed</div>
          </div>

          {/* Card 3 */}
          <div style={s.feat(2)} className="lp-feat">
            <div style={s.featIconWrap}><BarsIcon /></div>
            <div style={s.featTitle}>Progress Tracking</div>
            <div style={s.featText}>
              Watch your Husky Score grow across the semester. See which dimensions are improving, where
              you plateau, and how you rank in your class - all in one place.
            </div>
            <div style={s.featTag}>Student dashboard</div>
          </div>

          {/* Card 4 */}
          <div style={s.feat(3)} className="lp-feat">
            <div style={s.featIconWrap}><BookIcon /></div>
            <div style={s.featTitle}>Not just LLMs</div>
            <div style={s.featText}>
              Challenges cover AI image generation, data analysis, creative co-authoring, and more.
              AI literacy is broader than prompting ChatGPT - this platform teaches all of it.
            </div>
            <div style={s.featTag}>Full AI literacy</div>
          </div>
        </div>
      </section>

      {/* ── CLASSROOM ── */}
      <div style={s.classroomSection} id="instructors">
        <div style={s.classroomInner}>
          {/* Left text */}
          <div className="lp-reveal">
            <div style={s.clsLabel}>
              <div style={s.sectionLabelLine} />
              The classroom feature
            </div>
            <h2 style={s.clsH2}>
              Your class vs. theirs. <em style={s.clsH2Em}>Anonymously.</em>
            </h2>
            <p style={s.clsText}>
              Learning to use AI well is a social skill - it improves faster when you can see how others do it.
              Husky AI creates a live feedback loop between two classrooms, without revealing anyone's identity.
            </p>
            <div style={s.clsPoints}>
              {[
                'Aggregate scores only - no individual data is ever shared with the partner class',
                'Updates live during sessions so your class can see the signal and respond',
                'Coach insights tell you what the partner class is doing differently and how to close the gap',
              ].map((text, i) => (
                <div key={i} style={s.clsPoint}>
                  <div style={s.clsPointIcon}><CheckIcon /></div>
                  <div style={s.clsPointText}>{text}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Right visual */}
          <div style={s.clsVisual} className="lp-reveal">
            <div style={s.clsVisHeader}>
              <div style={s.clsVisTitle}>Section A vs. Partner Class</div>
              <div style={s.clsVisLive}>
                <div style={s.liveDot} />
                Live
              </div>
            </div>

            {/* Scores */}
            <div style={s.clsVsRow}>
              <div style={s.clsTeam}>
                <div style={s.clsTeamLabel}>Your class</div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: 42, lineHeight: 1, color: '#F97316' }}>6.8</div>
              </div>
              <div style={s.clsVs}>VS</div>
              <div style={{ ...s.clsTeam, textAlign: 'right' }}>
                <div style={s.clsTeamLabel}>Partner class</div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: 42, lineHeight: 1, color: '#4ADE80' }}>7.1</div>
              </div>
            </div>

            {/* Dimension bars */}
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 20 }}>
              {[
                { label: 'Specificity', yours: '8.0', theirs: '9.1', flex: 8 },
                { label: 'Iteration',   yours: '6.5', theirs: '6.8', flex: 7 },
                { label: 'Refinement', yours: '7.5', theirs: '8.9', flex: 7 },
              ].map(({ label, yours, theirs, flex }) => (
                <div key={label} style={s.clsDimRow}>
                  <div style={s.clsDimLabel}>
                    <span>{label}</span>
                    <span style={{ color: 'rgba(255,255,255,0.7)' }}>{yours} vs {theirs}</span>
                  </div>
                  <div style={s.clsDimBars}>
                    <div style={{ ...s.clsDimBar, background: '#F97316', flex }} />
                    <div style={{ ...s.clsDimBar, background: 'rgba(255,255,255,0.08)', flex: 10 - flex }} />
                  </div>
                </div>
              ))}
            </div>

            {/* Coach insight */}
            <div style={s.clsInsight}>
              <div style={s.clsInsightHeader}>
                <InfoIcon />
                <div style={s.clsInsightLabel}>Coach insight</div>
              </div>
              <div style={s.clsInsightText}>
                Partner class adds more context upfront. Try starting with "I'm designing for..." before your ask.
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── DIMENSIONS ── */}
      <section style={s.dimsSection}>
        <div className="lp-reveal">
          <div style={s.sectionLabel}>
            <div style={s.sectionLabelLine} />
            PEI Scoring
          </div>
          <h2 style={s.sectionH2}>
            Five dimensions. One <em style={s.sectionH2Em}>Husky Score.</em>
          </h2>
        </div>

        <div style={s.dimsGrid} className="lp-reveal">
          {[
            { abbr: 'PSQ', full: 'Prompt Structural Quality',  sub: 'Verb clarity, context, constraints, focus, and alignment to task',           bg: '#FEE2E2', fg: '#DC2626' },
            { abbr: 'CCM', full: 'Conversation Control',       sub: 'Initiative ratio, verification, and course correction across turns',         bg: '#FEF3C7', fg: '#D97706' },
            { abbr: 'TSI', full: 'Technical Sophistication',   sub: 'Decomposition, tool awareness, and error anticipation',                      bg: '#CCFBF1', fg: '#0D9488' },
            { abbr: 'CLM', full: 'Cognitive Load Mgmt',        sub: 'Chunk size, incremental building, and strategic clarification',              bg: '#EDE9FE', fg: '#7C3AED' },
            { abbr: 'RAS', full: 'Reliance Appropriateness',   sub: 'Appropriate AI use vs. over-reliance and blind acceptance',                  bg: '#FEF3E8', fg: '#F97316' },
          ].map(({ abbr, full, sub, bg, fg }, i) => (
            <div key={abbr} style={s.dimCard(i, 5)} className="lp-dim">
              <div style={{ ...s.dimAbbr, background: bg, color: fg }}>{abbr}</div>
              <div style={s.dimFull}>{full}</div>
              <div style={s.dimSub}>{sub}</div>
              <div style={s.dimMax}>20 <span style={s.dimMaxSpan}>/ 20</span></div>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={s.ctaSection}>
        <div style={s.ctaBox} className="lp-reveal">
          <div>
            <h2 style={s.ctaH2}>
              Ready to become<br /><em style={s.ctaH2Em}>AI-ready?</em>
            </h2>
            <p style={s.ctaSub}>
              Enter your class code and start your first challenge today. No setup, no downloads -
              just open your browser and begin.
            </p>
          </div>
          <div style={s.ctaActions}>
            <button
              style={{ ...s.btnPrimary, fontSize: 15, padding: '16px 32px' }}
              className="lp-btn-primary"
              onClick={() => navigate('/login?tab=register')}
            >
              Enter class code &rarr;
            </button>
            <div style={s.ctaNote}>Ask your instructor for your class code</div>
          </div>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer style={s.footer}>
        <div style={s.footerLogo}>
          <div style={s.footerPaw}><PawIcon size={13} color="white" /></div>
          Husky AI
        </div>
        <div style={s.footerLinks}>
          {['Privacy', 'Terms', 'For Instructors', 'Contact'].map((lbl) => (
            <span key={lbl} style={s.footerLink} className="lp-footer-link">{lbl}</span>
          ))}
        </div>
        <div style={s.footerCopy}>&copy; 2025 AIMES Lab, Northeastern University</div>
      </footer>

    </div>
  )
}
