const BASE_URL = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed: ${res.status}`);
  }

  return res.json();
}

export const api = {
  // Traces
  submitTrace: (data) => request('/trace', { method: 'POST', body: JSON.stringify(data) }),
  getTrace: (id) => request(`/trace/${id}`),
  listTraces: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/traces${query ? `?${query}` : ''}`);
  },
  listFailedTracesWithContext: () => request('/traces/failed-with-context'),

  // Analysis
  analyzeTrace: (data) => request('/analyze', { method: 'POST', body: JSON.stringify(data) }),

  // RCA & Healing
  runRCA: (data) => request('/rca', { method: 'POST', body: JSON.stringify(data) }),
  applyFix: (data) => request('/fix', { method: 'POST', body: JSON.stringify(data) }),
  compareResponses: (data) => request('/compare', { method: 'POST', body: JSON.stringify(data) }),

  // Metrics
  getMetrics: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/metrics${query ? `?${query}` : ''}`);
  },
  getCostMetrics: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/metrics/cost${query ? `?${query}` : ''}`);
  },
  getLatencyMetrics: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/metrics/latency${query ? `?${query}` : ''}`);
  },
  getStructuralFailures: () => request('/metrics/structural-failures'),
  getEvaluatorHealth: () => request('/evaluator-health'),
  recalibrateEvaluators: () =>
    request('/evaluator-health/recalibrate', { method: 'POST' }),
  getDrift: () => request('/drift'),

  // Review
  getReviewQueue: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/review/queue${query ? `?${query}` : ''}`);
  },
  labelReviewItem: (id, payload) =>
    request(`/review/${id}/label`, { method: 'POST', body: JSON.stringify(payload) }),

  // Health
  getHealth: () => request('/health'),
};
