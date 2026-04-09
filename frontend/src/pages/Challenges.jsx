import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { DEMO_CHALLENGE_LIST } from '../demo/demoData'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const CATEGORY_STYLES = {
  'Technical':          { color: '#C8102E', bg: '#FDE8EC' },
  'Creative & Strategy':{ color: '#7C3AED', bg: '#F5F3FF' },
  'Data & Analysis':    { color: '#0D9488', bg: '#E6F7F6' },
  'Product & Business': { color: '#D97706', bg: '#FEF9EC' },
}

const DIFF_STYLES = {
  'Beginner':     { color: '#16A34A', bg: '#DCFCE7' },
  'Intermediate': { color: '#F97316', bg: '#FEF3E8' },
  'Advanced':     { color: '#C8102E', bg: '#FDE8EC' },
}

function categoryStyle(cat) {
  return CATEGORY_STYLES[cat] || { color: '#4A4440', bg: '#F7F3EE' }
}

function diffStyle(d) {
  return DIFF_STYLES[d] || { color: '#4A4440', bg: '#F7F3EE' }
}

export default function Challenges() {
  const navigate = useNavigate()
  const location = useLocation()
  const isDemo = location.pathname.startsWith('/demo')
  const pathPrefix = isDemo ? '/demo' : ''
  const [challenges, setChallenges] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeFilter, setActiveFilter] = useState('All')

  const handleLogout = () => {
    if (isDemo) {
      navigate('/', { replace: true })
      return
    }
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  useEffect(() => {
    if (isDemo) {
      setChallenges(DEMO_CHALLENGE_LIST)
      setLoading(false)
      return
    }
    const token = localStorage.getItem('token')
    fetch(`${API_URL}/challenges`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) setChallenges(data)
        else setError('Unexpected response from server')
      })
      .catch(() => setError('Failed to load challenges'))
      .finally(() => setLoading(false))
  }, [isDemo])

  const categories = ['All', ...new Set(challenges.map(c => c.category))]

  const filtered = challenges.filter(c => {
    if (activeFilter === 'All') return true
    if (activeFilter === 'Completed') return c.sessions_completed === c.total_sessions
    return c.category === activeFilter
  })

  const filters = [...categories, 'Completed']

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        {/* Topbar */}
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Challenges</span>
          {!loading && (
            <span style={{ fontSize: '12px', color: '#9A948E', marginLeft: '6px' }}>
              {challenges.length} available
            </span>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* Filter bar */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', flexWrap: 'wrap' }}>
            {filters.map(f => (
              <button
                key={f}
                onClick={() => setActiveFilter(f)}
                style={{
                  padding: '6px 14px',
                  borderRadius: '20px',
                  fontSize: '13px',
                  fontWeight: activeFilter === f ? 600 : 500,
                  cursor: 'pointer',
                  border: activeFilter === f ? 'none' : '1.5px solid #E7E0D8',
                  background: activeFilter === f ? '#C8102E' : '#FDFCFB',
                  color: activeFilter === f ? '#fff' : '#4A4440',
                  transition: 'all 0.15s ease',
                }}
              >
                {f}
              </button>
            ))}
          </div>

          {/* States */}
          {loading && (
            <div style={{ textAlign: 'center', paddingTop: '80px', color: '#9A948E', fontSize: '14px' }}>
              Loading challenges...
            </div>
          )}
          {error && (
            <div style={{ textAlign: 'center', paddingTop: '80px', color: '#C8102E', fontSize: '14px' }}>
              {error}
            </div>
          )}

          {!loading && !error && !isDemo && challenges.length === 0 && (
            <div
              className="bg-[#FDFCFB] rounded-[14px] p-8 max-w-xl"
              style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
            >
              <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E', marginBottom: '10px' }}>
                No challenges yet
              </div>
              <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.65, marginBottom: '16px' }}>
                Challenges are assigned per class. Join a section with your instructor’s code on the{' '}
                <button
                  type="button"
                  onClick={() => navigate(`${pathPrefix}/classroom`)}
                  style={{ color: '#C8102E', fontWeight: 600, background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
                >
                  Classroom
                </button>
                {' '}page or in{' '}
                <button
                  type="button"
                  onClick={() => navigate(`${pathPrefix}/settings`)}
                  style={{ color: '#C8102E', fontWeight: 600, background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
                >
                  Settings
                </button>
                . After you join, assigned challenges appear here.
              </p>
              <p style={{ fontSize: '12px', color: '#9A948E', lineHeight: 1.5 }}>
                Local dev: the server seeds a test section <strong style={{ color: '#4A4440' }}>Husky Test Section</strong> with join code{' '}
                <strong style={{ color: '#4A4440' }}>HUSKYDMX</strong> (override with <code style={{ fontSize: '11px' }}>SEED_CLASSROOM_CODE</code> in <code style={{ fontSize: '11px' }}>backend/.env</code>).
              </p>
            </div>
          )}

          {/* Challenge grid */}
          {!loading && !error && filtered.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              {filtered.map(c => {
                const progress = c.total_sessions > 0
                  ? Math.round((c.sessions_completed / c.total_sessions) * 100)
                  : 0
                const isCompleted = c.sessions_completed === c.total_sessions
                const isStarted = c.sessions_completed > 0
                const cs = categoryStyle(c.category)
                const ds = diffStyle(c.difficulty)

                return (
                  <div
                    key={c.id}
                    style={{
                      background: '#FDFCFB',
                      borderRadius: '14px',
                      padding: '20px',
                      borderWidth: '1.5px',
                      borderStyle: 'solid',
                      borderColor: isStarted && !isCompleted ? '#F9BFCA' : '#E7E0D8',
                      cursor: 'pointer',
                      transition: 'box-shadow 0.15s ease, transform 0.1s ease',
                    }}
                    onClick={() => navigate(`${pathPrefix}/challenges/${c.id}`)}
                    onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 4px 16px rgba(22,18,14,0.08)'; e.currentTarget.style.transform = 'translateY(-1px)' }}
                    onMouseLeave={e => { e.currentTarget.style.boxShadow = 'none'; e.currentTarget.style.transform = 'none' }}
                  >
                    {/* Category + status */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                      <span style={{
                        fontSize: '11px', fontWeight: 700, padding: '3px 10px',
                        borderRadius: '20px', background: cs.bg, color: cs.color,
                      }}>
                        {c.category}
                      </span>
                      {isCompleted && (
                        <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: '#DCFCE7', color: '#16A34A', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                          Done
                        </span>
                      )}
                      {isStarted && !isCompleted && (
                        <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: '#FDE8EC', color: '#C8102E', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                          Active
                        </span>
                      )}
                      {c.instructor_preview && (
                        <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: '#E0E7FF', color: '#4338CA', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                          Test preview
                        </span>
                      )}
                    </div>

                    {/* Title */}
                    <div style={{ fontSize: '15px', fontWeight: 600, color: '#16120E', marginBottom: '8px', fontFamily: "'Instrument Serif', serif" }}>
                      {c.title}
                    </div>

                    {/* Description */}
                    <div style={{ fontSize: '12px', color: '#9A948E', lineHeight: 1.65, marginBottom: '16px' }}>
                      {c.description.length > 160 ? c.description.slice(0, 160) + '…' : c.description}
                    </div>

                    {/* Progress bar */}
                    <div style={{ marginBottom: '14px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                        <span style={{ fontSize: '11px', color: '#9A948E', fontWeight: 500 }}>
                          {c.sessions_completed}/{c.total_sessions} sessions
                        </span>
                        <span style={{ fontSize: '11px', fontWeight: 700, color: '#4A4440' }}>{progress}%</span>
                      </div>
                      <div style={{ height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                        <div style={{
                          width: `${progress}%`,
                          height: '100%',
                          borderRadius: '999px',
                          background: isCompleted ? '#16A34A' : isStarted ? '#C8102E' : '#E7E0D8',
                          transition: 'width 0.5s ease',
                        }} />
                      </div>
                    </div>

                    {/* Meta row */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                        </svg>
                        <span style={{ fontSize: '11px', color: '#9A948E' }}>{c.total_sessions} sessions</span>
                      </div>
                      {c.week && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
                          </svg>
                          <span style={{ fontSize: '11px', color: '#9A948E' }}>Week {c.week}</span>
                        </div>
                      )}
                      {c.best_pei != null && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <span style={{ fontSize: '11px', color: '#9A948E' }}>Best PEI:</span>
                          <span style={{ fontSize: '11px', fontWeight: 700, color: '#C8102E' }}>{Math.round(c.best_pei)}</span>
                        </div>
                      )}
                      <div style={{ marginLeft: 'auto' }}>
                        <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: ds.bg, color: ds.color }}>
                          {c.difficulty}
                        </span>
                      </div>
                    </div>

                    {/* CTA */}
                    <button
                      onClick={e => { e.stopPropagation(); navigate(`${pathPrefix}/challenges/${c.id}`) }}
                      style={{
                        marginTop: '14px',
                        width: '100%',
                        padding: '9px',
                        background: isStarted && !isCompleted ? '#C8102E' : 'transparent',
                        color: isStarted && !isCompleted ? '#fff' : '#4A4440',
                        border: isStarted && !isCompleted ? 'none' : '1.5px solid #E7E0D8',
                        borderRadius: '8px',
                        fontSize: '13px',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      {isCompleted ? 'View results' : isStarted ? 'Continue challenge' : 'View challenge'}
                    </button>
                  </div>
                )
              })}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
