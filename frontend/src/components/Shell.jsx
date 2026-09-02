// The mock's app shell: 236px sticky sidebar plus a 62px topbar carrying the
// current screen's title. Nav items, topbar copy and the router all read from
// the same ROUTES table so they cannot drift apart.
import { NavLink, useLocation } from 'react-router-dom'
import { initials } from '../lib/tokens'

export const ROUTES = [
  {
    path: '/',
    label: 'Defects Management',
    title: 'Defects Management',
    sub: 'Live queue, ageing and SLA',
    roles: ['reporter', 'maintenance', 'admin'],
    badge: 'open',
  },
  {
    path: '/insights',
    label: 'AI insights',
    title: 'AI insights',
    sub: 'Systemic, predictive and pre-emptive signals',
    roles: ['admin'],
    badge: 'insights',
  },
  {
    path: '/report',
    label: 'Report Issue',
    title: 'Report an issue',
    sub: 'AI categorisation and an ETA on submission',
    roles: ['reporter'],
  },
  {
    path: '/triage',
    label: 'Triage',
    title: 'Triage board',
    sub: 'Confirm or override the AI suggestion',
    roles: ['admin'],
  },
  {
    path: '/notifications',
    label: 'Notifications',
    title: 'Notifications',
    sub: 'Everything addressed to you',
    roles: ['reporter', 'maintenance', 'admin'],
    badge: 'unread',
  },
]

// Not in the sidebar, but the topbar still needs to name it. Fix & Verify was
// folded in here, so this is where the work order and its proofs live too.
const DETAIL = { title: 'Defect detail', sub: 'Work order, proof of work and history' }

export function screenFor(pathname) {
  if (pathname.startsWith('/issues/')) return DETAIL
  return ROUTES.find((r) => r.path === pathname) || ROUTES[0]
}

const ROLE_LABEL = { reporter: 'Reporter', maintenance: 'Maintenance', admin: 'Admin, CPS' }

export default function Shell({ identity, onIdentityChange, badges, children }) {
  const { pathname } = useLocation()
  const screen = screenFor(pathname)
  const visible = ROUTES.filter((route) => route.roles.includes(identity.role))

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">CPS</div>
          <div>
            <div className="brand-title">Defects Portal</div>
            <div className="brand-sub">Corporate Planning &amp; Services</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {visible.map((route) => {
            const count = badges[route.badge]
            return (
              <NavLink key={route.path} to={route.path} end={route.path === '/'}>
                <span className="nav-label">
                  <span className="nav-dot" />
                  <span>{route.label}</span>
                </span>
                {count > 0 && (
                  <span className={`nav-badge${route.badge === 'unread' ? ' alert' : ''}`}>
                    {count}
                  </span>
                )}
              </NavLink>
            )
          })}
        </nav>

        {/* Demo mode: no login — pick who you are (docs/01-architecture.md). */}
        <div className="sidebar-foot">
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '0 3px' }}>
            <div className="avatar">{initials(identity.user)}</div>
            <div style={{ lineHeight: 1.3, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600 }} className="cell-truncate">
                {identity.user}
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--muted-2)' }}>
                {ROLE_LABEL[identity.role] || identity.role}
              </div>
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <input
              style={{ margin: '0 0 6px', fontSize: 12 }}
              value={identity.user}
              onChange={(e) => onIdentityChange(e.target.value, identity.role)}
              title="Display name"
              aria-label="Display name"
            />
            <select
              style={{ margin: 0, fontSize: 12 }}
              value={identity.role}
              onChange={(e) => onIdentityChange(identity.user, e.target.value)}
              aria-label="Role"
            >
              <option value="reporter">Reporter</option>
              <option value="maintenance">Maintenance</option>
              <option value="admin">Admin</option>
            </select>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, minWidth: 0 }}>
            <div className="topbar-title">{screen.title}</div>
            <div className="topbar-sub cell-truncate">{screen.sub}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, flex: '0 0 auto' }}>
            <div className="avatar">{initials(identity.user)}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>{identity.user}</div>
          </div>
        </header>
        <main className="page">{children}</main>
      </div>
    </div>
  )
}
