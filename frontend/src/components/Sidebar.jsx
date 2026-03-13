import { useNavigate, useLocation } from 'react-router-dom'

const NAV = [
  {
    group: 'Learn',
    items: [
      { label: 'Dashboard',       path: '/dashboard', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> },
      { label: 'Challenges',      path: '/challenges', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>, badge: '3' },
      { label: 'Workspace',       path: '/workspace',  icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
    ],
  },
  {
    group: 'Compete',
    items: [
      { label: 'Classroom',       path: '/classroom', icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> },
    ],
  },
  {
    group: 'Account',
    items: [
      { label: 'My Progress',     path: '/progress',    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg> },
      { label: 'Instructor View', path: '/instructor',  icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>, badge: 'New', badgeGreen: true },
      { label: 'Settings',        path: '/settings',    icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg> },
    ],
  },
]

export default function Sidebar({ onLogout }) {
  const navigate = useNavigate()
  const location = useLocation()
  const user = JSON.parse(localStorage.getItem('user') || 'null')
  const initials = user?.name ? user.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() : 'U'
  const score = 68 // TODO: pull from user stats

  return (
    <div className="w-[220px] bg-white border-r border-r-[#E7E0D8] flex flex-col fixed top-0 left-0 bottom-0 z-50" style={{ borderRightWidth: '1.5px' }}>

      {/* Logo */}
      <div className="px-5 pt-[22px] pb-[18px] border-b border-[#E7E0D8]" style={{ borderBottomWidth: '1.5px' }}>
        <div className="flex items-center gap-[10px] mb-[3px]">
          <div className="w-8 h-8 bg-[#C8102E] rounded-[9px] flex items-center justify-center flex-shrink-0">
            <svg viewBox="0 0 24 24" className="w-4 h-4 stroke-white fill-none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="4" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="20" cy="16" r="2"/>
              <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
            </svg>
          </div>
          <span className="font-serif text-[19px] text-[#16120E]">Husky AI</span>
        </div>
        <div className="text-[10px] text-[#9A948E] italic pl-[42px]">Be an AI-Ready Husky!</div>
      </div>

      {/* Nav */}
      <div className="px-[10px] py-[14px] flex-1 overflow-y-auto">
        {NAV.map(({ group, items }) => (
          <div key={group}>
            <div className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[1.2px] px-[10px] pt-3 pb-[5px]">{group}</div>
            {items.map(({ label, path, icon, badge, badgeGreen }) => {
              const active = location.pathname === path
              return (
                <a
                  key={path}
                  onClick={() => navigate(path)}
                  className={`flex items-center gap-[10px] px-3 py-[9px] rounded-[9px] text-[13px] font-medium cursor-pointer mb-[1px] transition-all duration-[120ms] no-underline
                    ${active
                      ? 'bg-[#FDE8EC] text-[#C8102E] font-semibold'
                      : 'text-[#4A4440] hover:bg-[#F7F3EE] hover:text-[#16120E]'
                    }`}
                >
                  <span className={`w-[15px] h-[15px] flex-shrink-0 ${active ? 'text-[#C8102E]' : ''}`}>{icon}</span>
                  {label}
                  {badge && (
                    <span className={`ml-auto text-[10px] font-bold px-[7px] py-[2px] rounded-[20px] text-white ${badgeGreen ? 'bg-[#16A34A]' : 'bg-[#F97316]'}`}>
                      {badge}
                    </span>
                  )}
                </a>
              )
            })}
          </div>
        ))}
      </div>

      {/* User card */}
      <div className="m-[10px] p-3 rounded-[12px] bg-[#F7F3EE] border border-[#E7E0D8]" style={{ borderWidth: '1.5px' }}>
        <div className="flex items-center gap-[10px]">
          <div className="w-8 h-8 rounded-full bg-[#C8102E] text-white flex items-center justify-center text-[12px] font-bold flex-shrink-0">
            {initials}
          </div>
          <div>
            <div className="text-[13px] font-semibold text-[#16120E]">{user?.name || 'User'}</div>
            <div className="text-[11px] text-[#9A948E]">{user?.email?.split('@')[0] || ''}</div>
          </div>
        </div>
        <div className="mt-[10px] pt-[10px] border-t border-[#E7E0D8]">
          <div className="flex justify-between items-center mb-[5px]">
            <span className="text-[10px] font-semibold text-[#9A948E] uppercase tracking-[0.5px]">Husky Score</span>
            <span className="text-[14px] font-bold text-[#C8102E]">{score}</span>
          </div>
          <div className="h-1 bg-[#E7E0D8] rounded-full">
            <div className="h-1 bg-[#C8102E] rounded-full" style={{ width: `${score}%` }} />
          </div>
        </div>
        {onLogout && (
          <button
            onClick={onLogout}
            className="mt-2 w-full text-[11px] text-[#9A948E] hover:text-[#C8102E] transition-colors text-left"
          >
            Sign out
          </button>
        )}
      </div>
    </div>
  )
}
