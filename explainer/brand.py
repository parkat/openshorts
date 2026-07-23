"""Scientific Awareness — brand config for the explainer lane.

Aesthetic: 1980s retro-TV / VHS — muted, flat, simple; RadioShack + early-Apple
rainbow vibe. Palette sampled from the generated logo set. Consumed by the
Remotion `ExplainerShort` theme, the caption styling, and the scheduler.
"""

BRAND = {
    "name": "Scientific Awareness",
    "channels": {                      # Buffer-connected handles (see buffer_client)
        "youtube": "Scientific Awareness",
        "tiktok": "advancementaware",
        "instagram": "user15725355",
    },

    # Publishing cadence — 1/day.
    "publish_time": "06:00",           # local wall-clock
    "timezone": "America/Los_Angeles",

    # 80s retro-TV / VHS, muted + flat.
    "aesthetic": "80s retro-TV / VHS; muted flat; RadioShack + early-Apple rainbow",
    "palette": {
        "red":    "#C1544A",
        "orange": "#D98A45",
        "yellow": "#E3C05A",
        "teal":   "#5F9E9A",
        "blue":   "#5A7BA6",
        "purple": "#8A6BA1",
        "cream":  "#F3ECD9",           # background
        "ink":    "#2E2A26",           # text
    },
    "font": {
        "display": "geometric retro sans (Eurostile / Futura family)",
        "caption": "bold condensed sans",
    },

    # Narration — Aoede voice + a spoken style directive (chosen 2026-07-22).
    "voice": "Aoede",
    "tts_model": "google/gemini-3.1-flash-tts-preview",
    # Gemini TTS style control is PROMPT-driven: `tone` is a full natural-language
    # directive prepended as "<tone>: <text>" (the model styles delivery without
    # speaking the directive). Verified to beat the OpenAI-style `instructions`
    # field. Per-run override via `assets --tone`; per-shot via shot["tone"].
    "tts_tone": "Read aloud quickly in a deep professional Narrators voice",
    # Subtle VHS treatment on the Remotion composite (kept tasteful, not gimmicky).
    "vhs": {"scanlines": True, "grain": "light", "chroma_wobble": "subtle"},

    # Chosen 2026-07-22: rainbow retro letterform mark + full wordmark.
    "logo": "assets/brand/logo-mark.png",       # primary mark (corner bug / intro)
    "wordmark": "assets/brand/wordmark.png",    # SCIENTIFIC AWARENESS (intro / end card)
}
