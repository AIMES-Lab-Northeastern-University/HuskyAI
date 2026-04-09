import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders } from '../lib/api'

function PeiRing({ score }) {
  const r = 50
  const circ = Math.PI * 2 * r
  const display = score != null && !Number.isNaN(score) ? Math.round(score) : null
  const offset = display != null ? circ - (Math.min(100, display) / 100) * circ : circ
  return (
    <div style={{ position: 'relative', width: '120px', height: '120px', margin: '0 auto 12px' }}>
      <svg viewBox="0 0 120 120" width="120" height="120" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="60" cy="60" r={r} fill="none" stroke="#E7E0D8" strokeWidth="9" />
        {display != null && (
          <circle
            cx="60"
            cy="60"
            r={r}
            fill="none"
            stroke="#F97316"
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={offset}
          />
        )}
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontFamily: "'Instrument Serif', serif", fontSize: '28px', color: '#16120E', lineHeight: 1 }}>
          {display != null ? display : '—'}
        </span>
        <span style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginTop: '2px' }}>PEI Score</span>
      </div>
    </div>
  )
}

function ProgBar({ label, pct, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
      <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '40px', flexShrink: 0 }}>{label}</div>
      <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: '999px', background: color, transition: 'width 0.5s ease' }} />
      </div>
      <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>{pct}</div>
    </div>
  )
}

const DEMO_BAR_DATA = [
  { label: 'PSQ', pct: 72, color: '#C8102E' },
  { label: 'CCM', pct: 58, color: '#F97316' },
  { label: 'TSI', pct: 81, color: '#0D9488' },
  { label: 'CLM', pct: 64, color: '#7C3AED' },
  { label: 'RAS', pct: 55, color: '#D97706' },
]

const DEMO_WEEK_BARS = [
  { week: 'W1', height: 45, color: '#F97316' },
  { week: 'W2', height: 62, color: '#F97316' },
  { week: 'W3', height: 55, color: '#0D9488' },
  { week: 'W4', height: 78, color: '#0D9488' },
  { week: 'W5', height: 68, color: '#C8102E' },
]

const DEMO_BADGES = [
  { icon: '★', label: 'First Score', desc: 'Completed your first session', color: '#D97706', bg: '#FEF9EC', earned: true },
  { icon: '◆', label: 'Prompt Sharpener', desc: 'Scored 75+ on Specificity', color: '#0D9488', bg: '#E6F7F6', earned: true },
  { icon: '↑', label: 'On a Streak', desc: '5 days in a row', color: '#7C3AED', bg: '#F5F3FF', earned: true },
  { icon: '⊕', label: 'Class Leader', desc: 'Reach top 3 in class', color: '#9A948E', bg: '#F7F3EE', earned: false },
]

const DEMO_HISTORY = [
  { dot: '#16A34A', title: 'Social Media & Mental Health', date: 'Week 3 · Mar 3', pei: 74, status: 'Completed' },
  { dot: '#F97316', title: 'AI in Healthcare', date: 'Week 2 · Feb 24', pei: 68, status: 'Completed' },
  { dot: '#0D9488', title: 'Climate Communication', date: 'Week 1 · Feb 17', pei: 61, status: 'Completed' },
]

