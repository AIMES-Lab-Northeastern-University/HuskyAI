import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders } from '../lib/api'

const DEMO_LIST = [
  { id: 'demo-1', name: 'Husky Test Section', member_count: 12 },
  { id: 'demo-2', name: 'CS 2500 · Fall 2026', member_count: 45 },
]

export default function ClassroomBrowse() {
  const navigate = useNavigate()
  const location = useLocation()
  const isDemo = location.pathname.startsWith('/demo')
  const pathPrefix = isDemo ? '/demo' : ''

  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(!isDemo)
  const [error, setError] = useState('')

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
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Browse sections</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>
              Instructors can list a section here for discovery
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
                When an instructor turns on listing for their section, it will appear here. You still join using the code they give you — codes are not shown in this directory.
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

          {!loading && rows.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '560px' }}>
              {rows.map(row => (
                <div
                  key={row.id}
                  className="bg-[#FDFCFB] rounded-[14px] px-5 py-4 flex items-center justify-between gap-4"
                  style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}
                >
                  <div>
                    <div style={{ fontSize: '15px', fontWeight: 600, color: '#16120E', marginBottom: '4px' }}>
                      {row.name}
                    </div>
                    <div style={{ fontSize: '12px', color: '#9A948E' }}>
                      {row.member_count} member{row.member_count === 1 ? '' : 's'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(`${pathPrefix}/classroom`)}
                    style={{
                      flexShrink: 0,
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
                    I have a code
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
