import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'

export default function Dashboard() {
  const navigate = useNavigate()

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        {/* Topbar */}
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Dashboard</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>Week 4 of 12</span>
          </div>
          <div className="ml-auto">
            <button
              onClick={() => navigate('/challenges')}
              style={{
                background: '#C8102E',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '7px 16px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
              Active challenge
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* Hero task card */}
          <div
            style={{
              background: '#C8102E',
              borderRadius: '16px',
              padding: '28px 32px',
              marginBottom: '24px',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* Watermark SVG */}
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="white"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{
                position: 'absolute',
                right: '-10px',
                top: '-10px',
                width: '160px',
                height: '160px',
                opacity: 0.1,
                pointerEvents: 'none',
              }}
            >
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>

            {/* Label */}
            <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.65)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '10px' }}>
              Active · Week 4
            </div>

            {/* Title */}
            <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '24px', color: '#fff', marginBottom: '10px', lineHeight: 1.25 }}>
              Design a Public Awareness Campaign
            </div>

            {/* Description */}
            <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.75)', maxWidth: '480px', lineHeight: 1.65, marginBottom: '22px' }}>
              Use AI tools to design a compelling public awareness campaign for a social issue of your choosing. Your campaign should include messaging, visual direction, and target audience analysis.
            </div>

            {/* Buttons */}
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
              <button
                onClick={() => navigate('/workspace')}
                style={{
                  background: '#fff',
                  color: '#C8102E',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '9px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Continue working
              </button>
              <button
                style={{
                  background: 'rgba(255,255,255,0.15)',
                  color: '#fff',
                  border: '1.5px solid rgba(255,255,255,0.35)',
                  borderRadius: '8px',
                  padding: '9px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                View brief
              </button>
            </div>
          </div>

          {/* Stat cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', marginBottom: '24px' }}>
            {/* Prompt Score */}
            <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Prompt Score</div>
              <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>7.4</div>
              <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>+0.6 from last session</div>
            </div>
            {/* Challenges Done */}
            <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Challenges Done</div>
              <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>8</div>
              <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>of 12 this semester</div>
            </div>
            {/* Class Rank */}
            <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Class Rank</div>
              <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>#4</div>
              <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>out of 18 students</div>
            </div>
          </div>

          {/* 2-col grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px' }}>

            {/* Left: Prompt dimensions */}
            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Your prompt dimensions</div>

              {/* Specificity */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Specificity</div>
                <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                  <div style={{ width: '80%', height: '100%', borderRadius: '999px', background: '#0D9488', transition: 'width 0.5s ease' }} />
                </div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>80</div>
              </div>

              {/* Iteration */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Iteration</div>
                <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                  <div style={{ width: '65%', height: '100%', borderRadius: '999px', background: '#F97316', transition: 'width 0.5s ease' }} />
                </div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>65</div>
              </div>

              {/* Context */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Context</div>
                <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                  <div style={{ width: '72%', height: '100%', borderRadius: '999px', background: '#0D9488', transition: 'width 0.5s ease' }} />
                </div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>72</div>
              </div>

              {/* Refinement */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
                <div style={{ fontSize: '12px', color: '#4A4440', fontWeight: 500, width: '90px', flexShrink: 0 }}>Refinement</div>
                <div style={{ flex: 1, height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                  <div style={{ width: '55%', height: '100%', borderRadius: '999px', background: '#C8102E', transition: 'width 0.5s ease' }} />
                </div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#4A4440', width: '32px', textAlign: 'right' }}>55</div>
              </div>

              {/* Insight box */}
              <div style={{
                background: '#FDE8EC',
                border: '1.5px solid #F9BFCA',
                borderRadius: '10px',
                padding: '12px 14px',
                display: 'flex',
                gap: '8px',
                alignItems: 'flex-start',
              }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#C8102E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                  <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
                </svg>
                <div>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: '#C8102E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '3px' }}>Focus this week</div>
                  <div style={{ fontSize: '12px', color: '#9E0B24', lineHeight: 1.6 }}>
                    Try refining your prompts 2–3x per session. Iterating on your initial prompt leads to significantly better AI responses and higher scores.
                  </div>
                </div>
              </div>
            </div>

            {/* Right: Recent activity */}
            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Recent activity</div>

              {[
                { dot: '#16A34A', label: 'Workspace session', sub: '2 hours ago', score: '+0.6' },
                { dot: '#F97316', label: 'Challenge submitted', sub: 'Yesterday', score: '7.1' },
                { dot: '#0D9488', label: 'New badge earned', sub: '2 days ago', score: null },
                { dot: '#7C3AED', label: 'Prompt streak — 5 days', sub: '3 days ago', score: null },
                { dot: '#C8102E', label: 'Challenge started', sub: 'Week 4 began', score: null },
              ].map((item, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', marginBottom: i < 4 ? '14px' : 0, paddingBottom: i < 4 ? '14px' : 0, borderBottom: i < 4 ? '1px solid #F7F3EE' : 'none' }}>
                  <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: item.dot, flexShrink: 0, marginTop: '4px' }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '12px', fontWeight: 500, color: '#16120E' }}>{item.label}</div>
                    <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>{item.sub}</div>
                  </div>
                  {item.score && (
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#16A34A' }}>{item.score}</div>
                  )}
                </div>
              ))}
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
