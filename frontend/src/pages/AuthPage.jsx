import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function AuthPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState(searchParams.get('tab') === 'register' ? 'register' : 'login')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

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
      navigate('/dashboard')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex bg-[#F7F3EE]">

      {/* ── Left dark panel ── */}
      <div className="w-[480px] flex-shrink-0 flex flex-col p-12 relative overflow-hidden" style={{ background: '#16120E' }}>
        <div className="absolute inset-0 pointer-events-none" style={{ background: 'repeating-linear-gradient(45deg,rgba(200,16,46,0.04) 0,rgba(200,16,46,0.04) 1px,transparent 0,transparent 50%)', backgroundSize: '24px 24px' }} />

        {/* Logo */}
        <div className="flex items-center gap-[10px] relative z-10 mb-auto">
          <div className="w-[34px] h-[34px] bg-[#C8102E] rounded-[9px] flex items-center justify-center flex-shrink-0">
            <svg viewBox="0 0 24 24" className="w-[17px] h-[17px] stroke-white fill-none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="4" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="20" cy="16" r="2"/>
              <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
            </svg>
          </div>
          <span className="font-serif text-[20px] text-white">Husky AI</span>
        </div>

        {/* Hero */}
        <div className="relative z-10">
          <h1 className="font-serif text-[clamp(36px,4vw,52px)] text-white leading-[1.1] mb-[18px]">
            Learn to<br />think with<br /><em className="italic text-[#C8102E]">AI.</em>
          </h1>
          <p className="text-[14px] text-white/50 leading-[1.75] font-light max-w-[340px]">
            Real challenges. Real feedback. A coach that scores how you think — not just what you produce.
          </p>
          <div className="flex gap-7 mt-10 pt-8 border-t border-white/10">
            <div>
              <div className="font-serif text-[28px] text-white leading-none">5<span className="text-[#C8102E]">k+</span></div>
              <div className="text-[11px] text-white/40 mt-[3px] font-medium">Prompts evaluated</div>
            </div>
            <div>
              <div className="font-serif text-[28px] text-white leading-none">82<span className="text-[#C8102E]">%</span></div>
              <div className="text-[11px] text-white/40 mt-[3px] font-medium">Avg improvement</div>
            </div>
            <div>
              <div className="font-serif text-[28px] text-white leading-none">12</div>
              <div className="text-[11px] text-white/40 mt-[3px] font-medium">Weekly challenges</div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Right form panel ── */}
      <div className="flex-1 flex items-center justify-center p-12">
        <div className="w-full max-w-[400px]">
          {/* Tabs */}
          <div className="flex gap-[2px] bg-[#EDEAE4] rounded-[10px] p-[3px] mb-7">
            {['login', 'register'].map(t => (
              <button key={t} onClick={() => { setTab(t); setError('') }}
                className={`flex-1 py-[9px] rounded-[8px] text-[13px] font-semibold transition-all duration-150 border-none cursor-pointer ${tab === t ? 'bg-[#FDFCFB] text-[#16120E] shadow-sm' : 'bg-transparent text-[#9A948E] hover:text-[#4A4440]'}`}>
                {t === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <h2 className="font-serif text-[26px] text-[#16120E] mb-[6px]">
            {tab === 'login' ? 'Welcome back' : 'Join Husky AI'}
          </h2>
          <p className="text-[13px] text-[#9A948E] mb-6 leading-[1.6]">
            {tab === 'login' ? 'Sign in to continue your AI learning journey.' : 'Create your account to get started.'}
          </p>

          <form onSubmit={handleSubmit} className="flex flex-col gap-[18px]">
            {tab === 'register' && (
              <div>
                <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">Full name</label>
                <input type="text" required value={form.name} onChange={set('name')} placeholder="Your full name"
                  className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[14px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors" />
              </div>
            )}
            <div>
              <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">Email address</label>
              <input type="email" required value={form.email} onChange={set('email')} placeholder="you@northeastern.edu"
                className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[14px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors" />
            </div>
            <div>
              <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">Password</label>
              <input type="password" required value={form.password} onChange={set('password')} placeholder={tab === 'login' ? 'Enter your password' : 'Create a password'}
                className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[14px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors" />
              {tab === 'login' && (
                <div className="text-right mt-[5px]">
                  <a href="#" className="text-[11px] text-[#C8102E] font-semibold no-underline">Forgot password?</a>
                </div>
              )}
            </div>

            {error && (
              <div className="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-[9px] px-3 py-2">{error}</div>
            )}

            <button type="submit" disabled={loading}
              className="w-full py-[13px] bg-[#C8102E] hover:bg-[#9E0B24] disabled:opacity-60 text-white text-[14px] font-semibold border-none rounded-[9px] cursor-pointer transition-colors">
              {loading ? 'Please wait...' : tab === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>

          <div className="text-center mt-5 text-[13px] text-[#9A948E]">
            {tab === 'login'
              ? <>No account? <button onClick={() => setTab('register')} className="text-[#C8102E] font-semibold bg-transparent border-none cursor-pointer p-0">Create one</button></>
              : <>Already have an account? <button onClick={() => setTab('login')} className="text-[#C8102E] font-semibold bg-transparent border-none cursor-pointer p-0">Sign in</button></>
            }
          </div>
        </div>
      </div>
    </div>
  )
}
