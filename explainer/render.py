"""Render stage: aligned shot-list + assets -> a 9:16 MP4 via the render-service.

Turns the `align.py` output into the ExplainerShort scene list, posts it to the
Remotion render-service (`/render`, composition `ExplainerShort`), and polls to
completion. Asset files live on the shared ./output volume under
`output/explainer-<project_id>/`; we reference them by the renderer-relative
`/output/...` path, which the render-service rewrites to its own static server.

Scenes needing media (figure/accent_clip/broll) gracefully downgrade to a text
slide when no asset URL is supplied, so a Phase-1 slice renders with just
narration + captions + pasted accent clips.
"""
import os
import time

import requests

from explainer.brand import BRAND

RENDER_SERVICE_URL = os.environ.get("RENDER_SERVICE_URL", "http://renderer:3100")
FPS = 30
WIDTH = 1080
HEIGHT = 1920

# Scene types that want a media asset; without one they fall back to a text slide.
_MEDIA_SCENES = {"figure", "accent_clip", "broll"}


def job_id_for(project_id):
    """Namespace explainer renders on the output volume (reused by the media/Buffer
    flow, which serves output/<job_id>/<file>)."""
    return f"explainer-{project_id}"


def brand_theme():
    """ExplainerTheme dict from the Scientific Awareness palette (brand.py)."""
    p = BRAND["palette"]
    return {
        "bg": p["cream"],
        "ink": p["ink"],
        "rainbow": [p["red"], p["orange"], p["yellow"], p["teal"], p["blue"], p["purple"]],
        # Concrete stacks — headless Chromium has no Eurostile/Futura installed.
        "displayFont": '"Arial Black", "Helvetica Neue", Arial, sans-serif',
        "captionFont": '"Arial Black", Impact, "Helvetica Neue", sans-serif',
        "highlight": p["yellow"],
        "vhs": bool(BRAND.get("vhs")),
    }


import re

# Leading stage-direction label on a visual_note, e.g. "Split screen:", "Text punch-in:".
_DIRECTION_PREFIX = re.compile(r"^[A-Za-z][A-Za-z /-]{0,24}:\s*")


def _clean_note(note):
    """Strip a leading stage-direction label so an old draft's visual_note reads as
    display copy (fallback only — new drafts carry a clean `on_screen`)."""
    return _DIRECTION_PREFIX.sub("", (note or "").strip())


def _headline(shot):
    """On-screen headline for a text scene: the clean `on_screen` phrase if the
    script provided one, else the direction-stripped visual_note, else narration."""
    return (shot.get("on_screen") or _clean_note(shot.get("visual_note"))
            or shot.get("narration") or "").strip()


def build_scene_list(alignment, assets=None):
    """Aligned shots (+ optional per-index asset URLs) -> ExplainerShort scenes.

    `assets`: {shot_index: {"imageUrl"|"videoUrl": "/output/...", "attribution": str}}.
    A media scene with no asset downgrades to a slide so the render never breaks.
    """
    assets = assets or {}
    scenes = []
    for shot in alignment.get("shots", []):
        idx = shot.get("index")
        a = assets.get(idx) or assets.get(str(idx)) or {}
        visual = shot.get("visual") or "slide"
        scene = {
            "type": visual,
            "startMs": int(shot.get("startMs", 0)),
            "endMs": int(shot.get("endMs", 0)),
            "role": shot.get("role") or "",
        }
        if visual in _MEDIA_SCENES:
            # Attach whatever media was supplied (images/stills or a video clip).
            if a.get("images"):
                scene["images"] = a["images"]
            if a.get("imageUrl"):
                scene["imageUrl"] = a["imageUrl"]
            if a.get("videoUrl"):
                scene["videoUrl"] = a["videoUrl"]
            has_media = any(scene.get(k) for k in ("images", "imageUrl", "videoUrl"))
            if visual == "accent_clip" and scene.get("videoUrl"):
                src = shot.get("source")
                scene["attribution"] = a.get("attribution") or (
                    f"via {src}" if src and src != "general" else ""
                )
                # Soundbite shots let the clip's own audio play (Hinton speaks);
                # plain b-roll accents stay ducked/muted under the narration.
                scene["duckAudio"] = not shot.get("speaks")
            if not has_media:
                # No footage — keep the type (figure -> big stat, else animated
                # backdrop); the captions carry the spoken words, not a headline.
                scene["text"] = _headline(shot)
        else:
            scene["text"] = _headline(shot)
        scenes.append(scene)
    return scenes


