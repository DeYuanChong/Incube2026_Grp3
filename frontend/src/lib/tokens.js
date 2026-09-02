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

// The lifecycle spine: the states a defect walks through in order. Deliberately
// not STATUS_ORDER — that includes `cancelled`, which is a terminal off-ramp
// from `reported`, never a step on the way to anywhere.
export const LIFECYCLE_STEPS = [
  'reported',
  'triaged',
  'in_progress',
  'pending_verification',
  'verified',
  'closed',
]

// When each step was reached. `cancelled` never stamps closed_at (reporting
// stamps only updated_at on cancel), so it has no column of its own here.
export const STATUS_STAMP = {
  reported: 'created_at',
  triaged: 'triaged_at',
  in_progress: 'work_started_at',
  pending_verification: 'fixed_at',
  verified: 'verified_at',
  closed: 'closed_at',
}

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

// Urgency is a separate axis from severity (how bad) — how soon.
export const URGENCY = {
  emergency: { c: '#e5484d', bg: '#fdecec', label: 'Emergency' },
  urgent: { c: '#d9480f', bg: '#fdf0e7', label: 'Urgent' },
  routine: { c: '#5b6472', bg: '#f1f4f8', label: 'Routine' },
}

// Work orders carry their own enum (fixverify/app/models.py), distinct from the
// issue Status above — an issue sits at `pending_verification` while its work
// order is at `pending_human_verification`. They were sharing the issue-status
// `.badge` CSS before, which silently rendered nothing.
export const WO_STATUS_COLOR = {
  open: '#00a0c4',
  in_progress: '#0ea5a5',
  awaiting_proof: '#d9480f',
  pending_human_verification: '#8a94a6',
  verified: '#12a150',
  rejected: '#e5484d',
}

export const WO_STATUS_LABEL = {
  open: 'Not started',
  in_progress: 'Work in progress',
  awaiting_proof: 'Awaiting proof',
  pending_human_verification: 'Awaiting sign-off',
  verified: 'Verified',
  // modelled in fixverify but no code path sets it; mapped so it cannot fall
  // through as a raw enum value if one ever does
  rejected: 'Rejected',
}

// Proof verdicts: the AI relevance check and the human sign-off share this
// vocabulary because they answer the same question with different authority.
export const VERDICT = {
  relevant: { c: '#12a150', bg: '#e6f6ec', label: 'Relevant' },
  inconclusive: { c: '#b07a0c', bg: '#fdf6e3', label: 'Inconclusive' },
  irrelevant: { c: '#e5484d', bg: '#fdecec', label: 'Unrelated' },
  approved: { c: '#12a150', bg: '#e6f6ec', label: 'Approved' },
  rejected: { c: '#e5484d', bg: '#fdecec', label: 'Rejected' },
}

export const INSIGHT_KIND = {
  systemic: { c: '#d9480f', bg: '#fdf0e7', label: 'Systemic' },
  predictive: { c: '#1b65f8', bg: '#eaf1fe', label: 'Predictive' },
  'pre-emptive': { c: '#00a0c4', bg: '#e4f8fd', label: 'Pre-emptive' },
}

export const sev = (value) => SEV[value] || SEV.untriaged
export const statusLabel = (value) => STATUS_LABEL[value] || value
export const categoryLabel = (value) => CATEGORY_LABEL[value] || value
export const urgency = (value) => URGENCY[value] || null
export const woStatusLabel = (value) => WO_STATUS_LABEL[value] || value
export const woStatusColor = (value) => WO_STATUS_COLOR[value] || 'var(--muted-2)'
/** Unknown verdicts render as themselves in a neutral chip rather than crashing. */
export const verdict = (value) =>
  VERDICT[value] || { c: '#5b6472', bg: '#f1f4f8', label: value || '—' }

/** The mock's inline pill generator (`chip(c, bg)`), as a style object. */
export const chipStyle = (c, bg) => ({ color: c, background: bg })

export const initials = (name) =>
  (name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')
