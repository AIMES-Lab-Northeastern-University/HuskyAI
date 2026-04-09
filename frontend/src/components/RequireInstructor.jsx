import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { API_URL, authHeaders } from '../lib/api'

export default function RequireInstructor({ children }) {
  const location = useLocation()
  const isDemo = location.pathname.startsWith('/demo')
  const [state, setState] = useState(isDemo ? 'ok' : 'loading')

  useEffect(() => {
    if (isDemo) return
    const token = localStorage.getItem('token')
    if (!token) {
      setState('no')
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/classrooms/me`, { headers: { ...authHeaders() } })
        const list = await r.json().catch(() => [])
        const inst =
          Array.isArray(list) &&
          list.some(c => c.role === 'instructor' || c.role === 'admin')
        if (!cancelled) setState(inst ? 'ok' : 'no')
      } catch {
        if (!cancelled) setState('no')
      }
    })()
    return () => { cancelled = true }
  }, [isDemo])

  if (isDemo) return children
  if (state === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center bg-[#F7F3EE] text-[#9A948E] text-sm">
        Loading…
      </div>
    )
  }
  if (state === 'no') {
    return <Navigate to="/classroom" replace state={{ needInstructor: true }} />
  }
  return children
}
