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
};

// Project.status → tailwind tint. Mirrors the pipeline state machine.
export const STATUS_TINT = {
  draft: 'bg-zinc-500/15 text-zinc-300',
  assets: 'bg-amber-500/15 text-amber-300',
  render: 'bg-cyan-500/15 text-cyan-300',
  review: 'bg-violet-500/15 text-violet-300',
  scheduled: 'bg-blue-500/15 text-blue-300',
  published: 'bg-emerald-500/15 text-emerald-300',
  failed: 'bg-red-500/15 text-red-300',
};

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
