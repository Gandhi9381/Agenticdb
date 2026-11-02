const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => request<any>('/health'),
  dashboard: () => request<any>('/dashboard/summary'),

  // Tables
  getTables: () => request<any>('/tables'),
  getSchema: (t: string) => request<any>(`/tables/${t}/schema`),
  previewTable: (t: string, limit = 50) => request<any>(`/tables/${t}/preview?limit=${limit}`),

  // Datasets
  loadSample: (rows = 500) =>
    request<any>(`/datasets/load-sample?rows=${rows}`, { method: 'POST' }),
  uploadCSV: (file: File, tableName: string, overwrite = false) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('table_name', tableName);
    fd.append('overwrite', String(overwrite));
    return fetch(`${API}/datasets/upload`, { method: 'POST', body: fd }).then((r) =>
      r.ok ? r.json() : r.json().then((e) => Promise.reject(new Error(e.detail)))
    );
  },

  // Query
  generateSQL: (question: string, tables?: string[], history?: any[]) =>
    request<any>('/query/generate', {
      method: 'POST',
      body: JSON.stringify({ question, tables, history }),
    }),
  executeSQL: (sql: string, nl?: string) =>
    request<any>('/query/execute', {
      method: 'POST',
      body: JSON.stringify({ sql, natural_language: nl }),
    }),
  explainSQL: (sql: string) =>
    request<any>('/query/explain', { method: 'POST', body: JSON.stringify({ sql }) }),
  optimizeSQL: (sql: string) =>
    request<any>('/query/optimize', { method: 'POST', body: JSON.stringify({ sql }) }),
  queryHistory: (limit = 50) => request<any>(`/queries/history?limit=${limit}`),

  // Performance
  perfSummary: () => request<any>('/performance/summary'),
  slowQueries: () => request<any>('/performance/slow-queries'),

  // Incidents
  getIncidents: (status?: string) =>
    request<any>(`/incidents${status ? `?status=${status}` : ''}`),
  getIncident: (id: number) => request<any>(`/incidents/${id}`),
  diagnoseIncident: (id: number, query?: string, evidence?: any) =>
    request<any>(`/incidents/${id}/diagnose`, {
      method: 'POST',
      body: JSON.stringify({ query, evidence }),
    }),

  // Optimizations
  getOptimizations: () => request<any>('/optimizations'),
  getOptimization: (id: number) => request<any>(`/optimizations/${id}`),
  requestApproval: (id: number) =>
    request<any>(`/optimizations/${id}/request-approval`, { method: 'POST' }),
  executeOptimization: (optId: number, approvalId: number) =>
    request<any>(`/optimizations/${optId}/execute`, {
      method: 'POST',
      body: JSON.stringify({ approval_id: approvalId }),
    }),
  verifyIndex: (optId: number) =>
    request<any>(`/optimizations/${optId}/verify-index`),
  benchmarkOptimization: (optId: number, data: any) =>
    request<any>(`/optimizations/${optId}/benchmark`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Approvals
  getApprovals: () => request<any>('/approvals'),
  approve: (id: number, note?: string) =>
    request<any>(`/approvals/${id}/approve?note=${encodeURIComponent(note || '')}`, { method: 'POST' }),
  reject: (id: number, note?: string) =>
    request<any>(`/approvals/${id}/reject?note=${encodeURIComponent(note || '')}`, { method: 'POST' }),

  // Monitoring
  startMonitor: () => request<any>('/monitoring/start', { method: 'POST' }),
  stopMonitor: () => request<any>('/monitoring/stop', { method: 'POST' }),
  runCycle: () => request<any>('/monitoring/run-cycle', { method: 'POST' }),
  monitorStatus: () => request<any>('/monitoring/status'),

  // Experiments
  getExperiments: () => request<any>('/experiments'),
  runExperiment: (data: any) =>
    request<any>('/experiments/run', { method: 'POST', body: JSON.stringify(data) }),
};
