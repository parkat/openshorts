"""explainer/service.py — reusable store-glue shared by both drivers.

The CLI (`explainer/cli.py`) and the dashboard HTTP API (`explainer_routes.py`)
both call these functions, so the two control surfaces stay in lockstep on the
shared SQLite state. Stage-running functions take `log: Callable[[str], None] =
print` so the CLI keeps printing while the API captures the lines into a job's
live log.

This module grows one stage at a time (see the build plan). Step 1 = the
read-only queue/detail/post-kit helpers the dashboard needs before it can drive
anything.
"""
import os
import re
import json

import store

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")


# --- shared filesystem/query helpers (were private in cli.py) ---

def proj_dir(project_id):
    """Filesystem asset dir for a project (shared ./output volume)."""
    from explainer.render import job_id_for
    d = os.path.join(OUTPUT_DIR, job_id_for(project_id))
    os.makedirs(d, exist_ok=True)
    return d


def proj_url(project_id, filename):
    """Renderer-relative URL for an asset (render-service rewrites /output/...)."""
    from explainer.render import job_id_for
    return f"/output/{job_id_for(project_id)}/{filename}"


def latest_draft(s, project_id):
    return (s.query(store.Draft)
            .filter(store.Draft.project_id == project_id)
            .order_by(store.Draft.id.desc()).first())


# --- serialization (SQLAlchemy row -> plain dict for JSON responses) ---

def topic_dict(t):
    return {"id": t.id, "title": t.title, "summary": t.summary or "",
            "angle": t.angle or "", "status": t.status, "origin": t.origin,
            "score": t.score or 0.0, "source_url": t.source_url or "",
            "sources": t.sources or [],
            "created_at": t.created_at.isoformat() if t.created_at else None}


