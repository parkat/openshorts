// Thin client for the backend-synced edit presets (available on every device).
import { getApiUrl } from '../config';

export async function listPresets() {
    try {
        const res = await fetch(getApiUrl('/api/presets'));
        if (!res.ok) return [];
        const data = await res.json();
        return Array.isArray(data?.presets) ? data.presets : [];
    } catch {
        return [];
    }
}

// preset: { name, kind: 'subtitle', settings: {...} }  (id assigned by the server)
export async function savePreset(preset) {
    const res = await fetch(getApiUrl('/api/presets'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(preset),
    });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()).preset;
}

export async function deletePreset(id) {
    const res = await fetch(getApiUrl(`/api/presets/${id}`), { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return true;
}