def shot_assets_from_clips(shots, fetched_clips, job_id):
    """Pair fetched accent clips (in order) with the shots whose visual is
    'accent_clip'. Returns {shot_index: {videoUrl, [attribution]}} for render's
    `assets`. Clips that failed to fetch (no local_path) are skipped."""
    ready = [c for c in (fetched_clips or []) if c.get("local_path")]
    out, k = {}, 0
    for i, shot in enumerate(shots):
        if shot.get("visual") == "accent_clip" and k < len(ready):
            c = ready[k]
            k += 1
            entry = {"videoUrl": f"/output/{job_id}/{os.path.basename(c['local_path'])}"}
            if c.get("channel"):
                entry["attribution"] = f"via {c['channel']}"
            out[i] = entry
    return out


def accent_display_fraction(scenes):
    """Fraction of runtime that actually SHOWS accent-clip footage (displayed, not
    fetched). This is the honest narration-dominance signal (§5) — a 14s clip that
    only fills a 4s slot counts as 4s."""
    total = max(1, sum(s["endMs"] - s["startMs"] for s in scenes))
    accent = sum(s["endMs"] - s["startMs"] for s in scenes if s["type"] == "accent_clip")
    return accent / total


def build_props(alignment, narration_url, music_url=None, assets=None,
                theme=None, fps=FPS, width=WIDTH, height=HEIGHT):
    """Assemble the ExplainerShort inputProps."""
    duration_ms = alignment.get("duration_ms") or (
        alignment["shots"][-1]["endMs"] if alignment.get("shots") else 0
    )
    return {
        "durationInFrames": max(1, round(duration_ms / 1000 * fps)),
        "fps": fps,
        "width": width,
        "height": height,
        "narrationUrl": narration_url,
        "musicUrl": music_url,
        "captions": alignment.get("words", []),
        "scenes": build_scene_list(alignment, assets),
        "theme": theme or brand_theme(),
    }


def submit_render(props, job_id, clip_index=0, service_url=None):
    """POST the scene list to the render-service; return its renderId."""
    url = f"{(service_url or RENDER_SERVICE_URL).rstrip('/')}/render"
    body = {"jobId": job_id, "clipIndex": clip_index,
            "composition": "ExplainerShort", "props": props}
    r = requests.post(url, json=body, timeout=40)
    r.raise_for_status()
    return r.json()["renderId"]


def poll_render(render_id, service_url=None, interval=3.0, timeout=1800):
    """Block until the render finishes; return the job dict (status/outputUrl)."""
    base = (service_url or RENDER_SERVICE_URL).rstrip("/")
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{base}/render/{render_id}", timeout=30)
        r.raise_for_status()
        job = r.json()
        status = job.get("status")
        if status == "done":
            return job
        if status == "error":
            raise RuntimeError(f"render failed: {job.get('error')}")
        time.sleep(interval)
    raise TimeoutError(f"render {render_id} did not finish within {timeout}s")


def render(alignment, narration_url, project_id, music_url=None, assets=None,
           theme=None, service_url=None, clip_index=0, poll=True):
    """Full render: build props -> submit -> (optionally) poll. Returns the job
    dict; on success `output_basename` is the file under output/<job_id>/."""
    props = build_props(alignment, narration_url, music_url=music_url,
                        assets=assets, theme=theme)
    job_id = job_id_for(project_id)
    render_id = submit_render(props, job_id, clip_index=clip_index, service_url=service_url)
    if not poll:
        return {"renderId": render_id, "job_id": job_id, "status": "queued"}
    job = poll_render(render_id, service_url=service_url)
    job["job_id"] = job_id
    out = job.get("outputUrl")
    job["output_basename"] = os.path.basename(out) if out else None
    return job
