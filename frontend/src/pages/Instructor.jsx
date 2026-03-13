import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'

const STUDENTS = [
  { initials: 'AJ', name: 'Alex Johnson',   score: 7.4, trend: '+0.6', sessions: 12, bar: 74, trendUp: true },
  { initials: 'MP', name: 'Maya Patel',      score: 7.1, trend: '+0.3', sessions: 10, bar: 71, trendUp: true },
  { initials: 'LW', name: 'Liam Wang',       score: 6.8, trend: '−0.1', sessions: 9,  bar: 68, trendUp: false },
  { initials: 'SC', name: 'Sofia Chen',      score: 6.5, trend: '+0.2', sessions: 11, bar: 65, trendUp: true },
  { initials: 'BT', name: 'Ben Torres',      score: 6.2, trend: '−0.4', sessions: 7,  bar: 62, trendUp: false },
  { initials: 'RK', name: 'Rina Kobayashi',  score: 5.9, trend: '+0.1', sessions: 8,  bar: 59, trendUp: true },
]

const CHALLENGES = [
  { title: 'Design a Public Awareness Campaign', status: 'Active',     statusColor: '#C8102E',  statusBg: '#FDE8EC',  week: 'Week 4' },
  { title: 'Social Media & Mental Health',       status: 'Completed',  statusColor: '#16A34A',  statusBg: '#DCFCE7',  week: 'Week 3' },
  { title: 'AI in Healthcare',                   status: 'Completed',  statusColor: '#16A34A',  statusBg: '#DCFCE7',  week: 'Week 2' },
  { title: 'Climate Communication',              status: 'Draft',      statusColor: '#9A948E',  statusBg: '#F7F3EE',  week: 'Week 5' },
]

