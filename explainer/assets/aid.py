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
DURATION = 5              # <=5s per clip (per parkat)

# Brand style suffix — identical language to the SVG/icon formula so aid clips read
# as the same channel: flat vector, cream field, ink outlines, muted rainbow, VHS.
STYLE = (
    " Clean FLAT vector shapes with thick dark #2E2A26 outlines, no gradients, on a "
    "warm cream #F3ECD9 background. 1980s educational-science / retro-TV VHS look: "
    "soft analog film grain, faint horizontal scanlines, gentle chroma wobble, "
    "slightly washed-out MUTED rainbow palette (dusty red #C1544A, warm orange "
    "#D98A45, mustard #E3C05A, teal #5F9E9A, slate blue #5A7BA6, muted purple "
    "#8A6BA1). Vertical 9:16 framing, steady locked-off camera. Absolutely NO text, "
    "no numbers, no letters, no logos, no watermark."
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


def generate_aids(shots, out_dir, key=None, log=print):
    """Generate (or reuse) aid clips for every aid shot. Idempotent PER CLIP — an
    aid_<i>_<j>.mp4 already on disk is left alone. Returns (made, cost_usd)."""
    os.makedirs(out_dir, exist_ok=True)
    made, cost = 0, 0.0
    for i, shot in enumerate(shots):
        if shot.get("visual") != AID_SHOT:
            continue
        note = (shot.get("visual_note") or "").strip()
        labels = _svg._keywords(note)[:12]
        n = _n_clips(shot)
        for j in range(n):
            out = _clip_path(out_dir, i, j)
            if os.path.isfile(out):
                continue  # already in this project
            stage = f" Show {STAGES[j]}." if n > 1 else ""
            prompt = note + stage + STYLE
            rk = cache.ref_for_video(orc.VIDEO_MODEL, prompt, SIZE, DURATION)
            hit = cache.reuse(rk)
            if hit and cache.materialize(hit, out):
                log(f"  aid {i}.{j} <- cache reuse (no OpenRouter spend)")
                continue
            try:
                res = orc.generate_video(prompt, out, size=SIZE, duration=DURATION, key=key)
                cost += res.get("cost") or 0.0
                made += 1
                cache.put("video", out, ref_key=rk, source=prompt, model=orc.VIDEO_MODEL,
                          size=SIZE, duration_s=DURATION, labels=labels,
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
