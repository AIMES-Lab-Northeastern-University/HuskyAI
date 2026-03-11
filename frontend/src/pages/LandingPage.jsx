import { useNavigate } from 'react-router-dom'

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-surface-0 text-slate-200 flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-surface-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-white flex items-center justify-center overflow-hidden p-0.5">
            <img src="/logo.png" alt="Husky AI" className="w-full h-full object-contain" />
          </div>
          <span className="text-base font-semibold">Husky AI</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/login')}
            className="text-sm text-slate-400 hover:text-slate-200 transition-colors px-3 py-1.5"
          >
            Sign In
          </button>
          <button
            onClick={() => navigate('/login?tab=register')}
            className="text-sm px-4 py-2 rounded-lg bg-accent-blue hover:bg-blue-500 text-white transition-colors font-medium"
          >
            Get Started
          </button>
        </div>
      </header>

      {/* Hero */}
      <main className="flex-1 flex flex-col items-center justify-center px-6 text-center gap-8 py-20">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#C8102E]/30 text-[#C8102E] bg-[#C8102E]/10 text-xs font-medium">
          Northeastern University
        </div>

        <h1 className="text-5xl font-bold tracking-tight max-w-3xl leading-tight">
          Be an{' '}
          <span className="bg-gradient-to-r from-accent-blue to-accent-purple bg-clip-text text-transparent">
            AI-Ready
          </span>{' '}
          Husky
        </h1>

        <p className="text-lg text-slate-400 max-w-xl leading-relaxed">
          Practice coding conversations with Gemini AI while receiving real-time feedback
          on your prompting skills. Learn to lead — not be led by — AI.
        </p>

        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/login?tab=register')}
            className="px-8 py-3.5 rounded-xl bg-accent-blue hover:bg-blue-500 text-white font-semibold text-base transition-all hover:scale-105"
          >
            Start Learning Free
          </button>
          <button
            onClick={() => navigate('/login')}
            className="px-8 py-3.5 rounded-xl border border-surface-4 hover:border-slate-500 text-slate-300 font-medium text-base transition-all"
          >
            Sign In
          </button>
        </div>

        {/* Feature cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-3xl w-full mt-6">
          {[
            {
              icon: '💬',
              title: 'AI Coding Assistant',
              desc: 'Chat with Gemini 2.5 Pro on any programming question, debugging task, or architecture decision.',
            },
            {
              icon: '📊',
              title: 'Real-time Evaluation',
              desc: 'Get scored on 5 dimensions of prompting quality — PSQ, CCM, TSI, CLM, and RAS — after each turn.',
            },
            {
              icon: '📈',
              title: 'Track Progress',
              desc: 'Your conversations and scores are saved. Watch your PEI improve as you develop AI-ready habits.',
            },
          ].map(({ icon, title, desc }) => (
            <div key={title} className="bg-surface-1 border border-surface-3 rounded-xl p-5 text-left hover:border-surface-4 transition-colors">
              <div className="text-2xl mb-3">{icon}</div>
              <h3 className="text-sm font-semibold text-slate-200 mb-2">{title}</h3>
              <p className="text-xs text-slate-500 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>

        {/* PEI score preview */}
        <div className="mt-4 bg-surface-1 border border-surface-3 rounded-2xl px-8 py-5 max-w-sm w-full">
          <p className="text-xs text-slate-500 mb-3 text-center">Prompt Effectiveness Index (PEI)</p>
          <div className="flex items-end justify-center gap-1 h-12">
            {[22, 35, 41, 48, 55, 63, 71].map((h, i) => (
              <div
                key={i}
                className="w-6 rounded-t-sm bg-gradient-to-t from-accent-blue/40 to-accent-blue"
                style={{ height: `${h}%` }}
              />
            ))}
          </div>
          <p className="text-xs text-slate-600 text-center mt-2">Your score improves with practice</p>
        </div>
      </main>

      <footer className="text-center py-4 text-xs text-slate-600 border-t border-surface-3">
        Husky AI — Northeastern University © 2026
      </footer>
    </div>
  )
}
