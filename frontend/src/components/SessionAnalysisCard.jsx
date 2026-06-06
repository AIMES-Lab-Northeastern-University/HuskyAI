import { useEffect, useState } from 'react'

// Post-session analysis card. Presentational only — the parent fetches the
// analysis blob from GET /conversations/{id}/analysis and passes it in.
//
// `analysis` shape (from backend session_analysis.analyze_session):
//   { status, session_pei, level, dimension_averages: {PSQ,CCM,TSI,CLM,RAS},
//     strongest_dimension, weakest_dimension,
//     trend: { first_half_pei, second_half_pei, delta, direction } | null,
//     pei_series: [..per-turn PEI..],
//     narrative, takeaways: [..], strengths: [..], turns_analyzed }
//
// Props: analysis, loading, error, onRetry (optional — enables "Try again").

const DIM_META = {
  PSQ: { short: 'prompt structure', color: '#C8102E' },
  CCM: { short: 'conversation control', color: '#F97316' },
  TSI: { short: 'technical depth', color: '#0D9488' },
  CLM: { short: 'cognitive load', color: '#7C3AED' },
  RAS: { short: 'reliance balance', color: '#D97706' },
}
const DIM_ORDER = ['PSQ', 'CCM', 'TSI', 'CLM', 'RAS']

const TREND_META = {
  improving: { label: 'Improved across the session', arrow: '↑', color: '#0D9488' },
  declining: { label: 'Dipped across the session', arrow: '↓', color: '#C8102E' },
  steady: { label: 'Held steady across the session', arrow: '→', color: '#9A948E' },
}

function levelColor(level) {
  if (level === 'Advanced') return { bg: '#E6F7F6', fg: '#0D9488' }
  if (level === 'Intermediate') return { bg: '#FEF3E8', fg: '#F97316' }
  return { bg: '#F7F3EE', fg: '#6B6560' }
}

// A friendly one-line TL;DR derived from the deterministic rollup (no LLM).
function headline(a) {
  const lead = a.level === 'Advanced' ? 'Strong session'
    : a.level === 'Intermediate' ? 'Solid session'
    : 'Good start'
  const parts = []
  if (a.strongest_dimension && DIM_META[a.strongest_dimension]) {
    parts.push(`strongest in ${DIM_META[a.strongest_dimension].short}`)
  }
  if (a.weakest_dimension && a.weakest_dimension !== a.strongest_dimension && DIM_META[a.weakest_dimension]) {
    parts.push(`sharpen ${DIM_META[a.weakest_dimension].short} next`)
  }
  return parts.length ? `${lead} — ${parts.join('; ')}.` : `${lead}.`
}

