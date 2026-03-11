import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function AuthPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState(searchParams.get('tab') === 'register' ? 'register' : 'login')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Redirect if already logged in
  useEffect(() => {
    if (localStorage.getItem('token')) navigate('/app', { replace: true })
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const endpoint = tab === 'login' ? '/auth/login' : '/auth/register'
      const body = tab === 'login'
        ? { email: form.email, password: form.password }
        : { email: form.email, name: form.name, password: form.password }

      const res = await fetch(API_URL + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Something went wrong')

      localStorage.setItem('token', data.access_token)
      localStorage.setItem('user', JSON.stringify({ id: data.user_id, name: data.name, email: data.email }))
      navigate('/app', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const update = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }))

  return (
    <div className="min-h-screen bg-surface-0 flex flex-col items-center justify-center px-4">
      {/* Back to landing */}
      <button
        onClick={() => navigate('/')}
        className="absolute top-5 left-6 text-xs text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1"
      >
        ← Husky AI
      </button>

      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-xl bg-white flex items-center justify-center overflow-hidden p-1 mb-3">
            <img src="/logo.png" alt="Husky AI" className="w-full h-full object-contain" />
          </div>
          <h1 className="text-xl font-semibold text-slate-200">Husky AI</h1>
          <p className="text-sm text-slate-500 mt-1">Be an AI-Ready Husky</p>
        </div>

        {/* Card */}
        <div className="bg-surface-1 border border-surface-3 rounded-2xl p-6">
          {/* Tabs */}
          <div className="flex gap-1 mb-6 bg-surface-2 p-1 rounded-lg">
            {[['login', 'Sign In'], ['register', 'Register']].map(([t, label]) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={`flex-1 py-2 text-sm font-medium rounded-md transition-all ${
                  tab === t
                    ? 'bg-surface-0 text-slate-200 shadow'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {tab === 'register' && (
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">Full Name</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={update('name')}
                  placeholder="Your name"
                  className="w-full bg-surface-2 border border-surface-3 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-accent-blue/50 transition-colors"
                />
              </div>
            )}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Email</label>
              <input
                type="email"
                required
                value={form.email}
                onChange={update('email')}
                placeholder="you@northeastern.edu"
                className="w-full bg-surface-2 border border-surface-3 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-accent-blue/50 transition-colors"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Password</label>
              <input
                type="password"
                required
                minLength={6}
                value={form.password}
                onChange={update('password')}
                placeholder="••••••••"
                className="w-full bg-surface-2 border border-surface-3 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-accent-blue/50 transition-colors"
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-accent-blue hover:bg-blue-500 disabled:bg-surface-3 disabled:cursor-not-allowed text-white text-sm font-semibold transition-all mt-2"
            >
              {loading ? 'Please wait...' : tab === 'login' ? 'Sign In' : 'Create Account'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-slate-600 mt-4">
          Northeastern University — Husky AI
        </p>
      </div>
    </div>
  )
}
