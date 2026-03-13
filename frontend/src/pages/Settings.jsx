import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'

const NAV_ITEMS = [
  {
    id: 'profile',
    label: 'Profile',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
      </svg>
    ),
  },
  {
    id: 'account',
    label: 'Account & Security',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </svg>
    ),
  },
  {
    id: 'notifications',
    label: 'Notifications',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
    ),
  },
  {
    id: 'preferences',
    label: 'Preferences',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="4" y1="6" x2="20" y2="6" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="18" x2="20" y2="18" />
      </svg>
    ),
  },
]

function Toggle({ checked, onChange }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      style={{
        width: '36px',
        height: '20px',
        borderRadius: '10px',
        background: checked ? '#C8102E' : '#E7E0D8',
        border: 'none',
        cursor: 'pointer',
        position: 'relative',
        transition: 'background 0.2s ease',
        flexShrink: 0,
      }}
    >
      <div style={{
        position: 'absolute',
        top: '2px',
        left: checked ? '18px' : '2px',
        width: '16px',
        height: '16px',
        borderRadius: '50%',
        background: '#fff',
        transition: 'left 0.2s ease',
        boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </button>
  )
}

export default function Settings() {
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('user') || 'null')
  const [activeSection, setActiveSection] = useState('profile')
  const [name, setName] = useState(user?.name || 'Alex Johnson')
  const [email, setEmail] = useState(user?.email || 'alex.johnson@husky.edu')
  const [section, setSection] = useState('Section A — Spring 2026')
  const [notifs, setNotifs] = useState({
    weeklyReport: true,
    challengeReminders: true,
    classComparison: false,
    badgeAlerts: true,
  })

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    navigate('/login', { replace: true })
  }

  const initials = name ? name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() : 'U'

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        {/* Topbar */}
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#16120E' }}>Settings</span>
          <div className="ml-auto">
            <button style={{
              background: '#C8102E',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '7px 16px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
            }}>
              Save changes
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8">
          <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: '24px', maxWidth: '860px' }}>

            {/* Left nav */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {NAV_ITEMS.map(item => (
                <button
                  key={item.id}
                  onClick={() => setActiveSection(item.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '9px 12px',
                    borderRadius: '9px',
                    fontSize: '13px',
                    fontWeight: activeSection === item.id ? 600 : 500,
                    cursor: 'pointer',
                    border: 'none',
                    background: activeSection === item.id ? '#FDE8EC' : 'transparent',
                    color: activeSection === item.id ? '#C8102E' : '#4A4440',
                    textAlign: 'left',
                    width: '100%',
                    transition: 'all 0.12s ease',
                  }}
                >
                  <span style={{ color: activeSection === item.id ? '#C8102E' : '#9A948E' }}>{item.icon}</span>
                  {item.label}
                </button>
              ))}
            </div>

            {/* Right content */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

              {/* Profile section */}
              <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '18px' }}>Profile</div>

                {/* Avatar row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '20px' }}>
                  <div style={{
                    width: '52px',
                    height: '52px',
                    borderRadius: '50%',
                    background: '#C8102E',
                    color: '#fff',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '18px',
                    fontWeight: 700,
                    flexShrink: 0,
                  }}>
                    {initials}
                  </div>
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: '#16120E', marginBottom: '2px' }}>{name}</div>
                    <div style={{ fontSize: '12px', color: '#9A948E' }}>{email}</div>
                    <button style={{
                      marginTop: '6px',
                      fontSize: '12px',
                      color: '#C8102E',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      padding: '0',
                      fontWeight: 500,
                    }}>
                      Change photo
                    </button>
                  </div>
                </div>

                {/* Fields */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#4A4440', marginBottom: '5px' }}>Full name</label>
                    <input
                      type="text"
                      value={name}
                      onChange={e => setName(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '9px 12px',
                        borderRadius: '8px',
                        border: '1.5px solid #E7E0D8',
                        background: '#F7F3EE',
                        fontSize: '13px',
                        color: '#16120E',
                        outline: 'none',
                        fontFamily: "'DM Sans', sans-serif",
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#4A4440', marginBottom: '5px' }}>Email address</label>
                    <input
                      type="email"
                      value={email}
                      onChange={e => setEmail(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '9px 12px',
                        borderRadius: '8px',
                        border: '1.5px solid #E7E0D8',
                        background: '#F7F3EE',
                        fontSize: '13px',
                        color: '#16120E',
                        outline: 'none',
                        fontFamily: "'DM Sans', sans-serif",
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#4A4440', marginBottom: '5px' }}>Class section</label>
                    <input
                      type="text"
                      value={section}
                      onChange={e => setSection(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '9px 12px',
                        borderRadius: '8px',
                        border: '1.5px solid #E7E0D8',
                        background: '#F7F3EE',
                        fontSize: '13px',
                        color: '#16120E',
                        outline: 'none',
                        fontFamily: "'DM Sans', sans-serif",
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* Notifications section */}
              <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={{ borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Notifications</div>

                {[
                  { key: 'weeklyReport',         label: 'Weekly progress report',          sub: 'Get a summary of your scores every Monday' },
                  { key: 'challengeReminders',    label: 'Challenge reminders',             sub: 'Reminders 24 hours before a challenge is due' },
                  { key: 'classComparison',       label: 'Class comparison updates',        sub: 'Notified when your class ranking changes' },
                  { key: 'badgeAlerts',           label: 'Badge & achievement alerts',      sub: 'Celebrate when you earn a new badge' },
                ].map((item, i, arr) => (
                  <div key={item.key} style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 0',
                    borderBottom: i < arr.length - 1 ? '1px solid #F7F3EE' : 'none',
                  }}>
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 500, color: '#16120E' }}>{item.label}</div>
                      <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '2px' }}>{item.sub}</div>
                    </div>
                    <Toggle
                      checked={notifs[item.key]}
                      onChange={val => setNotifs(prev => ({ ...prev, [item.key]: val }))}
                    />
                  </div>
                ))}
              </div>

              {/* Danger zone */}
              <div style={{
                background: '#FDFCFB',
                borderRadius: '14px',
                padding: '20px',
                borderWidth: '1.5px',
                borderStyle: 'solid',
                borderColor: '#F9BFCA',
              }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#C8102E', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '14px' }}>Danger zone</div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '14px', borderBottom: '1px solid #F7F3EE', marginBottom: '14px' }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 500, color: '#16120E' }}>Reset all progress data</div>
                    <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '2px' }}>Delete all scores, session history, and badges</div>
                  </div>
                  <button style={{
                    padding: '7px 14px',
                    borderRadius: '8px',
                    border: '1.5px solid #F9BFCA',
                    background: 'transparent',
                    color: '#C8102E',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}>
                    Reset data
                  </button>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 500, color: '#16120E' }}>Delete account</div>
                    <div style={{ fontSize: '12px', color: '#9A948E', marginTop: '2px' }}>Permanently remove your account and all data</div>
                  </div>
                  <button style={{
                    padding: '7px 14px',
                    borderRadius: '8px',
                    border: 'none',
                    background: '#C8102E',
                    color: '#fff',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}>
                    Delete account
                  </button>
                </div>
              </div>

            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
