"""Generated visual-aid stage: turn each `aid` shot into short (<=5s) 720x1280
brand-styled clips via OpenRouter video (HappyHorse — see openrouter_client).

An `aid` beat is an animation that EXPLAINS the point (a concept made visible), not
decoration. A speaks:true aid rides the speaker's ~15s soundbite, and clips are
capped at 5s, so it becomes a MONTAGE of several staged clips that progress the same
concept; a narrated aid is one short clip.

Files land as `aid_<shot>_<n>.mp4` in the project dir; `gather_aids` wires them onto
the shot as `videos` (rendered MUTED — the audio is the AI narrator or the speaker's
baked soundbite). `generate_aids` is idempotent per clip, so it reuses anything
already on disk (a poor-man's cache until the content cache lands).
"""
import os
import glob

import openrouter_client as orc
from explainer import cache
from explainer.assets import svg as _svg   # reuse its keyword extractor for labels

AID_SHOT = "aid"
SIZE = "720x1280"          # vertical 9:16 (per parkat)
DURATION = 4               # fallback; Veo supports 4/6/8s (see openrouter_client)
DURATIONS = (4, 6, 8)      # selectable renders, ascending


def _duration_for(shot, n_clips):
    """Pick the shortest supported Veo duration that covers this clip's share of
    the beat. The script's `seconds` is an estimate and the real narration usually
    runs longer, so we bias up a little; the render also loops the clip, so a small
    under-shoot is cosmetic rather than a frozen frame."""
    try:
        beat = float(shot.get("seconds") or 0)
    except (TypeError, ValueError):
        beat = 0.0
    if beat <= 0:
        return DURATION
    per_clip = (beat / max(1, n_clips)) * 1.25   # +25% headroom for a slower read
    for d in DURATIONS:
        if d >= per_clip:
            return d
    return DURATIONS[-1]

# Brand style anchor (Veo prompting guide): name the medium up front, lock a LIMITED
# palette, and push against Veo's photoreal/gradient default with explicit flat-vector
# terms. Text/gradients/3D are excluded in the NEGATIVE field, not here. The comp adds
# VHS grain in post via VhsOverlay, so the generated clip stays CLEAN.
STYLE = (
    ". Flat 2D vector motion-graphic animation, bold clean minimal design, solid flat "
    "color fills, crisp sharp edges, consistent bold dark charcoal outlines, even flat "
    "lighting. Warm cream background, limited muted palette of teal and warm orange "
    "accents. Simple, high-contrast, smooth motion. Static locked-off camera, vertical "
    "composition. Completely WORDLESS: every speech bubble, sign, screen and label is "
    "EMPTY or holds only simple abstract glyphs (dots, wavy lines, small icons) — never "
    "written words or letterforms."
)

# Veo obeys the POSITIVE prompt over the negative field: a note that asks for
# "speech bubbles in many languages" forces it to invent garbled fake glyphs. So
# rewrite text-summoning phrases in the note itself before we ever send it.
# (Keeps existing scripts safe without regenerating them; script.py also teaches
# the writer not to ask for text in the first place.)
_TEXT_SUBS = [
    (r"\bspeech bubbles?\s+(?:in|with|of|showing|filled with)\s+[^,.;]+",
     "empty speech bubbles with small abstract glyph icons"),
    (r"\b(?:in|with)\s+(?:many|multiple|different|various|several|dozens of|100)\s+languages\b",
     "with small abstract glyph icons"),
    (r"\b(?:written|readable|legible)\s+(?:text|words?|labels?|captions?)\b",
     "abstract glyph icons"),
    (r"\b(?:text|words?|labels?|captions?|writing|letters?|headlines?)\s+(?:that\s+)?(?:reads?|saying|spelling)\s+[^,.;]+",
     "an abstract glyph icon"),
    (r"\blabell?ed\s+[\"“][^\"”]+[\"”]", "marked with an abstract glyph icon"),
]


