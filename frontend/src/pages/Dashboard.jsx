// Defects Management, ported from the CPS Defects Portal canvas mock:
// four KPI tiles, four rows of filter chips, and a grid table with ageing.
//
// The tiles come from GET /stats/dashboard, computed over the caller's whole
// scoped population, so the headline numbers are never capped by the table's
// page. The chips filter the fetched rows in the browser, which keeps the
// mock's instant feel — the two read different things on purpose, and the
// table says how many rows it is showing.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import {
  EmptyState,
  ErrorState,
  KpiCard,
  Pills,
  Segmented,
  SeverityBars,
  SeverityChip,
  Spinner,
  StatusCell,
} from '../components/ui'
import {
  AGE_BUCKETS,
  ageLabel,
  locationLabel,
  matchesAgeFilter,
  monthLabel,
  num,
  pct,
  signed,
  slaLabel,
  slaState,
} from '../lib/format'
import {
  CATEGORY_ORDER,
  SEVERITY_ORDER,
  STATUS_ORDER,
  categoryLabel,
  sev as sevToken,
  statusLabel,
} from '../lib/tokens'

const CATEGORY_FILTERS = ['All', ...CATEGORY_ORDER]
const SEVERITY_FILTERS = ['All', ...SEVERITY_ORDER]
const SETTLED = ['closed', 'cancelled']
const ROW_LIMIT = 500

const SLA_TONE = { danger: 'var(--danger)', warn: 'var(--warn)', muted: 'var(--muted-2)' }

// `openOnly` is its own dimension rather than a pretend status: the status
// pills are exactly the reporting.issues.status enum, and "open" is the
// complement of the two terminal states, not a value of the column.
const EMPTY_FILTERS = {
  category: 'All', status: 'All', severity: 'All', age: 'All', openOnly: false,
}