function DualBar({ label, yourPct, partnerPct, yourColor, partnerColor }) {
  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
        <span style={{ fontSize: '12px', color: '#9A948E', fontWeight: 500 }}>{label}</span>
        <div style={{ display: 'flex', gap: '10px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: yourColor }}>{yourPct}%</span>
          <span style={{ fontSize: '12px', fontWeight: 700, color: partnerColor }}>{partnerPct}%</span>
        </div>
      </div>
      <div style={{ height: '7px', background: '#2A2520', borderRadius: '999px', overflow: 'hidden', display: 'flex' }}>
        <div style={{ width: `${yourPct}%`, height: '100%', background: yourColor, transition: 'width 0.5s ease' }} />
        <div style={{ width: `${Math.max(0, partnerPct - yourPct)}%`, height: '100%', background: partnerColor, opacity: 0.5, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

export default function Instructor() {
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
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Instructor Dashboard</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{
              fontSize: '11px',
              fontWeight: 700,
              padding: '3px 10px',
              borderRadius: '20px',
              background: '#DCFCE7',
              color: '#16A34A',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}>
              Instructor view
            </span>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* Dark hero card */}
          <div style={{
            background: '#16120E',
            borderRadius: '16px',
            padding: '24px 28px',
            marginBottom: '24px',
          }}>
            <div style={{ fontSize: '10px', fontWeight: 700, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
              Currently active · Week 4 of 12
            </div>
            <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '22px', color: '#fff', marginBottom: '20px' }}>
              Week 4 Challenge — Public Awareness Campaign
            </div>
            <div style={{ display: 'flex', gap: '24px' }}>
              {[
                { value: '28', label: 'students enrolled' },
                { value: '6.8', label: 'class avg PEI' },
                { value: '3', label: 'challenges this week' },
              ].map((stat, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '28px', color: '#fff', lineHeight: 1 }}>{stat.value}</div>
                  <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>{stat.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 2-col grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>

            {/* Left: Student list */}
            <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>
                Student performance
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                {STUDENTS.map((s, i) => (
                  <div key={i} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '10px 0',
                    borderBottom: i < STUDENTS.length - 1 ? '1px solid #F7F3EE' : 'none',
                  }}>
                    {/* Avatar */}
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '50%',
                      background: '#C8102E',
                      color: '#fff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '11px',
                      fontWeight: 700,
                      flexShrink: 0,
                    }}>
                      {s.initials}
                    </div>
                    {/* Name + bar */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: '13px', fontWeight: 500, color: '#16120E', marginBottom: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {s.name}
                      </div>
                      <div style={{ height: '5px', background: '#F7F3EE', borderRadius: '999px', overflow: 'hidden' }}>
                        <div style={{
                          width: `${s.bar}%`,
                          height: '100%',
                          borderRadius: '999px',
                          background: s.bar >= 70 ? '#0D9488' : s.bar >= 60 ? '#F97316' : '#C8102E',
                          transition: 'width 0.5s ease',
                        }} />
                      </div>
                    </div>
                    {/* Score + trend */}
                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#16120E' }}>{s.score}</div>
                      <div style={{ fontSize: '11px', color: s.trendUp ? '#16A34A' : '#C8102E', fontWeight: 600 }}>{s.trend}</div>
                    </div>
                    {/* Sessions */}
                    <div style={{ fontSize: '11px', color: '#9A948E', flexShrink: 0, width: '30px', textAlign: 'right' }}>
                      {s.sessions}×
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: Class vs partner */}
            <div style={{
              background: '#FDFCFB',
              borderRadius: '14px',
              overflow: 'hidden',
              borderWidth: '1.5px',
              borderStyle: 'solid',
              borderColor: '#E7E0D8',
            }}>
              {/* Dark header */}
              <div style={{
                background: '#16120E',
                padding: '14px 18px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}>
                <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff' }}>
                  Live comparison — Week 4
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#16A34A' }} />
                  <span style={{ fontSize: '11px', fontWeight: 600, color: '#16A34A' }}>Live</span>
                </div>
              </div>

              <div style={{ padding: '18px' }}>
                {/* Score row */}
                <div style={{ display: 'flex', gap: '0', marginBottom: '20px' }}>
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>Your class</div>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '30px', color: '#F97316', lineHeight: 1 }}>6.8</div>
                  </div>
                  <div style={{ padding: '0 16px', display: 'flex', alignItems: 'center' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E' }}>VS</div>
                  </div>
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>Partner class</div>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '30px', color: '#16A34A', lineHeight: 1 }}>7.1</div>
                  </div>
                </div>

                {/* Legend */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '14px', marginBottom: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <div style={{ width: '8px', height: '3px', borderRadius: '2px', background: '#F97316' }} />
                    <span style={{ fontSize: '10px', color: '#9A948E' }}>Your class</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <div style={{ width: '8px', height: '3px', borderRadius: '2px', background: '#16A34A' }} />
                    <span style={{ fontSize: '10px', color: '#9A948E' }}>Partner</span>
                  </div>
                </div>

                <DualBar label="Specificity"  yourPct={72} partnerPct={78} yourColor="#F97316" partnerColor="#16A34A" />
                <DualBar label="Iteration"    yourPct={60} partnerPct={74} yourColor="#F97316" partnerColor="#16A34A" />
                <DualBar label="Refinement"   yourPct={55} partnerPct={68} yourColor="#F97316" partnerColor="#16A34A" />

                {/* Insight pill */}
                <div style={{
                  marginTop: '14px',
                  background: '#FEF9EC',
                  border: '1.5px solid #FDE68A',
                  borderRadius: '10px',
                  padding: '10px 12px',
                  display: 'flex',
                  gap: '7px',
                  alignItems: 'flex-start',
                }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                    <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                  <div style={{ fontSize: '12px', color: '#92400E', lineHeight: 1.6 }}>
                    Your class trails by 0.3 pts. Refinement has the largest gap.
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Manage Challenges */}
          <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px' }}>
                Manage challenges
              </div>
              <button style={{
                background: '#C8102E',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '6px 14px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
              }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                New challenge
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
              {CHALLENGES.map((c, i) => (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '14px',
                  padding: '13px 0',
                  borderBottom: i < CHALLENGES.length - 1 ? '1px solid #F7F3EE' : 'none',
                }}>
                  {/* Icon */}
                  <div style={{
                    width: '34px',
                    height: '34px',
                    borderRadius: '9px',
                    background: '#F7F3EE',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9A948E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                    </svg>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E' }}>{c.title}</div>
                    <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '2px' }}>{c.week}</div>
                  </div>
                  <span style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '3px 10px',
                    borderRadius: '20px',
                    background: c.statusBg,
                    color: c.statusColor,
                  }}>
                    {c.status}
                  </span>
                  <button style={{
                    padding: '5px 12px',
                    borderRadius: '7px',
                    border: '1.5px solid #E7E0D8',
                    background: 'transparent',
                    color: '#4A4440',
                    fontSize: '12px',
                    fontWeight: 500,
                    cursor: 'pointer',
                  }}>
                    Edit
                  </button>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
