import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders } from '../lib/api'

export default function Dashboard() {
  const navigate = useNavigate()
  const location = useLocation()
  const isDemo = location.pathname.startsWith('/demo')
  const pathPrefix = isDemo ? '/demo' : ''
  const user = isDemo
    ? { name: 'Demo Student', email: 'demo@husky.edu' }
    : JSON.parse(localStorage.getItem('user') || 'null')
  const firstName = user?.name?.split(' ')[0] || 'Husky'
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  const [challenges, setChallenges] = useState([])
  const [challengesLoading, setChallengesLoading] = useState(!isDemo)

  useEffect(() => {
    if (isDemo) return
    const token = localStorage.getItem('token')
    if (!token) {
      setChallengesLoading(false)
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
        if (!cancelled) setChallengesLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [isDemo])

  const liveStats = useMemo(() => {
    if (!challenges.length) {
      return {
        bestPei: null,
        completedFull: 0,
        inProgress: 0,
        active: null,
      }
    }
    const peis = challenges.map(c => c.best_pei).filter(p => p != null && !Number.isNaN(p))
    const bestPei = peis.length ? Math.round(Math.max(...peis) * 10) / 10 : null
    const completedFull = challenges.filter(c => c.sessions_completed >= c.total_sessions).length
    const inProgress = challenges.filter(
      c => c.sessions_completed > 0 && c.sessions_completed < c.total_sessions,
    ).length
    const active =
      challenges.find(c => c.sessions_completed < c.total_sessions) || challenges[0]
    return { bestPei, completedFull, inProgress, active }
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

  const subtitle = isDemo
    ? 'Week 4 of 12'
    : challengesLoading
      ? 'Loading…'
      : liveStats.active?.week != null
        ? `Week ${liveStats.active.week} · ${challenges.length} challenge${challenges.length === 1 ? '' : 's'}`
        : challenges.length
          ? `${challenges.length} challenge${challenges.length === 1 ? '' : 's'}`
          : 'Your overview'

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Dashboard</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>{subtitle}</span>
          </div>
          <div className="ml-auto">
            <button
              onClick={() => navigate(`${pathPrefix}/challenges`)}
              style={{
                background: '#C8102E',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '7px 16px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
              {isDemo ? 'Active challenge' : 'Challenges'}
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8">

          <div style={{ borderRadius: '16px', marginBottom: '24px', overflow: 'hidden', display: 'flex' }}>

            <div style={{ flex: 1, background: '#16120E', padding: '28px 32px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>
                  </svg>
                  Your AI Coach
                </div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#fff', marginBottom: '10px', lineHeight: 1.3 }}>
                  {greeting}, {firstName}.
                </div>
                <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.6)', lineHeight: 1.75, marginBottom: '20px' }}>
                  You're building real AI fluency - not just using tools, but directing them. Every prompt you write is a chance to lead smarter.
                </div>
                <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', fontStyle: 'italic', lineHeight: 1.65, borderLeft: '2px solid rgba(255,255,255,0.15)', paddingLeft: '12px' }}>
                  "The best AI users don't ask for answers - they ask better questions."
                </div>
              </div>
              <div style={{ marginTop: '24px' }}>
                <button
                  onClick={() => navigate(`${pathPrefix}/workspace`)}
                  style={{ background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.7)', border: '1.5px solid rgba(255,255,255,0.12)', borderRadius: '8px', padding: '8px 16px', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                  </svg>
                  Open workspace
                </button>
              </div>
            </div>

            <div style={{ flex: 1, background: '#C8102E', padding: '28px 32px', position: 'relative', overflow: 'hidden' }}>
              <svg
                viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                style={{ position: 'absolute', right: '-10px', top: '-10px', width: '140px', height: '140px', opacity: 0.08, pointerEvents: 'none' }}
              >
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              {isDemo ? (
                <>
                  <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.65)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '10px' }}>
                    Active · Week 4
                  </div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#fff', marginBottom: '10px', lineHeight: 1.25 }}>
                    Design a Public Awareness Campaign
                  </div>
                  <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.75)', lineHeight: 1.65, marginBottom: '22px' }}>
                    Use AI tools to design a compelling public awareness campaign for a social issue of your choosing.
                  </div>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <button
                      onClick={() => navigate(`${pathPrefix}/workspace`)}
                      style={{ background: '#fff', color: '#C8102E', border: 'none', borderRadius: '8px', padding: '9px 18px', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
                    >
                      Continue working
                    </button>
                    <button
                      type="button"
                      onClick={() => navigate(`${pathPrefix}/challenges`)}
                      style={{ background: 'rgba(255,255,255,0.15)', color: '#fff', border: '1.5px solid rgba(255,255,255,0.35)', borderRadius: '8px', padding: '9px 18px', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
                    >
                      View challenges
                    </button>
                  </div>
                </>
              ) : challengesLoading ? (
                <div style={{ fontSize: '14px', color: 'rgba(255,255,255,0.85)' }}>Loading challenge…</div>
              ) : liveStats.active ? (
                <>
                  <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.65)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '10px' }}>
                    {liveStats.active.sessions_completed >= liveStats.active.total_sessions
                      ? 'Completed'
                      : 'Continue'}{' '}
                    · {liveStats.active.sessions_completed}/{liveStats.active.total_sessions} sessions
                    {liveStats.active.week != null ? ` · Week ${liveStats.active.week}` : ''}
                  </div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#fff', marginBottom: '10px', lineHeight: 1.25 }}>
                    {liveStats.active.title}
                  </div>
                  <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.75)', lineHeight: 1.65, marginBottom: '22px' }}>
                    {liveStats.active.description}
                  </div>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <button
                      onClick={() => navigate(`${pathPrefix}/challenges/${liveStats.active.id}`)}
                      style={{ background: '#fff', color: '#C8102E', border: 'none', borderRadius: '8px', padding: '9px 18px', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
                    >
                      {liveStats.active.sessions_completed >= liveStats.active.total_sessions ? 'Review challenge' : 'Continue'}
                    </button>
                    <button
                      type="button"
                      onClick={() => navigate(`${pathPrefix}/workspace`)}
                      style={{ background: 'rgba(255,255,255,0.15)', color: '#fff', border: '1.5px solid rgba(255,255,255,0.35)', borderRadius: '8px', padding: '9px 18px', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
                    >
                      Open workspace
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.65)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '10px' }}>
                    Challenges
                  </div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#fff', marginBottom: '10px', lineHeight: 1.25 }}>
                    Pick your first challenge
                  </div>
                  <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.75)', lineHeight: 1.65, marginBottom: '22px' }}>
                    Your instructor’s challenges will appear here once they’re available. Open the list to start a session and earn a PEI score.
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(`${pathPrefix}/challenges`)}
                    style={{ background: '#fff', color: '#C8102E', border: 'none', borderRadius: '8px', padding: '9px 18px', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
                  >
                    Browse challenges
                  </button>
                </>
              )}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', marginBottom: '24px' }}>
            {isDemo ? (
              <>
                <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Prompt Score</div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>7.4</div>
                  <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>+0.6 from last session</div>
                </div>
                <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Challenges Done</div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>8</div>
                  <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>of 12 this semester</div>
                </div>
                <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Class Rank</div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>#4</div>
                  <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>out of 18 students</div>
                </div>
              </>
            ) : (
              <>
                <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Best PEI</div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>
                    {challengesLoading ? '…' : liveStats.bestPei != null ? liveStats.bestPei : '-'}
                  </div>
                  <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>
                    {liveStats.bestPei != null ? 'Across your challenges' : 'Complete a scored session'}
                  </div>
                </div>
                <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Challenges done</div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>
                    {challengesLoading ? '…' : liveStats.completedFull}
                  </div>
                  <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>
                    of {challenges.length} available
                  </div>
                </div>
                <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>In progress</div>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>
                    {challengesLoading ? '…' : liveStats.inProgress}
                  </div>
                  <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>Started, not finished</div>
                </div>
              </>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px' }}>

            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Your prompt dimensions</div>
              {isDemo ? (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                    <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Specificity</div>
                    <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                      <div style={{ width: '80%', height: '100%', borderRadius: '999px', background: '#0D9488', transition: 'width 0.5s ease' }} />
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>80</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                    <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Iteration</div>
                    <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                      <div style={{ width: '65%', height: '100%', borderRadius: '999px', background: '#F97316', transition: 'width 0.5s ease' }} />
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>65</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                    <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Context</div>
                    <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                      <div style={{ width: '72%', height: '100%', borderRadius: '999px', background: '#0D9488', transition: 'width 0.5s ease' }} />
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>72</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
                    <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Refinement</div>
                    <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                      <div style={{ width: '55%', height: '100%', borderRadius: '999px', background: '#C8102E', transition: 'width 0.5s ease' }} />
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>55</div>
                  </div>
                  <div style={{
                    background: '#FDE8EC',
                    border: '1.5px solid #F9BFCA',
                    borderRadius: '10px',
                    padding: '12px 14px',
                    display: 'flex',
                    gap: '8px',
                    alignItems: 'flex-start',
                  }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#C8102E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                      <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
                    </svg>
                    <div>
                      <div style={{ fontSize: '11px', fontWeight: 700, color: '#C8102E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '3px' }}>Focus this week</div>
                      <div style={{ fontSize: '12px', color: '#9E0B24', lineHeight: 1.6 }}>
                        Try refining your prompts 2–3x per session. Iterating on your initial prompt leads to significantly better AI responses and higher scores.
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.65 }}>
                  Dimension breakdowns (Specificity, Iteration, Context, etc.) will appear here after we aggregate your scored workspace sessions. Keep completing challenge sessions to build your profile.
                </div>
              )}
            </div>

            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Recent activity</div>
              {isDemo ? (
                [
                  { dot: '#16A34A', label: 'Workspace session', sub: '2 hours ago', score: '+0.6' },
                  { dot: '#F97316', label: 'Challenge submitted', sub: 'Yesterday', score: '7.1' },
                  { dot: '#0D9488', label: 'New badge earned', sub: '2 days ago', score: null },
                  { dot: '#7C3AED', label: 'Prompt streak - 5 days', sub: '3 days ago', score: null },
                  { dot: '#C8102E', label: 'Challenge started', sub: 'Week 4 began', score: null },
                ].map((item, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', marginBottom: i < 4 ? '14px' : 0, paddingBottom: i < 4 ? '14px' : 0, borderBottom: i < 4 ? '1px solid #F7F3EE' : 'none' }}>
                    <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: item.dot, flexShrink: 0, marginTop: '4px' }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '12px', fontWeight: 500, color: '#16120E' }}>{item.label}</div>
                      <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>{item.sub}</div>
                    </div>
                    {item.score && (
                      <div style={{ fontSize: '12px', fontWeight: 700, color: '#16A34A' }}>{item.score}</div>
                    )}
                  </div>
                ))
              ) : (
                <div style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6 }}>
                  No activity feed yet. Finish a challenge session in the workspace to see updates here soon.
                </div>
              )}
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