export default function Dashboard({ identity }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [issues, setIssues] = useState(null)
  const [stats, setStats] = useState(null)
  const [issuesError, setIssuesError] = useState(null)
  const [statsError, setStatsError] = useState(null)
  const [filters, setFilters] = useState(() => {
    // AI insights deep-links in with ?open=1&category=lighting&q=Block A / L3
    const status = searchParams.get('status')
    return {
      ...EMPTY_FILTERS,
      status: STATUS_ORDER.includes(status) ? status : 'All',
      category: CATEGORY_ORDER.includes(searchParams.get('category'))
        ? searchParams.get('category')
        : 'All',
      openOnly: searchParams.get('open') === '1',
    }
  })
  const [q, setQ] = useState(searchParams.get('q') || '')
  const [sevView, setSevView] = useState('chips')

  const load = useCallback(() => {
    setIssuesError(null)
    setStatsError(null)
    // Role scoping is resolved server-side from X-Role/X-User, so this asks for
    // everything the caller is allowed to see and nothing more.
    api.listIssues({ limit: ROW_LIMIT })
      .then(setIssues)
      .catch((err) => { setIssues([]); setIssuesError(err) })
    api.statsDashboard()
      .then(setStats)
      .catch((err) => { setStats(null); setStatsError(err) })
  }, [identity.user, identity.role])

  useEffect(load, [load])

  // A deep link from the insights page should not survive a filter reset.
  useEffect(() => {
    if (searchParams.toString()) setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])

  const set = (patch) => setFilters((prev) => ({ ...prev, ...patch }))
  const clear = () => { setFilters(EMPTY_FILTERS); setQ('') }

  const rows = useMemo(() => {
    if (!issues) return []
    const needle = q.trim().toLowerCase()
    return issues
      .filter((issue) => {
        if (filters.category !== 'All' && issue.category !== filters.category) return false
        if (filters.openOnly && SETTLED.includes(issue.status)) return false
        if (filters.status !== 'All' && issue.status !== filters.status) return false
        if (filters.severity !== 'All') {
          const value = issue.severity || 'untriaged'
          if (value !== filters.severity) return false
        }
        if (!matchesAgeFilter(issue, filters.age)) return false
        if (!needle) return true
        return [
          issue.reference_no, issue.title, issue.description,
          // the equipment is shown in the row, so it must be searchable —
          // the insights page also deep-links on it
          issue.equipment_name,
          categoryLabel(issue.category), locationLabel(issue),
        ].filter(Boolean).join(' ').toLowerCase().includes(needle)
      })
      // The mock's order: worst severity first, then oldest — an untriaged
      // issue ranks 0, so it does not jump the queue on an absent value.
      .sort((a, b) => {
        const rank = sevToken(b.severity).rank - sevToken(a.severity).rank
        return rank || Date.parse(a.created_at) - Date.parse(b.created_at)
      })
  }, [issues, filters, q])

  const month = stats?.month
  const breachDays = stats?.sla_breach_days ?? 30

  // Offer only the statuses this caller is scoped to. The server states the
  // scope, so the pill row cannot drift from what the table can contain.
  // "All" and "Open" stay: they are aggregates, not statuses, and for
  // maintenance "Open" is still a real subset (it drops closed and cancelled).
  const statusOptions = useMemo(() => {
    const allowed = stats?.scope?.statuses
    const scoped = allowed ? STATUS_ORDER.filter((s) => allowed.includes(s)) : STATUS_ORDER
    return ['All', ...scoped]
  }, [stats])

  // Switching role can leave a filter selected that the new scope cannot show
  // (admin filtering on Reported, then switching to maintenance). Without this
  // the table reads as empty with no visible cause.
  useEffect(() => {
    if (!statusOptions.includes(filters.status)) set({ status: 'All' })
  }, [statusOptions, filters.status])

  return (
    <div className="stack">
      {statsError ? (
        <div className="card"><ErrorState error={statsError} onRetry={load} /></div>
      ) : (
        <div className="kpi-grid">
          <KpiCard
            label="Open defects"
            value={stats ? stats.open_count : '·'}
            delta="view all →"
            deltaTone="accent"
            note={
              stats
                ? `${stats.total_count} reported in total`
                : 'Loading the scoped population'
            }
            active={filters.openOnly}
            onClick={() => set({ ...EMPTY_FILTERS, openOnly: !filters.openOnly })}
          />
          <KpiCard
            label={`Past SLA · ${breachDays}d`}
            value={stats ? stats.sla.breached : '·'}
            delta={stats?.sla.breached ? 'action' : null}
            deltaTone="danger"
            note={
              !stats
                ? 'Open longer than the SLA and not yet settled'
                : stats.sla.breach_rate === null
                  ? 'No open work to age'
                  : `${pct(stats.sla.breach_rate)} of open work · ${stats.age_buckets['30+']} over ${breachDays} days`
            }
            active={filters.age === 'Past SLA'}
            onClick={() => set({ ...EMPTY_FILTERS, age: 'Past SLA' })}
          />
          <KpiCard
            label={`Avg MTTR · ${monthLabel(month?.key)}`}
            value={num(month?.avg_mttr_days, 'd')}
            delta={signed(month?.mttr_delta_days, 'd')}
            deltaTone={month?.mttr_delta_days > 0 ? 'warn' : 'ok'}
            note={
              month?.avg_mttr_days === null || month?.avg_mttr_days === undefined
                ? 'No repairs recorded this month'
                : `${month.repaired} repaired · median ${num(month.median_repair_days, 'd')}`
            }
          />
          <KpiCard
            label={`Closed · ${monthLabel(month?.key)}`}
            value={month ? month.closed : '·'}
            delta={month?.avg_mttc_days ? `${month.avg_mttc_days}d avg` : null}
            deltaTone="ok"
            note={
              month
                ? `${month.verified} verified · ${month.cancelled} cancelled`
                : 'Closed and verified this month'
            }
          />
        </div>
      )}

      <div className="filter-card">
        <Pills
          legend="Category" options={CATEGORY_FILTERS} value={filters.category}
          onChange={(v) => set({ category: v })} labelOf={(v) => (v === 'All' ? 'All' : categoryLabel(v))}
        />
        <Pills
          legend="Status" options={statusOptions} value={filters.status}
          onChange={(v) => set({ status: v })}
          labelOf={(v) => (v === 'All' ? v : statusLabel(v))}
        />
        <Pills
          legend="Severity" options={SEVERITY_FILTERS} value={filters.severity}
          onChange={(v) => set({ severity: v })}
          labelOf={(v) => (v === 'All' ? 'All' : sevToken(v).label)}
        />
        <div
          className="filter-row"
          style={{
            justifyContent: 'space-between',
            borderTop: '1px solid var(--border-soft)',
            paddingTop: 12,
          }}
        >
          <Pills
            legend="Age / SLA" options={AGE_BUCKETS} value={filters.age}
            onChange={(v) => set({ age: v })}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <button className="linkish" onClick={clear}>Clear filters</button>
            <span style={{ fontSize: 11.5, color: 'var(--muted-2)' }}>Severity display</span>
            <Segmented
              value={sevView}
              onChange={setSevView}
              options={[
                { value: 'chips', label: 'Chips' },
                { value: 'bars', label: 'Escalation bars' },
              ]}
            />
          </div>
        </div>
      </div>

      <div className="table-card">
        <div className="table-head">
          <div className="search">
            <span style={{ color: 'var(--muted-2)', fontSize: 13 }}>⌕</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search ref, title, location, keyword"
              aria-label="Search defects"
            />
          </div>
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            <span style={{ fontWeight: 600, color: 'var(--text)' }}>{rows.length}</span>
            {issues && issues.length >= ROW_LIMIT ? ` of the newest ${ROW_LIMIT}` : ''}
            {rows.length === 1 ? ' defect matches' : ' defects match'}
          </div>
        </div>

        <div className="table-scroll">
          <div className="grid-row grid-header">
            <div>Ref</div><div>Defect</div><div>Location</div>
            <div>Status</div><div>Severity</div>
            <div style={{ textAlign: 'right' }}>Age / SLA</div>
          </div>

          {issues === null && <Spinner label="Loading defects…" />}
          {issuesError && <ErrorState error={issuesError} onRetry={load} />}
          {issues !== null && !issuesError && rows.length === 0 && (
            <EmptyState
              title={issues.length === 0 ? 'No defects to show' : 'No defects match these filters'}
              hint={
                issues.length === 0
                  ? identity.role === 'reporter'
                    ? 'Issues you report will appear here.'
                    : 'Nothing has reached your queue yet.'
                  : 'Clear the filters to see the full list.'
              }
            />
          )}
          {rows.map((issue) => (
            <Row key={issue.id} issue={issue} sevView={sevView} breachDays={breachDays} />
          ))}
        </div>
      </div>
    </div>
  )
}

