import { Outlet, Link } from 'react-router-dom'

export default function DemoLayout() {
  return (
    <div className="min-h-screen flex flex-col bg-[#F7F3EE]">
      <div
        className="flex-shrink-0 z-[60] flex flex-wrap items-center justify-center gap-3 px-4 py-2.5 text-center"
        style={{
          background: 'linear-gradient(90deg, #16120E 0%, #3D2E28 100%)',
          borderBottom: '1.5px solid #E7E0D8',
        }}
      >
        <span className="text-[12px] font-semibold text-white tracking-wide uppercase" style={{ letterSpacing: '0.06em' }}>
          Sample data
        </span>
        <span className="text-[12px] text-white/85 max-w-[560px]">
          Full product UI without sign-in — sample data only. Sign in to save progress, join a class, and run live chat + evaluation.
        </span>
        <Link
          to="/login?tab=register"
          className="text-[12px] font-bold text-white underline decoration-white/50 hover:decoration-white"
        >
          Create account
        </Link>
        <span className="text-white/40 hidden sm:inline">·</span>
        <Link to="/login" className="text-[12px] font-bold text-[#FDE68A] hover:text-white">
          Sign in
        </Link>
      </div>
      <div className="flex-1 min-h-0">
        <Outlet />
      </div>
    </div>
  )
}
