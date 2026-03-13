import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import AuthPage from './pages/AuthPage'
import Workspace from './pages/Workspace'
import Dashboard from './pages/Dashboard'
import Progress from './pages/Progress'
import Challenges from './pages/Challenges'
import ChallengeDetail from './pages/ChallengeDetail'
import Classroom from './pages/Classroom'
import Settings from './pages/Settings'
import Instructor from './pages/Instructor'

function RequireAuth({ children }) {
  const token = localStorage.getItem('token')
  if (!token) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public */}
        <Route path="/"      element={<LandingPage />} />
        <Route path="/login" element={<AuthPage />} />

        {/* Protected */}
        <Route path="/workspace"   element={<RequireAuth><Workspace /></RequireAuth>} />
        <Route path="/dashboard"   element={<RequireAuth><Dashboard /></RequireAuth>} />
        <Route path="/challenges"  element={<RequireAuth><Challenges /></RequireAuth>} />
        <Route path="/challenges/:id" element={<RequireAuth><ChallengeDetail /></RequireAuth>} />
        <Route path="/progress"    element={<RequireAuth><Progress /></RequireAuth>} />
        <Route path="/classroom"   element={<RequireAuth><Classroom /></RequireAuth>} />
        <Route path="/instructor"  element={<RequireAuth><Instructor /></RequireAuth>} />
        <Route path="/settings"    element={<RequireAuth><Settings /></RequireAuth>} />

        {/* Redirects */}
        <Route path="/app"  element={<Navigate to="/workspace" replace />} />
        <Route path="*"     element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
