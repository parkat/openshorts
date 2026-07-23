"""Visuals stage: generate on-brand 9:16 stills for figure/broll shots.

Cheap visual variety (HANDOFF §11: images ~free, video is the credit driver) — we
generate brand-styled stills per shot via OpenRouter image gen and let the Remotion
Ken Burns / jump-cut beats give them motion. Two framings per shot by default so a
shot can hard-cut between distinct images instead of holding one frame.

Only figure/broll shots WITHOUT an accent clip get generated art; text shots
(slide/motion_text) stay type; accent_clip shots already have their footage.
"""
import os

import openrouter_client as orc
from explainer.brand import BRAND

# 80s retro-TV / VHS look, no text (captions/headlines are burned separately).
STYLE = (
    "1980s retro-TV / VHS aesthetic, muted flat colors, cream and warm-ink palette "
    "with RadioShack + early-Apple rainbow accents, grainy analog film texture, "
    "bold simple editorial composition, vertical 9:16 framing. "
    "NO text, no words, no letters, no captions, no watermark, no logos."
)
# Distinct framings so the two stills of a shot actually cut, not repeat.
_FRAMINGS = ["wide establishing shot", "tight dramatic close-up detail"]

IMAGES_PER_SHOT = int(os.environ.get("EXPLAINER_IMAGES_PER_SHOT", "2"))
_IMAGE_SHOTS = {"figure", "broll"}


def _prompt(shot, framing):
    subject = (shot.get("visual_note") or shot.get("narration") or "").strip()
    return f"{framing}: {subject}. {STYLE}"


def generate_for_shot(shot, out_dir, index, n=IMAGES_PER_SHOT, model=None, key=None):
    """Generate up to n stills for one shot; return their /output-relative URLs.
    Failures are skipped (a shot with no image falls back to a text slide)."""
    job_id = os.path.basename(out_dir)  # out_dir == output/<job_id>
    urls = []
    for k in range(max(1, n)):
        framing = _FRAMINGS[k % len(_FRAMINGS)]
        fname = f"img_{index}_{k}.png"
        try:
            orc.generate_image(_prompt(shot, framing), out_path=os.path.join(out_dir, fname),
                               aspect_ratio="9:16", model=model, key=key)
            urls.append(f"/output/{job_id}/{fname}")
        except Exception:  # noqa: BLE001 — a missing still just means a text fallback
            continue
    return urls


def gather_visuals(shots, out_dir, shot_assets, model=None, key=None):
    """Generate stills for figure/broll shots not already covered by a clip.
    Merges {shot_index: {"images": [...]}} into a copy of shot_assets and returns it."""
    merged = {int(k): dict(v) for k, v in (shot_assets or {}).items()}
    for i, shot in enumerate(shots):
        if shot.get("visual") not in _IMAGE_SHOTS:
            continue
        if merged.get(i, {}).get("videoUrl"):   # already has footage
            continue
        urls = generate_for_shot(shot, out_dir, i, model=model, key=key)
        if urls:
            merged.setdefault(i, {})["images"] = urls
    return merged
