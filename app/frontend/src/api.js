// Thin fetch wrapper. Relative /api URLs work in dev (Vite proxy) and in
// production (FastAPI serves the built app on the same origin).
async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json()).detail
    } catch {
      detail = res.statusText
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return null
  return res.json()
}

export default {
  getConfig: () => request('/config'),
  updateConfig: (data) => request('/config', { method: 'PUT', body: JSON.stringify(data) }),
  suggestTerms: (prompt, model) =>
    request('/config/suggest-terms', { method: 'POST', body: JSON.stringify({ prompt, model }) }),
  getJobs: (params) => request('/jobs?' + new URLSearchParams(params).toString()),
  setJobState: (id, user_state) =>
    request(`/jobs/${encodeURIComponent(id)}/state`, {
      method: 'POST',
      body: JSON.stringify({ user_state }),
    }),
  rematch: (scope = 'all') => request('/jobs/rematch?scope=' + scope, { method: 'POST' }),
  clearJobs: () => request('/jobs/clear', { method: 'POST' }),
  startRun: () => request('/run', { method: 'POST' }),
  getRunStatus: () => request('/run/status'),
  getStats: () => request('/stats'),
  chat: (messages, model) => request('/chat', { method: 'POST', body: JSON.stringify({ messages, model }) }),
}
