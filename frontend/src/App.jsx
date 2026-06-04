import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import AuthPage from './pages/AuthPage'
import Workspace from './pages/Workspace'
import Dashboard from './pages/Dashboard'
import Progress from './pages/Progress'
import Challenges from './pages/Challenges'
import ChallengeDetail from './pages/ChallengeDetail'
import Classroom from './pages/Classroom'
import ClassroomBrowse from './pages/ClassroomBrowse'
import Settings from './pages/Settings'
import Instructor from './pages/Instructor'
import HowItWorks from './pages/HowItWorks'
import DemoLayout from './pages/DemoLayout'
import RequireInstructor from './components/RequireInstructor'
import RequirePlatformAdmin from './components/RequirePlatformAdmin'
import ConsentGate from './components/ConsentGate'
import Admin from './pages/Admin'

function RequireAuth({ children }) {
  const token = localStorage.getItem('token')
  if (!token) return <Navigate to="/login" replace />
  return <ConsentGate>{children}</ConsentGate>
}

export default function App() {
  return (
    <BrowserRouter
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
      <Routes>
        {/* Public */}
        <Route path="/"             element={<LandingPage />} />
        <Route path="/login"        element={<AuthPage />} />
        <Route path="/how-it-works" element={<HowItWorks />} />

        {/* Public interactive demo (no auth) */}
        <Route path="/demo" element={<DemoLayout />}>
          <Route index element={<Navigate to="/demo/dashboard" replace />} />
          <Route path="workspace" element={<Workspace />} />
          <Route path="challenges" element={<Challenges />} />
          <Route path="challenges/:id" element={<ChallengeDetail />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="progress" element={<Progress />} />
          <Route path="classroom" element={<Classroom />} />
          <Route path="classroom/browse" element={<ClassroomBrowse />} />
          <Route path="instructor" element={<Instructor />} />
          <Route path="settings" element={<Settings />} />
        </Route>

        {/* Protected */}
        <Route path="/workspace"   element={<RequireAuth><Workspace /></RequireAuth>} />
        <Route path="/dashboard"   element={<RequireAuth><Dashboard /></RequireAuth>} />
        <Route path="/challenges"  element={<RequireAuth><Challenges /></RequireAuth>} />
        <Route path="/challenges/:id" element={<RequireAuth><ChallengeDetail /></RequireAuth>} />
        <Route path="/progress"    element={<RequireAuth><Progress /></RequireAuth>} />
        <Route path="/classroom"   element={<RequireAuth><Classroom /></RequireAuth>} />
        <Route path="/classroom/browse" element={<RequireAuth><ClassroomBrowse /></RequireAuth>} />
        <Route path="/instructor"  element={<RequireAuth><RequireInstructor><Instructor /></RequireInstructor></RequireAuth>} />
        <Route path="/admin"       element={<RequireAuth><RequirePlatformAdmin><Admin /></RequirePlatformAdmin></RequireAuth>} />
        <Route path="/settings"    element={<RequireAuth><Settings /></RequireAuth>} />

        {/* Redirects */}
        <Route path="/app"  element={<Navigate to="/workspace" replace />} />
        <Route path="*"     element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
