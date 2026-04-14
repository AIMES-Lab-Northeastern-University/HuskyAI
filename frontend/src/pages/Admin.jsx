import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

// ─── helpers ────────────────────────────────────────────────────────────────

function fmt(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) }
  catch { return iso }
}

function fmtDate(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) }
  catch { return iso }
}

function initials(name) {
  const p = (name || '').trim().split(/\s+/)
  return p.length >= 2 ? (p[0][0] + p[p.length - 1][0]).toUpperCase() : (name || '?').slice(0, 2).toUpperCase()
}

const TILE = { borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }
const btnSm = {
  padding: '5px 12px', borderRadius: '7px', border: '1.5px solid #E7E0D8',
  background: 'transparent', color: '#4A4440', fontSize: '12px', fontWeight: 600, cursor: 'pointer',
}

// ─── StatTile ───────────────────────────────────────────────────────────────

function StatTile({ label, value }) {
  return (
    <div className="bg-[#FDFCFB] rounded-[12px] p-4" style={TILE}>
      <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
      <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '26px', color: '#16120E', marginTop: '4px' }}>{value ?? '—'}</div>
    </div>
  )
}

// ─── UserActivityModal ───────────────────────────────────────────────────────

function UserActivityModal({ userId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/admin/users/${userId}/activity`, { headers: { ...authHeaders() } })
        const d = await r.json().catch(() => ({}))
        if (!cancelled) {
          if (r.ok) setData(d)
          else setErr(formatApiErrorDetail(d.detail))
        }
      } catch { if (!cancelled) setErr('Network error') }
      finally { if (!cancelled) setLoading(false) }
    })()
    return () => { cancelled = true }
  }, [userId])

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(22,18,14,0.5)', zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="bg-[#FDFCFB] rounded-[16px] shadow-xl overflow-y-auto"
        style={{ ...TILE, width: '100%', maxWidth: '600px', maxHeight: '88vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* header */}
        <div style={{ padding: '18px 22px', borderBottom: '1px solid #F0EBE5', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E' }}>
              {data?.user?.name || 'User activity'}
            </div>
            {data?.user?.email && <div style={{ fontSize: '13px', color: '#6B6560', marginTop: '3px' }}>{data.user.email}</div>}
            {data?.user?.is_platform_admin && (
              <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: '#FDE8EC', color: '#C8102E', marginTop: '6px', display: 'inline-block' }}>Platform admin</span>
            )}
          </div>
          <button onClick={onClose} style={{ border: 'none', background: '#F7F3EE', borderRadius: '8px', width: '34px', height: '34px', cursor: 'pointer', fontSize: '18px', color: '#4A4440' }}>×</button>
        </div>

        <div style={{ padding: '20px 22px' }}>
          {loading && <div style={{ fontSize: '14px', color: '#9A948E' }}>Loading…</div>}
          {err && <div style={{ fontSize: '13px', color: '#C8102E' }}>{err}</div>}
          {!loading && !err && data && (
            <>
              {/* workspace */}
              <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Workspace</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '20px' }}>
                {[
                  ['Chats', data.workspace.conversations],
                  ['Turns', data.workspace.turns_total],
                  ['Scored', data.workspace.eval_count],
                  ['Avg PEI', data.workspace.avg_eval_pei != null ? data.workspace.avg_eval_pei.toFixed(1) : '—'],
                ].map(([k, v]) => (
                  <div key={k} style={{ background: '#F7F3EE', borderRadius: '8px', padding: '10px 8px', textAlign: 'center', border: '1px solid #E7E0D8' }}>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '20px', color: '#16120E' }}>{v}</div>
                    <div style={{ fontSize: '10px', fontWeight: 600, color: '#6B6560', marginTop: '2px' }}>{k}</div>
                  </div>
                ))}
              </div>

              {/* challenge sessions */}
              <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Challenge sessions</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', marginBottom: '20px' }}>
                {[
                  ['Started', data.challenge_sessions.sessions_started],
                  ['Completed', data.challenge_sessions.sessions_completed],
                  ['Avg PEI', data.challenge_sessions.avg_pei != null ? data.challenge_sessions.avg_pei.toFixed(1) : '—'],
                ].map(([k, v]) => (
                  <div key={k} style={{ background: '#FAFAF8', borderRadius: '8px', padding: '10px 8px', textAlign: 'center', border: '1px solid #EDE8E2' }}>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '20px', color: '#16120E' }}>{v}</div>
                    <div style={{ fontSize: '10px', fontWeight: 600, color: '#6B6560', marginTop: '2px' }}>{k}</div>
                  </div>
                ))}
              </div>

              {/* sections */}
              {data.sections.length > 0 && (
                <>
                  <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Sections</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '20px' }}>
                    {data.sections.map(s => (
                      <span key={s.id} style={{ fontSize: '12px', padding: '4px 10px', borderRadius: '20px', background: s.role === 'instructor' ? '#FDE8EC' : '#F7F3EE', color: s.role === 'instructor' ? '#C8102E' : '#4A4440', border: '1px solid #E7E0D8', fontWeight: 500 }}>
                        {s.name} <span style={{ opacity: 0.6 }}>· {s.role}</span>
                      </span>
                    ))}
                  </div>
                </>
              )}

              {/* recent conversations */}
              <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                Recent conversations (last 20, metadata only)
              </div>
              {data.recent_conversations.length === 0 ? (
                <p style={{ fontSize: '13px', color: '#6B6560', margin: 0 }}>No conversations yet.</p>
              ) : (
                <div style={{ border: '1px solid #E7E0D8', borderRadius: '10px', overflow: 'hidden' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                    <thead>
                      <tr style={{ background: '#F7F3EE', textAlign: 'left', color: '#6B6560' }}>
                        <th style={{ padding: '7px 10px', fontWeight: 700 }}>Started</th>
                        <th style={{ padding: '7px 10px', fontWeight: 700, textAlign: 'center' }}>Turns</th>
                        <th style={{ padding: '7px 10px', fontWeight: 700, color: '#9A948E', fontSize: '10px' }}>ID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_conversations.map(c => (
                        <tr key={c.id} style={{ borderTop: '1px solid #F0EBE5' }}>
                          <td style={{ padding: '7px 10px', color: '#16120E' }}>{fmt(c.started_at)}</td>
                          <td style={{ padding: '7px 10px', textAlign: 'center', color: '#4A4440' }}>{c.turn_count}</td>
                          <td style={{ padding: '7px 10px', color: '#9A948E', fontFamily: 'monospace', fontSize: '10px' }}>{c.id.slice(0, 8)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── ClassroomDetailModal ────────────────────────────────────────────────────

function ClassroomDetailModal({ classroomId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/admin/classrooms/${classroomId}`, { headers: { ...authHeaders() } })
        const d = await r.json().catch(() => ({}))
        if (!cancelled) {
          if (r.ok) setData(d)
          else setErr(formatApiErrorDetail(d.detail))
        }
      } catch { if (!cancelled) setErr('Network error') }
      finally { if (!cancelled) setLoading(false) }
    })()
    return () => { cancelled = true }
  }, [classroomId])

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(22,18,14,0.5)', zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="bg-[#FDFCFB] rounded-[16px] shadow-xl overflow-y-auto"
        style={{ ...TILE, width: '100%', maxWidth: '640px', maxHeight: '88vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* header */}
        <div style={{ padding: '18px 22px', borderBottom: '1px solid #F0EBE5', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E' }}>{data?.name || 'Classroom'}</div>
            {data?.join_code && (
              <div style={{ fontSize: '13px', color: '#6B6560', marginTop: '4px' }}>
                Join code: <strong style={{ letterSpacing: '0.1em', color: '#16120E' }}>{data.join_code}</strong>
                <span style={{ marginLeft: '10px', color: '#9A948E' }}>· Created {fmtDate(data.created_at)}</span>
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ border: 'none', background: '#F7F3EE', borderRadius: '8px', width: '34px', height: '34px', cursor: 'pointer', fontSize: '18px', color: '#4A4440' }}>×</button>
        </div>

        <div style={{ padding: '20px 22px' }}>
          {loading && <div style={{ fontSize: '14px', color: '#9A948E' }}>Loading…</div>}
          {err && <div style={{ fontSize: '13px', color: '#C8102E' }}>{err}</div>}
          {!loading && !err && data && (
            <>
              {/* analytics */}
              <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Analytics</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '20px' }}>
                {[
                  ['Students', data.analytics.student_count],
                  ['Started', data.analytics.sessions_started],
                  ['Completed', data.analytics.sessions_completed],
                  ['Avg PEI', data.analytics.avg_pei != null ? data.analytics.avg_pei.toFixed(1) : '—'],
                ].map(([k, v]) => (
                  <div key={k} style={{ background: '#F7F3EE', borderRadius: '8px', padding: '10px 8px', textAlign: 'center', border: '1px solid #E7E0D8' }}>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '20px', color: '#16120E' }}>{v}</div>
                    <div style={{ fontSize: '10px', fontWeight: 600, color: '#6B6560', marginTop: '2px' }}>{k}</div>
                  </div>
                ))}
              </div>

              {/* challenges */}
              {data.challenges.length > 0 && (
                <>
                  <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                    Assigned challenges ({data.challenges.length})
                  </div>
                  <div style={{ border: '1px solid #E7E0D8', borderRadius: '10px', overflow: 'hidden', marginBottom: '20px' }}>
                    {data.challenges.map((ch, i) => (
                      <div key={ch.id} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '9px 12px', borderBottom: i < data.challenges.length - 1 ? '1px solid #F0EBE5' : 'none', fontSize: '13px' }}>
                        <div style={{ flex: 1, fontWeight: 500, color: '#16120E' }}>{ch.title}</div>
                        {ch.week != null && <span style={{ fontSize: '11px', color: '#9A948E' }}>Wk {ch.week}</span>}
                        <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: ch.is_active ? '#DCFCE7' : '#F7F3EE', color: ch.is_active ? '#15803D' : '#9A948E' }}>
                          {ch.is_active ? 'Published' : 'Draft'}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* members */}
              <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                Members ({data.members.length})
              </div>
              {data.members.length === 0 ? (
                <p style={{ fontSize: '13px', color: '#6B6560', margin: 0 }}>No members yet.</p>
              ) : (
                <div style={{ border: '1px solid #E7E0D8', borderRadius: '10px', overflow: 'hidden', maxHeight: '260px', overflowY: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                    <thead>
                      <tr style={{ background: '#F7F3EE', textAlign: 'left', color: '#6B6560', position: 'sticky', top: 0 }}>
                        <th style={{ padding: '7px 10px', fontWeight: 700 }}>Name</th>
                        <th style={{ padding: '7px 10px', fontWeight: 700 }}>Email</th>
                        <th style={{ padding: '7px 10px', fontWeight: 700 }}>Role</th>
                        <th style={{ padding: '7px 10px', fontWeight: 700 }}>Joined</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.members.map(m => (
                        <tr key={m.user_id} style={{ borderTop: '1px solid #F0EBE5' }}>
                          <td style={{ padding: '7px 10px', fontWeight: 500, color: '#16120E' }}>{m.name}</td>
                          <td style={{ padding: '7px 10px', color: '#4A4440' }}>{m.email}</td>
                          <td style={{ padding: '7px 10px' }}>
                            <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 7px', borderRadius: '20px', background: m.role === 'instructor' ? '#FDE8EC' : '#F7F3EE', color: m.role === 'instructor' ? '#C8102E' : '#6B6560' }}>
                              {m.role}
                            </span>
                          </td>
                          <td style={{ padding: '7px 10px', color: '#9A948E', fontSize: '11px' }}>{fmtDate(m.joined_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main Admin component ───────────────────────────────────────────────────

export default function Admin() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('overview')

  // overview
  const [overviewData, setOverviewData] = useState(null)
  const [overviewErr, setOverviewErr] = useState('')
  const [overviewLoading, setOverviewLoading] = useState(true)

  // users tab
  const [users, setUsers] = useState([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersErr, setUsersErr] = useState('')
  const [usersLoaded, setUsersLoaded] = useState(false)
  const [userSearch, setUserSearch] = useState('')
  const [promotingId, setPromotingId] = useState(null)
  const [promoteMsg, setPromoteMsg] = useState('')

  // modals
  const [drillUserId, setDrillUserId] = useState(null)
  const [drillClassroomId, setDrillClassroomId] = useState(null)

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  // Load overview on mount
  const loadOverview = useCallback(async () => {
    setOverviewErr('')
    setOverviewLoading(true)
    try {
      const r = await fetch(`${API_URL}/admin/overview`, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (r.ok) setOverviewData(d)
      else setOverviewErr(formatApiErrorDetail(d.detail))
    } catch { setOverviewErr('Network error') }
    finally { setOverviewLoading(false) }
  }, [])

  useEffect(() => { loadOverview() }, [loadOverview])

  // Load users lazily when tab first opened
  const loadUsers = useCallback(async () => {
    setUsersErr('')
    setUsersLoading(true)
    try {
      const r = await fetch(`${API_URL}/admin/users`, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => [])
      if (r.ok) { setUsers(Array.isArray(d) ? d : []); setUsersLoaded(true) }
      else setUsersErr(formatApiErrorDetail(d.detail))
    } catch { setUsersErr('Network error') }
    finally { setUsersLoading(false) }
  }, [])

  useEffect(() => {
    if (activeTab === 'users' && !usersLoaded) loadUsers()
  }, [activeTab, usersLoaded, loadUsers])

  const toggleAdmin = async (user) => {
    if (!window.confirm(`${user.is_platform_admin ? 'Remove' : 'Grant'} platform admin for ${user.name}?`)) return
    setPromotingId(user.id)
    setPromoteMsg('')
    try {
      const r = await fetch(`${API_URL}/admin/users/${user.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_platform_admin: !user.is_platform_admin }),
      })
      const d = await r.json().catch(() => ({}))
      if (r.ok) {
        setUsers(prev => prev.map(u => u.id === user.id ? { ...u, is_platform_admin: d.is_platform_admin } : u))
        setPromoteMsg(`Updated ${user.name}`)
      } else {
        setPromoteMsg(formatApiErrorDetail(d.detail) || 'Could not update')
      }
    } catch { setPromoteMsg('Network error') }
    finally { setPromotingId(null) }
  }

  const counts = overviewData?.counts
  const ax = overviewData?.analytics
  const filteredUsers = users.filter(u =>
    !userSearch || u.name?.toLowerCase().includes(userSearch.toLowerCase()) || u.email?.toLowerCase().includes(userSearch.toLowerCase())
  )

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'users', label: 'Users' },
    { id: 'classrooms', label: 'Classrooms' },
  ]

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        {/* topbar */}
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-4 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Platform admin</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            {tabs.map(t => (
              <button
                key={t.id}
                type="button"
                onClick={() => setActiveTab(t.id)}
                style={{
                  padding: '5px 14px', borderRadius: '7px', fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                  background: activeTab === t.id ? '#16120E' : 'transparent',
                  color: activeTab === t.id ? '#fff' : '#6B6560',
                  border: activeTab === t.id ? 'none' : '1.5px solid transparent',
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8">

          {/* ── OVERVIEW TAB ── */}
          {activeTab === 'overview' && (
            <>
              {overviewErr && <div className="text-sm text-red-700 mb-4">{overviewErr}</div>}
              {overviewLoading && <div className="text-sm text-[#9A948E]">Loading…</div>}
              {!overviewLoading && counts && (
                <>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '12px' }}>Directory</div>
                  <div className="grid gap-4 mb-8" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', maxWidth: '900px' }}>
                    {[
                      ['Users', counts.users],
                      ['Sections', counts.classrooms],
                      ['Memberships', counts.memberships],
                      ['Challenges', counts.challenges],
                      ['Assignments', counts.classroom_challenge_links],
                    ].map(([label, n]) => <StatTile key={label} label={label} value={n} />)}
                  </div>
                  {ax && (
                    <>
                      <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '12px' }}>Activity</div>
                      <div className="grid gap-4 mb-8" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', maxWidth: '900px' }}>
                        {[
                          ['Conversations', ax.conversations],
                          ['Messages', ax.messages],
                          ['Eval rows', ax.eval_rows],
                          ['Avg eval PEI', ax.avg_eval_pei != null ? Number(ax.avg_eval_pei).toFixed(1) : '—'],
                          ['Student seats', ax.student_memberships],
                          ['New users (7d)', ax.users_joined_last_7_days],
                          ['Sessions started', ax.challenge_sessions_started],
                          ['Sessions done', ax.challenge_sessions_completed],
                          ['Avg session PEI', ax.avg_challenge_session_pei != null ? Number(ax.avg_challenge_session_pei).toFixed(1) : '—'],
                          ['Active sections', ax.active_classrooms],
                          ['Inactive sections', ax.inactive_classrooms],
                        ].map(([label, n]) => <StatTile key={label} label={label} value={n} />)}
                      </div>
                    </>
                  )}
                </>
              )}
            </>
          )}

          {/* ── USERS TAB ── */}
          {activeTab === 'users' && (
            <>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap' }}>
                <input
                  value={userSearch}
                  onChange={e => setUserSearch(e.target.value)}
                  placeholder="Search by name or email…"
                  style={{ padding: '8px 12px', borderRadius: '8px', border: '1.5px solid #E7E0D8', fontSize: '13px', minWidth: '260px', background: '#fff' }}
                />
                {promoteMsg && (
                  <span style={{ fontSize: '13px', color: promoteMsg.includes('error') || promoteMsg.includes('Could') ? '#C8102E' : '#15803D' }}>
                    {promoteMsg}
                  </span>
                )}
              </div>
              {usersErr && <div className="text-sm text-red-700 mb-4">{usersErr}</div>}
              {usersLoading && <div style={{ fontSize: '13px', color: '#9A948E' }}>Loading users…</div>}
              {!usersLoading && (
                <div className="bg-[#FDFCFB] rounded-[14px] overflow-hidden" style={{ ...TILE, maxWidth: '960px' }}>
                  {filteredUsers.length === 0 ? (
                    <div style={{ padding: '20px', fontSize: '13px', color: '#6B6560' }}>No users found.</div>
                  ) : (
                    <div style={{ overflowX: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                        <thead>
                          <tr style={{ background: '#F7F3EE', textAlign: 'left', color: '#6B6560' }}>
                            <th style={{ padding: '10px 14px', fontWeight: 700 }}>User</th>
                            <th style={{ padding: '10px 14px', fontWeight: 700 }}>Email</th>
                            <th style={{ padding: '10px 14px', fontWeight: 700 }}>Joined</th>
                            <th style={{ padding: '10px 14px', fontWeight: 700, textAlign: 'center' }}>Sections</th>
                            <th style={{ padding: '10px 14px', fontWeight: 700 }}>Role</th>
                            <th style={{ padding: '10px 14px', fontWeight: 700, width: '160px' }} />
                          </tr>
                        </thead>
                        <tbody>
                          {filteredUsers.map(u => (
                            <tr
                              key={u.id}
                              style={{ borderTop: '1px solid #F0EBE5', cursor: 'pointer' }}
                              onMouseEnter={e => e.currentTarget.style.background = '#FAFAF8'}
                              onMouseLeave={e => e.currentTarget.style.background = ''}
                            >
                              <td style={{ padding: '10px 14px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                  <div style={{ width: '30px', height: '30px', borderRadius: '50%', background: '#C8102E', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px', fontWeight: 700, flexShrink: 0 }}>
                                    {initials(u.name)}
                                  </div>
                                  <span style={{ fontWeight: 600, color: '#16120E' }}>{u.name}</span>
                                </div>
                              </td>
                              <td style={{ padding: '10px 14px', color: '#4A4440' }}>{u.email}</td>
                              <td style={{ padding: '10px 14px', color: '#9A948E', fontSize: '12px' }}>{fmtDate(u.created_at)}</td>
                              <td style={{ padding: '10px 14px', textAlign: 'center', color: '#4A4440' }}>{u.section_count}</td>
                              <td style={{ padding: '10px 14px' }}>
                                {u.is_platform_admin
                                  ? <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: '#FDE8EC', color: '#C8102E' }}>Admin</span>
                                  : <span style={{ fontSize: '10px', color: '#9A948E' }}>User</span>
                                }
                              </td>
                              <td style={{ padding: '10px 14px' }}>
                                <div style={{ display: 'flex', gap: '6px' }}>
                                  <button
                                    type="button"
                                    onClick={() => setDrillUserId(u.id)}
                                    style={btnSm}
                                  >
                                    View activity
                                  </button>
                                  <button
                                    type="button"
                                    disabled={promotingId === u.id}
                                    onClick={() => toggleAdmin(u)}
                                    style={{
                                      ...btnSm,
                                      color: u.is_platform_admin ? '#C8102E' : '#16120E',
                                      borderColor: u.is_platform_admin ? '#F9BFCA' : '#16120E',
                                      opacity: promotingId === u.id ? 0.5 : 1,
                                    }}
                                  >
                                    {u.is_platform_admin ? 'Remove admin' : 'Make admin'}
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {/* ── CLASSROOMS TAB ── */}
          {activeTab === 'classrooms' && (
            <>
              {overviewLoading && <div style={{ fontSize: '13px', color: '#9A948E' }}>Loading…</div>}
              {!overviewLoading && (!overviewData?.classrooms || overviewData.classrooms.length === 0) && (
                <div style={{ fontSize: '13px', color: '#6B6560' }}>No active sections found.</div>
              )}
              {!overviewLoading && overviewData?.classrooms?.length > 0 && (
                <div className="bg-[#FDFCFB] rounded-[14px] overflow-hidden" style={{ ...TILE, maxWidth: '820px' }}>
                  <div style={{ padding: '12px 18px', borderBottom: '1px solid #F7F3EE', fontSize: '12px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                    Active sections — click to drill in
                  </div>
                  {overviewData.classrooms.map((row, i) => (
                    <div
                      key={row.id}
                      onClick={() => setDrillClassroomId(row.id)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '12px',
                        padding: '13px 18px',
                        borderBottom: i < overviewData.classrooms.length - 1 ? '1px solid #F7F3EE' : 'none',
                        cursor: 'pointer', fontSize: '13px',
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = '#FAFAF8'}
                      onMouseLeave={e => e.currentTarget.style.background = ''}
                    >
                      <div style={{ flex: 1, fontWeight: 600, color: '#16120E' }}>{row.name}</div>
                      <div style={{ fontSize: '12px', color: '#9A948E' }}>{row.member_count} members</div>
                      <div style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '0.08em', color: '#4A4440' }}>{row.join_code}</div>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 18l6-6-6-6" />
                      </svg>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

        </div>
      </div>

      {/* modals */}
      {drillUserId && <UserActivityModal userId={drillUserId} onClose={() => setDrillUserId(null)} />}
      {drillClassroomId && <ClassroomDetailModal classroomId={drillClassroomId} onClose={() => setDrillClassroomId(null)} />}
    </div>
  )
}
