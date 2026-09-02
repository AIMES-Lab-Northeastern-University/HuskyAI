import { useState } from 'react'
import { Link } from 'react-router-dom'
import { API_URL, formatApiErrorDetail } from '../lib/api'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch(API_URL + '/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(formatApiErrorDetail(data.detail))
      setSent(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F3EE] px-4">
      <div className="w-full max-w-[400px] bg-white border-[1.5px] border-[#E7E0D8] rounded-[14px] p-8">
        <h1 className="text-[22px] font-semibold text-[#16120E] mb-[6px]">Reset your password</h1>

        {sent ? (
          <>
            <p className="text-[13px] text-[#6B655F] leading-[1.6] mb-6">
              If an account exists for <span className="font-semibold text-[#16120E]">{email}</span>,
              a reset link is on its way. It expires in 60 minutes and can be used once.
            </p>
            <p className="text-[12px] text-[#9A948E] leading-[1.6] mb-6">
              Nothing arrived? Check your spam folder, then try again.
            </p>
            <Link to="/login" className="text-[13px] text-[#C8102E] font-semibold no-underline">
              Back to sign in
            </Link>
          </>
        ) : (
          <>
            <p className="text-[13px] text-[#6B655F] leading-[1.6] mb-6">
              Enter your email and we&apos;ll send you a link to choose a new password.
            </p>
            <form onSubmit={handleSubmit}>
              <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">
                Email
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@northeastern.edu"
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
                {loading ? 'Sending…' : 'Send reset link'}
              </button>
            </form>
            <div className="mt-5 text-center">
              <Link to="/login" className="text-[12px] text-[#C8102E] font-semibold no-underline">
                Back to sign in
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
