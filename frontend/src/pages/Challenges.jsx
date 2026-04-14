import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { DEMO_CHALLENGE_LIST } from '../demo/demoData'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function authHeaders() {
  const token = localStorage.getItem('token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

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

  // Instructor state
  const [instructorSections, setInstructorSections] = useState([])
  const [selectedSectionId, setSelectedSectionId] = useState('')
  const [sectionChallenges, setSectionChallenges] = useState([])
  const [sectionChallengesLoading, setSectionChallengesLoading] = useState(false)
  const [createTitle, setCreateTitle] = useState('')
  const [createDesc, setCreateDesc] = useState('')
  const [createCategory, setCreateCategory] = useState('General')
  const [createDifficulty, setCreateDifficulty] = useState('Beginner')
  const [createWeek, setCreateWeek] = useState('')
  const [createTotalSessions, setCreateTotalSessions] = useState(3)
  const [createMsg, setCreateMsg] = useState('')
  const [creating, setCreating] = useState(false)
  const [creatingDraft, setCreatingDraft] = useState(false)
  const [actionMsg, setActionMsg] = useState('')

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

  // Load instructor sections
  useEffect(() => {
    if (isDemo) return
    fetch(`${API_URL}/classrooms/me`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => {
        if (!Array.isArray(data)) return
        const inst = data.filter(c => c.role === 'instructor' || c.role === 'admin')
        setInstructorSections(inst)
        if (inst.length > 0) setSelectedSectionId(inst[0].id)
      })
      .catch(() => {})
  }, [isDemo])

  const loadSectionChallenges = useCallback(async () => {
    if (!selectedSectionId) return
    setSectionChallengesLoading(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedSectionId}/challenges`, { headers: authHeaders() })
      const data = await r.json().catch(() => [])
      if (r.ok) setSectionChallenges(Array.isArray(data) ? data : [])
    } catch {} finally {
      setSectionChallengesLoading(false)
    }
  }, [selectedSectionId])

  useEffect(() => {
    loadSectionChallenges()
    setActionMsg('')
    setCreateMsg('')
  }, [loadSectionChallenges])

  const createChallenge = async (publish = true) => {
    if (!selectedSectionId) return
    const title = createTitle.trim()
    const description = createDesc.trim()
    if (!title || !description) { setCreateMsg('Title and description are required'); return }
    let weekNum = null
    if (createWeek.trim() !== '') {
      const n = parseInt(createWeek, 10)
      if (Number.isNaN(n)) { setCreateMsg('Week must be a number'); return }
      weekNum = n
    }
    setCreateMsg('')
    if (publish) setCreating(true); else setCreatingDraft(true)
    try {
      const r = await fetch(`${API_URL}/challenges`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          classroom_id: selectedSectionId,
          title, description,
          category: createCategory.trim() || 'General',
          difficulty: createDifficulty,
          week: weekNum,
          total_sessions: createTotalSessions,
          is_active: publish,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setCreateMsg(typeof d.detail === 'string' ? d.detail : 'Could not create challenge'); return }
      setCreateMsg(publish ? 'Challenge published — students can see it now.' : 'Draft saved.')
      setCreateTitle(''); setCreateDesc(''); setCreateWeek('')
      await loadSectionChallenges()
    } catch { setCreateMsg('Network error') }
    finally { setCreating(false); setCreatingDraft(false) }
  }

  const setChallengeActive = async (challengeId, isActive) => {
    setActionMsg('')
    try {
      await fetch(`${API_URL}/challenges/${challengeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_active: isActive }),
      })
      await loadSectionChallenges()
    } catch { setActionMsg('Network error') }
  }

  const unlinkChallenge = async (challengeId) => {
    if (!selectedSectionId) return
    if (!window.confirm('Remove this challenge from this section?')) return
    try {
      await fetch(`${API_URL}/classrooms/${selectedSectionId}/challenges/${challengeId}`, {
        method: 'DELETE', headers: authHeaders(),
      })
      await loadSectionChallenges()
    } catch { setActionMsg('Network error') }
  }

  const inputStyle = {
    width: '100%', padding: '10px 12px', borderRadius: '8px',
    border: '1.5px solid #E7E0D8', fontSize: '14px', background: '#fff',
  }

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

          {/* Instructor: Manage Challenges */}
          {!isDemo && instructorSections.length > 0 && (
            <div style={{ marginTop: '40px', borderTop: '1.5px solid #E7E0D8', paddingTop: '32px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '10px' }}>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E' }}>
                  Manage challenges
                </div>
                {instructorSections.length > 1 && (
                  <select
                    value={selectedSectionId}
                    onChange={e => setSelectedSectionId(e.target.value)}
                    style={{ ...inputStyle, width: 'auto', fontSize: '13px' }}
                  >
                    {instructorSections.map(s => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                )}
                {instructorSections.length === 1 && (
                  <span style={{ fontSize: '13px', color: '#9A948E' }}>
                    {instructorSections[0].name}
                  </span>
                )}
              </div>

              {/* Existing section challenges */}
              {sectionChallengesLoading ? (
                <div style={{ fontSize: '13px', color: '#9A948E', marginBottom: '20px' }}>Loading…</div>
              ) : sectionChallenges.length === 0 ? (
                <div style={{ fontSize: '13px', color: '#9A948E', marginBottom: '20px' }}>No challenges linked to this section yet.</div>
              ) : (
                <div style={{ marginBottom: '24px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {sectionChallenges.map(c => {
                    const badge = c.is_active
                      ? { label: 'Published', color: '#15803D', bg: '#DCFCE7' }
                      : { label: 'Draft', color: '#9A948E', bg: '#F7F3EE' }
                    return (
                      <div key={c.id} style={{ background: '#FDFCFB', border: '1.5px solid #E7E0D8', borderRadius: '10px', padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: '14px', fontWeight: 600, color: '#16120E' }}>{c.title}</div>
                          {c.week != null && <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>Week {c.week}</div>}
                        </div>
                        <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: badge.bg, color: badge.color, flexShrink: 0 }}>
                          {badge.label}
                        </span>
                        <button
                          onClick={() => setChallengeActive(c.id, !c.is_active)}
                          style={{ fontSize: '12px', padding: '4px 10px', borderRadius: '6px', border: '1.5px solid #E7E0D8', background: '#fff', cursor: 'pointer', color: '#4A4440', flexShrink: 0 }}
                        >
                          {c.is_active ? 'Unpublish' : 'Publish'}
                        </button>
                        <button
                          onClick={() => unlinkChallenge(c.id)}
                          style={{ fontSize: '12px', padding: '4px 10px', borderRadius: '6px', border: '1.5px solid #FDE8EC', background: '#FDE8EC', cursor: 'pointer', color: '#C8102E', flexShrink: 0 }}
                        >
                          Remove
                        </button>
                      </div>
                    )
                  })}
                  {actionMsg && <div style={{ fontSize: '12px', color: '#C8102E', marginTop: '4px' }}>{actionMsg}</div>}
                </div>
              )}

              {/* Create challenge form */}
              <div style={{ background: '#FDFCFB', border: '1.5px solid #E7E0D8', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '14px' }}>
                  Create challenge for this section
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <input
                    placeholder="Title"
                    value={createTitle}
                    onChange={e => setCreateTitle(e.target.value)}
                    style={inputStyle}
                  />
                  <textarea
                    placeholder="Description (what students should do)"
                    value={createDesc}
                    onChange={e => setCreateDesc(e.target.value)}
                    rows={3}
                    style={{ ...inputStyle, resize: 'vertical' }}
                  />
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <select value={createCategory} onChange={e => setCreateCategory(e.target.value)} style={{ ...inputStyle, flex: 1 }}>
                      {['General', 'Technical', 'Creative & Strategy', 'Data & Analysis', 'Product & Business'].map(c => (
                        <option key={c}>{c}</option>
                      ))}
                    </select>
                    <select value={createDifficulty} onChange={e => setCreateDifficulty(e.target.value)} style={{ ...inputStyle, flex: 1 }}>
                      {['Beginner', 'Intermediate', 'Advanced'].map(d => <option key={d}>{d}</option>)}
                    </select>
                    <input
                      placeholder="Week (optional)"
                      value={createWeek}
                      onChange={e => setCreateWeek(e.target.value)}
                      style={{ ...inputStyle, flex: 1 }}
                    />
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
                      <span style={{ fontSize: '13px', color: '#4A4440', whiteSpace: 'nowrap' }}>{createTotalSessions} sessions</span>
                      <input type="range" min={1} max={10} value={createTotalSessions} onChange={e => setCreateTotalSessions(Number(e.target.value))} style={{ flex: 1 }} />
                    </div>
                  </div>
                  {createMsg && <div style={{ fontSize: '12px', color: createMsg.includes('published') || createMsg.includes('saved') ? '#16A34A' : '#C8102E' }}>{createMsg}</div>}
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <button
                      onClick={() => createChallenge(true)}
                      disabled={creating}
                      style={{ flex: 1, padding: '10px', background: '#C8102E', color: '#fff', border: 'none', borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer', opacity: creating ? 0.6 : 1 }}
                    >
                      {creating ? 'Publishing…' : 'Publish challenge'}
                    </button>
                    <button
                      onClick={() => createChallenge(false)}
                      disabled={creatingDraft}
                      style={{ flex: 1, padding: '10px', background: 'transparent', color: '#4A4440', border: '1.5px solid #E7E0D8', borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer', opacity: creatingDraft ? 0.6 : 1 }}
                    >
                      {creatingDraft ? 'Saving…' : 'Save as draft'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
