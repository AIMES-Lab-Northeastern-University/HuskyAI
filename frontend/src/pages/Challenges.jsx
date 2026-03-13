import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'

const FILTERS = ['All', 'LLM Prompting', 'Image AI', 'Data & Analysis', 'Creative', 'Completed']

const CHALLENGES = [
  {
    id: 1,
    category: 'LLM Prompting',
    categoryColor: '#C8102E',
    categoryBg: '#FDE8EC',
    title: 'Design a Public Awareness Campaign',
    description: 'Use AI tools to design a compelling public awareness campaign for a social issue. Your campaign should include messaging, visual direction, and target audience analysis.',
    progress: 40,
    sessions: '3 sessions',
    due: 'Due in 4 days',
    difficulty: 'Medium',
    diffColor: '#F97316',
    diffBg: '#FEF3E8',
    active: true,
  },
  {
    id: 2,
    category: 'Data & Analysis',
    categoryColor: '#0D9488',
    categoryBg: '#E6F7F6',
    title: 'Analyse a Real-World Dataset',
    description: 'Prompt an AI assistant to help you interpret a public dataset. Document your approach, the questions you asked, and how the AI helped surface key insights.',
    progress: 0,
    sessions: '0 sessions',
    due: 'Starts Week 5',
    difficulty: 'Hard',
    diffColor: '#C8102E',
    diffBg: '#FDE8EC',
    active: false,
  },
  {
    id: 3,
    category: 'Image AI',
    categoryColor: '#7C3AED',
    categoryBg: '#F5F3FF',
    title: 'Visual Storytelling with AI',
    description: 'Generate and iterate on a series of AI images that tell a coherent visual story. Focus on prompt refinement and how small changes affect the output dramatically.',
    progress: 100,
    sessions: '5 sessions',
    due: 'Completed',
    difficulty: 'Easy',
    diffColor: '#16A34A',
    diffBg: '#DCFCE7',
    active: false,
    completed: true,
  },
  {
    id: 4,
    category: 'Creative',
    categoryColor: '#D97706',
    categoryBg: '#FEF9EC',
    title: 'Co-write a Short Story',
    description: 'Collaborate with an LLM to co-author a short story under 1,000 words. Experiment with different narrative prompting strategies and reflect on the creative process.',
    progress: 0,
    sessions: '0 sessions',
    due: 'Starts Week 6',
    difficulty: 'Medium',
    diffColor: '#F97316',
    diffBg: '#FEF3E8',
    active: false,
  },
]

export default function Challenges() {
  const navigate = useNavigate()
  const [activeFilter, setActiveFilter] = useState('All')

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  const filtered = CHALLENGES.filter(c => {
    if (activeFilter === 'All') return true
    if (activeFilter === 'Completed') return c.completed
    return c.category === activeFilter
  })

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        {/* Topbar */}
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Challenges</span>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* Filter bar */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', flexWrap: 'wrap' }}>
            {FILTERS.map(f => (
              <button
                key={f}
                onClick={() => setActiveFilter(f)}
                style={{
                  padding: '6px 14px',
                  borderRadius: '20px',
                  fontSize: '13px',
                  fontWeight: activeFilter === f ? 600 : 500,
                  cursor: 'pointer',
                  border: activeFilter === f ? 'none' : '1.5px solid #E7E0D8',
                  background: activeFilter === f ? '#C8102E' : '#FDFCFB',
                  color: activeFilter === f ? '#fff' : '#4A4440',
                  transition: 'all 0.15s ease',
                }}
              >
                {f}
              </button>
            ))}
          </div>

          {/* Challenge grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {filtered.map(c => (
              <div
                key={c.id}
                style={{
                  background: '#FDFCFB',
                  borderRadius: '14px',
                  padding: '20px',
                  borderWidth: '1.5px',
                  borderStyle: 'solid',
                  borderColor: c.active ? '#F9BFCA' : '#E7E0D8',
                }}
              >
                {/* Category pill */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                  <span style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '3px 10px',
                    borderRadius: '20px',
                    background: c.categoryBg,
                    color: c.categoryColor,
                  }}>
                    {c.category}
                  </span>
                  {c.active && (
                    <span style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: '20px',
                      background: '#FDE8EC',
                      color: '#C8102E',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}>
                      Active
                    </span>
                  )}
                  {c.completed && (
                    <span style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: '20px',
                      background: '#DCFCE7',
                      color: '#16A34A',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}>
                      Done
                    </span>
                  )}
                </div>

                {/* Title */}
                <div style={{ fontSize: '15px', fontWeight: 600, color: '#16120E', marginBottom: '8px', fontFamily: "'Instrument Serif', serif" }}>
                  {c.title}
                </div>

                {/* Description */}
                <div style={{ fontSize: '12px', color: '#9A948E', lineHeight: 1.65, marginBottom: '16px' }}>
                  {c.description}
                </div>

                {/* Progress bar */}
                <div style={{ marginBottom: '14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                    <span style={{ fontSize: '11px', color: '#9A948E', fontWeight: 500 }}>Progress</span>
                    <span style={{ fontSize: '11px', fontWeight: 700, color: '#4A4440' }}>{c.progress}%</span>
                  </div>
                  <div style={{ height: '7px', background: '#F7F3EE', borderRadius: '999px', border: '1px solid #E7E0D8', overflow: 'hidden' }}>
                    <div style={{
                      width: `${c.progress}%`,
                      height: '100%',
                      borderRadius: '999px',
                      background: c.active ? '#C8102E' : c.completed ? '#16A34A' : '#E7E0D8',
                      transition: 'width 0.5s ease',
                    }} />
                  </div>
                </div>

                {/* Meta row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                    </svg>
                    <span style={{ fontSize: '11px', color: '#9A948E' }}>{c.sessions}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
                    </svg>
                    <span style={{ fontSize: '11px', color: '#9A948E' }}>{c.due}</span>
                  </div>
                  <div style={{ marginLeft: 'auto' }}>
                    <span style={{
                      fontSize: '11px',
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: '20px',
                      background: c.diffBg,
                      color: c.diffColor,
                    }}>
                      {c.difficulty}
                    </span>
                  </div>
                </div>

                {/* Action button */}
                {c.active && (
                  <button
                    onClick={() => navigate('/workspace')}
                    style={{
                      marginTop: '14px',
                      width: '100%',
                      padding: '9px',
                      background: '#C8102E',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '8px',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    Continue in Workspace
                  </button>
                )}
                {!c.active && !c.completed && (
                  <button
                    style={{
                      marginTop: '14px',
                      width: '100%',
                      padding: '9px',
                      background: 'transparent',
                      color: '#4A4440',
                      border: '1.5px solid #E7E0D8',
                      borderRadius: '8px',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    View brief
                  </button>
                )}
              </div>
            ))}
          </div>

        </div>
      </div>
    </div>
  )
}
