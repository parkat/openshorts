"""Render stage: a cut clip -> a finished 9:16 MP4.

Reuses the explainer lane's `ExplainerShort` composition rather than adding a
second one. A Short cut from real footage is exactly one full-length `accent_clip`
scene: the composition already lays a 16:9 clip over a blurred, zoomed copy of
itself to fill the vertical frame, rides word-level captions on the master audio,
and themes both from `brand.py`. Nothing about it is explainer-specific.

The one wrinkle is audio. `AccentClipScene` renders its video muted — in the
explainer lane the narration is the master track and the footage plays under it —
so the speaker would be silent if we passed only `videoUrl`. We hand the audio
extracted from the same cut in as `narrationUrl` instead, which makes the
speaker's own voice the master track. Same source, same cut, so it cannot drift.

Duration comes from `calculateMetadata` in Root.tsx, which uses max(scene.endMs) —
so a single scene ending at the clip's real duration gives an exact-length Short.
"""
import os

from explainer.render import (FPS, WIDTH, HEIGHT, brand_theme, poll_render,  # noqa: F401
                              submit_render, RENDER_SERVICE_URL)

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")


def job_id_for(candidate_id):
    """Namespace clip renders on the shared ./output volume."""
    return f"clips-{candidate_id}"


def cand_dir(candidate_id):
    d = os.path.join(OUTPUT_DIR, job_id_for(candidate_id))
    os.makedirs(d, exist_ok=True)
    return d


def cand_url(candidate_id, filename):
    """Renderer-relative URL — the render-service rewrites /output/... to its own
    static server."""
    return f"/output/{job_id_for(candidate_id)}/{filename}"


def build_props(candidate_id, duration_ms, captions, attribution="", theme=None,
                fps=FPS, width=WIDTH, height=HEIGHT):
    """Assemble the ExplainerShort inputProps for a single-clip Short."""
    scene = {
        "type": "accent_clip",
        "startMs": 0,
        "endMs": int(duration_ms),
        "videoUrl": cand_url(candidate_id, "clip.mp4"),
        "role": "hook",
    }
    if attribution:
        scene["attribution"] = attribution
    return {
        "durationInFrames": max(1, round(duration_ms / 1000 * fps)),
        "fps": fps,
        "width": width,
        "height": height,
        # The clip's own audio is the master track (see module docstring).
        "narrationUrl": cand_url(candidate_id, "audio.wav"),
        "musicUrl": None,
        "captions": captions or [],
        "scenes": [scene],
        "theme": theme or brand_theme(),
    }


def render(candidate_id, duration_ms, captions, attribution="", mood=None,
           service_url=None, poll=True):
    """Build props -> submit -> (optionally) poll. Returns the render-service job."""
    props = build_props(candidate_id, duration_ms, captions,
                        attribution=attribution,
                        theme=brand_theme(mood) if mood else None)
    job_id = job_id_for(candidate_id)
    render_id = submit_render(props, job_id, clip_index=0, service_url=service_url)
    if not poll:
        return {"renderId": render_id, "job_id": job_id, "status": "queued"}
    job = poll_render(render_id, service_url=service_url)
    job["job_id"] = job_id
    out = job.get("outputUrl")
    job["output_basename"] = os.path.basename(out) if out else None
    return job
