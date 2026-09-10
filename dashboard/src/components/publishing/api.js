// Fetch helpers for the publishing calendar. Same shape as the clips lane's.
import { getApiUrl } from '../../config';

const BASE = '/api/publishing';

async function jsonOrThrow(res) {
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* non-JSON body */ }
    throw new Error(msg);
  }
  return res.json();
}

const send = (method, path, body) => fetch(getApiUrl(`${BASE}${path}`), {
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
}).then(jsonOrThrow);

export const publishingApi = {
  status: () => fetch(getApiUrl(`${BASE}/status`)).then(jsonOrThrow),
  // With a token, this tests THAT key without storing it — so you learn whether
  // a pasted token works before it replaces one that might still be good.
  connection: (token) => fetch(getApiUrl(`${BASE}/connection`), {
    headers: token ? { 'X-Buffer-Key': token } : {},
  }).then(jsonOrThrow),
  saveToken: (token) => send('POST', '/token', { token }),
  clearToken: () => fetch(getApiUrl(`${BASE}/token`), { method: 'DELETE' })
    .then(jsonOrThrow),
  queue: () => fetch(getApiUrl(`${BASE}/queue`)).then(jsonOrThrow),
  ready: () => fetch(getApiUrl(`${BASE}/ready`)).then(jsonOrThrow),
  saveSettings: (patch) => send('PUT', '/settings', patch),
  resetSettings: () => send('POST', '/settings/reset'),
  cancel: (id) => fetch(getApiUrl(`${BASE}/queue/${id}`), { method: 'DELETE' })
    .then(jsonOrThrow),
  clearFailed: (lane) => send('POST', '/queue/clear-failed', { lane: lane || null }),
  publish: (lane, refId, dueAt) => send('POST', '/publish',
    { lane, ref_id: refId, due_at: dueAt || null }),
};

export const PLATFORM_LABEL = {
  youtube: 'YouTube', tiktok: 'TikTok', instagram: 'Instagram',
};

export const LANE_LABEL = { explainer: 'Explainer', clips: 'Clips' };

export const LANE_TINT = {
  explainer: 'bg-cyan-500/15 text-cyan-300',
  clips: 'bg-violet-500/15 text-violet-300',
};

export const STATUS_TINT = {
  queued: 'bg-blue-500/15 text-blue-300',
  posted: 'bg-emerald-500/15 text-emerald-300',
  failed: 'bg-red-500/15 text-red-300',
  cancelled: 'bg-zinc-500/15 text-zinc-400',
};

// Timezones worth offering without pulling in a full IANA list. Anything else
// can still be saved — the backend validates against the real zone database.
export const COMMON_TIMEZONES = [
  'America/Los_Angeles', 'America/Denver', 'America/Chicago', 'America/New_York',
  'UTC', 'Europe/London', 'Europe/Berlin', 'Asia/Tokyo', 'Australia/Sydney',
];

export function fmtWhen(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}

export { getApiUrl };
