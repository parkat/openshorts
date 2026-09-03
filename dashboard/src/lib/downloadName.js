// Build a collision-proof, human-referenceable download filename:
//   <uuid>_<ThreeWordCamelCase>.mp4   e.g.  a1b2c3d4_HowWeHacked.mp4
// The short UUID prevents overwrites across jobs / re-downloads; the 3-word
// CamelCase slug (from the clip's title) makes the file easy to eyeball.

export function shortUuid() {
    try {
        // Secure contexts (https / localhost). Falls back on plain-http LAN.
        return crypto.randomUUID().replace(/-/g, '').slice(0, 8);
    } catch {
        return Math.random().toString(16).slice(2, 10);
    }
}

export function camelWords(text, count = 3) {
    const words = String(text || '')
        .replace(/[^\p{L}\p{N}\s]/gu, ' ')  // drop punctuation, emoji, symbols
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, count)
        .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
    return words.join('') || 'OpenShortsClip';
}

// Prefer the YouTube title, then other descriptive fields.
export function clipDownloadName(clip) {
    const source = clip?.video_title_for_youtube_short
        || clip?.title
        || clip?.viral_hook_text
        || clip?.video_description_for_tiktok
        || clip?.video_description_for_instagram
        || 'OpenShorts Clip';
    return `${shortUuid()}_${camelWords(source, 3)}.mp4`;
}
