// Thin fetch helpers for the explainer lane. All calls go through getApiUrl so
// they work in dev (vite proxy) and prod (same-origin behind Cloudflare Access).
import { getApiUrl } from '../../config';

const BASE = '/api/explainer';

async function jsonOrThrow(res) {
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

const postJson = (path, body) => fetch(getApiUrl(`${BASE}${path}`), {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
}).then(jsonOrThrow);

export const explainerApi = {
  queue: () => fetch(getApiUrl(`${BASE}/queue`)).then(jsonOrThrow),
  project: (id) => fetch(getApiUrl(`${BASE}/projects/${id}`)).then(jsonOrThrow),
  postkit: (id) => fetch(getApiUrl(`${BASE}/projects/${id}/postkit`)).then(jsonOrThrow),
  cacheStats: () => fetch(getApiUrl(`${BASE}/cache/stats`)).then(jsonOrThrow),
  cacheItems: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return fetch(getApiUrl(`${BASE}/cache/items${q ? `?${q}` : ''}`)).then(jsonOrThrow);
  },
  cacheDelete: (id) => fetch(getApiUrl(`${BASE}/cache/items/${id}`), { method: 'DELETE' }).then(jsonOrThrow),
  job: (jobId) => fetch(getApiUrl(`${BASE}/jobs/${jobId}`)).then(jsonOrThrow),
  // stage runners → { job_id }
  script: (topicId, opts = {}) => postJson('/script', { topic_id: topicId, ...opts }),
  clipfind: (id, opts = {}) => postJson('/clipfind', { project_id: id, ...opts }),
  factcheck: (id, opts = {}) => postJson('/factcheck', { project_id: id, ...opts }),
  assets: (id, opts = {}) => postJson('/assets', { project_id: id, ...opts }),
  align: (id, opts = {}) => postJson('/align', { project_id: id, ...opts }),
  render: (id, opts = {}) => postJson('/render', { project_id: id, ...opts }),
  schedule: (id) => postJson('/schedule', { project_id: id }),
  // direct (non-job) actions
  approve: (id) => postJson(`/drafts/${id}/approve`, {}),
  // topics
  topics: () => fetch(getApiUrl(`${BASE}/topics`)).then(jsonOrThrow),
  addTopic: (body) => postJson('/topics', body),
  approveTopic: (id, accentSources = []) => postJson(`/topics/${id}/approve`, { accent_sources: accentSources }),
  // gate 1
  saveScript: (id, script) => fetch(getApiUrl(`${BASE}/drafts/${id}/script`), {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ script }),
  }).then(jsonOrThrow),
  resolveFlag: (id, kind, target) => postJson(`/flags/${id}/resolve`, { kind, target }),
  // scheduler
  scheduleList: () => fetch(getApiUrl(`${BASE}/schedule`)).then(jsonOrThrow),
  cancelScheduled: (itemId) => fetch(getApiUrl(`${BASE}/schedule/${itemId}`), { method: 'DELETE' }).then(jsonOrThrow),
  clearFailedSchedule: () => postJson('/schedule/clear-failed', {}),
  // reject + learn
  reject: (id, reason, tags = []) => postJson(`/projects/${id}/reject`, { reason, tags }),
  feedback: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null)).toString();
    return fetch(getApiUrl(`${BASE}/feedback${q ? `?${q}` : ''}`)).then(jsonOrThrow);
  },
};

// Project.status → tailwind tint. Mirrors the pipeline state machine.
export const STATUS_TINT = {
  draft: 'bg-zinc-500/15 text-zinc-300',
  assets: 'bg-amber-500/15 text-amber-300',
  render: 'bg-cyan-500/15 text-cyan-300',
  review: 'bg-violet-500/15 text-violet-300',
  scheduled: 'bg-blue-500/15 text-blue-300',
  published: 'bg-emerald-500/15 text-emerald-300',
  rejected: 'bg-red-500/15 text-red-300',
  failed: 'bg-red-500/15 text-red-300',
};

// Category tags for a rejection — help route lessons + keep reasons consistent.
export const REJECT_TAGS = ['hook', 'pacing', 'script', 'captions', 'visuals', 'audio', 'accuracy', 'other'];

export function humanBytes(n) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = Number(n) || 0;
  for (const u of units) {
    if (v < 1024 || u === 'TB') return `${u === 'B' ? v : v.toFixed(1)}${u}`;
    v /= 1024;
  }
  return `${v}B`;
}

export { getApiUrl };
