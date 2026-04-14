import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

const STUDENTS = [
  { initials: 'AJ', name: 'Alex Johnson',   score: 7.4, trend: '+0.6', sessions: 12, bar: 74, trendUp: true },
  { initials: 'MP', name: 'Maya Patel',      score: 7.1, trend: '+0.3', sessions: 10, bar: 71, trendUp: true },
  { initials: 'LW', name: 'Liam Wang',       score: 6.8, trend: '−0.1', sessions: 9,  bar: 68, trendUp: false },
  { initials: 'SC', name: 'Sofia Chen',      score: 6.5, trend: '+0.2', sessions: 11, bar: 65, trendUp: true },
  { initials: 'BT', name: 'Ben Torres',      score: 6.2, trend: '−0.4', sessions: 7,  bar: 62, trendUp: false },
  { initials: 'RK', name: 'Rina Kobayashi',  score: 5.9, trend: '+0.1', sessions: 8,  bar: 59, trendUp: true },
]

const CHALLENGES = [
  { title: 'Design a Public Awareness Campaign', status: 'Active',     statusColor: '#C8102E',  statusBg: '#FDE8EC',  week: 'Week 4' },
  { title: 'Social Media & Mental Health',       status: 'Completed',  statusColor: '#16A34A',  statusBg: '#DCFCE7',  week: 'Week 3' },
  { title: 'AI in Healthcare',                   status: 'Completed',  statusColor: '#16A34A',  statusBg: '#DCFCE7',  week: 'Week 2' },
  { title: 'Climate Communication',              status: 'Draft',      statusColor: '#9A948E',  statusBg: '#F7F3EE',  week: 'Week 5' },
]

