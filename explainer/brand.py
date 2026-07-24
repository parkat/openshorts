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
    "tts_tone": "Read like a top science-explainer YouTuber hooking a viewer: confident, punchy, fast-paced and energetic, with strong emphasis on the key words and a sense of intrigue and urgency",
    # Subtle VHS treatment on the Remotion composite (kept tasteful, not gimmicky).
    "vhs": {"scanlines": True, "grain": "light", "chroma_wobble": "subtle"},

    # Chosen 2026-07-22: rainbow retro letterform mark + full wordmark.
    "logo": "assets/brand/logo-mark.png",       # primary mark (corner bug / intro)
    "wordmark": "assets/brand/wordmark.png",    # SCIENTIFIC AWARENESS (intro / end card)
}


# --- MOODS ------------------------------------------------------------------
# A mood overrides the palette, the TTS delivery, and the generated-aid art
# direction for a batch whose subject demands a different register (e.g. an
# investigative/warning piece vs. the default upbeat explainer). Selected per
# project via draft.script["mood"]; falls back to "default".
MOODS = {
    "default": {
        "palette": BRAND["palette"],
        "highlight": "#FFD21E",
        "voice": BRAND.get("voice"),
        "speed": 1.0,
        "tts_tone": BRAND["tts_tone"],
        "aid_style": None,          # None = aid.py's standard cream/teal STYLE
        "vhs": BRAND.get("vhs"),
    },
    # Dark: investigative / grave. Near-black ground, cold steel + warning amber,
    # blood red for the accusation beats. Delivery is measured and heavy.
    "dark": {
        "palette": {
            "red":    "#B4342B",
            "orange": "#C2762E",
            "yellow": "#D6A63C",
            "teal":   "#3E6E78",
            "blue":   "#3C5B84",
            "purple": "#5B4472",
            "cream":  "#0E1013",   # background (near-black)
            "ink":    "#ECE8E1",   # text (bone white)
        },
        "highlight": "#FFC93C",     # amber — max legibility on dark footage
        # Approved by parkat 2026-07-24 after A/B: Charon at 1.08. NOTE the word
        # "deep" was deliberately REMOVED — pitch words make Gemini drag the vowels
        # (the same line ran 26.8s with "deep" vs 22.4s without, a 16% slowdown).
        "voice": "Charon",
        "speed": 1.08,
        "tts_tone": ("a strong, persuasive tone warning a serious audience of "
                     "impending doom"),
        "aid_style": (
            ". Flat 2D vector motion-graphic animation, stark minimal design, solid flat "
            "color fills, crisp sharp edges, heavy dark outlines. Deep near-black charcoal "
            "background, severe limited palette of cold steel blue and warning amber with "
            "sparing blood red. High contrast, ominous, restrained. Slow deliberate motion. "
            "Static locked-off camera, vertical composition. Completely WORDLESS: every "
            "speech bubble, sign, screen and label is EMPTY or holds only simple abstract "
            "glyphs — never written words or letterforms."
        ),
        "vhs": {"scanlines": True, "grain": "light", "chroma_wobble": "subtle"},
    },
}


def mood(name=None):
    """Resolve a mood preset by name (unknown/None -> default)."""
    return MOODS.get((name or "default"), MOODS["default"])
