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

# Scene types that require a media asset; without one they fall back to text.
_MEDIA_SCENES = {"figure": "imageUrl", "accent_clip": "videoUrl", "broll": "videoUrl"}


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


def _headline(shot):
    """Short on-screen headline for a text scene (the visual note, else narration)."""
    return (shot.get("visual_note") or shot.get("narration") or "").strip()


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
        media_key = _MEDIA_SCENES.get(visual)
        if media_key:
            url = a.get(media_key)
            if url:
                scene[media_key] = url
                if visual == "accent_clip":
                    src = shot.get("source")
                    scene["attribution"] = a.get("attribution") or (
                        f"via {src}" if src and src != "general" else ""
                    )
                    scene["duckAudio"] = True
            else:
                # No asset yet — show the point as a title card instead.
                scene["type"] = "slide"
                scene["text"] = _headline(shot)
        else:
            scene["text"] = _headline(shot)
        scenes.append(scene)
    return scenes


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