// Smoothly count a number up to `target` on mount.
function useCountUp(target, duration = 700) {
  const [val, setVal] = useState(0)
  useEffect(() => {
    if (target == null) return
    let raf
    const start = performance.now()
    const tick = (now) => {
      const p = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      setVal(Math.round(target * eased))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return val
}

/* ─── Animated radial score (matches the Progress PeiRing) ─── */
function RadialScore({ score }) {
  const [mounted, setMounted] = useState(false)
  const counted = useCountUp(score)
  useEffect(() => { const t = setTimeout(() => setMounted(true), 50); return () => clearTimeout(t) }, [])
  const r = 34, circ = Math.PI * 2 * r
  const pct = score != null ? Math.min(100, score) : 0
  const offset = mounted ? circ - (pct / 100) * circ : circ
  return (
    <div style={{ position: 'relative', width: '84px', height: '84px', flexShrink: 0 }}>
      <svg viewBox="0 0 84 84" width="84" height="84" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="42" cy="42" r={r} fill="none" stroke="#E7E0D8" strokeWidth="7" />
        {score != null && (
          <circle
            cx="42" cy="42" r={r} fill="none" stroke="#C8102E" strokeWidth="7" strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 0.9s cubic-bezier(0.22,1,0.36,1)' }}
          />
        )}
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontFamily: "'Instrument Serif', serif", fontSize: '26px', color: '#16120E', lineHeight: 1 }}>
          {score != null ? counted : '–'}
        </span>
        <span style={{ fontSize: '8px', fontWeight: 700, color: '#9A948E', letterSpacing: '0.5px' }}>PEI</span>
      </div>
    </div>
  )
}

/* ─── Pentagon radar of the five PEI dimensions (hand-rolled SVG) ─── */
function RadarChart({ dims, weakest, strongest }) {
  const size = 200, cx = size / 2, cy = size / 2 + 6, R = 66
  const angleFor = (i) => (-90 + i * (360 / DIM_ORDER.length)) * (Math.PI / 180)
  const pt = (value, i, radius = R) => {
    const a = angleFor(i)
    return [cx + (value / 100) * radius * Math.cos(a), cy + (value / 100) * radius * Math.sin(a)]
  }
  const poly = (vals) => vals.map((v, i) => pt(v, i).join(',')).join(' ')
  const grid = [25, 50, 75, 100]
  const dataVals = DIM_ORDER.map((k) => (dims[k] != null ? dims[k] : 0))
  const [mounted, setMounted] = useState(false)
  useEffect(() => { const t = setTimeout(() => setMounted(true), 60); return () => clearTimeout(t) }, [])

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" style={{ maxWidth: '220px', display: 'block', margin: '0 auto' }}>
      {/* grid rings */}
      {grid.map((g) => (
        <polygon key={g} points={poly(DIM_ORDER.map(() => g))} fill="none" stroke="#E7E0D8" strokeWidth="1" />
      ))}
      {/* axes */}
      {DIM_ORDER.map((k, i) => {
        const [x, y] = pt(100, i)
        return <line key={k} x1={cx} y1={cy} x2={x} y2={y} stroke="#E7E0D8" strokeWidth="1" />
      })}
      {/* data polygon (scales up on mount) */}
      <polygon
        points={poly(dataVals)}
        fill="rgba(200,16,46,0.16)" stroke="#C8102E" strokeWidth="2" strokeLinejoin="round"
        style={{
          transformOrigin: `${cx}px ${cy}px`,
          transform: mounted ? 'scale(1)' : 'scale(0.1)',
          opacity: mounted ? 1 : 0,
          transition: 'transform 0.7s cubic-bezier(0.22,1,0.36,1), opacity 0.5s ease',
        }}
      />
      {/* vertices + labels */}
      {DIM_ORDER.map((k, i) => {
        const v = dims[k]
        const [vx, vy] = pt(v != null ? v : 0, i)
        const [lx, ly] = pt(118, i)
        const a = angleFor(i)
        const anchor = Math.abs(Math.cos(a)) < 0.3 ? 'middle' : Math.cos(a) > 0 ? 'start' : 'end'
        const isWeak = k === weakest, isStrong = k === strongest
        return (
          <g key={k}>
            {v != null && (
              <circle cx={vx} cy={vy} r="3" fill={DIM_META[k].color}
                style={{ opacity: mounted ? 1 : 0, transition: 'opacity 0.6s ease 0.3s' }} />
            )}
            <text x={lx} y={ly} textAnchor={anchor} dominantBaseline="middle"
              fontSize="10" fontWeight="700"
              fill={isStrong ? '#0D9488' : isWeak ? '#C8102E' : '#6B6560'}>
              {k}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

/* ─── Per-turn PEI sparkline ─── */
function Sparkline({ series }) {
  if (!series || series.length < 2) return null
  const w = 240, h = 44, pad = 4
  const n = series.length
  const x = (i) => pad + (i / (n - 1)) * (w - pad * 2)
  const y = (v) => h - pad - (Math.min(100, Math.max(0, v)) / 100) * (h - pad * 2)
  const line = series.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: 'block' }}>
      <polyline points={line} fill="none" stroke="#C8102E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {series.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r={i === n - 1 ? 3.5 : 2.2}
          fill={i === n - 1 ? '#C8102E' : '#FDFCFB'} stroke="#C8102E" strokeWidth="1.5" />
      ))}
    </svg>
  )
}

function SectionLabel({ children }) {
  return (
    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '10px' }}>
      {children}
    </div>
  )
}

const KEYFRAMES = `
@keyframes analysis-spin { to { transform: rotate(360deg) } }
@keyframes analysis-shimmer { 0% { background-position: -340px 0 } 100% { background-position: 340px 0 } }
@keyframes analysis-rise { from { opacity: 0; transform: translateY(8px) } to { opacity: 1; transform: none } }
`

function Skeleton() {
  const bar = (w, h = 14) => ({
    width: w, height: h, borderRadius: '6px',
    background: 'linear-gradient(90deg, #F0EAE3 25%, #E7E0D8 37%, #F0EAE3 63%)',
    backgroundSize: '680px 100%', animation: 'analysis-shimmer 1.3s infinite linear',
  })
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
      <style>{KEYFRAMES}</style>
      <div style={{ textAlign: 'center', color: '#9A948E', fontSize: '13px', fontWeight: 500 }}>Analyzing your session…</div>
      <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
        <div style={{ ...bar('84px', 84), borderRadius: '50%' }} />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={bar('60%')} /><div style={bar('85%')} />
        </div>
      </div>
      <div style={bar('100%', 60)} />
      <div style={{ ...bar('220px', 160), margin: '0 auto', borderRadius: '12px' }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={bar('90%')} /><div style={bar('80%')} /><div style={bar('70%')} />
      </div>
    </div>
  )
}

