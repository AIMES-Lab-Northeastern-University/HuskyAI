import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

export default function Admin() {
  const navigate = useNavigate()

  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  const load = useCallback(async () => {
    setErr('')
    setLoading(true)
    try {
      const r = await fetch(`${API_URL}/admin/overview`, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setErr(formatApiErrorDetail(d.detail))
        setData(null)
        return
      }
      setData(d)
    } catch {
      setErr('Network error')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const counts = data?.counts
  const ax = data?.analytics

  const adminStatTiles = ax
    ? [
        ['Conversations', ax.conversations],
        ['Messages', ax.messages],
        ['Eval rows', ax.eval_rows],
        ['Avg eval PEI', ax.avg_eval_pei != null ? Number(ax.avg_eval_pei).toFixed(2) : '—'],
        ['Student seats', ax.student_memberships],
        ['New users (7d)', ax.users_joined_last_7_days],
        ['Sessions started', ax.challenge_sessions_started],
        ['Sessions done', ax.challenge_sessions_completed],
        ['Avg session PEI', ax.avg_challenge_session_pei != null ? Number(ax.avg_challenge_session_pei).toFixed(2) : '—'],
        ['Active sections', ax.active_classrooms],
        ['Inactive sections', ax.inactive_classrooms],
      ]
    : []

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Platform admin</span>
          <span style={{ fontSize: '12px', color: '#9A948E' }}>Cross-section overview</span>
        </div>
        <div className="flex-1 overflow-y-auto p-8">
          {err && <div className="text-sm text-red-700 mb-4">{err}</div>}
          {loading && <div className="text-sm text-[#9A948E]">Loading overview…</div>}
          {!loading && counts && (
            <>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '12px' }}>
                Directory totals
              </div>
              <div className="grid gap-4 mb-8" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', maxWidth: '960px' }}>
                {[
                  ['Users', counts.users],
                  ['Sections', counts.classrooms],
                  ['Memberships', counts.memberships],
                  ['Challenges', counts.challenges],
                  ['Assignments', counts.classroom_challenge_links],
                ].map(([label, n]) => (
                  <div
                    key={label}
                    className="bg-[#FDFCFB] rounded-[12px] p-4"
                    style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
                  >
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '28px', color: '#16120E', marginTop: '4px' }}>{n}</div>
                  </div>
                ))}
              </div>
              {adminStatTiles.length > 0 && (
                <>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '12px' }}>
                    Activity from database
                  </div>
                  <div className="grid gap-4 mb-8" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', maxWidth: '960px' }}>
                    {adminStatTiles.map(([label, n]) => (
                      <div
                        key={label}
                        className="bg-[#FDFCFB] rounded-[12px] p-4"
                        style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
                      >
                        <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
                        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '24px', color: '#16120E', marginTop: '4px' }}>{n}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
          {!loading && Array.isArray(data?.classrooms) && data.classrooms.length > 0 && (
            <div className="bg-[#FDFCFB] rounded-[14px] overflow-hidden" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8', maxWidth: '900px' }}>
              <div style={{ padding: '14px 18px', borderBottom: '1px solid #F7F3EE', fontSize: '12px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Active sections
              </div>
              <div style={{ maxHeight: '420px', overflowY: 'auto' }}>
                {data.classrooms.map(row => (
                  <div
                    key={row.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '12px 18px',
                      borderBottom: '1px solid #F7F3EE',
                      fontSize: '13px',
                    }}
                  >
                    <div style={{ flex: 1, fontWeight: 600, color: '#16120E' }}>{row.name}</div>
                    <div style={{ fontSize: '12px', color: '#9A948E' }}>{row.member_count} members</div>
                    <div style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '0.08em', color: '#4A4440' }}>{row.join_code}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
