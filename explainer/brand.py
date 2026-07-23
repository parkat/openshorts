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
    # Subtle VHS treatment on the Remotion composite (kept tasteful, not gimmicky).
    "vhs": {"scanlines": True, "grain": "light", "chroma_wobble": "subtle"},

    # Chosen 2026-07-22: rainbow retro letterform mark + full wordmark.
    "logo": "assets/brand/logo-mark.png",       # primary mark (corner bug / intro)
    "wordmark": "assets/brand/wordmark.png",    # SCIENTIFIC AWARENESS (intro / end card)
}
