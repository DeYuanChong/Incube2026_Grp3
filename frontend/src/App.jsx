import { useCallback, useEffect, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { api, getIdentity, setIdentity } from './api'
import Shell from './components/Shell'
import AiInsights from './pages/AiInsights'
import Dashboard from './pages/Dashboard'
import DefectWorkspace from './pages/DefectWorkspace'
import IssueDetail from './pages/IssueDetail'
import Notifications from './pages/Notifications'
import ReportIssue from './pages/ReportIssue'
import TriageBoard from './pages/TriageBoard'

export default function App() {
  const [identity, setIdentityState] = useState(getIdentity())
  const [badges, setBadges] = useState({ unread: 0, open: 0, insights: 0 })

  const changeIdentity = (user, role) => {
    setIdentity(user, role)
    setIdentityState({ user, role })
  }

  // Sidebar counts. Each is independent, so one dead service leaves the others
  // showing rather than blanking the whole nav.
  const refreshBadges = useCallback(() => {
    api.unreadCount()
      .then((r) => setBadges((b) => ({ ...b, unread: r.unread })))
      .catch(() => {})
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

  return (
    <Shell identity={identity} onIdentityChange={changeIdentity} badges={badges}>
      <Routes>
        <Route path="/" element={<Dashboard identity={identity} />} />
        <Route path="/insights" element={<AiInsights />} />
        <Route path="/report" element={<ReportIssue />} />
        <Route path="/issues/:id" element={<IssueRoute identity={identity} />} />
        <Route path="/triage" element={<TriageBoard />} />
        <Route path="/notifications" element={<Notifications />} />
      </Routes>
    </Shell>
  )
}

// Reporters and the roles that work the defect want different things from the
// same URL: a reporter reads status and confirms the fix, maintenance and admin
// need the work order. Rather than one page bristling with role conditionals,
// the route picks the page.
function IssueRoute({ identity }) {
  return identity.role === 'reporter'
    ? <IssueDetail />
    : <DefectWorkspace identity={identity} />
}
