import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { API_URL, authHeaders } from '../lib/api'

export default function RequirePlatformAdmin({ children }) {
  const [state, setState] = useState('loading')

  useEffect(() => {
    const raw = localStorage.getItem('user')
    const u = raw ? JSON.parse(raw) : null
    if (u?.is_platform_admin) {
      setState('ok')
      return
    }
    const token = localStorage.getItem('token')
    if (!token) {
      setState('no')
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/auth/me`, { headers: { ...authHeaders() } })
        const d = await r.json().catch(() => ({}))
        if (cancelled) return
        if (r.ok && d.is_platform_admin) {
          localStorage.setItem(
            'user',
            JSON.stringify({
              id: d.user_id,
              name: d.name,
              email: d.email,
              is_platform_admin: true,
            }),
          )
          setState('ok')
        } else {
          setState('no')
        }
      } catch {
        if (!cancelled) setState('no')
      }
    })()
    return () => { cancelled = true }
  }, [])

  if (state === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center bg-[#F7F3EE] text-[#9A948E] text-sm">
        Loading…
      </div>
    )
  }
  if (state === 'no') return <Navigate to="/dashboard" replace />
  return children
}
