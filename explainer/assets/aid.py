"""Generated visual-aid stage. An `aid` beat is an animation that EXPLAINS the
point (a concept made visible), not decoration — the lane's primary explanatory
visual.

Two ways to make one, chosen by `EXPLAINER_AID_MODE`:

  motion (default)   The LLM writes a small Remotion COMPONENT (explainer/assets/
                     aidgen.py). Lands as `aid_<shot>.jsx` (readable, editable) +
                     `aid_<shot>.js` (compiled); `gather_aids` wires the compiled
                     code onto the shot as `aidCode`. Costs ~$0.04, generates in
                     seconds, fills the beat exactly, and re-themes with the mood
                     because it draws only from `theme`.

  video              The original path: 720x1280 clips from OpenRouter video (Veo).
                     Lands as `aid_<shot>_<n>.mp4`, wired as `videos`. A speaks:true
                     aid rides a long soundbite and clips cap at 8s, so it becomes a
                     MONTAGE of staged clips progressing one concept. ~$0.20/s.

  motion-then-video  Motion first; anything the codegen loop can't produce falls
                     back to a generated clip.

Either way the visual is MUTED at render — the audio is the AI narrator or the
speaker's baked soundbite. Generation is idempotent per output file, so re-running
the stage reuses whatever is already on disk.
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

MODES = ("motion", "video", "motion-then-video")
MODE = (os.environ.get("EXPLAINER_AID_MODE") or "motion").strip().lower()


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


def _code_paths(out_dir, i):
    """Readable source + compiled output for a motion aid."""
    return (os.path.join(out_dir, f"aid_{i}.jsx"),
            os.path.join(out_dir, f"aid_{i}.js"))


def _aid_indices(shots):
    return [i for i, sh in enumerate(shots) if sh.get("visual") == AID_SHOT]


def _generate_motion(shots, out_dir, theme, style=None, key=None, log=print, only=None):
    """Author a motion-graphic component per aid shot. Idempotent per shot — an
    aid_<i>.js already on disk is left alone. Returns (made, cost, unresolved)
    where `unresolved` is the aid shot indices codegen could not produce."""
    from explainer.assets import aidgen

    made, cost, unresolved = 0, 0.0, []
    for i in _aid_indices(shots):
        if only is not None and i not in only:
            continue
        jsx_path, js_path = _code_paths(out_dir, i)
        if os.path.isfile(js_path):
            continue  # already in this project
        note = (shots[i].get("visual_note") or "").strip()
        labels = _svg._keywords(note)[:12]
        log(f"  aid {i}: authoring motion graphic …")
        try:
            m, c = aidgen.author_cached(shots[i], theme, style=style, key=key, log=log,
                                        labels=labels, jsx_path=jsx_path, js_path=js_path)
        except Exception as e:  # noqa: BLE001 — one failed aid shouldn't abort the stage
            log(f"  aid {i} FAILED: {e}")
            unresolved.append(i)
            continue
        cost += c
        if os.path.isfile(js_path):
            made += m
            log(f"  aid {i} -> {os.path.basename(js_path)}"
                + (f" (${c:.4f})" if c else ""))
        else:
            log(f"  aid {i}: codegen gave up")
            unresolved.append(i)
    return made, cost, unresolved


def _generate_video(shots, out_dir, style=None, key=None, log=print, only=None):
    """The original paid path: staged 720x1280 clips from OpenRouter video.
    Idempotent PER CLIP. Returns (made, cost_usd)."""
    style = style or STYLE
    made, cost = 0, 0.0
    for i in _aid_indices(shots):
        if only is not None and i not in only:
            continue
        shot = shots[i]
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


def generate_aids(shots, out_dir, key=None, log=print, style=None, mode=None,
                  theme=None, code_style=None):
    """Produce a visual aid for every aid shot. Returns (made, cost_usd).

    `mode` is motion | video | motion-then-video (default from EXPLAINER_AID_MODE).
    `style` is the video-model art direction, `code_style` the motion-graphics art
    direction — a mood preset supplies both. `theme` is the ExplainerTheme the
    motion aid will render against; the probe uses it, so a component that would be
    invisible in this mood is rejected at generation rather than on screen.
    """
    os.makedirs(out_dir, exist_ok=True)
    mode = (mode or MODE).strip().lower()
    if mode not in MODES:
        log(f"  unknown aid mode {mode!r} — falling back to 'motion'")
        mode = "motion"

    if mode == "video":
        return _generate_video(shots, out_dir, style=style, key=key, log=log)

    if theme is None:
        from explainer.render import brand_theme
        theme = brand_theme()

    made, cost, unresolved = _generate_motion(shots, out_dir, theme, style=code_style,
                                              key=key, log=log)
    if unresolved and mode == "motion-then-video":
        log(f"  falling back to generated video for {len(unresolved)} aid shot(s)")
        vmade, vcost = _generate_video(shots, out_dir, style=style, key=key, log=log,
                                       only=set(unresolved))
        made, cost = made + vmade, cost + vcost
    elif unresolved:
        log(f"  {len(unresolved)} aid shot(s) have no visual — they degrade to a "
            "concept graphic or the brand backdrop")
    return made, cost


def gather_aids(shots, out_dir, shot_assets):
    """Wire each aid shot's generated visual onto it. A motion component is inlined
    as `aidCode` (a few KB — cheaper than a second fetch inside headless Chromium);
    generated clips wire as `videos`. Merges into {shot_index: {...}} shot_assets.
    Returns (merged, n_shots_wired)."""
    merged = {int(k): dict(v) for k, v in (shot_assets or {}).items()}
    job_id = os.path.basename(out_dir)
    n = 0
    for i in _aid_indices(shots):
        _, js_path = _code_paths(out_dir, i)
        if os.path.isfile(js_path):
            with open(js_path, encoding="utf-8") as f:
                merged.setdefault(i, {})["aidCode"] = f.read()
            n += 1
            continue
        files = _existing(out_dir, i)
        if not files:
            continue
        merged.setdefault(i, {})["videos"] = [
            f"/output/{job_id}/{os.path.basename(f)}" for f in files
        ]
        n += 1
    return merged, n