function Row({ issue, sevView, breachDays }) {
  const { breached, daysOver } = slaState(issue)
  const sla = slaLabel(issue)
  const repeats = issue.duplicate_count > 1 ? issue.duplicate_count : 0

  return (
    <div className={`grid-row grid-body${breached ? ' breached' : ''}`}>
      <div className="cell-mono">
        <Link to={`/issues/${issue.id}`}>{issue.reference_no}</Link>
      </div>

      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Link
            to={`/issues/${issue.id}`}
            className="cell-truncate"
            style={{ fontWeight: 500, color: 'var(--text)' }}
          >
            {issue.title}
          </Link>
          {/* duplicate_count >= 3 is what actually bumps severity (docs/05) */}
          {repeats >= 3 && (
            <span style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--accent)', flex: '0 0 auto' }}>
              ▲ {repeats} reports
            </span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--muted-2)', marginTop: 3 }}>
          {categoryLabel(issue.category)}
          {repeats > 0 && ` · ${repeats} report${repeats > 1 ? 's' : ''}`}
          {issue.equipment_name && ` · ${issue.equipment_name}`}
        </div>

        {breached && (
          <div className="ai-frame" style={{ marginTop: 8 }}>
            <div
              style={{
                padding: '7px 9px', display: 'flex', alignItems: 'center',
                gap: 9, boxSizing: 'border-box',
              }}
            >
              <span className="ai-dot" />
              <span style={{ fontSize: 11, lineHeight: 1.4, color: 'var(--muted)', flex: 1, minWidth: 0 }}>
                Day {Math.floor(daysOver + breachDays)} of a {breachDays}-day SLA, still{' '}
                {statusLabel(issue.status).toLowerCase()}.
              </span>
              <Link
                to={`/issues/${issue.id}`}
                style={{
                  flex: '0 0 auto', background: 'var(--grad)', color: '#fff',
                  fontSize: 11, fontWeight: 600, padding: '6px 10px', borderRadius: 8,
                }}
              >
                Review
              </Link>
            </div>
          </div>
        )}
      </div>

      <div className="cell-truncate" style={{ color: 'var(--muted)', fontSize: 12.5 }}>
        {locationLabel(issue)}
      </div>

      <StatusCell value={issue.status} />

      <div style={{ minWidth: 0 }}>
        {sevView === 'chips' ? (
          <SeverityChip value={issue.severity} />
        ) : (
          <SeverityBars
            value={issue.severity}
            note={
              issue.urgency
                ? `${issue.urgency}${repeats > 1 ? ` · ${repeats} reports` : ''}`
                : 'not triaged yet'
            }
          />
        )}
      </div>

      <div style={{ textAlign: 'right', minWidth: 0 }}>
        <div
          style={{
            fontSize: 12, fontWeight: 600, fontFamily: 'var(--mono)', color: 'var(--text-2)',
          }}
        >
          {ageLabel(issue)}
        </div>
        <div style={{ fontSize: 10.5, marginTop: 3, fontWeight: 600, color: SLA_TONE[sla.tone] }}>
          {sla.text}
        </div>
      </div>
    </div>
  )
}
