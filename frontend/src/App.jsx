import { useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { api, getIdentity, setIdentity } from './api'
import Dashboard from './pages/Dashboard'
import FixVerify from './pages/FixVerify'
import IssueDetail from './pages/IssueDetail'
import Notifications from './pages/Notifications'
import ReportIssue from './pages/ReportIssue'
import TriageBoard from './pages/TriageBoard'

// Guards a route to a set of roles. If the active identity's role isn't
// (or is no longer, e.g. after switching in the RolePicker) allowed here,
// bounce back to the Dashboard rather than leaving stale, inaccessible
// content on screen.
function RequireRole({ role, allowed, children }) {
  return allowed.includes(role) ? children : <Navigate to="/" replace />
}

// Demo mode: no login — pick who you are (docs/01-architecture.md).
function RolePicker({ identity, onChange }) {
  return (
    <span>
      <input
        style={{ width: 120, margin: 0, display: 'inline-block' }}
        value={identity.user}
        onChange={(e) => onChange(e.target.value, identity.role)}
        title="Display name"
      />{' '}
      <select
        style={{ width: 140, margin: 0, display: 'inline-block' }}
        value={identity.role}
        onChange={(e) => onChange(identity.user, e.target.value)}
      >
        <option value="reporter">Reporter</option>
        <option value="maintenance">Maintenance</option>
        <option value="admin">Admin</option>
      </select>
    </span>
  )
}

export default function App() {
  const [identity, setIdentityState] = useState(getIdentity())
  const [unread, setUnread] = useState(0)

  const changeIdentity = (user, role) => {
    setIdentity(user, role)
    setIdentityState({ user, role })
  }

  useEffect(() => {
    const poll = () => api.unreadCount().then((r) => setUnread(r.unread)).catch(() => {})
    poll()
    const t = setInterval(poll, 10000)
    return () => clearInterval(t)
  }, [identity])

  const { role } = identity
  return (
    <div className="app">
      <nav>
        <span className="brand">🛠 Defect Reporting</span>
        <NavLink to="/">Dashboard</NavLink>
        {role === 'reporter' && <NavLink to="/report">Report Issue</NavLink>}
        {role === 'admin' && <NavLink to="/triage">Triage</NavLink>}
        {(role === 'maintenance' || role === 'admin') && (
          <NavLink to="/fix-verify">Fix & Verify</NavLink>
        )}
        <NavLink to="/notifications">🔔 {unread > 0 ? `(${unread})` : ''}</NavLink>
        <span className="spacer" />
        <RolePicker identity={identity} onChange={changeIdentity} />
      </nav>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route
          path="/report"
          element={
            <RequireRole role={role} allowed={['reporter']}>
              <ReportIssue />
            </RequireRole>
          }
        />
        <Route path="/issues/:id" element={<IssueDetail />} />
        <Route
          path="/triage"
          element={
            <RequireRole role={role} allowed={['admin']}>
              <TriageBoard />
            </RequireRole>
          }
        />
        <Route
          path="/fix-verify"
          element={
            <RequireRole role={role} allowed={['maintenance', 'admin']}>
              <FixVerify />
            </RequireRole>
          }
        />
        <Route path="/notifications" element={<Notifications />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
