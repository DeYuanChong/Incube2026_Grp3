// Age, SLA and location formatting. The codebase had no formatters at all —
// dates were `new Date(x).toLocaleString()` inline and durations were string
// templates — so these live here for every page to share.

/**
 * SLA breach rule. Must stay identical to reporting/app/config.py:
 *   SLA_BREACH_DAYS = 30
 *   SLA_SETTLED_STATUSES = pending_verification | verified | closed | cancelled
 * The server is the authority for the KPI counts; this mirror only decides how
 * a row is drawn, so the two are asserted against each other in verification.
 */
export const SLA_BREACH_DAYS = 30
export const SLA_SETTLED_STATUSES = [
  'pending_verification',
  'verified',
  'closed',
  'cancelled',
]

export function ageDays(createdAt, now = Date.now()) {
  if (!createdAt) return null
  const then = Date.parse(createdAt)
  if (Number.isNaN(then)) return null
  return (now - then) / 86400000
}

/**
 * `{ age, breached, daysOver, daysLeft, settled }` for one issue.
 * `daysLeft` is null once settled — there is no clock left to run down.
 */
export function slaState(issue, now = Date.now()) {
  const age = ageDays(issue?.created_at, now)
  const settled = SLA_SETTLED_STATUSES.includes(issue?.status)
  if (age === null) return { age: null, breached: false, daysOver: null, daysLeft: null, settled }
  const over = age - SLA_BREACH_DAYS
  const breached = !settled && over > 0
  return {
    age,
    settled,
    breached,
    daysOver: breached ? Math.floor(over) : null,
    daysLeft: settled ? null : Math.max(Math.ceil(-over), 0),
  }
}

export function ageLabel(issue, now = Date.now()) {
  const age = ageDays(issue?.created_at, now)
  return age === null ? '—' : `${Math.floor(age)}d`
}

/** The right-hand column under the age: how the SLA is going. */
export function slaLabel(issue, now = Date.now()) {
  const { age, settled, breached, daysOver, daysLeft } = slaState(issue, now)
  if (age === null) return { text: '—', tone: 'muted' }
  if (settled) return { text: 'settled', tone: 'muted' }
  if (breached) return { text: `${daysOver}d over SLA`, tone: 'danger' }
  return { text: `${daysLeft}d left`, tone: daysLeft <= 5 ? 'warn' : 'muted' }
}

export const AGE_BUCKETS = ['All', 'Within SLA', 'Past SLA', 'Over 30 days']

export function matchesAgeFilter(issue, filter, now = Date.now()) {
  if (filter === 'All') return true
  const { age, breached } = slaState(issue, now)
  if (age === null) return false
  if (filter === 'Past SLA') return breached
  if (filter === 'Within SLA') return !breached
  if (filter === 'Over 30 days') return age > SLA_BREACH_DAYS
  return true
}

export function locationLabel(issue) {
  if (!issue) return '—'
  return [issue.building, issue.floor, issue.room].filter(Boolean).join(' / ')
}

/** Durations and rates render as an em dash when the server sends null —
 *  no data is not the same as zero. */
export const num = (value, suffix = '') =>
  value === null || value === undefined ? '—' : `${value}${suffix}`

export const days = (value) => num(value, 'd')

export const pct = (rate) =>
  rate === null || rate === undefined ? '—' : `${Math.round(rate * 100)}%`

export const signed = (value, suffix = '') =>
  value === null || value === undefined ? null : `${value > 0 ? '+' : ''}${value}${suffix}`

/** Elapsed time as whole units, floored throughout.
 *
 *  Floor rather than round, so this agrees with `ageDays`/`ageLabel`/`slaState`
 *  above: a 5.7-day-old issue is "5d" in the age column and must not be "6d ago"
 *  in the timeline beside it. Flooring is also the ordinary reading of elapsed
 *  time — five whole days have passed, the sixth has not. */
export function relativeDate(iso) {
  if (!iso) return '—'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return '—'
  const mins = Math.floor((Date.now() - then) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`
  const d = Math.floor(mins / 1440)
  return d < 30 ? `${d}d ago` : new Date(then).toLocaleDateString()
}

export function monthLabel(key) {
  if (!key) return ''
  const [year, month] = key.split('-').map(Number)
  if (!year || !month) return key
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleString(undefined, {
    month: 'short',
    year: 'numeric',
  })
}