def scrub_text_requests(note):
    """Neutralize phrases that ask the video model to render written words.
    Returns the rewritten note (unchanged if nothing matched)."""
    import re
    out = note or ""
    for pat, repl in _TEXT_SUBS:
        out = re.sub(pat, repl, out, flags=re.I)
    return out

# Dedicated negative-prompt field — bare nouns Veo should never render.
NEGATIVE = (
    "text, letters, words, captions, subtitles, numbers, watermark, logo, signature, "
    "gradient, glow, 3D render, photorealistic, realistic texture, drop shadow, "
    "shadows, depth of field, painterly, blurry, distorted, warped, glitch, extra shapes"
)

# Staged hints so a montage of clips reads as one progressing animation.
STAGES = [
    "the very beginning of the motion",
    "the motion developing further",
    "the dramatic final state of the motion",
]


def _n_clips(shot):
    """A spoken aid rides a ~15s soundbite -> montage; a narrated aid is one beat."""
    return 3 if shot.get("speaks") else 1


def _clip_path(out_dir, i, j):
    return os.path.join(out_dir, f"aid_{i}_{j}.mp4")


def _existing(out_dir, i):
    return sorted(glob.glob(os.path.join(out_dir, f"aid_{i}_*.mp4")))


def generate_aids(shots, out_dir, key=None, log=print, style=None):
    """Generate (or reuse) aid clips for every aid shot. Idempotent PER CLIP — an
    aid_<i>_<j>.mp4 already on disk is left alone. `style` overrides the brand art
    direction (e.g. a mood preset). Returns (made, cost_usd)."""
    os.makedirs(out_dir, exist_ok=True)
    style = style or STYLE
    made, cost = 0, 0.0
    for i, shot in enumerate(shots):
        if shot.get("visual") != AID_SHOT:
            continue
        note = scrub_text_requests((shot.get("visual_note") or "").strip())
        labels = _svg._keywords(note)[:12]
        n = _n_clips(shot)
        for j in range(n):
            out = _clip_path(out_dir, i, j)
            if os.path.isfile(out):
                continue  # already in this project
            stage = f" Show {STAGES[j]}." if n > 1 else ""
            prompt = note + stage + style
            secs = _duration_for(shot, n)
            rk = cache.ref_for_video(orc.VIDEO_MODEL, prompt, SIZE, secs)
            hit = cache.reuse(rk)
            if hit and cache.materialize(hit, out):
                log(f"  aid {i}.{j} <- cache reuse (no OpenRouter spend)")
                continue
            try:
                res = orc.generate_video(prompt, out, size=SIZE, duration=secs,
                                         negative_prompt=NEGATIVE, key=key)
                cost += res.get("cost") or 0.0
                made += 1
                cache.put("video", out, ref_key=rk, source=prompt, model=orc.VIDEO_MODEL,
                          size=SIZE, duration_s=secs, labels=labels,
                          meta={"cost": res.get("cost"), "shot": i})
                log(f"  aid {i}.{j} -> {os.path.basename(out)} (${res.get('cost')})")
            except Exception as e:  # noqa: BLE001 — one failed clip shouldn't abort
                log(f"  aid {i}.{j} FAILED: {e}")
    return made, cost


def gather_aids(shots, out_dir, shot_assets):
    """Wire aid_<i>_*.mp4 clips onto each aid shot as `videos` (visual). Merges into
    {shot_index: {...}} shot_assets. Returns (merged, n_shots_wired)."""
    merged = {int(k): dict(v) for k, v in (shot_assets or {}).items()}
    job_id = os.path.basename(out_dir)
    n = 0
    for i, shot in enumerate(shots):
        if shot.get("visual") != AID_SHOT:
            continue
        files = _existing(out_dir, i)
        if not files:
            continue
        merged.setdefault(i, {})["videos"] = [
            f"/output/{job_id}/{os.path.basename(f)}" for f in files
        ]
        n += 1
    return merged, n
