// Shared subtitle-style helpers so the Subtitle modal (single clip) and the batch
// runner (many clips) build byte-identical Remotion configs from the same saved
// settings. A "settings" object is the raw modal state; a preset stores exactly
// this shape.

export const DEFAULT_SUBTITLE_SETTINGS = {
    positionY: 85,          // vertical %, 0=top .. 100=bottom (single source of truth)
    fontSize: 28,
    fontName: 'Verdana',
    fontColor: '#FFFFFF',
    highlightColor: '#FFDD00',
    borderColor: '#000000',
    borderWidth: 2,
    bgColor: '#000000',
    bgOpacity: 0.0,
    animation: 'pop',
};

// Coarse zone from the fine vertical %, used for the FFmpeg fallback + UI highlight.
export function positionZone(positionY) {
    return positionY <= 33 ? 'top' : positionY >= 66 ? 'bottom' : 'middle';
}

// FFmpeg fallback: map vertical % to an ASS MarginV (PlayResY=288 virtual units).
export function ffMarginV(positionY) {
    const zone = positionZone(positionY);
    return zone === 'top' ? Math.round((positionY / 100) * 288)
        : zone === 'bottom' ? Math.round(((100 - positionY) / 100) * 288)
        : 25;
}

// Build the Remotion subtitle config for a clip from saved settings + its captions.
export function buildSubtitleConfig(settings, captions) {
    const s = { ...DEFAULT_SUBTITLE_SETTINGS, ...(settings || {}) };
    return {
        captions: captions || [],
        position: positionZone(s.positionY),
        positionY: s.positionY,
        style: {
            fontFamily: s.fontName,
            fontSize: s.fontSize * 2.2,       // scale up for 1080p (modal size is for the small preview)
            fontColor: s.fontColor,
            highlightColor: s.highlightColor,
            borderColor: s.borderColor,
            borderWidth: s.borderWidth * 1.5,
            bgColor: s.bgColor,
            bgOpacity: s.bgOpacity,
            animation: s.animation,
        },
    };
}

// The flat payload the FFmpeg fallback (/api/subtitle) expects, from settings.
export function ffSubtitlePayload(settings) {
    const s = { ...DEFAULT_SUBTITLE_SETTINGS, ...(settings || {}) };
    return {
        position: positionZone(s.positionY),
        margin_v: ffMarginV(s.positionY),
        font_size: s.fontSize,
        font_name: s.fontName,
        font_color: s.fontColor,
        border_color: s.borderColor,
        border_width: s.borderWidth,
        bg_color: s.bgColor,
        bg_opacity: s.bgOpacity,
    };
}

// Fetch a clip's word-level captions (returns [] if unavailable).
export async function fetchClipCaptions(getApiUrl, jobId, clipIndex) {
    try {
        const res = await fetch(getApiUrl(`/api/clip/${jobId}/${clipIndex}/transcript`));
        if (!res.ok) return { captions: [], durationSec: 30 };
        const data = await res.json();
        return { captions: data?.captions || [], durationSec: data?.durationSec || 30 };
    } catch {
        return { captions: [], durationSec: 30 };
    }
}
