import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders } from '../lib/api'

function DualBar({ label, yourPct, partnerPct, yourColor, partnerColor }) {
  return (
    <div style={{ marginBottom: '14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
        <span style={{ fontSize: '12px', color: '#9A948E', fontWeight: 500 }}>{label}</span>
        <div style={{ display: 'flex', gap: '10px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: yourColor }}>{yourPct}%</span>
          <span style={{ fontSize: '12px', fontWeight: 700, color: partnerColor }}>{partnerPct}%</span>
        </div>
      </div>
      <div style={{ height: '7px', background: '#2A2520', borderRadius: '999px', overflow: 'hidden', display: 'flex' }}>
        <div style={{ width: `${yourPct}%`, height: '100%', background: yourColor, transition: 'width 0.5s ease' }} />
        <div style={{ width: `${partnerPct - yourPct}%`, height: '100%', background: partnerColor, opacity: 0.6, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

function DemoClassroomView({ navigate, onLogout }) {
  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={onLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Classroom</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>Sample comparison (demo)</span>
          </div>
          <div className="ml-auto">
            <button
              type="button"
              onClick={() => navigate('/demo/classroom/browse')}
              style={{
                background: 'transparent',
                border: '1.5px solid #E7E0D8',
                borderRadius: '8px',
                padding: '7px 14px',
                fontSize: '13px',
                fontWeight: 600,
                color: '#4A4440',
                cursor: 'pointer',
              }}
            >
              Browse sections
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-8">
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px' }}>
            <div style={{
              background: '#FDFCFB',
              borderRadius: '14px',
              overflow: 'hidden',
              borderWidth: '1.5px',
              borderStyle: 'solid',
              borderColor: '#E7E0D8',
            }}>
              <div style={{
                background: '#16120E',
                padding: '16px 20px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff', marginBottom: '2px' }}>
                    Live comparison — Week 4
                  </div>
                  <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
                    Section A vs. Partner Class
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#16A34A' }} />
                  <span style={{ fontSize: '11px', fontWeight: 600, color: '#16A34A' }}>Live</span>
                </div>
              </div>
              <div style={{ padding: '20px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0', marginBottom: '24px' }}>
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
                      Your class
                    </div>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '36px', color: '#F97316', lineHeight: 1 }}>6.8</div>
                    <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '4px' }}>avg PEI score</div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '0 20px' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '1px' }}>VS</div>
                    <div style={{ width: '1px', height: '40px', background: '#E7E0D8', marginTop: '4px' }} />
                  </div>
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
                      Partner class
                    </div>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '36px', color: '#16A34A', lineHeight: 1 }}>7.1</div>
                    <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '4px' }}>avg PEI score</div>
                  </div>
                </div>
                <div style={{ marginBottom: '18px' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '16px', marginBottom: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <div style={{ width: '10px', height: '4px', borderRadius: '2px', background: '#F97316' }} />
                      <span style={{ fontSize: '11px', color: '#9A948E' }}>Your class</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <div style={{ width: '10px', height: '4px', borderRadius: '2px', background: '#16A34A' }} />
                      <span style={{ fontSize: '11px', color: '#9A948E' }}>Partner</span>
                    </div>
                  </div>
                  <DualBar label="Specificity" yourPct={72} partnerPct={78} yourColor="#F97316" partnerColor="#16A34A" />
                  <DualBar label="Iteration" yourPct={60} partnerPct={74} yourColor="#F97316" partnerColor="#16A34A" />
                  <DualBar label="Refinement" yourPct={55} partnerPct={68} yourColor="#F97316" partnerColor="#16A34A" />
                </div>
                <div style={{
                  background: '#FEF9EC',
                  border: '1.5px solid #FDE68A',
                  borderRadius: '10px',
                  padding: '12px 14px',
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'flex-start',
                }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                    <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                  <div>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#D97706', marginBottom: '3px' }}>Class insight</div>
                    <div style={{ fontSize: '12px', color: '#92400E', lineHeight: 1.6 }}>
                      Your class is 0.3 points behind the partner class this week. Focus on Refinement dimension — it has the largest gap and biggest potential impact on your PEI.
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Gap to close</div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#C8102E', lineHeight: 1 }}>−0.3</div>
                <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>points behind partner</div>
              </div>
              <button
                onClick={() => navigate('/demo/workspace')}
                style={{
                  background: '#C8102E',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '10px',
                  padding: '12px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                </svg>
                Try workspace (demo)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Classroom() {
  const navigate = useNavigate()
  const location = useLocation()
  const isDemo = location.pathname.startsWith('/demo')
  const pathPrefix = isDemo ? '/demo' : ''

  const [classrooms, setClassrooms] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [classCode, setClassCode] = useState('')
  const [joinMsg, setJoinMsg] = useState('')
  const [joining, setJoining] = useState(false)
  const [loadErr, setLoadErr] = useState('')
  const [listedSaving, setListedSaving] = useState(false)
  const [roleTab, setRoleTab] = useState('student')
  const [newSectionName, setNewSectionName] = useState('')
  const [newSectionListed, setNewSectionListed] = useState(false)
  const [newSectionTest, setNewSectionTest] = useState(false)
  const [creatingSection, setCreatingSection] = useState(false)
  const [createSectionMsg, setCreateSectionMsg] = useState('')
  const [createdJoinCode, setCreatedJoinCode] = useState('')

  const needInstructorHint = Boolean(location.state?.needInstructor)
  const instructingClassrooms = classrooms.filter(c => c.role === 'instructor' || c.role === 'admin')

  const handleLogout = () => {
    if (isDemo) {
      navigate('/', { replace: true })
      return
    }
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  const loadClassrooms = useCallback(async () => {
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      return
    }
    setLoadErr('')
    try {
      const r = await fetch(`${API_URL}/classrooms/me`, { headers: { ...authHeaders() } })
      if (!r.ok) {
        const errBody = await r.json().catch(() => ({}))
        setLoadErr(typeof errBody.detail === 'string' ? errBody.detail : 'Could not load classrooms')
        setClassrooms([])
        return
      }
      const data = await r.json()
      setClassrooms(Array.isArray(data) ? data : [])
    } catch {
      setLoadErr('Network error')
      setClassrooms([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isDemo) return
    loadClassrooms()
  }, [isDemo, loadClassrooms])

  useEffect(() => {
    if (location.state?.needInstructor) setRoleTab('instructor')
  }, [location.state?.needInstructor])

  const studentPrimary = classrooms.find(c => c.role === 'student') ?? null

  const updateListedInDirectory = async (classroomId, next) => {
    if (!classroomId) return
    setListedSaving(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/${classroomId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ listed_in_directory: next }),
      })
      if (r.ok) {
        await loadClassrooms()
        if (studentPrimary?.id) {
          const sr = await fetch(`${API_URL}/classrooms/${studentPrimary.id}/summary`, { headers: { ...authHeaders() } })
          const sd = await sr.json().catch(() => null)
          if (sr.ok && sd) setSummary(sd)
        }
      }
    } finally {
      setListedSaving(false)
    }
  }

  useEffect(() => {
    if (isDemo || !studentPrimary?.id) {
      setSummary(null)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/classrooms/${studentPrimary.id}/summary`, { headers: { ...authHeaders() } })
        const d = await r.json().catch(() => ({}))
        if (!cancelled && r.ok) setSummary(d)
        else if (!cancelled) setSummary(null)
      } catch {
        if (!cancelled) setSummary(null)
      }
    })()
    return () => { cancelled = true }
  }, [isDemo, studentPrimary?.id])

  const joinClass = async () => {
    const token = localStorage.getItem('token')
    if (!token) {
      navigate('/login')
      return
    }
    setJoinMsg('')
    setJoining(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/join`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ code: classCode.trim() }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setJoinMsg(typeof d.detail === 'string' ? d.detail : 'Could not join class')
        return
      }
      setJoinMsg(d.status === 'already_member' ? `Already in ${d.name}` : `Joined ${d.name}`)
      setClassCode('')
      await loadClassrooms()
    } catch {
      setJoinMsg('Network error')
    } finally {
      setJoining(false)
    }
  }

  const createSection = async () => {
    const token = localStorage.getItem('token')
    if (!token) {
      navigate('/login')
      return
    }
    const name = newSectionName.trim()
    if (!name) {
      setCreateSectionMsg('Enter a section name')
      return
    }
    setCreateSectionMsg('')
    setCreatingSection(true)
    setCreatedJoinCode('')
    try {
      const r = await fetch(`${API_URL}/classrooms`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name, listed_in_directory: newSectionListed }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setCreateSectionMsg(typeof d.detail === 'string' ? d.detail : 'Could not create section')
        return
      }
      setCreateSectionMsg(`Created "${d.name}". Share the join code with students.`)
      setCreatedJoinCode(d.join_code || '')
      setNewSectionName('')
      setNewSectionTest(false)
      await loadClassrooms()
    } catch {
      setCreateSectionMsg('Network error')
    } finally {
      setCreatingSection(false)
    }
  }

  if (isDemo) {
    return <DemoClassroomView navigate={navigate} onLogout={handleLogout} />
  }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Classroom</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>
              {studentPrimary?.name
                || (instructingClassrooms.length ? 'Manage sections & join codes' : 'Join as student or create a section')}
            </span>
          </div>
          <div className="ml-auto">
            <button
              type="button"
              onClick={() => navigate(`${pathPrefix}/classroom/browse`)}
              style={{
                background: 'transparent',
                border: '1.5px solid #E7E0D8',
                borderRadius: '8px',
                padding: '7px 14px',
                fontSize: '13px',
                fontWeight: 600,
                color: '#4A4440',
                cursor: 'pointer',
              }}
            >
              Browse sections
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8">
          {needInstructorHint && (
            <div
              className="mb-5 px-4 py-3 rounded-[10px] text-sm"
              style={{ background: '#FEF9EC', border: '1.5px solid #FDE68A', color: '#92400E', maxWidth: '640px' }}
            >
              The instructor dashboard is only for users who own or manage a section. Use <strong>I’m an instructor</strong> below to create one, then open <strong>Instructor</strong> in the sidebar.
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
            {[
              { id: 'student', label: 'Join as student' },
              { id: 'instructor', label: 'I’m an instructor' },
            ].map(t => (
              <button
                key={t.id}
                type="button"
                onClick={() => setRoleTab(t.id)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  fontSize: '13px',
                  fontWeight: 600,
                  border: roleTab === t.id ? 'none' : '1.5px solid #E7E0D8',
                  background: roleTab === t.id ? '#C8102E' : '#FDFCFB',
                  color: roleTab === t.id ? '#fff' : '#4A4440',
                  cursor: 'pointer',
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          {roleTab === 'student' && (
          <div
            className="bg-[#FDFCFB] rounded-[14px] p-5 mb-6"
            style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '520px' }}
          >
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '10px' }}>
              Join with your instructor’s code
            </div>
            <p style={{ fontSize: '13px', color: '#4A4440', marginBottom: '12px', lineHeight: 1.55 }}>
              Enter the code your instructor shared (letters and numbers). You can also{' '}
              <button
                type="button"
                onClick={() => navigate(`${pathPrefix}/classroom/browse`)}
                style={{ color: '#C8102E', fontWeight: 600, background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
              >
                browse listed sections
              </button>
              {' '}for names only — codes stay private until your instructor gives you one.
            </p>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
              <input
                value={classCode}
                onChange={e => setClassCode(e.target.value.toUpperCase())}
                placeholder="e.g. AB12CD34"
                maxLength={16}
                style={{
                  flex: '1 1 200px',
                  minWidth: '180px',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: '1.5px solid #E7E0D8',
                  fontSize: '14px',
                  fontWeight: 600,
                  letterSpacing: '0.05em',
                }}
              />
              <button
                type="button"
                onClick={joinClass}
                disabled={joining || !classCode.trim()}
                style={{
                  background: joining || !classCode.trim() ? '#E7E0D8' : '#C8102E',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '10px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: joining || !classCode.trim() ? 'default' : 'pointer',
                }}
              >
                {joining ? 'Joining…' : 'Join as student'}
              </button>
            </div>
            {joinMsg && (
              <div style={{ marginTop: '10px', fontSize: '13px', color: joinMsg.startsWith('Joined') || joinMsg.startsWith('Already') ? '#15803D' : '#C8102E' }}>
                {joinMsg}
              </div>
            )}
          </div>
          )}

          {roleTab === 'instructor' && (
            <div
              className="bg-[#FDFCFB] rounded-[14px] p-5 mb-6"
              style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '560px' }}
            >
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '10px' }}>
                Create a section (you become the instructor)
              </div>
              <p style={{ fontSize: '13px', color: '#4A4440', marginBottom: '14px', lineHeight: 1.55 }}>
                This is not the same as joining with a code — you’ll get a new join code to share with students. After creating, use <strong>Instructor</strong> in the sidebar to assign challenges.
              </p>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', fontSize: '13px', color: '#4A4440', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={newSectionListed}
                  onChange={e => setNewSectionListed(e.target.checked)}
                  style={{ accentColor: '#C8102E' }}
                />
                List this section on Browse sections (name + member count only)
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', fontSize: '13px', color: '#4A4440', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={newSectionTest}
                  onChange={e => setNewSectionTest(e.target.checked)}
                  style={{ accentColor: '#C8102E' }}
                />
                Test section — auto-enable “try as student” for you so assigned challenges appear on your Challenges page
              </label>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                <input
                  value={newSectionName}
                  onChange={e => setNewSectionName(e.target.value)}
                  placeholder="e.g. CS 2500 · Fall 2026"
                  style={{
                    flex: '1 1 220px',
                    minWidth: '200px',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: '1.5px solid #E7E0D8',
                    fontSize: '14px',
                  }}
                />
                <button
                  type="button"
                  onClick={createSection}
                  disabled={creatingSection}
                  style={{
                    background: creatingSection ? '#E7E0D8' : '#16120E',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '8px',
                    padding: '10px 18px',
                    fontSize: '13px',
                    fontWeight: 600,
                    cursor: creatingSection ? 'default' : 'pointer',
                  }}
                >
                  {creatingSection ? 'Creating…' : 'Create section'}
                </button>
              </div>
              {createSectionMsg && (
                <div style={{ marginTop: '12px', fontSize: '13px', color: createSectionMsg.startsWith('Created') ? '#15803D' : '#C8102E' }}>
                  {createSectionMsg}
                </div>
              )}
              {createdJoinCode && (
                <div style={{ marginTop: '12px', padding: '12px 14px', background: '#F7F3EE', borderRadius: '10px', border: '1.5px solid #E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', marginBottom: '4px' }}>Student join code</div>
                  <div style={{ fontSize: '18px', fontWeight: 700, letterSpacing: '0.12em', color: '#16120E' }}>{createdJoinCode}</div>
                </div>
              )}
              {instructingClassrooms.length > 0 && (
                <div style={{ marginTop: '18px', paddingTop: '14px', borderTop: '1px solid #F7F3EE' }}>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#16120E', marginBottom: '10px' }}>Sections you manage</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {instructingClassrooms.map(c => (
                      <div
                        key={c.id}
                        style={{
                          padding: '12px 14px',
                          background: '#F7F3EE',
                          borderRadius: '10px',
                          border: '1.5px solid #E7E0D8',
                        }}
                      >
                        <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E', marginBottom: '6px' }}>
                          {c.name}
                          {c.is_test_section ? (
                            <span style={{
                              marginLeft: '8px',
                              fontSize: '10px',
                              fontWeight: 700,
                              textTransform: 'uppercase',
                              letterSpacing: '0.04em',
                              padding: '2px 8px',
                              borderRadius: '20px',
                              background: '#FEF9EC',
                              color: '#D97706',
                              verticalAlign: 'middle',
                            }}>
                              Test section
                            </span>
                          ) : null}
                        </div>
                        {c.join_code && (
                          <div style={{ marginBottom: '8px' }}>
                            <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', marginBottom: '2px' }}>Student join code</div>
                            <div style={{ fontSize: '16px', fontWeight: 700, letterSpacing: '0.1em', color: '#16120E' }}>{c.join_code}</div>
                          </div>
                        )}
                        <label
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            cursor: listedSaving ? 'default' : 'pointer',
                            fontSize: '12px',
                            color: '#4A4440',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={!!c.listed_in_directory}
                            disabled={listedSaving}
                            onChange={e => updateListedInDirectory(c.id, e.target.checked)}
                            style={{ width: '15px', height: '15px', accentColor: '#C8102E' }}
                          />
                          <span>List on <strong style={{ color: '#16120E' }}>Browse sections</strong> (name + member count only)</span>
                        </label>
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(`${pathPrefix}/instructor`)}
                    style={{
                      marginTop: '12px',
                      background: 'transparent',
                      border: '1.5px solid #C8102E',
                      color: '#C8102E',
                      borderRadius: '8px',
                      padding: '8px 14px',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    Open instructor dashboard
                  </button>
                </div>
              )}
            </div>
          )}

          {loadErr && (
            <div className="text-sm text-red-700 mb-4">{loadErr}</div>
          )}

          {roleTab === 'student' && (
            <>
          {loading ? (
            <div style={{ fontSize: '14px', color: '#9A948E' }}>Loading…</div>
          ) : !studentPrimary ? (
            <div
              className="bg-[#FDFCFB] rounded-[14px] p-8"
              style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '640px' }}
            >
              <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E', marginBottom: '8px' }}>
                You’re not enrolled as a student yet
              </div>
              <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6, marginBottom: '16px' }}>
                Use <strong>Join as student</strong> above with your instructor’s code, or browse listed sections. Creating a section (instructor) does not enroll you as a student.
              </p>
              <button
                type="button"
                onClick={() => navigate(`${pathPrefix}/challenges`)}
                style={{
                  background: 'transparent',
                  border: '1.5px solid #E7E0D8',
                  borderRadius: '8px',
                  padding: '8px 16px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#16120E',
                  cursor: 'pointer',
                }}
              >
                Browse challenges
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', maxWidth: '900px' }}>
              <div
                className="bg-[#FDFCFB] rounded-[14px] p-6"
                style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
              >
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
                  Your section
                </div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '26px', color: '#16120E', marginBottom: '12px' }}>
                  {studentPrimary.name}
                </div>
                <div style={{ fontSize: '13px', color: '#4A4440', marginBottom: '6px' }}>
                  Role: <strong style={{ color: '#16120E' }}>{studentPrimary.role}</strong>
                </div>
                {summary && (
                  <div style={{ fontSize: '13px', color: '#4A4440', marginBottom: '6px' }}>
                    Members: <strong style={{ color: '#16120E' }}>{summary.member_count}</strong>
                  </div>
                )}
              </div>
              <div
                className="bg-[#FDFCFB] rounded-[14px] p-6 flex flex-col justify-between"
                style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
              >
                <div>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
                    Class activity
                  </div>
                  <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6 }}>
                    Cohort comparisons and live leaderboards will show here as more students complete scored sessions.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => navigate(`${pathPrefix}/workspace`)}
                  style={{
                    marginTop: '16px',
                    background: '#C8102E',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '10px',
                    padding: '12px',
                    fontSize: '13px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Open workspace
                </button>
              </div>
            </div>
          )}

          {classrooms.filter(c => c.role === 'student').length > 1 && (
            <div style={{ marginTop: '20px', fontSize: '13px', color: '#9A948E' }}>
              You’re a student in {classrooms.filter(c => c.role === 'student').length} sections; showing <strong style={{ color: '#4A4440' }}>{studentPrimary.name}</strong>. Switching sections can be added in a future update.
            </div>
          )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
