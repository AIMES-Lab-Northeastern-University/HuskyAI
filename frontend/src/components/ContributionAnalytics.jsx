import { useCallback, useEffect, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

/**
 * Instructor-facing contribution analytics for one group-challenge team.
 *
 * Per-student numbers are PARTICIPATION only (prompts sent + share of the team's
 * prompts) — a valid attribution from who authored each turn. Quality (PEI +
 * dimension averages) is shown at the TEAM level on purpose: a turn's score
 * reflects the whole shared conversation, not its lone author. True per-student
 * skill scoring is a separate feature (attributed re-evaluation), not this one.
 *
 * Self-contained (own fetch + helpers) so it can later be dropped onto a
 * student-facing completion screen without a rewrite.
 */

const AVATAR_COLORS = ['#C8102E', '#0D9488', '#7C3AED', '#D97706', '#2563EB', '#DB2777']

function colorFor(name) {
  let h = 0
  for (const ch of (name || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

function initials(name) {
  return (name || '?').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()
}

function scoreColor(pei) {
  if (pei <= 40) return '#C8102E'
  if (pei <= 65) return '#F97316'
  if (pei <= 80) return '#0D9488'
  return '#16A34A'
}

function scoreLabel(pei) {
  if (pei <= 40) return 'Novice'
  if (pei <= 65) return 'Developing'
  if (pei <= 80) return 'Practitioner'
  return 'Expert'
}

const DIM_META = {
  PSQ: { label: 'Prompt Quality', color: '#C8102E' },
  CCM: { label: 'Conversation Control', color: '#F97316' },
  TSI: { label: 'Tech Sophistication', color: '#0D9488' },
  CLM: { label: 'Cognitive Load', color: '#7C3AED' },
  RAS: { label: 'Reliance Calibration', color: '#D97706' },
}

const SECTION_LABEL = {
  fontSize: '11px',
  fontWeight: 700,
  color: '#9A948E',
  textTransform: 'uppercase',
  letterSpacing: '0.7px',
  marginBottom: '12px',
}

function ScoreRing({ pei }) {
  const R = 50
  const C = 2 * Math.PI * R
  const pct = Math.max(0, Math.min(100, pei || 0))
  const offset = C * (1 - pct / 100)
  return (
    <div style={{ position: 'relative', width: '108px', height: '108px', flexShrink: 0 }}>
      <svg viewBox="0 0 120 120" width="108" height="108">
        <circle cx="60" cy="60" r={R} fill="none" stroke="#E7E0D8" strokeWidth="9" />
        <circle
          cx="60" cy="60" r={R} fill="none"
          stroke={scoreColor(pct)} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={offset}
          transform="rotate(-90 60 60)"
          style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ fontFamily: '"Instrument Serif", serif', fontSize: '30px', color: '#16120E', lineHeight: 1 }}>
          {pei == null ? '–' : Math.round(pei)}
        </div>
        <div style={{ fontSize: '9px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginTop: '2px' }}>
          Team Avg
        </div>
      </div>
    </div>
  )
}

function DimBar({ code, value }) {
  const meta = DIM_META[code]
  const pct = Math.max(0, Math.min(100, value || 0))
  return (
    <div style={{ marginBottom: '11px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
        <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: '10px', fontWeight: 700, color: meta.color, background: '#F7F3EE', borderRadius: '4px', padding: '1px 5px' }}>{code}</span>
        <span style={{ fontSize: '12px', color: '#4A4440', flex: 1 }}>{meta.label}</span>
        <span style={{ fontSize: '12px', fontWeight: 700, color: '#16120E' }}>{value == null ? '–' : Math.round(value)}</span>
      </div>
      <div style={{ height: '6px', background: '#F7F3EE', border: '1px solid #E7E0D8', borderRadius: '999px', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: meta.color, borderRadius: '999px', transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

function Sparkline({ timeline }) {
  const [hover, setHover] = useState(null)
  const pts = timeline.filter(t => t.pei != null)
  if (pts.length < 2) return null
  const PAD = 5
  const span = 100 - PAD * 2
  // Coordinates in a 0–100 space (both axes); the SVG line and the HTML dots
  // share this mapping so they stay aligned at any container width.
  const coords = pts.map((p, i) => ({
    x: PAD + (i / (pts.length - 1)) * span,
    y: PAD + (1 - (p.pei || 0) / 100) * span,
    p,
  }))
  const line = coords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
  return (
    <div style={{ position: 'relative', width: '100%', height: '56px' }}>
      <svg viewBox="0 0 100 100" width="100%" height="56" preserveAspectRatio="none" style={{ display: 'block', position: 'absolute', inset: 0 }}>
        <polyline points={line} fill="none" stroke="#C9C2B8" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
      {coords.map((c, i) => (
        <div
          key={i}
          onMouseEnter={() => setHover(i)}
          onMouseLeave={() => setHover(h => (h === i ? null : h))}
          style={{
            position: 'absolute', left: `${c.x}%`, top: `${c.y}%`,
            width: '11px', height: '11px', borderRadius: '50%',
            background: colorFor(c.p.sender_name), border: '2px solid #FDFCFB',
            boxShadow: hover === i ? '0 0 0 3px rgba(22,18,14,0.10)' : 'none',
            transform: 'translate(-50%, -50%)', cursor: 'pointer',
            transition: 'box-shadow 0.15s ease',
          }}
        />
      ))}
      {hover != null && (
        <div
          style={{
            position: 'absolute', left: `${coords[hover].x}%`, top: `${coords[hover].y}%`,
            transform: 'translate(-50%, calc(-100% - 10px))',
            background: '#16120E', color: '#FDFCFB', borderRadius: '8px',
            padding: '6px 9px', fontSize: '11px', lineHeight: 1.35, whiteSpace: 'nowrap',
            pointerEvents: 'none', zIndex: 5, boxShadow: '0 4px 14px rgba(22,18,14,0.18)',
          }}
        >
          <div style={{ fontWeight: 700 }}>Turn {coords[hover].p.turn} · PEI {Math.round(coords[hover].p.pei)}</div>
          <div style={{ color: '#C9C2B8' }}>{coords[hover].p.sender_name}</div>
        </div>
      )}
    </div>
  )
}

export default function ContributionAnalytics({ classroomId, challengeId, teamId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const url = `${API_URL}/classrooms/${classroomId}/challenges/${challengeId}/teams/${teamId}/analytics`

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const r = await fetch(url, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setErr(formatApiErrorDetail(d.detail)); setData(null) }
      else setData(d)
    } catch {
      setErr('Network error')
    } finally {
      setLoading(false)
    }
  }, [url])

  useEffect(() => { load() }, [load])

  const card = { background: '#FDFCFB', borderRadius: '14px', border: '1.5px solid #E7E0D8', padding: '18px' }

  if (loading) return <div style={{ ...card, marginTop: '10px', fontSize: '13px', color: '#9A948E' }}>Loading analytics…</div>
  if (err) return <div style={{ ...card, marginTop: '10px', fontSize: '13px', color: '#C8102E' }}>{err}</div>
  if (!data) return null

  const { total_turns, sessions_with_activity, members = [], team_pei_avg, team_pei_best, team_dimensions = {}, timeline = [] } = data
  const hasActivity = total_turns > 0
  const idleMembers = members.filter(m => m.turns === 0 && m.on_team)
  // Members who sent at least one prompt, for the activity legend.
  const active = members.filter(m => m.turns > 0)

  if (!hasActivity) {
    return (
      <div style={{ ...card, marginTop: '10px', textAlign: 'center' }}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E', marginBottom: '4px' }}>No activity yet</div>
        <div style={{ fontSize: '12px', color: '#9A948E' }}>This team hasn’t sent any prompts in the challenge yet. Analytics will appear once they start.</div>
      </div>
    )
  }

  return (
    <div style={{ ...card, marginTop: '10px', display: 'grid', gap: '20px' }}>
      {/* Team score + dimensions */}
      <div>
        <div style={SECTION_LABEL}>Team performance</div>
        <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <ScoreRing pei={team_pei_avg} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {team_pei_avg != null && (
                <span style={{ display: 'inline-block', alignSelf: 'flex-start', fontSize: '11px', fontWeight: 700, color: scoreColor(team_pei_avg), background: '#F7F3EE', borderRadius: '999px', padding: '3px 10px' }}>
                  {scoreLabel(team_pei_avg)}
                </span>
              )}
              <Stat label="Best turn" value={team_pei_best == null ? '–' : Math.round(team_pei_best)} />
              <Stat label="Total prompts" value={total_turns} />
              <Stat label="Sessions active" value={sessions_with_activity} />
            </div>
          </div>
          <div style={{ flex: 1, minWidth: '220px' }}>
            {['PSQ', 'CCM', 'TSI', 'CLM', 'RAS'].map(code => (
              <DimBar key={code} code={code} value={team_dimensions[code]} />
            ))}
          </div>
        </div>
      </div>

      <div style={{ height: '1px', background: '#E7E0D8' }} />

      {/* Contribution breakdown */}
      <div>
        <div style={SECTION_LABEL}>Contribution — who sent the prompts</div>

        {/* Stacked share bar */}
        <div style={{ display: 'flex', height: '14px', borderRadius: '999px', overflow: 'hidden', border: '1px solid #E7E0D8', marginBottom: '14px' }}>
          {active.map(m => (
            <div
              key={m.user_id}
              title={`${m.name} · ${m.share_pct}%`}
              style={{ width: `${m.share_pct}%`, background: colorFor(m.name), transition: 'width 0.5s ease' }}
            />
          ))}
        </div>

        {/* Per-member rows */}
        <div style={{ display: 'grid', gap: '10px' }}>
          {members.map(m => (
            <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{ width: '28px', height: '28px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: '11px', fontWeight: 700, color: '#fff', background: m.turns > 0 ? colorFor(m.name) : '#C9C2B8' }}>
                {initials(m.name)}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#16120E', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.name}</span>
                  {!m.on_team && <span style={{ fontSize: '10px', color: '#9A948E', border: '1px solid #E7E0D8', borderRadius: '4px', padding: '0 4px' }}>left team</span>}
                </div>
                <div style={{ height: '6px', background: '#F7F3EE', border: '1px solid #E7E0D8', borderRadius: '999px', overflow: 'hidden', marginTop: '4px' }}>
                  <div style={{ height: '100%', width: `${m.share_pct}%`, background: m.turns > 0 ? colorFor(m.name) : 'transparent', borderRadius: '999px', transition: 'width 0.5s ease' }} />
                </div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0, minWidth: '72px' }}>
                {m.turns > 0 ? (
                  <>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: '#16120E' }}>{m.share_pct}%</div>
                    <div style={{ fontSize: '11px', color: '#9A948E' }}>{m.turns} prompt{m.turns !== 1 ? 's' : ''}</div>
                  </>
                ) : (
                  <span style={{ fontSize: '10px', fontWeight: 700, color: '#C8102E', background: '#FDE8EC', borderRadius: '999px', padding: '2px 8px' }}>No prompts</span>
                )}
              </div>
            </div>
          ))}
        </div>

        {idleMembers.length > 0 && (
          <div style={{ fontSize: '11px', color: '#C8102E', marginTop: '12px' }}>
            {idleMembers.length} assigned member{idleMembers.length !== 1 ? 's' : ''} sent no prompts.
          </div>
        )}
      </div>

      {/* Activity over time */}
      {timeline.filter(t => t.pei != null).length >= 2 && (
        <>
          <div style={{ height: '1px', background: '#E7E0D8' }} />
          <div>
            <div style={SECTION_LABEL}>Team score over the conversation</div>
            <Sparkline timeline={timeline} />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px 16px', marginTop: '10px' }}>
              {active.map(m => (
                <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '9px', height: '9px', borderRadius: '50%', background: colorFor(m.name) }} />
                  <span style={{ fontSize: '11px', color: '#6B6560' }}>{m.name}</span>
                </div>
              ))}
            </div>
            <div style={{ fontSize: '10px', color: '#9A948E', marginTop: '8px', lineHeight: 1.4 }}>
              Each dot is a turn, colored by who sent it. The line is the <em>team’s</em> shared score — it isn’t an individual skill measure.
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
      <span style={{ fontSize: '15px', fontWeight: 700, color: '#16120E', fontFamily: '"JetBrains Mono", monospace' }}>{value}</span>
      <span style={{ fontSize: '11px', color: '#9A948E' }}>{label}</span>
    </div>
  )
}
