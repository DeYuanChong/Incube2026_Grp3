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

export const api = {
  // reporting
  createIssue: (data) => request('/api/reporting/issues', { method: 'POST', body: data }),
  listIssues: (params = {}) =>
    request(`/api/reporting/issues?${new URLSearchParams(params)}`),
  getIssue: (id) => request(`/api/reporting/issues/${id}`),
  acceptSuggestedCategory: (id) =>
    request(`/api/reporting/issues/${id}/accept-suggested-category`, { method: 'POST' }),
  closeIssue: (id, data) =>
    request(`/api/reporting/issues/${id}/close`, { method: 'POST', body: data }),
  statsLoad: () => request('/api/reporting/stats/load'),

  // triage
  triageResult: (issueId) => request(`/api/triage/triage/results/${issueId}`),
  runTriage: (issueId) => request(`/api/triage/triage/run/${issueId}`, { method: 'POST' }),
  confirmTriage: (issueId, data) =>
    request(`/api/triage/triage/results/${issueId}/confirm`, { method: 'POST', body: data }),
  systemic: () => request('/api/triage/analytics/systemic'),
  metrics: (groupBy = 'category') => request(`/api/triage/analytics/metrics?group_by=${groupBy}`),
  profiles: (by = 'location') => request(`/api/triage/analytics/profiles?by=${by}`),
  vendorPerformance: () => request('/api/triage/analytics/vendor-performance'),

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
  humanVerify: (proofId, approved, notes) =>
    request(`/api/fixverify/proofs/${proofId}/human-verify`, {
      method: 'POST', body: { approved, notes },
    }),

  // notifications
  notifications: (unreadOnly = false) =>
    request(`/api/notifications/notifications?unread_only=${unreadOnly}`),
  unreadCount: () => request('/api/notifications/notifications/unread-count'),
  markRead: (id) => request(`/api/notifications/notifications/${id}/read`, { method: 'POST' }),
  markAllRead: () => request('/api/notifications/notifications/read-all', { method: 'POST' }),
}