function DualBar({ label, yourPct, partnerPct, yourColor, partnerColor }) {
  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
        <span style={{ fontSize: '12px', color: '#9A948E', fontWeight: 500 }}>{label}</span>
        <div style={{ display: 'flex', gap: '10px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: yourColor }}>{yourPct}%</span>
          <span style={{ fontSize: '12px', fontWeight: 700, color: partnerColor }}>{partnerPct}%</span>
        </div>
      </div>
      <div style={{ height: '7px', background: '#2A2520', borderRadius: '999px', overflow: 'hidden', display: 'flex' }}>
        <div style={{ width: `${yourPct}%`, height: '100%', background: yourColor, transition: 'width 0.5s ease' }} />
        <div style={{ width: `${Math.max(0, partnerPct - yourPct)}%`, height: '100%', background: partnerColor, opacity: 0.5, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

function challengeBadge(c) {
  const active = c.is_active
  return {
    label: active ? 'Published' : 'Draft',
    color: active ? '#15803D' : '#9A948E',
    bg: active ? '#DCFCE7' : '#F7F3EE',
    week: c.week != null ? `Week ${c.week}` : 'No week set',
  }
}

function formatActivityTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

function initialsFromName(name) {
  const s = (name && String(name).trim()) || ''
  if (!s) return '?'
  const parts = s.split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  return s.slice(0, 2).toUpperCase()
}

export default function Instructor() {
  const navigate = useNavigate()
  const location = useLocation()
  const isDemo = location.pathname.startsWith('/demo')
  const pathPrefix = isDemo ? '/demo' : ''

  const [sections, setSections] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [challenges, setChallenges] = useState([])
  const [sectionsLoading, setSectionsLoading] = useState(!isDemo)
  const [challengesLoading, setChallengesLoading] = useState(false)
  const [sectionsErr, setSectionsErr] = useState('')
  const [challengesErr, setChallengesErr] = useState('')
  const [createTitle, setCreateTitle] = useState('')
  const [createDesc, setCreateDesc] = useState('')
  const [createCategory, setCreateCategory] = useState('General')
  const [createDifficulty, setCreateDifficulty] = useState('Beginner')
  const [createWeek, setCreateWeek] = useState('')
  const [createTotalSessions, setCreateTotalSessions] = useState(3)
  const [createMsg, setCreateMsg] = useState('')
  const [creating, setCreating] = useState(false)
  const [creatingDraft, setCreatingDraft] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [testToggleSaving, setTestToggleSaving] = useState(false)
  const [renamingSection, setRenamingSection] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [renameMsg, setRenameMsg] = useState('')
  const [renameSaving, setRenameSaving] = useState(false)
  const [reordering, setReordering] = useState(false)
  const [analytics, setAnalytics] = useState(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  const [analyticsErr, setAnalyticsErr] = useState('')
  const [roster, setRoster] = useState([])
  const [rosterLoading, setRosterLoading] = useState(false)
  const [rosterErr, setRosterErr] = useState('')
  const [drillUserId, setDrillUserId] = useState(null)
  const [drillData, setDrillData] = useState(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillErr, setDrillErr] = useState('')

  const handleLogout = () => {
    if (isDemo) {
      navigate('/', { replace: true })
      return
    }
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  const loadSections = useCallback(async () => {
    if (isDemo) return
    const token = localStorage.getItem('token')
    if (!token) {
      setSectionsLoading(false)
      navigate('/login')
      return
    }
    setSectionsErr('')
    setSectionsLoading(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/me`, { headers: { ...authHeaders() } })
      const data = await r.json().catch(() => [])
      if (!r.ok) {
        setSectionsErr(typeof data.detail === 'string' ? data.detail : 'Could not load sections')
        setSections([])
        return
      }
      const inst = (Array.isArray(data) ? data : []).filter(c => c.role === 'instructor' || c.role === 'admin')
      setSections(inst)
      setSelectedId(prev => {
        if (prev && inst.some(x => x.id === prev)) return prev
        return inst[0]?.id || ''
      })
    } catch {
      setSectionsErr('Network error')
      setSections([])
    } finally {
      setSectionsLoading(false)
    }
  }, [isDemo, navigate])

  useEffect(() => {
    loadSections()
  }, [loadSections])

  const loadAnalytics = useCallback(async () => {
    if (isDemo || !selectedId) {
      setAnalytics(null)
      setAnalyticsErr('')
      return
    }
    setAnalyticsErr('')
    setAnalyticsLoading(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}/analytics`, { headers: { ...authHeaders() } })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        setAnalyticsErr(formatApiErrorDetail(data.detail))
        setAnalytics(null)
        return
      }
      setAnalytics(data)
    } catch {
      setAnalyticsErr('Network error')
      setAnalytics(null)
    } finally {
      setAnalyticsLoading(false)
    }
  }, [isDemo, selectedId])

  useEffect(() => {
    if (isDemo || !selectedId) {
      setAnalytics(null)
      setAnalyticsErr('')
      return
    }
    loadAnalytics()
  }, [isDemo, selectedId, challenges.length, loadAnalytics])

  const loadRoster = useCallback(async () => {
    if (isDemo || !selectedId) {
      setRoster([])
      setRosterErr('')
      return
    }
    setRosterErr('')
    setRosterLoading(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}/roster`, { headers: { ...authHeaders() } })
      const data = await r.json().catch(() => [])
      if (!r.ok) {
        setRosterErr(formatApiErrorDetail(data.detail))
        setRoster([])
        return
      }
      setRoster(Array.isArray(data) ? data : [])
    } catch {
      setRosterErr('Network error')
      setRoster([])
    } finally {
      setRosterLoading(false)
    }
  }, [isDemo, selectedId])

  useEffect(() => {
    loadRoster()
  }, [loadRoster])

  useEffect(() => {
    setDrillUserId(null)
    setDrillData(null)
    setDrillErr('')
  }, [selectedId])

  const openStudentDrilldown = async (userId) => {
    if (!selectedId || !userId) return
    setDrillUserId(userId)
    setDrillData(null)
    setDrillErr('')
    setDrillLoading(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}/students/${userId}/activity`, {
        headers: { ...authHeaders() },
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        setDrillErr(formatApiErrorDetail(data.detail))
        return
      }
      setDrillData(data)
    } catch {
      setDrillErr('Network error')
    } finally {
      setDrillLoading(false)
    }
  }

  const closeStudentDrilldown = () => {
    setDrillUserId(null)
    setDrillData(null)
    setDrillErr('')
  }

  const loadChallenges = useCallback(async () => {
    if (isDemo || !selectedId) {
      setChallenges([])
      return
    }
    setChallengesErr('')
    setChallengesLoading(true)
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}/challenges`, { headers: { ...authHeaders() } })
      const data = await r.json().catch(() => [])
      if (!r.ok) {
        setChallengesErr(typeof data.detail === 'string' ? data.detail : 'Could not load challenges')
        setChallenges([])
        return
      }
      setChallenges(Array.isArray(data) ? data : [])
    } catch {
      setChallengesErr('Network error')
      setChallenges([])
    } finally {
      setChallengesLoading(false)
    }
  }, [isDemo, selectedId])

  useEffect(() => {
    loadChallenges()
  }, [loadChallenges])

  useEffect(() => {
    setActionMsg('')
    setEditingId(null)
  }, [selectedId])

  const setTestAsStudent = async (enabled) => {
    if (!selectedId) return
    setTestToggleSaving(true)
    setActionMsg('')
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}/test-as-student`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ enabled }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setActionMsg(typeof d.detail === 'string' ? d.detail : 'Could not update test mode')
        return
      }
      setActionMsg(
        enabled
          ? 'This section’s challenges now appear on your Challenges page — open Challenges to try them like a student.'
          : 'Test-as-student mode off for this section.',
      )
      await loadSections()
    } catch {
      setActionMsg('Network error')
    } finally {
      setTestToggleSaving(false)
    }
  }

  const renameSection = async () => {
    const name = renameValue.trim()
    if (!name) { setRenameMsg('Name cannot be empty'); return }
    if (!selectedId) return
    setRenameSaving(true)
    setRenameMsg('')
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setRenameMsg(typeof d.detail === 'string' ? d.detail : 'Could not rename'); return }
      setRenamingSection(false)
      setRenameMsg('')
      await loadSections()
    } catch { setRenameMsg('Network error') }
    finally { setRenameSaving(false) }
  }

  const reorderChallenge = async (fromIdx, toIdx) => {
    if (!selectedId || fromIdx === toIdx || fromIdx < 0 || toIdx < 0 || toIdx >= challenges.length) return
    const arr = [...challenges]
    const [removed] = arr.splice(fromIdx, 1)
    arr.splice(toIdx, 0, removed)
    const ids = arr.map(c => c.id)
    setReordering(true)
    setActionMsg('')
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}/challenges/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ ordered_challenge_ids: ids }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setActionMsg(typeof d.detail === 'string' ? d.detail : 'Could not reorder')
        return
      }
      await loadChallenges()
    } catch {
      setActionMsg('Network error')
    } finally {
      setReordering(false)
    }
  }

  const saveChallengeEdit = async (challengeId) => {
    const title = editTitle.trim()
    const description = editDesc.trim()
    if (!title || !description) {
      setActionMsg('Title and description are required')
      return
    }
    setActionMsg('')
    try {
      const r = await fetch(`${API_URL}/challenges/${challengeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ title, description }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setActionMsg(typeof d.detail === 'string' ? d.detail : 'Could not save')
        return
      }
      setEditingId(null)
      await loadChallenges()
    } catch {
      setActionMsg('Network error')
    }
  }

  const setChallengeActive = async (challengeId, isActive) => {
    setActionMsg('')
    try {
      const r = await fetch(`${API_URL}/challenges/${challengeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_active: isActive }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setActionMsg(typeof d.detail === 'string' ? d.detail : 'Could not update status')
        return
      }
      await loadChallenges()
    } catch {
      setActionMsg('Network error')
    }
  }

  const unlinkChallenge = async (challengeId) => {
    if (!selectedId) return
    if (!window.confirm('Remove this challenge from this section? The challenge itself is not deleted.')) return
    setActionMsg('')
    try {
      const r = await fetch(`${API_URL}/classrooms/${selectedId}/challenges/${challengeId}`, {
        method: 'DELETE',
        headers: { ...authHeaders() },
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setActionMsg(typeof d.detail === 'string' ? d.detail : 'Could not remove assignment')
        return
      }
      if (editingId === challengeId) setEditingId(null)
      await loadChallenges()
    } catch {
      setActionMsg('Network error')
    }
  }

  const createChallenge = async (publish = true) => {
    if (!selectedId) {
      setCreateMsg('Select a section first')
      return
    }
    const title = createTitle.trim()
    const description = createDesc.trim()
    if (!title || !description) {
      setCreateMsg('Title and description are required')
      return
    }
    let weekNum = null
    if (createWeek.trim() !== '') {
      const n = parseInt(createWeek, 10)
      if (Number.isNaN(n)) {
        setCreateMsg('Week must be a number')
        return
      }
      weekNum = n
    }
    setCreateMsg('')
    if (publish) setCreating(true)
    else setCreatingDraft(true)
    try {
      const r = await fetch(`${API_URL}/challenges`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          classroom_id: selectedId,
          title,
          description,
          category: createCategory.trim() || 'General',
          difficulty: createDifficulty,
          week: weekNum,
          total_sessions: createTotalSessions,
          is_active: publish,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setCreateMsg(typeof d.detail === 'string' ? d.detail : 'Could not create challenge')
        return
      }
      setCreateMsg(publish
        ? 'Challenge published — students can see it now.'
        : 'Draft saved. Use Publish to make it visible to students.')
      setCreateTitle('')
      setCreateDesc('')
      setCreateWeek('')
      await loadChallenges()
    } catch {
      setCreateMsg('Network error')
    } finally {
      setCreating(false)
      setCreatingDraft(false)
    }
  }

  const selectedSection = sections.find(s => s.id === selectedId)

  const inputStyle = {
    width: '100%',
    padding: '10px 12px',
    borderRadius: '8px',
    border: '1.5px solid #E7E0D8',
    fontSize: '14px',
    background: '#fff',
  }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Instructor Dashboard</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{
              fontSize: '11px',
              fontWeight: 700,
              padding: '3px 10px',
              borderRadius: '20px',
              background: '#DCFCE7',
              color: '#16A34A',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}>
              Instructor view
            </span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8">
          {isDemo ? (
            <>
              <div style={{
                background: '#16120E',
                borderRadius: '16px',
                padding: '24px 28px',
                marginBottom: '24px',
              }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
                  Currently active · Week 4 of 12
                </div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#fff', marginBottom: '20px' }}>
                  Week 4 Challenge — Public Awareness Campaign
                </div>
                <div style={{ display: 'flex', gap: '24px' }}>
                  {[
                    { value: '28', label: 'students enrolled' },
                    { value: '6.8', label: 'class avg PEI' },
                    { value: '3', label: 'challenges this week' },
                  ].map((stat, i) => (
                    <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                      <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '28px', color: '#fff', lineHeight: 1 }}>{stat.value}</div>
                      <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>{stat.label}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
                <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>
                    Student performance
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                    {STUDENTS.map((s, i) => (
                      <div key={i} style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '12px',
                        padding: '10px 0',
                        borderBottom: i < STUDENTS.length - 1 ? '1px solid #F7F3EE' : 'none',
                      }}>
                        <div style={{
                          width: '32px',
                          height: '32px',
                          borderRadius: '50%',
                          background: '#C8102E',
                          color: '#fff',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '11px',
                          fontWeight: 700,
                          flexShrink: 0,
                        }}>
                          {s.initials}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: '13px', fontWeight: 500, color: '#16120E', marginBottom: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {s.name}
                          </div>
                          <div style={{ height: '5px', background: '#F7F3EE', borderRadius: '999px', overflow: 'hidden' }}>
                            <div style={{
                              width: `${s.bar}%`,
                              height: '100%',
                              borderRadius: '999px',
                              background: s.bar >= 70 ? '#0D9488' : s.bar >= 60 ? '#F97316' : '#C8102E',
                              transition: 'width 0.5s ease',
                            }} />
                          </div>
                        </div>
                        <div style={{ textAlign: 'right', flexShrink: 0 }}>
                          <div style={{ fontSize: '13px', fontWeight: 700, color: '#16120E' }}>{s.score}</div>
                          <div style={{ fontSize: '11px', color: s.trendUp ? '#16A34A' : '#C8102E', fontWeight: 600 }}>{s.trend}</div>
                        </div>
                        <div style={{ fontSize: '11px', color: '#9A948E', flexShrink: 0, width: '30px', textAlign: 'right' }}>
                          {s.sessions}×
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

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
                    padding: '14px 18px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff' }}>
                      Live comparison — Week 4
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#16A34A' }} />
                      <span style={{ fontSize: '11px', fontWeight: 600, color: '#16A34A' }}>Live</span>
                    </div>
                  </div>

                  <div style={{ padding: '18px' }}>
                    <div style={{ display: 'flex', gap: '0', marginBottom: '20px' }}>
                      <div style={{ flex: 1, textAlign: 'center' }}>
                        <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>Your class</div>
                        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '30px', color: '#F97316', lineHeight: 1 }}>6.8</div>
                      </div>
                      <div style={{ padding: '0 16px', display: 'flex', alignItems: 'center' }}>
                        <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E' }}>VS</div>
                      </div>
                      <div style={{ flex: 1, textAlign: 'center' }}>
                        <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>Partner class</div>
                        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '30px', color: '#16A34A', lineHeight: 1 }}>7.1</div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '14px', marginBottom: '10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div style={{ width: '8px', height: '3px', borderRadius: '2px', background: '#F97316' }} />
                        <span style={{ fontSize: '10px', color: '#9A948E' }}>Your class</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div style={{ width: '8px', height: '3px', borderRadius: '2px', background: '#16A34A' }} />
                        <span style={{ fontSize: '10px', color: '#9A948E' }}>Partner</span>
                      </div>
                    </div>

                    <DualBar label="Specificity"  yourPct={72} partnerPct={78} yourColor="#F97316" partnerColor="#16A34A" />
                    <DualBar label="Iteration"    yourPct={60} partnerPct={74} yourColor="#F97316" partnerColor="#16A34A" />
                    <DualBar label="Refinement"   yourPct={55} partnerPct={68} yourColor="#F97316" partnerColor="#16A34A" />

                    <div style={{
                      marginTop: '14px',
                      background: '#FEF9EC',
                      border: '1.5px solid #FDE68A',
                      borderRadius: '10px',
                      padding: '10px 12px',
                      display: 'flex',
                      gap: '7px',
                      alignItems: 'flex-start',
                    }}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                        <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
                      </svg>
                      <div style={{ fontSize: '12px', color: '#92400E', lineHeight: 1.6 }}>
                        Your class trails by 0.3 pts. Refinement has the largest gap.
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px' }}>
                    Manage challenges
                  </div>
                  <button type="button" style={{
                    background: '#C8102E',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '8px',
                    padding: '6px 14px',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                  }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                    New challenge
                  </button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                  {CHALLENGES.map((c, i) => (
                    <div key={i} style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '14px',
                      padding: '13px 0',
                      borderBottom: i < CHALLENGES.length - 1 ? '1px solid #F7F3EE' : 'none',
                    }}>
                      <div style={{
                        width: '34px',
                        height: '34px',
                        borderRadius: '9px',
                        background: '#F7F3EE',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                      }}>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                        </svg>
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E' }}>{c.title}</div>
                        <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>{c.week}</div>
                      </div>
                      <span style={{
                        fontSize: '11px',
                        fontWeight: 700,
                        padding: '3px 10px',
                        borderRadius: '20px',
                        background: c.statusBg,
                        color: c.statusColor,
                      }}>
                        {c.status}
                      </span>
                      <button type="button" style={{
                        padding: '5px 12px',
                        borderRadius: '7px',
                        border: '1.5px solid #E7E0D8',
                        background: 'transparent',
                        color: '#4A4440',
                        fontSize: '12px',
                        fontWeight: 500,
                        cursor: 'pointer',
                      }}>
                        Edit
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <>
              {sectionsErr && (
                <div className="text-sm text-red-700 mb-4">{sectionsErr}</div>
              )}
              {sectionsLoading ? (
                <div style={{ fontSize: '14px', color: '#9A948E', marginBottom: '24px' }}>Loading sections…</div>
              ) : sections.length === 0 ? (
                <div
                  className="bg-[#FDFCFB] rounded-[14px] p-8 mb-6"
                  style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '560px' }}
                >
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E', marginBottom: '8px' }}>
                    No section to manage
                  </div>
                  <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6, marginBottom: '16px' }}>
                    Create a section under Classroom → <strong>I’m an instructor</strong>, then return here to assign challenges.
                  </p>
                  <button
                    type="button"
                    onClick={() => navigate('/classroom')}
                    style={{
                      background: '#C8102E',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '8px',
                      padding: '10px 18px',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    Go to Classroom
                  </button>
                </div>
              ) : (
                <>
                  <div style={{
                    background: '#16120E',
                    borderRadius: '16px',
                    padding: '24px 28px',
                    marginBottom: '24px',
                  }}>
                    <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '10px' }}>
                      Section you’re managing
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', alignItems: 'center', marginBottom: '16px' }}>
                      <select
                        value={selectedId}
                        onChange={e => setSelectedId(e.target.value)}
                        style={{
                          minWidth: '240px',
                          padding: '10px 14px',
                          borderRadius: '8px',
                          border: '1.5px solid rgba(255,255,255,0.25)',
                          background: 'rgba(255,255,255,0.08)',
                          color: '#fff',
                          fontSize: '14px',
                          fontWeight: 600,
                        }}
                      >
                        {sections.map(s => (
                          <option key={s.id} value={s.id} style={{ color: '#16120E' }}>{s.name}</option>
                        ))}
                      </select>
                      {!renamingSection ? (
                        <button
                          onClick={() => { setRenameValue(selectedSection?.name || ''); setRenamingSection(true); setRenameMsg('') }}
                          style={{ padding: '8px 14px', borderRadius: '8px', border: '1.5px solid rgba(255,255,255,0.2)', background: 'transparent', color: 'rgba(255,255,255,0.7)', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}
                        >
                          Rename
                        </button>
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                          <input
                            value={renameValue}
                            onChange={e => setRenameValue(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') renameSection(); if (e.key === 'Escape') setRenamingSection(false) }}
                            autoFocus
                            style={{ padding: '8px 12px', borderRadius: '8px', border: '1.5px solid rgba(255,255,255,0.3)', background: 'rgba(255,255,255,0.1)', color: '#fff', fontSize: '14px', minWidth: '200px' }}
                          />
                          <button
                            onClick={renameSection}
                            disabled={renameSaving}
                            style={{ padding: '8px 14px', borderRadius: '8px', border: 'none', background: '#C8102E', color: '#fff', fontSize: '12px', fontWeight: 600, cursor: 'pointer', opacity: renameSaving ? 0.6 : 1 }}
                          >
                            {renameSaving ? 'Saving…' : 'Save'}
                          </button>
                          <button
                            onClick={() => setRenamingSection(false)}
                            style={{ padding: '8px 14px', borderRadius: '8px', border: '1.5px solid rgba(255,255,255,0.2)', background: 'transparent', color: 'rgba(255,255,255,0.7)', fontSize: '12px', cursor: 'pointer' }}
                          >
                            Cancel
                          </button>
                          {renameMsg && <span style={{ fontSize: '12px', color: '#FCA5A5' }}>{renameMsg}</span>}
                        </div>
                      )}
                    </div>
                    {selectedSection?.join_code && (
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ fontSize: '11px', fontWeight: 700, color: 'rgba(255,255,255,0.45)', marginBottom: '4px' }}>Student join code</div>
                        <div style={{ fontSize: '20px', fontWeight: 700, letterSpacing: '0.12em', color: '#fff' }}>{selectedSection.join_code}</div>
                      </div>
                    )}
                    {selectedSection?.is_test_section && (
                      <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', marginBottom: '12px', maxWidth: '520px', lineHeight: 1.5 }}>
                        This is a <strong style={{ color: 'rgba(255,255,255,0.85)' }}>test section</strong>: you were auto-enrolled to preview challenges on your student Challenges list. You can still turn that off below.
                      </div>
                    )}
                    <label style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '10px',
                      cursor: testToggleSaving ? 'default' : 'pointer',
                      marginBottom: '16px',
                      maxWidth: '520px',
                    }}
                    >
                      <input
                        type="checkbox"
                        checked={Boolean(selectedSection?.test_as_student_enabled)}
                        disabled={testToggleSaving}
                        onChange={e => setTestAsStudent(e.target.checked)}
                        style={{ accentColor: '#C8102E', marginTop: '3px', flexShrink: 0 }}
                      />
                      <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.88)', lineHeight: 1.5 }}>
                        <strong style={{ color: '#fff' }}>Test as student</strong> — show this section’s assigned challenges on my <strong style={{ color: '#fff' }}>Challenges</strong> page so I can run through them after posting (same flow as students).
                      </span>
                    </label>
                    <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '28px', color: '#fff', lineHeight: 1 }}>{challengesLoading ? '…' : challenges.filter(c => c.is_active).length}</div>
                        <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>published</div>
                      </div>
                      {!challengesLoading && challenges.filter(c => !c.is_active).length > 0 && (
                        <div>
                          <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '28px', color: 'rgba(255,255,255,0.45)', lineHeight: 1 }}>{challenges.filter(c => !c.is_active).length}</div>
                          <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.35)' }}>draft</div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div
                    className="bg-[#FDFCFB] rounded-[14px] p-6 mb-6"
                    style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '800px' }}
                  >
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>
                      Section activity
                    </div>
                    {analyticsErr && (
                      <div className="text-sm text-red-700 mb-3">{analyticsErr}</div>
                    )}
                    {analyticsLoading && !analytics ? (
                      <div style={{ fontSize: '13px', color: '#9A948E' }}>Loading activity…</div>
                    ) : analytics ? (
                      <>
                        <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                          Assigned challenges
                        </div>
                        <div
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))',
                            gap: '10px',
                            marginBottom: '16px',
                          }}
                        >
                          {[
                            { k: 'Students', v: analytics.student_count, sub: 'enrolled' },
                            { k: 'Active', v: analytics.students_with_activity, sub: '≥1 challenge session' },
                            { k: 'Idle', v: analytics.students_idle_count ?? Math.max(0, analytics.student_count - analytics.students_with_activity), sub: 'no session yet' },
                            { k: 'Started', v: analytics.sessions_started, sub: 'session rows' },
                            { k: 'Completed', v: analytics.sessions_completed, sub: 'session rows' },
                            {
                              k: 'Avg PEI',
                              v: analytics.avg_best_pei != null ? Number(analytics.avg_best_pei).toFixed(1) : '—',
                              sub: 'challenge sessions',
                            },
                          ].map(({ k, v, sub }) => (
                            <div
                              key={k}
                              style={{
                                background: '#F7F3EE',
                                borderRadius: '10px',
                                padding: '10px 8px',
                                border: '1px solid #E7E0D8',
                                textAlign: 'center',
                              }}
                            >
                              <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '24px', color: '#16120E', lineHeight: 1.1 }}>
                                {v}
                              </div>
                              <div style={{ fontSize: '10px', fontWeight: 600, color: '#4A4440', marginTop: '3px' }}>{k}</div>
                              <div style={{ fontSize: '9px', color: '#9A948E', marginTop: '2px' }}>{sub}</div>
                            </div>
                          ))}
                        </div>

                        <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                          Workspace & evals (students in this section)
                        </div>
                        <div
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))',
                            gap: '10px',
                            marginBottom: '14px',
                          }}
                        >
                          {[
                            { k: 'Chats', v: analytics.workspace_conversations ?? 0, sub: 'workspace threads' },
                            { k: 'Turns', v: analytics.workspace_turns_total ?? 0, sub: 'in those chats' },
                            { k: 'In chat', v: analytics.students_in_workspace ?? 0, sub: 'distinct students' },
                            { k: 'Scored turns', v: analytics.eval_turns_count ?? 0, sub: 'eval rows' },
                            {
                              k: 'Avg eval PEI',
                              v: analytics.avg_eval_pei != null ? Number(analytics.avg_eval_pei).toFixed(1) : '—',
                              sub: 'per scored turn',
                            },
                            { k: 'Last activity', v: formatActivityTime(analytics.last_activity_at), sub: 'any metric above' },
                          ].map(({ k, v, sub }) => (
                            <div
                              key={k}
                              style={{
                                background: '#FAFAF8',
                                borderRadius: '10px',
                                padding: '10px 8px',
                                border: '1px solid #EDE8E2',
                                textAlign: 'center',
                              }}
                            >
                              <div style={{ fontFamily: k === 'Last activity' ? 'inherit' : "'Instrument Serif', serif", fontSize: k === 'Last activity' ? '12px' : '24px', fontWeight: k === 'Last activity' ? 600 : 400, color: '#16120E', lineHeight: 1.2 }}>
                                {v}
                              </div>
                              <div style={{ fontSize: '10px', fontWeight: 600, color: '#4A4440', marginTop: '3px' }}>{k}</div>
                              <div style={{ fontSize: '9px', color: '#9A948E', marginTop: '2px' }}>{sub}</div>
                            </div>
                          ))}
                        </div>

                        {Array.isArray(analytics.by_challenge) && analytics.by_challenge.length > 0 && (
                          <div style={{ marginBottom: '10px' }}>
                            <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                              By assigned challenge
                            </div>
                            <div style={{ overflowX: 'auto', border: '1px solid #E7E0D8', borderRadius: '10px' }}>
                              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                                <thead>
                                  <tr style={{ background: '#F7F3EE', textAlign: 'left', color: '#6B6560' }}>
                                    <th style={{ padding: '8px 10px', fontWeight: 700 }}>Challenge</th>
                                    <th style={{ padding: '8px 10px', fontWeight: 700 }}>Started</th>
                                    <th style={{ padding: '8px 10px', fontWeight: 700 }}>Done</th>
                                    <th style={{ padding: '8px 10px', fontWeight: 700 }}>Avg PEI</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {analytics.by_challenge.map(row => (
                                    <tr key={row.challenge_id} style={{ borderTop: '1px solid #F0EBE5' }}>
                                      <td style={{ padding: '8px 10px', color: '#16120E', fontWeight: 500 }}>{row.title || row.challenge_id.slice(0, 8)}</td>
                                      <td style={{ padding: '8px 10px', color: '#4A4440' }}>{row.sessions_started}</td>
                                      <td style={{ padding: '8px 10px', color: '#4A4440' }}>{row.sessions_completed}</td>
                                      <td style={{ padding: '8px 10px', color: '#4A4440' }}>
                                        {row.avg_best_pei != null ? Number(row.avg_best_pei).toFixed(1) : '—'}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                        <p style={{ fontSize: '11px', color: '#9A948E', lineHeight: 1.5, margin: 0 }}>
                          {analytics.assigned_challenge_count} challenge{analytics.assigned_challenge_count !== 1 ? 's' : ''} assigned ·{' '}
                          {analytics.total_member_count} total member{analytics.total_member_count !== 1 ? 's' : ''} (instructors included)
                        </p>
                      </>
                    ) : null}
                  </div>

                  <div
                    className="bg-[#FDFCFB] rounded-[14px] p-6 mb-6"
                    style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '900px' }}
                  >
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
                      Students
                    </div>
                    <p style={{ fontSize: '12px', color: '#6B6560', lineHeight: 1.5, margin: '0 0 14px 0' }}>
                      Roster for this section. Open a student for workspace and challenge-session stats (no chat transcripts).
                    </p>
                    {rosterErr && (
                      <div className="text-sm text-red-700 mb-3">{rosterErr}</div>
                    )}
                    {rosterLoading ? (
                      <div style={{ fontSize: '13px', color: '#9A948E' }}>Loading roster…</div>
                    ) : roster.length === 0 ? (
                      <div style={{ fontSize: '13px', color: '#6B6560' }}>No students enrolled yet. Share the join code above.</div>
                    ) : (
                      <div style={{ overflowX: 'auto', border: '1px solid #E7E0D8', borderRadius: '10px' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                          <thead>
                            <tr style={{ background: '#F7F3EE', textAlign: 'left', color: '#6B6560' }}>
                              <th style={{ padding: '10px 12px', fontWeight: 700 }}>Student</th>
                              <th style={{ padding: '10px 12px', fontWeight: 700 }}>Email</th>
                              <th style={{ padding: '10px 12px', fontWeight: 700 }}>Joined</th>
                              <th style={{ padding: '10px 12px', fontWeight: 700, width: '120px' }} />
                            </tr>
                          </thead>
                          <tbody>
                            {roster.map(row => (
                              <tr key={row.user_id} style={{ borderTop: '1px solid #F0EBE5' }}>
                                <td style={{ padding: '10px 12px' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <div style={{
                                      width: '32px',
                                      height: '32px',
                                      borderRadius: '50%',
                                      background: '#C8102E',
                                      color: '#fff',
                                      display: 'flex',
                                      alignItems: 'center',
                                      justifyContent: 'center',
                                      fontSize: '11px',
                                      fontWeight: 700,
                                      flexShrink: 0,
                                    }}
                                    >
                                      {initialsFromName(row.name)}
                                    </div>
                                    <span style={{ fontWeight: 600, color: '#16120E' }}>{row.name}</span>
                                  </div>
                                </td>
                                <td style={{ padding: '10px 12px', color: '#4A4440' }}>{row.email}</td>
                                <td style={{ padding: '10px 12px', color: '#9A948E', fontSize: '12px' }}>{formatActivityTime(row.joined_at)}</td>
                                <td style={{ padding: '10px 12px' }}>
                                  <button
                                    type="button"
                                    onClick={() => openStudentDrilldown(row.user_id)}
                                    style={{
                                      padding: '6px 12px',
                                      borderRadius: '8px',
                                      border: '1.5px solid #E7E0D8',
                                      background: '#fff',
                                      color: '#C8102E',
                                      fontSize: '12px',
                                      fontWeight: 600,
                                      cursor: 'pointer',
                                    }}
                                  >
                                    View activity
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  {drillUserId && (
                    <div
                      role="dialog"
                      aria-modal="true"
                      aria-labelledby="student-drill-title"
                      style={{
                        position: 'fixed',
                        inset: 0,
                        background: 'rgba(22,18,14,0.45)',
                        zIndex: 50,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: '24px',
                      }}
                      onClick={e => { if (e.target === e.currentTarget) closeStudentDrilldown() }}
                    >
                      <div
                        className="bg-[#FDFCFB] rounded-[14px] shadow-xl max-w-[560px] w-full max-h-[90vh] overflow-y-auto"
                        style={{ border: '1.5px solid #E7E0D8' }}
                        onClick={e => e.stopPropagation()}
                      >
                        <div style={{ padding: '18px 20px', borderBottom: '1px solid #F0EBE5', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
                          <div>
                            <div id="student-drill-title" style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E' }}>
                              {drillData?.student?.name || 'Student activity'}
                            </div>
                            {drillData?.student?.email && (
                              <div style={{ fontSize: '13px', color: '#6B6560', marginTop: '4px' }}>{drillData.student.email}</div>
                            )}
                          </div>
                          <button
                            type="button"
                            onClick={closeStudentDrilldown}
                            style={{
                              border: 'none',
                              background: '#F7F3EE',
                              borderRadius: '8px',
                              width: '36px',
                              height: '36px',
                              cursor: 'pointer',
                              fontSize: '18px',
                              lineHeight: 1,
                              color: '#4A4440',
                            }}
                            aria-label="Close"
                          >
                            ×
                          </button>
                        </div>
                        <div style={{ padding: '18px 20px 22px' }}>
                          {drillLoading && (
                            <div style={{ fontSize: '14px', color: '#9A948E' }}>Loading…</div>
                          )}
                          {drillErr && (
                            <div className="text-sm text-red-700">{drillErr}</div>
                          )}
                          {!drillLoading && !drillErr && drillData && (
                            <>
                              <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                                Workspace (this section)
                              </div>
                              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: '8px', marginBottom: '18px' }}>
                                {[
                                  { k: 'Chats', v: drillData.workspace?.conversations ?? 0 },
                                  { k: 'Turns', v: drillData.workspace?.turns_total ?? 0 },
                                  { k: 'Scored turns', v: drillData.workspace?.eval_turns ?? 0 },
                                  { k: 'Avg eval PEI', v: drillData.workspace?.avg_eval_pei != null ? Number(drillData.workspace.avg_eval_pei).toFixed(1) : '—' },
                                  { k: 'Last activity', v: formatActivityTime(drillData.workspace?.last_activity_at) },
                                ].map(({ k, v }) => (
                                  <div key={k} style={{ background: '#F7F3EE', borderRadius: '8px', padding: '8px', border: '1px solid #E7E0D8', textAlign: 'center' }}>
                                    <div style={{ fontSize: k === 'Last activity' ? '11px' : '18px', fontFamily: k === 'Last activity' ? 'inherit' : "'Instrument Serif', serif", fontWeight: k === 'Last activity' ? 600 : 400, color: '#16120E' }}>{v}</div>
                                    <div style={{ fontSize: '9px', fontWeight: 600, color: '#6B6560', marginTop: '2px' }}>{k}</div>
                                  </div>
                                ))}
                              </div>
                              <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                                Assigned challenges
                              </div>
                              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: '8px', marginBottom: '16px' }}>
                                {[
                                  { k: 'Started', v: drillData.challenge_sessions?.sessions_started ?? 0 },
                                  { k: 'Completed', v: drillData.challenge_sessions?.sessions_completed ?? 0 },
                                  { k: 'Avg PEI', v: drillData.challenge_sessions?.avg_best_pei != null ? Number(drillData.challenge_sessions.avg_best_pei).toFixed(1) : '—' },
                                ].map(({ k, v }) => (
                                  <div key={k} style={{ background: '#FAFAF8', borderRadius: '8px', padding: '8px', border: '1px solid #EDE8E2', textAlign: 'center' }}>
                                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '18px', color: '#16120E' }}>{v}</div>
                                    <div style={{ fontSize: '9px', fontWeight: 600, color: '#6B6560', marginTop: '2px' }}>{k}</div>
                                  </div>
                                ))}
                              </div>
                              {Array.isArray(drillData.by_challenge) && drillData.by_challenge.length > 0 && (
                                <div style={{ marginBottom: '16px' }}>
                                  <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>By challenge</div>
                                  <div style={{ overflowX: 'auto', border: '1px solid #E7E0D8', borderRadius: '8px' }}>
                                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                                      <thead>
                                        <tr style={{ background: '#F7F3EE' }}>
                                          <th style={{ padding: '6px 8px', textAlign: 'left' }}>Challenge</th>
                                          <th style={{ padding: '6px 8px' }}>Started</th>
                                          <th style={{ padding: '6px 8px' }}>Done</th>
                                          <th style={{ padding: '6px 8px' }}>Avg PEI</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {drillData.by_challenge.map(bc => (
                                          <tr key={bc.challenge_id} style={{ borderTop: '1px solid #F0EBE5' }}>
                                            <td style={{ padding: '6px 8px' }}>{bc.title || bc.challenge_id?.slice(0, 8)}</td>
                                            <td style={{ padding: '6px 8px', textAlign: 'center' }}>{bc.sessions_started}</td>
                                            <td style={{ padding: '6px 8px', textAlign: 'center' }}>{bc.sessions_completed}</td>
                                            <td style={{ padding: '6px 8px', textAlign: 'center' }}>{bc.avg_best_pei != null ? Number(bc.avg_best_pei).toFixed(1) : '—'}</td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                </div>
                              )}
                              {Array.isArray(drillData.session_rows) && drillData.session_rows.length > 0 && (
                                <div>
                                  <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>Session rows</div>
                                  <div style={{ overflowX: 'auto', border: '1px solid #E7E0D8', borderRadius: '8px', maxHeight: '220px', overflowY: 'auto' }}>
                                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                                      <thead>
                                        <tr style={{ background: '#F7F3EE', position: 'sticky', top: 0 }}>
                                          <th style={{ padding: '6px 8px', textAlign: 'left' }}>Challenge</th>
                                          <th style={{ padding: '6px 8px' }}>S#</th>
                                          <th style={{ padding: '6px 8px' }}>Status</th>
                                          <th style={{ padding: '6px 8px' }}>PEI</th>
                                          <th style={{ padding: '6px 8px' }}>Started</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {drillData.session_rows.map((sr, idx) => (
                                          <tr key={`${sr.challenge_id}-${sr.session_number}-${idx}`} style={{ borderTop: '1px solid #F0EBE5' }}>
                                            <td style={{ padding: '6px 8px', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={sr.challenge_title}>{sr.challenge_title}</td>
                                            <td style={{ padding: '6px 8px', textAlign: 'center' }}>{sr.session_number}</td>
                                            <td style={{ padding: '6px 8px', textAlign: 'center' }}>{sr.status}</td>
                                            <td style={{ padding: '6px 8px', textAlign: 'center' }}>{sr.best_pei != null ? Number(sr.best_pei).toFixed(1) : '—'}</td>
                                            <td style={{ padding: '6px 8px', fontSize: '10px', color: '#6B6560' }}>{formatActivityTime(sr.started_at)}</td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '900px' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '16px' }}>
                      Manage challenges
                    </div>
                    {challengesErr && (
                      <div className="text-sm text-red-700 mb-3">{challengesErr}</div>
                    )}
                    {actionMsg && (
                      <div
                        style={{
                          fontSize: '13px',
                          marginBottom: '12px',
                          color:
                            actionMsg.includes('Could not') || actionMsg.includes('Network') || actionMsg.includes('required')
                              ? '#C8102E'
                              : '#15803D',
                        }}
                      >
                        {actionMsg}
                      </div>
                    )}
                    {challengesLoading ? (
                      <div style={{ fontSize: '13px', color: '#9A948E', marginBottom: '16px' }}>Loading challenges…</div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0', marginBottom: '24px' }}>
                        {challenges.length === 0 ? (
                          <div style={{ fontSize: '14px', color: '#6B6560', padding: '8px 0' }}>No challenges linked to this section yet. Create one below.</div>
                        ) : (
                          challenges.map((c, i) => {
                            const b = challengeBadge(c)
                            const isEditing = editingId === c.id
                            const btnSm = {
                              padding: '5px 10px',
                              borderRadius: '7px',
                              border: '1.5px solid #E7E0D8',
                              background: 'transparent',
                              color: '#4A4440',
                              fontSize: '11px',
                              fontWeight: 600,
                              cursor: reordering ? 'default' : 'pointer',
                            }
                            return (
                              <div
                                key={c.id}
                                style={{
                                  padding: '13px 0',
                                  borderBottom: i < challenges.length - 1 ? '1px solid #F7F3EE' : 'none',
                                }}
                              >
                                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', flexWrap: 'wrap' }}>
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flexShrink: 0 }}>
                                    <button
                                      type="button"
                                      aria-label="Move up"
                                      disabled={reordering || i === 0}
                                      onClick={() => reorderChallenge(i, i - 1)}
                                      style={{ ...btnSm, opacity: i === 0 ? 0.4 : 1 }}
                                    >
                                      ↑
                                    </button>
                                    <button
                                      type="button"
                                      aria-label="Move down"
                                      disabled={reordering || i === challenges.length - 1}
                                      onClick={() => reorderChallenge(i, i + 1)}
                                      style={{ ...btnSm, opacity: i === challenges.length - 1 ? 0.4 : 1 }}
                                    >
                                      ↓
                                    </button>
                                  </div>
                                  <div style={{
                                    width: '34px',
                                    height: '34px',
                                    borderRadius: '9px',
                                    background: '#F7F3EE',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    flexShrink: 0,
                                    marginTop: '2px',
                                  }}
                                  >
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                                    </svg>
                                  </div>
                                  <div style={{ flex: '1 1 200px', minWidth: 0 }}>
                                    {isEditing ? (
                                      <div style={{ display: 'grid', gap: '8px' }}>
                                        <input
                                          value={editTitle}
                                          onChange={e => setEditTitle(e.target.value)}
                                          style={inputStyle}
                                        />
                                        <textarea
                                          value={editDesc}
                                          onChange={e => setEditDesc(e.target.value)}
                                          rows={3}
                                          style={{ ...inputStyle, resize: 'vertical' }}
                                        />
                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                          <button
                                            type="button"
                                            onClick={() => saveChallengeEdit(c.id)}
                                            style={{ ...btnSm, background: '#16120E', color: '#fff', borderColor: '#16120E' }}
                                          >
                                            Save
                                          </button>
                                          <button
                                            type="button"
                                            onClick={() => { setEditingId(null) }}
                                            style={btnSm}
                                          >
                                            Cancel
                                          </button>
                                        </div>
                                      </div>
                                    ) : (
                                      <>
                                        <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E' }}>{c.title}</div>
                                        <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>
                                          {b.week} · {c.category} · {c.difficulty} · order {typeof c.sort_order === 'number' ? c.sort_order : i} · {c.total_sessions} session{c.total_sessions !== 1 ? 's' : ''}
                                        </div>
                                      </>
                                    )}
                                  </div>
                                  <span style={{
                                    fontSize: '11px',
                                    fontWeight: 700,
                                    padding: '3px 10px',
                                    borderRadius: '20px',
                                    background: b.bg,
                                    color: b.color,
                                    alignSelf: 'flex-start',
                                  }}>
                                    {b.label}
                                  </span>
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center', justifyContent: 'flex-end' }}>
                                    {!isEditing && (
                                      <>
                                        <button
                                          type="button"
                                          onClick={() => {
                                            setEditingId(c.id)
                                            setEditTitle(c.title)
                                            setEditDesc(c.description || '')
                                          }}
                                          style={btnSm}
                                        >
                                          Edit
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => setChallengeActive(c.id, !c.is_active)}
                                          style={c.is_active
                                            ? btnSm
                                            : { ...btnSm, background: '#16120E', color: '#fff', borderColor: '#16120E' }
                                          }
                                        >
                                          {c.is_active ? 'Unpublish' : 'Publish'}
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => unlinkChallenge(c.id)}
                                          style={{ ...btnSm, borderColor: '#F9BFCA', color: '#C8102E' }}
                                        >
                                          Remove
                                        </button>
                                      </>
                                    )}
                                    <button
                                      type="button"
                                      onClick={() => navigate(`${pathPrefix}/challenges/${c.id}`)}
                                      style={{
                                        padding: '5px 12px',
                                        borderRadius: '7px',
                                        border: '1.5px solid #C8102E',
                                        background: 'transparent',
                                        color: '#C8102E',
                                        fontSize: '12px',
                                        fontWeight: 600,
                                        cursor: 'pointer',
                                      }}
                                    >
                                      Try flow
                                    </button>
                                  </div>
                                </div>
                              </div>
                            )
                          })
                        )}
                      </div>
                    )}

                    <div style={{ paddingTop: '8px', borderTop: '1px solid #F7F3EE' }}>
                      <div style={{ fontSize: '12px', fontWeight: 600, color: '#16120E', marginBottom: '12px' }}>Create challenge for this section</div>
                      <div style={{ display: 'grid', gap: '12px', maxWidth: '640px' }}>
                        <input
                          type="text"
                          placeholder="Title"
                          value={createTitle}
                          onChange={e => setCreateTitle(e.target.value)}
                          style={inputStyle}
                        />
                        <textarea
                          placeholder="Description (what students should do)"
                          value={createDesc}
                          onChange={e => setCreateDesc(e.target.value)}
                          rows={4}
                          style={{ ...inputStyle, resize: 'vertical', minHeight: '100px' }}
                        />
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
                          <input
                            type="text"
                            placeholder="Category"
                            value={createCategory}
                            onChange={e => setCreateCategory(e.target.value)}
                            style={{ ...inputStyle, flex: '1 1 160px' }}
                          />
                          <select
                            value={createDifficulty}
                            onChange={e => setCreateDifficulty(e.target.value)}
                            style={{ ...inputStyle, flex: '0 0 160px' }}
                          >
                            <option value="Beginner">Beginner</option>
                            <option value="Intermediate">Intermediate</option>
                            <option value="Advanced">Advanced</option>
                          </select>
                          <input
                            type="number"
                            placeholder="Week (optional)"
                            value={createWeek}
                            onChange={e => setCreateWeek(e.target.value)}
                            style={{ ...inputStyle, flex: '0 0 120px' }}
                            min={1}
                          />
                          <select
                            value={createTotalSessions}
                            onChange={e => setCreateTotalSessions(Number(e.target.value))}
                            style={{ ...inputStyle, flex: '0 0 140px' }}
                          >
                            {[1, 2, 3, 4, 5, 6].map(n => (
                              <option key={n} value={n}>{n} session{n !== 1 ? 's' : ''}</option>
                            ))}
                          </select>
                        </div>
                        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            onClick={() => createChallenge(true)}
                            disabled={creating || creatingDraft}
                            style={{
                              background: creating || creatingDraft ? '#E7E0D8' : '#C8102E',
                              color: '#fff',
                              border: 'none',
                              borderRadius: '8px',
                              padding: '10px 20px',
                              fontSize: '13px',
                              fontWeight: 600,
                              cursor: creating || creatingDraft ? 'default' : 'pointer',
                            }}
                          >
                            {creating ? 'Publishing…' : 'Publish challenge'}
                          </button>
                          <button
                            type="button"
                            onClick={() => createChallenge(false)}
                            disabled={creating || creatingDraft}
                            style={{
                              background: 'transparent',
                              color: creating || creatingDraft ? '#9A948E' : '#16120E',
                              border: `1.5px solid ${creating || creatingDraft ? '#E7E0D8' : '#16120E'}`,
                              borderRadius: '8px',
                              padding: '10px 20px',
                              fontSize: '13px',
                              fontWeight: 600,
                              cursor: creating || creatingDraft ? 'default' : 'pointer',
                            }}
                          >
                            {creatingDraft ? 'Saving draft…' : 'Save as draft'}
                          </button>
                        </div>
                        {createMsg && (
                          <div style={{
                            fontSize: '13px',
                            color: createMsg.startsWith('Challenge') || createMsg.startsWith('Draft')
                              ? '#15803D'
                              : '#C8102E',
                          }}>
                            {createMsg}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
