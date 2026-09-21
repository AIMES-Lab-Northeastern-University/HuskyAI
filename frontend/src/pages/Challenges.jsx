import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import GroupTeamManager from '../components/GroupTeamManager'
import SectionsEditor, { sectionsProblem } from '../components/SectionsEditor'
import InfoIcon from '../components/InfoIcon'
import { PEI_INFO } from '../lib/metricInfo'
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

/**
 * Section picker.
 *
 * Not a <select>. `appearance: none` restyles the closed control, but the open
 * options panel is drawn by the OS -- on Windows that is a hard square with its
 * own fonts and colours, and no CSS reaches it. The only way to round it is to
 * render the menu ourselves.
 *
 * What a native select gave us for free and is re-added by hand: close on
 * outside click, close on Escape, and listbox/option roles so it is still
 * announced as a picker.
 */
function SectionPicker({ sections, value, onChange }) {
  const [open, setOpen] = useState(false)
  const [hovered, setHovered] = useState(null)
  const boxRef = useRef(null)
  const current = sections.find(x => x.id === value) || sections[0]

  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (!boxRef.current?.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={boxRef} style={{ position: 'relative' }}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: '10px',
          fontSize: '14px', fontWeight: 600, color: '#16120E',
          padding: '9px 16px', borderRadius: '999px',
          border: '1.5px solid #E7E0D8', background: '#FDFCFB', cursor: 'pointer',
        }}
      >
        {current?.name}
        <svg width="12" height="8" viewBox="0 0 12 8" fill="none"
             style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s ease' }}>
          <path d="M1 1l5 5 5-5" stroke="#9A948E" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div
          role="listbox"
          style={{
            position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 30,
            minWidth: '100%', padding: '6px',
            background: '#FDFCFB', border: '1.5px solid #E7E0D8',
            borderRadius: '14px', boxShadow: '0 8px 24px rgba(22,18,14,0.10)',
          }}
        >
          {sections.map(sec => {
            const selected = sec.id === value
            return (
              <button
                key={sec.id}
                type="button"
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setHovered(sec.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => { onChange(sec.id); setOpen(false) }}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  gap: '16px', width: '100%', textAlign: 'left', whiteSpace: 'nowrap',
                  fontSize: '14px', fontWeight: selected ? 600 : 500,
                  color: selected ? '#16120E' : '#4A4440',
                  padding: '9px 12px', borderRadius: '10px', border: 'none', cursor: 'pointer',
                  background: hovered === sec.id ? '#F7F3EE' : 'transparent',
                }}
              >
                {sec.name}
                {selected && (
                  <svg width="13" height="10" viewBox="0 0 13 10" fill="none">
                    <path d="M1 5l4 4 7-8" stroke="#C8102E" strokeWidth="2"
                          strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
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
  const [createSections, setCreateSections] = useState([])
  const [createDifficulty, setCreateDifficulty] = useState('Beginner')
  const [createWeek, setCreateWeek] = useState('')
  const [createTotalSessions, setCreateTotalSessions] = useState(3)
  // Timed-session settings for the create form. Off by default = untimed.
  const [createTimed, setCreateTimed] = useState(false)
  const [createTimeLimit, setCreateTimeLimit] = useState(15)
  const [createMinTurns, setCreateMinTurns] = useState(5)
  const [createGroup, setCreateGroup] = useState(false)
  const [createTeamMin, setCreateTeamMin] = useState(2)
  const [createTeamMax, setCreateTeamMax] = useState(4)
  const [manageTeamsId, setManageTeamsId] = useState(null)
  // Which half of this page an instructor is looking at. Defaults to the
  // student view, so a non-instructor's experience is unchanged.
  // null until /classrooms/me answers. Rendering a default first made the
  // page show the student view for a beat and then swap -- the role is not
  // known at mount, so there is no honest default to paint.
  const [pageTab, setPageTab] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
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
    if (isDemo) { setPageTab('mine'); return }
    fetch(`${API_URL}/classrooms/me`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => {
        const inst = Array.isArray(data)
          ? data.filter(c => c.role === 'instructor' || c.role === 'admin')
          : []
        setInstructorSections(inst)
        if (inst.length > 0) {
          setSelectedSectionId(inst[0].id)
          setPageTab('manage')      // land on the first tab
        } else {
          setPageTab('mine')
        }
      })
      // Every path must resolve the tab, or the page stays blank forever.
      .catch(() => setPageTab('mine'))
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
    const secProblem = sectionsProblem(createSections)
    if (secProblem) { setCreateMsg(secProblem); return }
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
          time_limit_minutes: createTimed ? createTimeLimit : null,
          min_turns: createTimed ? createMinTurns : null,
          is_active: publish,
          mode: createGroup ? 'group' : 'solo',
          sections: createSections.map(x => ({
            key: (x.key || '').trim(),
            title: (x.title || '').trim(),
            prompt: (x.prompt || '').trim(),
          })),
          team_min: createTeamMin,
          team_max: createTeamMax,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setCreateMsg(typeof d.detail === 'string' ? d.detail : 'Could not create challenge'); return }
      setCreateMsg(publish
        ? 'Challenge published - students can see it now.'
        : 'Draft saved. Use Publish to make it visible to students.')
      setCreateTitle(''); setCreateDesc(''); setCreateWeek(''); setCreateSections([])
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
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: 'var(--sidebar-width, 220px)', transition: 'margin-left 200ms ease' }}>

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

          {/* Two modes for an instructor: the challenges they are enrolled in,
              and the section they manage. They used to be stacked down one
              scroll with the create form permanently open; now one at a time.
              A student has no instructor sections, so no strip renders and the
              page is byte-for-byte what it always was for them. */}
          {!isDemo && instructorSections.length > 0 && (
            <div style={{ display: 'flex', gap: '4px', marginBottom: '24px', borderBottom: '1.5px solid #E7E0D8' }}>
              {/* Named by the ROLE you are acting in, not by ownership. "My
                  challenges" read as "the ones I own", which to an instructor is
                  the other tab -- and the manage tab is not ownership anyway: it
                  lists everything linked to the section, including challenges
                  someone else authored or the server seeded. */}
              {[['manage', 'As instructor'], ['mine', 'As a student']].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setPageTab(key)}
                  style={{ padding: '8px 16px', fontSize: '13px', cursor: 'pointer',
                    background: 'none', border: 'none', marginBottom: '-1.5px',
                    fontWeight: pageTab === key ? 700 : 500,
                    color: pageTab === key ? '#16120E' : '#9A948E',
                    borderBottom: pageTab === key ? '2px solid #C8102E' : '2px solid transparent' }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {pageTab === 'mine' && (
          <>
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
                      {c.group_mode && (
                        <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: '#EDE9FE', color: '#7C3AED', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                          Group
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
                          <InfoIcon text={PEI_INFO.description} />
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
          </>
          )}

          {/* Instructor: Manage Challenges */}
          {!isDemo && instructorSections.length > 0 && pageTab === 'manage' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '10px' }}>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E' }}>
                  Manage challenges
                </div>
<div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '12px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                    Section
                  </span>
                  {instructorSections.length > 1 ? (
                    <SectionPicker
                      sections={instructorSections}
                      value={selectedSectionId}
                      onChange={setSelectedSectionId}
                    />
                  ) : (
                    <span style={{ fontSize: '14px', fontWeight: 600, color: '#16120E' }}>
                      {instructorSections[0].name}
                    </span>
                  )}
                </div>
              </div>

              {/* Existing section challenges */}
              {sectionChallengesLoading ? (
                <div style={{ fontSize: '13px', color: '#9A948E', marginBottom: '20px' }}>Loading…</div>
              ) : sectionChallenges.length === 0 ? (
                <div style={{ fontSize: '13px', color: '#9A948E', marginBottom: '20px' }}>No challenges linked to this section yet.</div>
              ) : (
                <div style={{ marginBottom: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {sectionChallenges.map(c => {
                    const badge = c.is_active
                      ? { label: 'Published', color: '#15803D', bg: '#DCFCE7' }
                      : { label: 'Draft', color: '#9A948E', bg: '#F7F3EE' }
                    return (
                      <div key={c.id} style={{ background: '#FDFCFB', border: '1.5px solid #E7E0D8', borderRadius: '14px', padding: '22px 24px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: '17px', fontWeight: 600, color: '#16120E' }}>{c.title}</div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '7px', flexWrap: 'wrap' }}>
                              {c.week != null && (
                                <span style={{ fontSize: '12px', color: '#9A948E' }}>Week {c.week}</span>
                              )}
                              {c.mode === 'group' && (
                                <span style={{
                                  display: 'inline-flex', alignItems: 'center', gap: '5px',
                                  fontSize: '11px', fontWeight: 700, letterSpacing: '0.3px',
                                  padding: '3px 10px', borderRadius: '999px',
                                  background: '#F3EDFF', color: '#7C3AED',
                                }}>
                                  Group
                                  <span style={{ fontWeight: 600, opacity: 0.75 }}>
                                    {c.team_min}–{c.team_max}
                                  </span>
                                </span>
                              )}
                            </div>
                          </div>
                          <span style={{ fontSize: '12px', fontWeight: 700, padding: '4px 10px', borderRadius: '20px', background: badge.bg, color: badge.color, flexShrink: 0 }}>
                            {badge.label}
                          </span>
                          {c.mode === 'group' && (
                            <button
                              onClick={() => setManageTeamsId(manageTeamsId === c.id ? null : c.id)}
                              style={{ fontSize: '13px', padding: '8px 14px', borderRadius: '8px', border: '1.5px solid', borderColor: manageTeamsId === c.id ? '#7C3AED' : '#E7E0D8', background: manageTeamsId === c.id ? '#7C3AED' : '#fff', cursor: 'pointer', color: manageTeamsId === c.id ? '#fff' : '#4A4440', flexShrink: 0 }}
                            >
                              {manageTeamsId === c.id ? 'Hide teams' : 'Manage teams'}
                            </button>
                          )}
                          <button
                            onClick={() => setChallengeActive(c.id, !c.is_active)}
                            style={{ fontSize: '13px', padding: '8px 14px', borderRadius: '8px', border: '1.5px solid #E7E0D8', background: '#fff', cursor: 'pointer', color: '#4A4440', flexShrink: 0 }}
                          >
                            {c.is_active ? 'Unpublish' : 'Publish'}
                          </button>
                          <button
                            onClick={() => unlinkChallenge(c.id)}
                            style={{ fontSize: '13px', padding: '8px 14px', borderRadius: '8px', border: '1.5px solid #FDE8EC', background: '#FDE8EC', cursor: 'pointer', color: '#C8102E', flexShrink: 0 }}
                          >
                            Remove
                          </button>
                        </div>
                        {c.mode === 'group' && manageTeamsId === c.id && (
                          <GroupTeamManager classroomId={selectedSectionId} challengeId={c.id} />
                        )}
                      </div>
                    )
                  })}
                  {actionMsg && <div style={{ fontSize: '12px', color: '#C8102E', marginTop: '4px' }}>{actionMsg}</div>}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '12px' }}>
                <button
                  type="button"
                  onClick={() => setShowCreate(v => !v)}
                  style={{ fontSize: '14px', fontWeight: 600, padding: '10px 20px', borderRadius: '10px', cursor: 'pointer',
                    border: showCreate ? '1.5px solid #E7E0D8' : 'none',
                    background: showCreate ? 'transparent' : '#C8102E',
                    color: showCreate ? '#4A4440' : '#fff' }}
                >
                  {showCreate ? 'Cancel' : 'New challenge'}
                </button>
              </div>

              {/* Create challenge form */}
              {showCreate && (
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
                    <input
                      type="text"
                      placeholder="Category"
                      value={createCategory}
                      onChange={e => setCreateCategory(e.target.value)}
                      style={{ ...inputStyle, flex: 1 }}
                    />
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
                  {/* Timed session (optional) */}
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#4A4440', cursor: 'pointer' }}>
                    <input type="checkbox" checked={createTimed} onChange={e => setCreateTimed(e.target.checked)} />
                    Timed session
                  </label>
                  {createTimed && (
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                      <label style={{ fontSize: '12px', color: '#6B6560', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        Time limit
                        <input type="number" min={1} max={120} value={createTimeLimit}
                          onChange={e => setCreateTimeLimit(Number(e.target.value))}
                          style={{ ...inputStyle, flex: '0 0 80px' }} /> min
                      </label>
                      <label style={{ fontSize: '12px', color: '#6B6560', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        Min turns
                        <input type="number" min={1} max={50} value={createMinTurns}
                          onChange={e => setCreateMinTurns(Number(e.target.value))}
                          style={{ ...inputStyle, flex: '0 0 80px' }} />
                      </label>
                      <span style={{ fontSize: '11px', color: '#9A948E', flexBasis: '100%', lineHeight: 1.5 }}>
                        Auto-ends at the time limit. Students can end early only after the minimum turns. Applies to sessions started after you save.
                      </span>
                    </div>
                  )}
                  {/* Group challenge (optional) */}
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#4A4440', cursor: 'pointer' }}>
                    <input type="checkbox" checked={createGroup} onChange={e => setCreateGroup(e.target.checked)} />
                    Group challenge (prof-assigned teams)
                  </label>
                  {createGroup && (
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                      <label style={{ fontSize: '12px', color: '#6B6560', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        Team min
                        <input type="number" min={2} max={4} value={createTeamMin}
                          onChange={e => setCreateTeamMin(Number(e.target.value))}
                          style={{ ...inputStyle, flex: '0 0 72px' }} />
                      </label>
                      <label style={{ fontSize: '12px', color: '#6B6560', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        Team max
                        <input type="number" min={2} max={4} value={createTeamMax}
                          onChange={e => setCreateTeamMax(Number(e.target.value))}
                          style={{ ...inputStyle, flex: '0 0 72px' }} />
                      </label>
                      <span style={{ fontSize: '11px', color: '#9A948E', flexBasis: '100%', lineHeight: 1.5 }}>
                        After publishing, use “Manage teams” on the challenge above to assign students. A team needs at least the minimum online to run — no solo fallback.
                      </span>
                    </div>
                  )}
                  <SectionsEditor
                    sections={createSections}
                    onChange={setCreateSections}
                    disabled={creating || creatingDraft}
                  />
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
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
