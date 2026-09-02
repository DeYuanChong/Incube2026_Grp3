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

export const INSIGHT_KIND = {
  systemic: { c: '#d9480f', bg: '#fdf0e7', label: 'Systemic' },
  predictive: { c: '#1b65f8', bg: '#eaf1fe', label: 'Predictive' },
  'pre-emptive': { c: '#00a0c4', bg: '#e4f8fd', label: 'Pre-emptive' },
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
