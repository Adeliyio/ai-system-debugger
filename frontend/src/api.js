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
  getEvaluatorHealth: () => request('/evaluator-health'),
  getDrift: () => request('/drift'),

  // Health
  getHealth: () => request('/health'),
};
