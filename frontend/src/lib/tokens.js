// Colour and label vocabulary for the real enums, ported from the CPS Defects
// Portal canvas mock. The mock invented eight statuses ("Assigned to vendor",
// "Pending equipment/tools"); the seven below are the ones the backend actually
// has, so the labels are prose over reporting/app/models.py:Status.

export const SEV = {
  critical: { c: '#e5484d', bg: '#fdecec', rank: 4, label: 'Critical' },
  high: { c: '#d9480f', bg: '#fdf0e7', rank: 3, label: 'High' },
  medium: { c: '#b07a0c', bg: '#fdf6e3', rank: 2, label: 'Medium' },
  low: { c: '#5b6472', bg: '#f1f4f8', rank: 1, label: 'Low' },
  // severity is nullable until triage runs — an absence, not a level
  untriaged: { c: '#8a94a6', bg: '#f2f4f8', rank: 0, label: 'Untriaged' },
}

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'untriaged']

export const STATUS_COLOR = {
  reported: '#1b65f8',
  triaged: '#00a0c4',
  in_progress: '#0ea5a5',
  pending_verification: '#8a94a6',
  verified: '#12a150',
  closed: '#5b6472',
  cancelled: '#c6cdd8',
}

export const STATUS_LABEL = {
  reported: 'Reported',
  triaged: 'Triaged',
  in_progress: 'Work in progress',
  pending_verification: 'Pending verification',
  verified: 'Verified',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

export const STATUS_ORDER = Object.keys(STATUS_LABEL)

// fixverify work orders run their own status enum, distinct from the issue's
// (services/fixverify/app/models.py:28). Passing one through STATUS_LABEL
// silently returns the raw value, so it gets its own table.
export const WORK_ORDER_LABEL = {
  open: 'Open — not started',
  in_progress: 'Work in progress',
  awaiting_proof: 'Awaiting proof of work',
  pending_human_verification: 'Awaiting CPS sign-off',
  verified: 'Verified',
  rejected: 'Proof rejected — rework needed',
}

export const workOrderLabel = (value) =>
  WORK_ORDER_LABEL[value] || (value || '').replaceAll('_', ' ') || '—'

// The mock's six categories map one-to-one onto the real Category enum.
export const CATEGORY_LABEL = {
  air_conditioning: 'Air-Conditioning',
  lighting: 'Lighting',
  cleanliness: 'Cleanliness',
  toilet: 'Toilet',
  physical_security: 'Physical Security',
  others: 'Others',
}

export const CATEGORY_ORDER = Object.keys(CATEGORY_LABEL)

// The timeline's vocabulary. Every type reporting/app/main.py writes through
// `_log_event`, plus the `status:<status>` family it emits on a transition.
// A type with no entry falls through to its raw string rather than an empty
// row — a new event added server-side stays legible until it is named here.
export const EVENT_LABEL = {
  created: 'Defect reported',
  // scripts/import_defects.py backfills history from the ITeFM export; today
  // it is the only event type in the database
  imported: 'Imported from ITeFM',
  updated: 'Details edited',
  category_accepted: 'AI category accepted',
  title_accepted: 'AI title accepted',
  description_accepted: 'AI description accepted',
  photo_uploaded: 'Photo uploaded',
  photo_category_conflict: 'Photo disagrees with the category',
  triaged: 'Triaged by AI',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

// Dot colour on the timeline rail. `ai` draws the gradient the mock reserves
// for anything a model produced; the rest are flat tokens.
export const EVENT_TONE = {
  created: 'accent',
  imported: 'muted',
  updated: 'muted',
  category_accepted: 'ai',
  title_accepted: 'ai',
  description_accepted: 'ai',
  photo_uploaded: 'muted',
  photo_category_conflict: 'warn',
  triaged: 'ai',
  closed: 'ok',
  cancelled: 'muted',
}

/** `status:in_progress` → "Work in progress", reusing STATUS_LABEL so the
 *  timeline and the status cell can never name the same state differently. */
export function eventLabel(type) {
  if (type?.startsWith('status:')) return statusLabel(type.slice(7))
  return EVENT_LABEL[type] || type || 'Event'
}

export function eventTone(type) {
  if (type?.startsWith('status:')) {
    const status = type.slice(7)
    if (status === 'verified') return 'ok'
    if (status === 'cancelled') return 'muted'
    return 'active'
  }
  return EVENT_TONE[type] || 'muted'
}

export const EVENT_DOT = {
  ai: 'var(--grad)',
  accent: 'var(--accent)',
  active: '#0ea5a5',
  ok: 'var(--ok)',
  warn: '#f5a524',
  muted: '#c6cdd8',
}

// `hint` is what the kind claims, not what the rule measured — the badges are
// the only place the three words are defined for a reader.
export const INSIGHT_KIND = {
  systemic: {
    c: '#d9480f', bg: '#fdf0e7', label: 'Systemic',
    hint: 'These tickets are one fault. A shared cause has been identified, not just volume.',
  },
  predictive: {
    c: '#1b65f8', bg: '#eaf1fe', label: 'Predictive',
    hint: 'This is getting worse against its own baseline. Nothing is named as broken yet.',
  },
  'pre-emptive': {
    c: '#00a0c4', bg: '#e4f8fd', label: 'Pre-emptive',
    hint: 'A standing condition with an obvious lever — act now and the next tickets do not arrive.',
  },
}

export const sev = (value) => SEV[value] || SEV.untriaged
export const statusLabel = (value) => STATUS_LABEL[value] || value
export const categoryLabel = (value) => CATEGORY_LABEL[value] || value

/** The mock's inline pill generator (`chip(c, bg)`), as a style object. */
export const chipStyle = (c, bg) => ({ color: c, background: bg })

export const initials = (name) =>
  (name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')

/** Icon, colour and wording for one proof, shared by the Fix & Verify board and
 *  the issue-detail card so the proof vocabulary can't drift between them. The
 *  human verdict wins where it exists — an admin's decision supersedes the
 *  model's. */
export function proofState(proof) {
  if (proof.human_verdict === 'approved') {
    return { icon: '✓', label: 'Approved', c: 'var(--ok)', bg: 'var(--ok-soft)' }
  }
  if (proof.human_verdict === 'rejected') {
    return { icon: '✕', label: 'Rejected', c: 'var(--danger)', bg: 'var(--danger-soft)' }
  }
  if (proof.ai_verdict === 'irrelevant') {
    // Submitted despite the AI: it's in the human queue, so read it as awaiting
    // sign-off (with the override called out) rather than a dead-end rejection.
    if (proof.ai_overridden) {
      return { icon: '◎', label: 'Overridden — awaiting sign-off', c: 'var(--accent)', bg: 'var(--accent-soft)' }
    }
    return { icon: '✕', label: 'AI: irrelevant', c: 'var(--danger)', bg: 'var(--danger-soft)' }
  }
  if (proof.ai_verdict === 'relevant') {
    return { icon: '◎', label: 'Awaiting sign-off', c: 'var(--accent)', bg: 'var(--accent-soft)' }
  }
  return { icon: '◎', label: 'Inconclusive', c: '#b07a0c', bg: '#fdf6e3' }
}