export default function SessionAnalysisCard({ analysis, loading = false, error = null, onRetry = null }) {
  if (loading || (analysis && analysis.status === 'pending')) {
    return <Skeleton />
  }

  if (error || (analysis && analysis.status === 'failed')) {
    return (
      <div style={{ padding: '28px 24px', textAlign: 'center', color: '#9A948E', fontSize: '13px' }}>
        <div style={{ marginBottom: onRetry ? '16px' : 0 }}>
          We couldn’t generate your session analysis this time. Your scores are still saved.
        </div>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            style={{
              background: '#C8102E', color: '#fff', border: 'none', borderRadius: '8px',
              padding: '8px 18px', fontSize: '13px', fontWeight: 600, cursor: 'pointer',
            }}
          >
            Try again
          </button>
        )}
      </div>
    )
  }

  if (!analysis || analysis.status === 'none' || analysis.turns_analyzed === 0) {
    return (
      <div style={{ padding: '24px', textAlign: 'center', color: '#9A948E', fontSize: '13px' }}>
        No scored turns to analyze yet.
      </div>
    )
  }

  const pei = analysis.session_pei != null ? Math.round(analysis.session_pei) : null
  const lvl = levelColor(analysis.level)
  const dims = analysis.dimension_averages || {}
  const trend = analysis.trend ? TREND_META[analysis.trend.direction] : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px', animation: 'analysis-rise 0.45s ease both' }}>
      <style>{KEYFRAMES}</style>

      {/* Hero header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '16px',
        background: 'linear-gradient(135deg, #FBF6F1, #F7F3EE)',
        border: '1.5px solid #E7E0D8', borderRadius: '14px', padding: '16px 18px',
      }}>
        <RadialScore score={pei} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            {analysis.level && (
              <span style={{ fontSize: '11px', fontWeight: 700, padding: '3px 10px', borderRadius: '20px', background: lvl.bg, color: lvl.fg }}>
                {analysis.level}
              </span>
            )}
            <span style={{ fontSize: '12px', color: '#9A948E' }}>
              {analysis.turns_analyzed} turn{analysis.turns_analyzed !== 1 ? 's' : ''}
            </span>
          </div>
          <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '19px', color: '#16120E', lineHeight: 1.25 }}>
            {headline(analysis)}
          </div>
        </div>
      </div>

      {/* Narrative */}
      {analysis.narrative && (
        <p style={{ fontSize: '14px', color: '#4A4440', lineHeight: 1.65, margin: 0 }}>
          {analysis.narrative}
        </p>
      )}

      {/* Trend: sparkline if we have a per-turn series, else the text summary */}
      {(analysis.pei_series?.length >= 2 || trend) && (
        <div style={{ background: '#F7F3EE', border: '1.5px solid #E7E0D8', borderRadius: '12px', padding: '12px 14px' }}>
          {trend && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: analysis.pei_series?.length >= 2 ? '6px' : 0 }}>
              <span style={{ fontSize: '17px', color: trend.color, fontWeight: 700 }}>{trend.arrow}</span>
              <span style={{ fontSize: '13px', color: '#4A4440', fontWeight: 500 }}>
                {trend.label}
                <span style={{ color: '#9A948E' }}>
                  {' '}({Math.round(analysis.trend.first_half_pei)} → {Math.round(analysis.trend.second_half_pei)})
                </span>
              </span>
            </div>
          )}
          <Sparkline series={analysis.pei_series} />
        </div>
      )}

      {/* Dimension radar */}
      <div>
        <SectionLabel>Dimension breakdown</SectionLabel>
        <RadarChart dims={dims} weakest={analysis.weakest_dimension} strongest={analysis.strongest_dimension} />
        {/* numeric legend */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '6px 12px', marginTop: '10px' }}>
          {DIM_ORDER.map((k) => (
            <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: '#6B6560' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: DIM_META[k].color }} />
              {k} <strong style={{ color: '#4A4440' }}>{dims[k] != null ? Math.round(dims[k]) : '–'}</strong>
            </span>
          ))}
        </div>
      </div>

      {/* Takeaways — amber, numbered */}
      {analysis.takeaways?.length > 0 && (
        <div style={{ background: '#FEF9EC', border: '1.5px solid #F5E4C3', borderRadius: '12px', padding: '14px 16px' }}>
          <SectionLabel>What to try next time</SectionLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {analysis.takeaways.map((t, i) => (
              <div key={i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                <span style={{
                  flexShrink: 0, width: '20px', height: '20px', borderRadius: '50%', background: '#D97706', color: '#fff',
                  fontSize: '11px', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: '1px',
                }}>{i + 1}</span>
                <span style={{ fontSize: '13px', color: '#4A4440', lineHeight: 1.55 }}>{t}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Strengths — green, checks */}
      {analysis.strengths?.length > 0 && (
        <div style={{ background: '#ECFAF6', border: '1.5px solid #C5EBE2', borderRadius: '12px', padding: '14px 16px' }}>
          <SectionLabel>What you did well</SectionLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {analysis.strengths.map((s, i) => (
              <div key={i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                <span style={{ flexShrink: 0, color: '#0D9488', fontSize: '14px', fontWeight: 700, marginTop: '1px' }}>✓</span>
                <span style={{ fontSize: '13px', color: '#0F766E', lineHeight: 1.55 }}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
