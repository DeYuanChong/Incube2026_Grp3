import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, getIdentity, setIdentity } from './api'
import Shell from './components/Shell'
import AiInsights from './pages/AiInsights'
import Dashboard from './pages/Dashboard'
import FixVerify from './pages/FixVerify'
import IssueDetail from './pages/IssueDetail'
import ReportIssue from './pages/ReportIssue'

// Guards a route to a set of roles. Shell's sidebar already hides links a
// role can't use, but that's cosmetic — this is what actually stops a direct
// URL/back-button visit. If the active identity's role isn't (or is no
// longer, e.g. after switching roles in Shell) allowed here, bounce back to
// the Dashboard rather than leaving stale, inaccessible content on screen.
function RequireRole({ role, allowed, children }) {
  return allowed.includes(role) ? children : <Navigate to="/" replace />
}

export default function App() {
  const [identity, setIdentityState] = useState(getIdentity())
  const [badges, setBadges] = useState({ open: 0, insights: 0 })

  const changeIdentity = (user, role) => {
    setIdentity(user, role)
    setIdentityState({ user, role })
  }

  // Sidebar counts. Each is independent, so one dead service leaves the others
  // showing rather than blanking the whole nav.
  const refreshBadges = useCallback(() => {
    api.statsDashboard()
      .then((s) => setBadges((b) => ({ ...b, open: s.open_count })))
      .catch(() => {})
    if (identity.role === 'admin') {
      api.insights()
        .then((list) => setBadges((b) => ({ ...b, insights: list.filter((i) => i.active).length })))
        .catch(() => {})
    } else {
      setBadges((b) => ({ ...b, insights: 0 }))
    }
  }, [identity.role])

  useEffect(() => {
    refreshBadges()
    const timer = setInterval(refreshBadges, 10000)
    return () => clearInterval(timer)
  }, [refreshBadges, identity.user])

  const { role } = identity
  return (
    <Shell identity={identity} onIdentityChange={changeIdentity} badges={badges}>
      <Routes>
        <Route path="/" element={<Dashboard identity={identity} />} />
        <Route
          path="/insights"
          element={
            <RequireRole role={role} allowed={['admin']}>
              <AiInsights />
            </RequireRole>
          }
        />
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
          path="/fix-verify"
          element={
            <RequireRole role={role} allowed={['maintenance', 'admin']}>
              <FixVerify />
            </RequireRole>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
