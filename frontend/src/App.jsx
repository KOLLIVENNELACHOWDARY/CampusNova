import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import AdminDashboard from './pages/AdminDashboard'
import AIReview from './pages/AIReview'
import Complaints from './pages/Complaints'
import Login from './pages/Login'
import NewComplaint from './pages/NewComplaint'
import Routing from './pages/Routing'
import History from './pages/History'
import Notifications from './pages/Notifications'
import Users from './pages/Users'
import { MyWork, Pool } from './pages/Work'
import { roleHome, useAuth } from './store'

/** Redirects to /login when signed out, and to the user's own home when their role may not see the page. */
export function Protected({ roles, children }) {
  const user = useAuth((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  if (roles && !roles.includes(user.role)) return <Navigate to={roleHome(user.role)} replace />
  return children
}

const REPORTERS = ['floor_incharge', 'faculty', 'staff']

export default function App() {
  const user = useAuth((s) => s.user)
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/admin" element={<Protected roles={['admin']}><AdminDashboard /></Protected>} />
        <Route path="/reviews" element={<Protected roles={['admin']}><AIReview /></Protected>} />
        <Route path="/routing" element={<Protected roles={['admin']}><Routing /></Protected>} />
        <Route path="/users" element={<Protected roles={['admin']}><Users /></Protected>} />
        <Route path="/work" element={<Protected roles={['maintenance']}><MyWork /></Protected>} />
        <Route path="/pool" element={<Protected roles={['maintenance', 'admin']}><Pool /></Protected>} />
        <Route path="/new" element={<Protected roles={REPORTERS}><NewComplaint /></Protected>} />
        <Route path="/complaints" element={<Protected roles={[...REPORTERS, 'admin']}><Complaints /></Protected>} />
        <Route path="/history" element={<History />} />
        <Route path="/notifications" element={<Notifications />} />
      </Route>
      <Route path="*" element={<Navigate to={user ? roleHome(user.role) : '/login'} replace />} />
    </Routes>
  )
}