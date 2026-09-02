// All calls go through the gateway. Demo-mode identity travels as headers.
const GATEWAY = import.meta.env.VITE_GATEWAY_URL || 'http://localhost:8000'

export function getIdentity() {
  return {
    user: localStorage.getItem('demo_user') || 'Alex Tan',
    role: localStorage.getItem('demo_role') || 'reporter',
  }
}

export function setIdentity(user, role) {
  localStorage.setItem('demo_user', user)
  localStorage.setItem('demo_role', role)
}

async function request(path, { method = 'GET', body, formData } = {}) {
  const { user, role } = getIdentity()
  const headers = { 'X-User': user, 'X-Role': role }
  if (body) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${GATEWAY}${path}`, {
    method,
    headers,
    body: formData ?? (body ? JSON.stringify(body) : undefined),
  })
  if (!res.ok) {
    let detail
    try { detail = (await res.json()).detail } catch { detail = res.statusText }
    const err = new Error(typeof detail === 'string' ? detail : detail?.message || 'request failed')
    err.detail = detail
    err.status = res.status
    throw err
  }
  return res.json()
}

/** Serialises array values as repeated params (?status=a&status=b), which
 *  `new URLSearchParams(obj)` would otherwise flatten to "a,b". */
function qs(params = {}) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v))
    else search.append(key, value)
  }
  return search.toString()
}

export const api = {
  // reporting
  createIssue: (data) => request('/api/reporting/issues', { method: 'POST', body: data }),
  suggestDescription: (data) =>
    request('/api/reporting/issues/suggest-description', { method: 'POST', body: data }),
  previewPhotoCheck: (file, { category, title, description }) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('category', category)
    formData.append('title', title)
    if (description) formData.append('description', description)
    return request('/api/reporting/issues/preview-photo-check', { method: 'POST', formData })
  },
  listIssues: (params = {}) => request(`/api/reporting/issues?${qs(params)}`),
  getIssue: (id) => request(`/api/reporting/issues/${id}`),
  acceptSuggestedCategory: (id) =>
    request(`/api/reporting/issues/${id}/accept-suggested-category`, { method: 'POST' }),
  acceptSuggestedTitle: (id) =>
    request(`/api/reporting/issues/${id}/accept-suggested-title`, { method: 'POST' }),
  acceptSuggestedDescription: (id) =>
    request(`/api/reporting/issues/${id}/accept-suggested-description`, { method: 'POST' }),
  uploadIssuePhoto: (issueId, file) => {
    const formData = new FormData()
    formData.append('file', file)
    return request(`/api/reporting/issues/${issueId}/photos`, { method: 'POST', formData })
  },
  issuePhotoUrl: (issueId, photoId) =>
    `${GATEWAY}/api/reporting/issues/${issueId}/photos/${photoId}/file`,
  closeIssue: (id, data) =>
    request(`/api/reporting/issues/${id}/close`, { method: 'POST', body: data }),
  statsLoad: () => request('/api/reporting/stats/load'),
  // Role-scoped KPI aggregates behind the dashboard tiles
  statsDashboard: (month) => request(`/api/reporting/stats/dashboard?${qs({ month })}`),

  // triage
  triageResult: (issueId) => request(`/api/triage/results/${issueId}`),
  // Body is {severity, urgency}; either may be null to mean "no override,
  // take the AI's suggestion". Sets admin_confirmed either way.
  confirmTriage: (issueId, data) =>
    request(`/api/triage/results/${issueId}/confirm`, { method: 'POST', body: data }),
  // One GET returns the whole analytics output — systemic, profiles,
  // vendor_performance and the ranked insight cards (docs/05).
  triageOverview: (by = 'location') => request(`/api/triage?${qs({ by })}`),
  // Kept for the sidebar badge, which wants the cards and nothing else.
  insights: () => request('/api/triage').then((d) => d.insights),

  // fix & verify
  listWorkOrders: (params = {}) =>
    request(`/api/fixverify/work-orders?${new URLSearchParams(params)}`),
  getWorkOrder: (id) => request(`/api/fixverify/work-orders/${id}`),
  startWorkOrder: (id, assignee) =>
    request(`/api/fixverify/work-orders/${id}/start`, { method: 'POST', body: { assignee } }),
  evidenceRecommendation: (id) =>
    request(`/api/fixverify/work-orders/${id}/evidence-recommendation`),
  uploadProof: (id, file, note) => {
    const formData = new FormData()
    formData.append('file', file)
    if (note) formData.append('note', note)
    return request(`/api/fixverify/work-orders/${id}/proofs`, { method: 'POST', formData })
  },
  proofFileUrl: (proofId) => `${GATEWAY}/api/fixverify/proofs/${proofId}/file`,
  humanVerify: (proofId, approved, notes) =>
    request(`/api/fixverify/proofs/${proofId}/human-verify`, {
      method: 'POST', body: { approved, notes },
    }),

}
