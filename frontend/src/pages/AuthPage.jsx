import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { API_URL, formatApiErrorDetail } from '../lib/api'

const ROLES = [
  {
    id: 'student',
    label: 'Student',
    hint: 'Join with your class code on Classroom after sign-in.',
    icon: (
      <svg viewBox="0 0 24 24" className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
      </svg>
    ),
  },
  {
    id: 'instructor',
    label: 'Instructor',
    hint: "You’ll create your first section right after registering.",
    icon: (
      <svg viewBox="0 0 24 24" className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" />
      </svg>
    ),
  },
  {
    id: 'admin',
    label: 'Admin',
    hint: 'Admin link in the sidebar when your account is a platform admin.',
    icon: (
      <svg viewBox="0 0 24 24" className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
  },
]

export default function AuthPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  /** URL is source of truth: Sign in unless `?tab=register`. Fixes stale tab when navigating /login?tab=register → /login. */
  const tab = searchParams.get('tab') === 'register' ? 'register' : 'login'
  const [role, setRole] = useState('student')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const switchTab = (next) => {
    setError('')
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev)
        if (next === 'register') n.set('tab', 'register')
        else n.delete('tab')
        return n
      },
      { replace: true },
    )
  }

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  useEffect(() => {
    const id = (location.hash || '').replace(/^#/, '')
    if (id === 'educators-login-info') setRole('instructor')
    if (!id) return
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [location.pathname, location.hash])

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
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(formatApiErrorDetail(data.detail))
      localStorage.setItem('token', data.access_token)
      localStorage.setItem(
        'user',
        JSON.stringify({
          id: data.user_id,
          name: data.name,
          email: data.email,
          is_platform_admin: Boolean(data.is_platform_admin),
        }),
      )
      // Seed the research-notice gate from this login, so it reflects whoever
      // just signed in (prevents a prior user's acknowledgement leaking over).
      localStorage.setItem('research_ack', data.research_acknowledged ? 'true' : 'false')
      if (tab === 'register' && role === 'instructor') {
        // Auto-create a default section so instructor role is live immediately
        try {
          await fetch(API_URL + '/classrooms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${data.access_token}` },
            body: JSON.stringify({ name: `${form.name.trim()}'s Section` }),
          })
        } catch {
          // Non-fatal - they can create a section manually
        }
        navigate('/instructor')
      } else {
        navigate('/dashboard')
      }
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
            Real challenges. Real feedback. A coach that scores how you think - not just what you produce.
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
          <div className="flex gap-[2px] bg-[#EDEAE4] rounded-[10px] p-[3px] mb-5">
            {['login', 'register'].map(t => (
              <button key={t} type="button" onClick={() => switchTab(t)}
                className={`flex-1 py-[9px] rounded-[8px] text-[13px] font-semibold transition-all duration-150 border-none cursor-pointer ${tab === t ? 'bg-[#FDFCFB] text-[#16120E] shadow-sm' : 'bg-transparent text-[#9A948E] hover:text-[#4A4440]'}`}>
                {t === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <div id="educators-login-info" className="mb-5">
            <div className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-2.5 px-0.5">
              I am a
            </div>
            <div className="flex gap-2">
              {ROLES.map((r) => {
                const on = role === r.id
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => {
                      setRole(r.id)
                      setError('')
                      if (r.id === 'admin' && tab === 'login' && !form.email.trim()) {
                        setForm(f => ({ ...f, email: 'admin' }))
                      }
                    }}
                    className={`flex-1 flex flex-col items-center gap-1.5 rounded-[12px] border-[1.5px] py-3 px-1 transition-all cursor-pointer ${
                      on
                        ? 'border-[#C8102E] bg-[#FDE8EC] text-[#C8102E] shadow-sm'
                        : 'border-[#E7E0D8] bg-[#FDFCFB] text-[#9A948E] hover:border-[#C4BCB3] hover:text-[#4A4440]'
                    }`}
                  >
                    <span
                      className={`w-11 h-11 rounded-full flex items-center justify-center ${
                        on ? 'bg-white text-[#C8102E]' : 'bg-[#F7F3EE] text-[#6B6560]'
                      }`}
                    >
                      {r.icon}
                    </span>
                    <span className={`text-[12px] font-semibold ${on ? 'text-[#16120E]' : 'text-[#4A4440]'}`}>{r.label}</span>
                  </button>
                )
              })}
            </div>
            <p className="text-[11px] text-[#6B6560] leading-snug mt-2.5 min-h-[2.5rem] px-0.5">
              {ROLES.find((x) => x.id === role)?.hint}
            </p>
          </div>

          {tab === 'register' && role === 'admin' ? (
            <div className="rounded-[12px] border-[1.5px] border-[#E7E0D8] bg-[#FDFCFB] p-6 text-center">
              <div className="w-12 h-12 rounded-full bg-[#F7F3EE] flex items-center justify-center mx-auto mb-3">
                <svg viewBox="0 0 24 24" className="w-6 h-6 text-[#C8102E]" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
              </div>
              <div className="text-[14px] font-semibold text-[#16120E] mb-1">Admin accounts are invite-only</div>
              <div className="text-[12px] text-[#6B6560] leading-relaxed">
                Reach out to the HuskyAI team to get admin access.<br />
                Already have an account?{' '}
                <button type="button" onClick={() => { switchTab('login'); setRole('admin') }} className="text-[#C8102E] font-semibold bg-transparent border-none cursor-pointer p-0">
                  Sign in here
                </button>
              </div>
            </div>
          ) : (
          <>
          <h2 className="font-serif text-[26px] text-[#16120E] mb-5">
            {tab === 'login' ? 'Welcome back' : role === 'instructor' ? 'Join as Instructor' : 'Join Husky AI'}
          </h2>

          <form onSubmit={handleSubmit} className="flex flex-col gap-[18px]">
            {tab === 'register' && (
              <div>
                <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">Full name</label>
                <input type="text" required value={form.name} onChange={set('name')} placeholder="Your full name"
                  className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[14px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors" />
              </div>
            )}
            <div>
              <label className="block text-[12px] font-semibold text-[#4A4440] mb-[6px] tracking-[0.2px]">
                {tab === 'login' ? 'Email or username' : 'Email address'}
              </label>
              <input
                type={tab === 'login' ? 'text' : 'email'}
                required
                value={form.email}
                onChange={set('email')}
                placeholder={tab === 'login' ? 'you@school.edu or admin' : 'you@northeastern.edu'}
                className="w-full px-[14px] py-[10px] border-[1.5px] border-[#E7E0D8] rounded-[9px] text-[14px] text-[#16120E] bg-[#FDFCFB] outline-none placeholder-[#9A948E] focus:border-[#C8102E] transition-colors"
              />
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
              ? <>No account? <button type="button" onClick={() => switchTab('register')} className="text-[#C8102E] font-semibold bg-transparent border-none cursor-pointer p-0">Create one</button></>
              : <>Already have an account? <button type="button" onClick={() => switchTab('login')} className="text-[#C8102E] font-semibold bg-transparent border-none cursor-pointer p-0">Sign in</button></>
            }
          </div>
          </>
          )}
        </div>
      </div>
    </div>
  )
}