export default function Progress() {
  const navigate = useNavigate()
  const location = useLocation()
  const isDemo = location.pathname.startsWith('/demo')
  const pathPrefix = isDemo ? '/demo' : ''

  const [challenges, setChallenges] = useState([])
  const [loading, setLoading] = useState(!isDemo)

  useEffect(() => {
    if (isDemo) return
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/challenges`, { headers: { ...authHeaders() } })
        const data = await r.json().catch(() => [])
        if (!cancelled && Array.isArray(data)) setChallenges(data)
      } catch {
        if (!cancelled) setChallenges([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [isDemo])

  const live = useMemo(() => {
    const peis = challenges.map(c => c.best_pei).filter(p => p != null && !Number.isNaN(p))
    const bestPei = peis.length ? Math.max(...peis) : null
    const history = challenges
      .filter(c => c.best_pei != null || c.sessions_completed > 0)
      .map(c => ({
        title: c.title,
        date: c.week != null ? `Week ${c.week}` : c.category || 'Challenge',
        pei: c.best_pei != null ? Math.round(c.best_pei * 10) / 10 : null,
        dot: '#C8102E',
        status: c.sessions_completed >= c.total_sessions ? 'Completed' : 'In progress',
      }))
    return { bestPei, history }
  }, [challenges])

  const handleLogout = () => {
    if (isDemo) {
      navigate('/', { replace: true })
      return
    }
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>My Progress</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>
              {isDemo ? 'Semester overview' : loading ? 'Loading…' : 'Your challenges'}
            </span>
          </div>
          <div className="ml-auto">
            <button
              type="button"
              onClick={() => navigate(`${pathPrefix}/challenges`)}
              style={{
                background: 'transparent',
                border: '1.5px solid #E7E0D8',
                borderRadius: '8px',
                padding: '6px 14px',
                fontSize: '13px',
                fontWeight: 500,
                color: '#4A4440',
                cursor: 'pointer',
              }}
            >
              Challenges
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8">

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', marginBottom: '24px' }}>

            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', textAlign: 'center' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Your PEI Score</div>
              <PeiRing score={isDemo ? 68 : live.bestPei} />
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                {isDemo ? (
                  <span style={{ fontSize: '11px', fontWeight: 700, padding: '3px 10px', borderRadius: '20px', background: '#FEF3E8', color: '#F97316' }}>Developing</span>
                ) : (
                  <span style={{ fontSize: '11px', fontWeight: 700, padding: '3px 10px', borderRadius: '20px', background: '#F7F3EE', color: '#6B6560' }}>
                    {live.bestPei != null ? 'From your best session' : 'No score yet'}
                  </span>
                )}
              </div>
              <div style={{ fontSize: '12px', color: '#9A948E' }}>
                {isDemo ? 'Top 35% of class' : 'Class rankings coming later'}
              </div>
            </div>

            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Dimension breakdown</div>
              {isDemo ? (
                DEMO_BAR_DATA.map(b => <ProgBar key={b.label} {...b} />)
              ) : (
                <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6, margin: 0 }}>
                  Per-dimension scores (PSQ, CCM, TSI, …) will show here once we surface your latest evaluation breakdown from the API.
                </p>
              )}
            </div>

            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Score over time</div>
              {isDemo ? (
                <>
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px', height: '90px', marginBottom: '8px' }}>
                    {DEMO_WEEK_BARS.map(b => (
                      <div key={b.week} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', height: '100%', justifyContent: 'flex-end' }}>
                        <div style={{ width: '100%', height: `${b.height}%`, background: b.color, borderRadius: '4px 4px 0 0', transition: 'height 0.5s ease' }} />
                        <div style={{ fontSize: '10px', color: '#9A948E', fontWeight: 600 }}>{b.week}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: '12px', color: '#9A948E', textAlign: 'center' }}>Weeks 1 – 5</div>
                </>
              ) : (
                <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6, margin: 0 }}>
                  A week-by-week chart will appear after more scored sessions are recorded.
                </p>
              )}
            </div>
          </div>

          <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', marginBottom: '24px' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Badges earned</div>
            {isDemo ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '12px' }}>
                {DEMO_BADGES.map((b, i) => (
                  <div key={i} style={{
                    background: b.earned ? b.bg : '#F7F3EE',
                    borderRadius: '12px',
                    padding: '16px',
                    textAlign: 'center',
                    border: '1.5px solid',
                    borderColor: b.earned ? 'transparent' : '#E7E0D8',
                    opacity: b.earned ? 1 : 0.55,
                  }}>
                    <div style={{
                      width: '40px',
                      height: '40px',
                      borderRadius: '50%',
                      background: b.bg,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      margin: '0 auto 10px',
                      fontSize: '18px',
                      color: b.color,
                      border: `2px solid ${b.color}22`,
                    }}>
                      {b.icon}
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#16120E', marginBottom: '4px' }}>{b.label}</div>
                    <div style={{ fontSize: '11px', color: '#9A948E', lineHeight: 1.5 }}>{b.desc}</div>
                    {!b.earned && (
                      <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', marginTop: '6px', letterSpacing: '0.5px' }}>Locked</div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6, margin: 0 }}>
                Badges are not wired to the backend yet. Complete sessions to build history; achievements will show here in a future release.
              </p>
            )}
          </div>

          <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Challenge history</div>
            {isDemo ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                {DEMO_HISTORY.map((item, i) => (
                  <div key={i} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '14px',
                    padding: '14px 0',
                    borderBottom: i < DEMO_HISTORY.length - 1 ? '1px solid #F7F3EE' : 'none',
                  }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                      <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: item.dot }} />
                      {i < DEMO_HISTORY.length - 1 && (
                        <div style={{ width: '2px', height: '20px', background: '#E7E0D8', marginTop: '3px' }} />
                      )}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E' }}>{item.title}</div>
                      <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>{item.date}</div>
                    </div>
                    <div style={{
                      fontSize: '12px',
                      fontWeight: 700,
                      padding: '3px 10px',
                      borderRadius: '20px',
                      background: item.pei >= 70 ? '#E6F7F6' : '#FEF3E8',
                      color: item.pei >= 70 ? '#0D9488' : '#F97316',
                    }}>
                      PEI {item.pei}
                    </div>
                  </div>
                ))}
              </div>
            ) : live.history.length === 0 ? (
              <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6, margin: 0 }}>
                No challenge progress yet. Open <button type="button" onClick={() => navigate(`${pathPrefix}/challenges`)} style={{ color: '#C8102E', fontWeight: 600, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>Challenges</button> and start a session.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                {live.history.map((item, i) => (
                  <div key={item.title + i} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '14px',
                    padding: '14px 0',
                    borderBottom: i < live.history.length - 1 ? '1px solid #F7F3EE' : 'none',
                  }}>
                    <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: item.dot, flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E' }}>{item.title}</div>
                      <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>{item.date} · {item.status}</div>
                    </div>
                    {item.pei != null ? (
                      <div style={{
                        fontSize: '12px',
                        fontWeight: 700,
                        padding: '3px 10px',
                        borderRadius: '20px',
                        background: item.pei >= 70 ? '#E6F7F6' : '#FEF3E8',
                        color: item.pei >= 70 ? '#0D9488' : '#F97316',
                      }}>
                        PEI {item.pei}
                      </div>
                    ) : (
                      <span style={{ fontSize: '11px', color: '#9A948E' }}>—</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  )
}
