import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'

function DualBar({ label, yourPct, partnerPct, yourColor, partnerColor }) {
  return (
    <div style={{ marginBottom: '14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
        <span style={{ fontSize: '12px', color: '#9A948E', fontWeight: 500 }}>{label}</span>
        <div style={{ display: 'flex', gap: '10px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: yourColor }}>{yourPct}%</span>
          <span style={{ fontSize: '12px', fontWeight: 700, color: partnerColor }}>{partnerPct}%</span>
        </div>
      </div>
      <div style={{ height: '7px', background: '#2A2520', borderRadius: '999px', overflow: 'hidden', display: 'flex' }}>
        <div style={{ width: `${yourPct}%`, height: '100%', background: yourColor, transition: 'width 0.5s ease' }} />
        <div style={{ width: `${partnerPct - yourPct}%`, height: '100%', background: partnerColor, opacity: 0.6, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  )
}

export default function Classroom() {
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
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Classroom</span>
            <span style={{ fontSize: '12px', color: '#9A948E' }}>Section A vs. Partner Class</span>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8">
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px' }}>

            {/* Left: class-vs-card */}
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
                padding: '16px 20px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff', marginBottom: '2px' }}>
                    Live comparison — Week 4
                  </div>
                  <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
                    Section A vs. Partner Class
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#16A34A' }} />
                  <span style={{ fontSize: '11px', fontWeight: 600, color: '#16A34A' }}>Live</span>
                </div>
              </div>

              {/* Body */}
              <div style={{ padding: '20px' }}>

                {/* Score row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0', marginBottom: '24px' }}>
                  {/* Your class */}
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
                      Your class
                    </div>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '36px', color: '#F97316', lineHeight: 1 }}>6.8</div>
                    <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '4px' }}>avg PEI score</div>
                  </div>

                  {/* VS divider */}
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '0 20px' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '1px' }}>VS</div>
                    <div style={{ width: '1px', height: '40px', background: '#E7E0D8', marginTop: '4px' }} />
                  </div>

                  {/* Partner class */}
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
                      Partner class
                    </div>
                    <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '36px', color: '#16A34A', lineHeight: 1 }}>7.1</div>
                    <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '4px' }}>avg PEI score</div>
                  </div>
                </div>

                {/* Dimension bars */}
                <div style={{ marginBottom: '18px' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '16px', marginBottom: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <div style={{ width: '10px', height: '4px', borderRadius: '2px', background: '#F97316' }} />
                      <span style={{ fontSize: '11px', color: '#9A948E' }}>Your class</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <div style={{ width: '10px', height: '4px', borderRadius: '2px', background: '#16A34A' }} />
                      <span style={{ fontSize: '11px', color: '#9A948E' }}>Partner</span>
                    </div>
                  </div>
                  <DualBar label="Specificity"  yourPct={72} partnerPct={78} yourColor="#F97316" partnerColor="#16A34A" />
                  <DualBar label="Iteration"    yourPct={60} partnerPct={74} yourColor="#F97316" partnerColor="#16A34A" />
                  <DualBar label="Refinement"   yourPct={55} partnerPct={68} yourColor="#F97316" partnerColor="#16A34A" />
                </div>

                {/* Amber insight pill */}
                <div style={{
                  background: '#FEF9EC',
                  border: '1.5px solid #FDE68A',
                  borderRadius: '10px',
                  padding: '12px 14px',
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'flex-start',
                }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                    <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                  <div>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#D97706', marginBottom: '3px' }}>Class insight</div>
                    <div style={{ fontSize: '12px', color: '#92400E', lineHeight: 1.6 }}>
                      Your class is 0.3 points behind the partner class this week. Focus on Refinement dimension — it has the largest gap and biggest potential impact on your PEI.
                    </div>
                  </div>
                </div>

              </div>
            </div>

            {/* Right col: 3 stat cards */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

              {/* Gap to close */}
              <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Gap to close</div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#C8102E', lineHeight: 1 }}>−0.3</div>
                <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>points behind partner</div>
              </div>

              {/* Your strongest */}
              <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Your strongest</div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '24px', color: '#16120E', lineHeight: 1.2, marginBottom: '4px' }}>Specificity</div>
                <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>72 — closest to partner avg</div>
              </div>

              {/* Sessions active */}
              <div className="bg-[#FDFCFB] rounded-[14px] px-5 py-[18px]" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Sessions active</div>
                <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '32px', color: '#16120E', lineHeight: 1 }}>14</div>
                <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '4px' }}>this week across your class</div>
              </div>

              {/* Quick action */}
              <button
                onClick={() => navigate('/workspace')}
                style={{
                  background: '#C8102E',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '10px',
                  padding: '12px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                </svg>
                Help close the gap
              </button>

            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
