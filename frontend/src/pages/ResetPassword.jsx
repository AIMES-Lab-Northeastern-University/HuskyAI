import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { API_URL, formatApiErrorDetail } from '../lib/api'

export default function ResetPassword() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const navigate = useNavigate()

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (password !== confirm) {
      setError('Those passwords do not match.')
      return
    }
    setLoading(true)
    try {
      const res = await fetch(API_URL + '/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(formatApiErrorDetail(data.detail))
      // The reset invalidated every existing session for this account, including
      // any stale token in this browser. Clear it so the app cannot act on it.
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      setDone(true)
      window.setTimeout(() => navigate('/login'), 2200)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F3EE] px-4">
      <div className="w-full max-w-[400px] bg-white border-[1.5px] border-[#E7E0D8] rounded-[14px] p-8">
        <h1 className="text-[22px] font-semibold text-[#16120E] mb-[6px]">Choose a new password</h1>

        {!token ? (
          <>
            <p className="text-[13px] text-[#6B655F] leading-[1.6] mb-6">
              This link is missing its reset token. Request a new one and use the most
              recent email.
            </p>
            <Link to="/forgot-password" className="text-[13px] text-[#C8102E] font-semibold no-underline">
              Request a new link
            </Link>
          </>
        ) : done ? (
          <>
            <p className="text-[13px] text-[#6B655F] leading-[1.6] mb-6">
              Your password has been reset. Taking you to sign in…
            </p>
            <Link to="/login" className="text-[13px] text-[#C8102E] font-semibold no-underline">
              Sign in now
            </Link>
          </>
        ) : (
          <>
            <p className="text-[13px] text-[#6B655F] leading-[1.6] mb-6">
              At least 10 characters, including a letter and a digit.
            </p>
            <form onSubmit={handleSubmit}>
              <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">
                New password
              </label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Create a password"
                className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[14px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors"
              />

              <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] mt-4 tracking-[0.2px]">
                Confirm password
              </label>
              <input
                type="password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Re-enter it"
                className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[14px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors"
              />

              {error && (
                <div className="mt-4 text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-[9px] px-3 py-2">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full mt-5 py-[11px] rounded-[9px] bg-[#C8102E] text-white text-[14px] font-semibold disabled:opacity-60"
              >
                {loading ? 'Saving…' : 'Set new password'}
              </button>
            </form>
            <div className="mt-5 text-center">
              <Link to="/forgot-password" className="text-[12px] text-[#C8102E] font-semibold no-underline">
                Request a new link
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