def project_dict(p):
    return {"id": p.id, "topic_id": p.topic_id, "title": p.title or "",
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def draft_dict(d):
    if not d:
        return None
    return {"id": d.id, "project_id": d.project_id, "script": d.script or {},
            "factcheck": d.factcheck or [], "voice_id": d.voice_id or "",
            "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None}


def cache_item_dict(r):
    return {"id": r.id, "kind": r.kind, "sha256": r.sha256, "ref_key": r.ref_key,
            "path": r.path, "bytes": int(r.bytes or 0), "mime": r.mime or "",
            "source": r.source or "", "model": r.model or "", "size": r.size or "",
            "duration_s": r.duration_s or 0.0, "labels": r.labels or [],
            "use_count": r.use_count or 1,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None}


# --- post kit: title + per-platform captions + a guaranteed 10-hashtag block ---

_HASHTAG_RE = re.compile(r"#\w+")


def postkit(script):
    """Build the manual-post kit from a draft's script: title, per-platform
    captions (as authored by script.py), and a deduped 10-hashtag copy-block
    derived from the captions. No model call."""
    script = script or {}
    caps = script.get("captions", {}) or {}
    # Collect hashtags across all platform captions, preserving first-seen order.
    seen, tags = set(), []
    for key in ("youtube", "tiktok", "instagram"):
        for m in _HASHTAG_RE.findall(caps.get(key, "") or ""):
            low = m.lower()
            if low not in seen:
                seen.add(low)
                tags.append(m)
    # Pad toward 10 with brand-safe broad fallbacks (only ones not already present).
    for extra in ("#ai", "#artificialintelligence", "#tech", "#machinelearning",
                  "#future", "#innovation", "#technology", "#aiexplained",
                  "#deeplearning", "#science"):
        if len(tags) >= 10:
            break
        if extra.lower() not in seen:
            seen.add(extra.lower())
            tags.append(extra)
    return {"title": script.get("title") or "",
            "captions": {k: caps.get(k, "") for k in ("youtube", "tiktok", "instagram")},
            "hashtags": tags[:10],
            "hashtag_block": " ".join(tags[:10])}


# --- read-only views for the dashboard ---

def list_queue():
    """All projects, newest-updated first (backs the queue view)."""
    with store.session() as s:
        rows = s.query(store.Project).order_by(store.Project.updated_at.desc()).all()
        return [{**project_dict(p),
                 "draft_status": (latest_draft(s, p.id).status
                                  if latest_draft(s, p.id) else None)}
                for p in rows]


def project_detail(project_id):
    """Everything the studio view needs for one project: the project + latest
    draft, the assets manifest, the newest render URL, guardrail + fact-check
    flags, and the post kit. Read-only; None if the project doesn't exist."""
    from explainer import schedule as sch
    from explainer.render import job_id_for
    with store.session() as s:
        p = s.get(store.Project, project_id)
        if not p:
            return None
        d = latest_draft(s, project_id)
        detail = {"project": project_dict(p), "draft": draft_dict(d)}

    pdir = proj_dir(project_id)
    # assets.json (music, shot map, guardrail flags) if assets have been built.
    assets, clip_flags = None, []
    apath = os.path.join(pdir, "assets.json")
    if os.path.isfile(apath):
        try:
            with open(apath, encoding="utf-8") as f:
                assets = json.load(f)
            clip_flags = assets.get("clip_flags") or []
        except (ValueError, OSError):
            pass

    # Newest render, served via the existing /videos static mount.
    render_file = sch.latest_render(project_id)
    render_url = (f"/videos/{job_id_for(project_id)}/{render_file}"
                  if render_file else None)

    script = (detail["draft"] or {}).get("script") if detail["draft"] else None
    factcheck = (detail["draft"] or {}).get("factcheck") if detail["draft"] else []
    detail.update({
        "assets": assets,
        "clip_flags": clip_flags,
        "factcheck": factcheck,
        "render_url": render_url,
        "post_kit": postkit(script) if script else None,
    })
    return detail


# --- pipeline stages (shared by CLI + API; log() streams progress) -----------

def run_render(project_id, force=False, no_wait=False, service_url=None, log=print):
    """Render a project (align.json + narration + assets) → 9:16 MP4.

    Blocks on unresolved guardrail block-flags unless `force`. Flips
    Project.status render→review. Returns a result dict; on a guardrail block it
    returns {'blocked': True, 'blocks': [...]} WITHOUT rendering (a gate, not an
    error). Missing prerequisites raise FileNotFoundError."""
    from explainer import render as rnd
    from explainer.render import job_id_for
    pdir = proj_dir(project_id)
    align_path = os.path.join(pdir, "align.json")
    if not os.path.isfile(align_path):
        raise FileNotFoundError(f"no align.json for project #{project_id} — run `align` first")
    with open(align_path, encoding="utf-8") as f:
        alignment = json.load(f)

    music_url, shot_assets, clip_flags = None, None, []
    apath = os.path.join(pdir, "assets.json")
    if os.path.isfile(apath):
        with open(apath, encoding="utf-8") as f:
            man = json.load(f)
        music_url = man.get("music")
        shot_assets = {int(k): v for k, v in (man.get("shot_assets") or {}).items()}
        clip_flags = man.get("clip_flags") or []

    blocks = [f for f in clip_flags if f.get("level") == "block"]
    if blocks and not force:
        log(f"⛔ {len(blocks)} unresolved guardrail block(s) — resolve or force:")
        for f in blocks:
            log(f"   {f['code']}: {f['message']}")
        return {"blocked": True, "blocks": blocks}

    narration_url = proj_url(project_id, "narration.wav")
    # Honest narration-dominance signal (§5), from displayed (not fetched) durations.
    scenes = rnd.build_scene_list(alignment, shot_assets)
    frac = rnd.accent_display_fraction(scenes)
    if frac > 0.4:
        log(f"⚠️ accent footage is {frac*100:.0f}% of runtime — keep original ≥60% (§5).")

    with store.session() as s:
        s.get(store.Project, project_id).status = "render"
        s.commit()
    log(f"rendering project #{project_id} via {rnd.RENDER_SERVICE_URL} …")
    job = rnd.render(alignment, narration_url, project_id, music_url=music_url,
                     assets=shot_assets, poll=not no_wait,
                     service_url=(service_url or None))
    if no_wait:
        log(f"submitted render {job['renderId']} (job {job['job_id']})")
        return {"blocked": False, "submitted": True, "job": job}
    with store.session() as s:
        s.get(store.Project, project_id).status = "review"
        s.commit()
    basename = job.get("output_basename")
    log(f"rendered → output/{job['job_id']}/{basename}")
    return {"blocked": False, "submitted": False, "job": job,
            "output_basename": basename,
            "render_url": (f"/videos/{job_id_for(project_id)}/{basename}" if basename else None)}
