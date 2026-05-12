import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders } from '../lib/api'

const DEMO_LIST = [
  { id: 'demo-1', name: 'Husky Test Section', member_count: 12 },
  { id: 'demo-2', name: 'CS 2500 · Fall 2026', member_count: 45 },
]

export default function ClassroomBrowse() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const isDemo = location.pathname.startsWith('/demo')
  const pathPrefix = isDemo ? '/demo' : ''

  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(!isDemo)
  const [error, setError] = useState('')
  const [query, setQuery] = useState(() => searchParams.get('q') || '')
  const [joiningId, setJoiningId] = useState('')
  const [joinedIds, setJoinedIds] = useState(() => new Set())
  const [rowMsg, setRowMsg] = useState({ id: '', text: '', kind: 'info' })

  useEffect(() => {
    if (isDemo) {
      setRows(DEMO_LIST)
      setLoading(false)
      return
    }
    const token = localStorage.getItem('token')
    if (!token) {
      navigate('/login', { replace: true })
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/classrooms/browse`, { headers: { ...authHeaders() } })
        const d = await r.json().catch(() => [])
        if (!cancelled) {
          if (!r.ok) {
            setError(typeof d.detail === 'string' ? d.detail : 'Could not load directory')
            setRows([])
          } else {
            setRows(Array.isArray(d) ? d : [])
          }
        }
      } catch {
        if (!cancelled) {
          setError('Network error')
          setRows([])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [isDemo, navigate])

  // Mark sections the user is already in so we can render "Open" instead of "Join"
  useEffect(() => {
    if (isDemo) return
    const token = localStorage.getItem('token')
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/classrooms/me`, { headers: { ...authHeaders() } })
        if (!r.ok) return
        const d = await r.json().catch(() => [])
        if (!cancelled && Array.isArray(d)) {
          setJoinedIds(new Set(d.map(c => c.id)))
        }
      } catch {
        // ignore - not fatal for browse
      }
    })()
    return () => { cancelled = true }
  }, [isDemo])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(r => r.name.toLowerCase().includes(q))
  }, [rows, query])

  const handleLogout = () => {
    if (isDemo) {
      navigate('/', { replace: true })
      return
    }
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  const joinDirect = async (row) => {
    if (isDemo) {
      navigate(`${pathPrefix}/classroom`)
      return
    }
    setRowMsg({ id: '', text: '', kind: 'info' })
    setJoiningId(row.id)
    try {
      const r = await fetch(`${API_URL}/classrooms/${row.id}/join-listed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setRowMsg({
          id: row.id,
          text: typeof d.detail === 'string' ? d.detail : 'Could not join section',
          kind: 'error',
        })
        return
      }
      setJoinedIds(prev => {
        const next = new Set(prev)
        next.add(row.id)
        return next
      })
      setRows(prev => prev.map(x =>
        x.id === row.id && d.status === 'joined'
          ? { ...x, member_count: (x.member_count || 0) + 1 }
          : x
      ))
      navigate(`${pathPrefix}/classroom`)
    } catch {
      setRowMsg({ id: row.id, text: 'Network error', kind: 'error' })
    } finally {
      setJoiningId('')
    }
  }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Browse sections</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>
              Search listed sections and join directly
            </span>
          </div>
          <div className="ml-auto">
            <button
              type="button"
              onClick={() => navigate(`${pathPrefix}/classroom`)}
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
              Join with code
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8">
          {isDemo && (
            <p style={{ fontSize: '13px', color: '#9A948E', marginBottom: '20px', maxWidth: '640px' }}>
              Demo sample list. Sign in to see real sections where the instructor enabled “Show in browse directory.”
            </p>
          )}

          <div style={{ maxWidth: '560px', marginBottom: '20px', position: 'relative' }}>
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#9A948E"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="search"
              value={query}
              onChange={e => {
                const v = e.target.value
                setQuery(v)
                const next = new URLSearchParams(searchParams)
                if (v.trim()) next.set('q', v)
                else next.delete('q')
                setSearchParams(next, { replace: true })
              }}
              autoFocus={Boolean(query)}
              placeholder="Search sections by name…"
              style={{
                width: '100%',
                padding: '10px 14px 10px 38px',
                borderRadius: '10px',
                border: '1.5px solid #E7E0D8',
                background: '#FDFCFB',
                fontSize: '14px',
                color: '#16120E',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {loading && (
            <div style={{ color: '#9A948E', fontSize: '14px' }}>Loading…</div>
          )}
          {error && (
            <div style={{ color: '#C8102E', fontSize: '14px', marginBottom: '16px' }}>{error}</div>
          )}

          {!loading && !error && rows.length === 0 && (
            <div
              className="bg-[#FDFCFB] rounded-[14px] p-8 max-w-xl"
              style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
            >
              <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#16120E', marginBottom: '8px' }}>
                No sections listed yet
              </div>
              <p style={{ fontSize: '14px', color: '#6B6560', lineHeight: 1.6, marginBottom: '12px' }}>
                When an instructor turns on listing for their section, it will appear here. Until then you can still join with a code from your instructor.
              </p>
              <button
                type="button"
                onClick={() => navigate(`${pathPrefix}/classroom`)}
                style={{
                  background: '#C8102E',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '9px 16px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Go to Classroom
              </button>
            </div>
          )}

          {!loading && rows.length > 0 && filtered.length === 0 && (
            <div style={{ fontSize: '13px', color: '#9A948E' }}>
              No sections match “{query}”.
            </div>
          )}

          {!loading && filtered.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '560px' }}>
              {filtered.map(row => {
                const isMember = joinedIds.has(row.id)
                const isJoining = joiningId === row.id
                const showMsg = rowMsg.id === row.id && rowMsg.text
                return (
                  <div
                    key={row.id}
                    className="bg-[#FDFCFB] rounded-[14px] px-5 py-4"
                    style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <div style={{ fontSize: '15px', fontWeight: 600, color: '#16120E', marginBottom: '4px' }}>
                          {row.name}
                        </div>
                        <div style={{ fontSize: '12px', color: '#9A948E' }}>
                          {row.member_count} member{row.member_count === 1 ? '' : 's'}
                        </div>
                      </div>
                      {isMember ? (
                        <button
                          type="button"
                          onClick={() => navigate(`${pathPrefix}/classroom`)}
                          style={{
                            flexShrink: 0,
                            background: 'transparent',
                            border: '1.5px solid #E7E0D8',
                            color: '#4A4440',
                            borderRadius: '8px',
                            padding: '8px 14px',
                            fontSize: '12px',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          Already joined
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => joinDirect(row)}
                          disabled={isJoining}
                          style={{
                            flexShrink: 0,
                            background: isJoining ? '#E7E0D8' : '#C8102E',
                            border: 'none',
                            color: '#fff',
                            borderRadius: '8px',
                            padding: '8px 14px',
                            fontSize: '12px',
                            fontWeight: 600,
                            cursor: isJoining ? 'default' : 'pointer',
                          }}
                        >
                          {isJoining ? 'Joining…' : 'Join'}
                        </button>
                      )}
                    </div>
                    {showMsg && (
                      <div style={{
                        marginTop: '8px',
                        fontSize: '12px',
                        color: rowMsg.kind === 'error' ? '#C8102E' : '#15803D',
                      }}>
                        {rowMsg.text}
                      </div>
                    )}
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
