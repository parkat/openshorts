// Thin fetch helpers for the clips lane. All calls go through getApiUrl so they
// work in dev (vite proxy) and prod (same-origin behind Cloudflare Access).
import { getApiUrl } from '../../config';

const BASE = '/api/clips';

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

const del = (path) => fetch(getApiUrl(`${BASE}${path}`), { method: 'DELETE' }).then(jsonOrThrow);

export const clipsApi = {
  // reads
  sources: () => fetch(getApiUrl(`${BASE}/sources`)).then(jsonOrThrow),
  candidates: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== '' && v != null),
    ).toString();
    return fetch(getApiUrl(`${BASE}/candidates${q ? `?${q}` : ''}`)).then(jsonOrThrow);
  },
  candidate: (id) => fetch(getApiUrl(`${BASE}/candidates/${id}`)).then(jsonOrThrow),
  job: (jobId) => fetch(getApiUrl(`${BASE}/jobs/${jobId}`)).then(jsonOrThrow),
  // stage runners → { job_id }
  ingest: (url) => postJson('/ingest', { url }),
  moments: (sourceId, opts = {}) => postJson('/moments', { source_id: sourceId, ...opts }),
  cut: (candidateId, opts = {}) => postJson('/cut', { candidate_id: candidateId, ...opts }),
  render: (candidateId, opts = {}) => postJson('/render', { candidate_id: candidateId, ...opts }),
  run: (url, opts = {}) => postJson('/run', { url, ...opts }),
  // direct actions
  approve: (id) => postJson(`/candidates/${id}/approve`, {}),
  reject: (id) => postJson(`/candidates/${id}/reject`, {}),
  deleteCandidate: (id) => del(`/candidates/${id}`),
  deleteSource: (id) => del(`/sources/${id}`),
};

// ClipCandidate.status → tailwind tint. Mirrors the lane's state machine.
export const STATUS_TINT = {
  candidate: 'bg-zinc-500/15 text-zinc-300',
  cut: 'bg-amber-500/15 text-amber-300',
  rendered: 'bg-violet-500/15 text-violet-300',
  approved: 'bg-emerald-500/15 text-emerald-300',
  rejected: 'bg-red-500/15 text-red-300',
};

// brand.py MOODS — the render theme. '' = the brand default.
export const MOODS = ['', 'dark', 'teach'];

// How the window is assembled. `loop` rotates the clip about its payoff point so
// it opens on the punchline and ends where the punchline began — the wrap back to
// the start is continuous speech, so a repeat plays as one unbroken take.
export const EDITS = [
  { value: 'loop', label: 'Loop (payoff first)' },
  { value: 'linear', label: 'Linear' },
];

export const DEFAULT_EDIT = 'loop';

export function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h ? String(m).padStart(2, '0') : String(m);
  return `${h ? `${h}:` : ''}${mm}:${String(sec).padStart(2, '0')}`;
}

export { getApiUrl };
