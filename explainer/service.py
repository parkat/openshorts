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
from dataclasses import dataclass

import store

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")


@dataclass
class AssetOpts:
    """Mirrors the `assets` CLI toggles; the API request body maps 1:1."""
    voice: str = None
    tone: str = None        # None = brand default; "none"/"off"/"" = disabled
    speed: float = 1.0
    no_clips: bool = False
    no_visuals: bool = False
    ai_visuals: bool = False
    no_svg: bool = False
    no_music: bool = False


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


def feedback_dict(f):
    return {"id": f.id, "project_id": f.project_id, "topic_id": f.topic_id,
            "draft_id": f.draft_id, "verdict": f.verdict, "reason": f.reason or "",
            "tags": f.tags or [],
            "created_at": f.created_at.isoformat() if f.created_at else None}


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
    # Rejection history for this project's TOPIC — past lessons the next
    # generation will learn from (so the reviewer sees what's being carried).
    topic_id = detail["project"].get("topic_id")
    detail.update({
        "assets": assets,
        "clip_flags": clip_flags,
        "factcheck": factcheck,
        "render_url": render_url,
        "post_kit": postkit(script) if script else None,
        "feedback": list_feedback(topic_id=topic_id) if topic_id else [],
    })
    return detail


# --- reject + learn ----------------------------------------------------------

def reject_project(project_id, reason="", tags=None, log=print):
    """Reject a rendered project with a reason (+ category tags). Records Feedback
    tied to the project's TOPIC (so the next generation for that topic can learn),
    sets Project.status='rejected'. Returns the feedback row."""
    with store.session() as s:
        p = s.get(store.Project, project_id)
        if not p:
            raise ValueError(f"project #{project_id} not found")
        d = latest_draft(s, project_id)
        fb = store.Feedback(project_id=project_id, topic_id=p.topic_id,
                            draft_id=(d.id if d else None), verdict="rejected",
                            reason=(reason or "").strip(), tags=list(tags or []))
        s.add(fb)
        p.status = "rejected"
        if d:
            d.status = "needs_review"
        s.commit()
        row = feedback_dict(fb)
    log(f"rejected project #{project_id}: {reason[:80]}")
    return row


def list_feedback(topic_id=None, project_id=None, limit=50):
    """Recent rejections, newest first (UI history + guidance source)."""
    with store.session() as s:
        q = s.query(store.Feedback)
        if topic_id is not None:
            q = q.filter(store.Feedback.topic_id == topic_id)
        if project_id is not None:
            q = q.filter(store.Feedback.project_id == project_id)
        rows = q.order_by(store.Feedback.created_at.desc()).limit(limit).all()
        return [feedback_dict(f) for f in rows]


def feedback_guidance(topic_id=None, per_topic=8, recent_global=4):
    """Build a 'lessons from rejected versions' block for the script prompt:
    every rejection for THIS topic (most relevant) + a few recent rejections from
    other topics (channel-wide style lessons). Returns '' if there's nothing."""
    with store.session() as s:
        lessons, seen = [], set()

        def _add(f):
            txt = (f.reason or "").strip()
            if not txt:
                return
            key = txt.lower()
            if key in seen:
                return
            seen.add(key)
            tag = f"[{', '.join(f.tags)}] " if f.tags else ""
            lessons.append(f"- {tag}{txt}")

        if topic_id is not None:
            for f in (s.query(store.Feedback)
                      .filter(store.Feedback.topic_id == topic_id)
                      .order_by(store.Feedback.created_at.desc())
                      .limit(per_topic).all()):
                _add(f)
        for f in (s.query(store.Feedback)
                  .order_by(store.Feedback.created_at.desc())
                  .limit(recent_global + per_topic).all()):
            if topic_id is not None and f.topic_id == topic_id:
                continue
            if len([l for l in lessons]) >= per_topic + recent_global:
                break
            _add(f)

    if not lessons:
        return ""
    return ("LESSONS FROM REJECTED VERSIONS — a previous attempt was rejected by the "
            "reviewer. Do NOT repeat these mistakes; fix each one explicitly in this "
            "new version:\n" + "\n".join(lessons))


# --- topics (manual add + approve) -------------------------------------------

def add_topic(title, summary="", angle="", sources=None, log=print):
    with store.session() as s:
        t = store.Topic(title=title, origin="manual", angle=angle or "",
                        summary=summary or "", sources=sources or [])
        s.add(t)
        s.commit()
        row = topic_dict(t)
    log(f"added topic #{row['id']}: {title}")
    return row


def list_topics():
    with store.session() as s:
        rows = s.query(store.Topic).order_by(store.Topic.created_at.desc()).all()
        return [topic_dict(t) for t in rows]


def approve_topic(topic_id, accent_sources=None, log=print):
    """Greenlight a topic and (optionally) append accent-clip sources
    (URLs + in/out timestamps) to its source list."""
    from sqlalchemy.orm.attributes import flag_modified
    with store.session() as s:
        t = s.get(store.Topic, topic_id)
        if not t:
            raise ValueError(f"topic #{topic_id} not found")
        t.status = "approved"
        if accent_sources:
            t.sources = (t.sources or []) + list(accent_sources)
            flag_modified(t, "sources")
        s.commit()
        row = topic_dict(t)
    log(f"approved topic #{topic_id}")
    return row


# --- gate 1: edit the script, resolve flags ----------------------------------

def save_draft_script(project_id, script, log=print):
    """Persist an edited shot-list/captions back to the latest draft."""
    with store.session() as s:
        draft = latest_draft(s, project_id)
        if not draft:
            raise ValueError(f"no draft for project #{project_id}")
        draft.script = script or {}
        s.commit()
        did = draft.id
    log(f"saved script → draft #{did}")
    return {"project_id": project_id, "draft_id": did}


def _flag_matches(fl, target):
    return (fl.get("code") == target.get("code")
            and fl.get("clip_index") == target.get("clip_index"))


def resolve_flag(project_id, kind, target, log=print):
    """Gate-1 resolution. kind='clip' removes a guardrail flag from assets.json
    (an explicit override — after this, render won't block on it). kind='claim'
    marks a fact-check claim reviewed. `target` is the flag/claim object."""
    from sqlalchemy.orm.attributes import flag_modified
    if kind == "clip":
        apath = os.path.join(proj_dir(project_id), "assets.json")
        if not os.path.isfile(apath):
            raise FileNotFoundError("no assets.json — run assets first")
        with open(apath, encoding="utf-8") as f:
            man = json.load(f)
        before = man.get("clip_flags") or []
        after = [fl for fl in before if not _flag_matches(fl, target)]
        man["clip_flags"] = after
        with open(apath, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
        log(f"resolved {len(before) - len(after)} clip flag(s)")
        return {"removed": len(before) - len(after), "clip_flags": after}
    if kind == "claim":
        with store.session() as s:
            draft = latest_draft(s, project_id)
            if not draft:
                raise ValueError(f"no draft for project #{project_id}")
            fc = draft.factcheck or {}
            for c in fc.get("claims", []):
                if c.get("claim") == target.get("claim"):
                    c["resolved"] = True
            draft.factcheck = fc
            flag_modified(draft, "factcheck")
            s.commit()
        return {"ok": True}
    raise ValueError(f"unknown flag kind {kind!r}")


def cancel_scheduled(item_id, log=print):
    """Pull a queued post back out of Buffer and mark the ScheduleItem cancelled.
    Safe to call on an item with no buffer_post_id (just marks it locally)."""
    import os
    import buffer_client
    with store.session() as s:
        it = s.get(store.ScheduleItem, item_id)
        if not it:
            raise ValueError(f"schedule item #{item_id} not found")
        bpid = (it.buffer_post_id or "").strip()
        if bpid:
            key = os.environ.get("BUFFER")
            if not key:
                raise ValueError("no BUFFER key on the server")
            buffer_client.delete_post(key, bpid)
            log(f"removed Buffer post {bpid}")
        it.status = "cancelled"
        # Drop the matching Post row (it never went live).
        for p in (s.query(store.Post)
                  .filter(store.Post.buffer_post_id == bpid).all() if bpid else []):
            s.delete(p)
        s.commit()
    log(f"cancelled schedule item #{item_id}")
    return {"ok": True, "id": item_id, "status": "cancelled"}


def clear_failed_schedule(project_id=None, log=print):
    """Remove stale `failed` schedule rows (e.g. from before media hosting worked)
    so the queue view reflects reality. Returns how many were dropped."""
    with store.session() as s:
        q = s.query(store.ScheduleItem).filter(store.ScheduleItem.status == "failed")
        if project_id is not None:
            q = q.filter(store.ScheduleItem.project_id == project_id)
        rows = q.all()
        n = len(rows)
        for r in rows:
            s.delete(r)
        s.commit()
    log(f"cleared {n} failed schedule row(s)")
    return {"cleared": n}


def list_schedule():
    """Scheduled items + recent publish log (scheduler view)."""
    with store.session() as s:
        items = (s.query(store.ScheduleItem)
                 .order_by(store.ScheduleItem.due_at.desc()).all())
        posts = (s.query(store.Post)
                 .order_by(store.Post.posted_at.desc()).limit(50).all())
        return {
            "scheduled": [{"id": it.id, "project_id": it.project_id,
                           "platform": it.platform, "status": it.status,
                           "due_at": it.due_at.isoformat() if it.due_at else None,
                           "buffer_post_id": it.buffer_post_id or ""} for it in items],
            "posts": [{"id": p.id, "project_id": p.project_id, "platform": p.platform,
                       "url": p.url or "", "buffer_post_id": p.buffer_post_id or "",
                       "posted_at": p.posted_at.isoformat() if p.posted_at else None}
                      for p in posts],
        }


# --- pipeline stages (shared by CLI + API; log() streams progress) -----------

def run_script(topic_id, model=None, use_feedback=True, log=print):
    """Generate a shot-list from a topic; create the Project + Draft. Returns
    {project_id, draft_id, script}. New projects start at status 'draft' (reserve
    'review' for the post-render gate). When `use_feedback`, folds lessons from any
    rejected prior version of this topic into the writer's prompt."""
    from explainer import script as scr
    guidance = feedback_guidance(topic_id) if use_feedback else ""
    with store.session() as s:
        topic = s.get(store.Topic, topic_id)
        if not topic:
            raise ValueError(f"topic #{topic_id} not found")
        log(f"drafting script for topic #{topic.id}: {topic.title} …")
        if guidance:
            n = guidance.count("\n- ")
            log(f"  applying {n} lesson(s) from rejected version(s)")
        sl = scr.generate_script(topic.title, topic.summary, topic.sources or [],
                                 model=(model or None), guidance=guidance)
        proj = store.Project(topic_id=topic.id, title=sl.get("title") or topic.title,
                             status="draft")
        s.add(proj)
        s.flush()
        draft = store.Draft(project_id=proj.id, script=sl, status="needs_review")
        s.add(draft)
        s.commit()
        pid, did = proj.id, draft.id
    log(f"=== {sl.get('title')}  (~{sl.get('estimated_seconds')}s) ===")
    for shot in sl.get("shots", []):
        log(f"[{str(shot.get('role','?')):6}] {shot.get('seconds','?')}s  {shot.get('narration','')}")
    log(f"stored → project #{pid}, draft #{did} (status: draft / needs_review)")
    return {"project_id": pid, "draft_id": did, "script": sl}


def run_clipfind(project_id, model=None, log=print):
    """Pick the best accent-clip window per accent_clip shot from the reference
    transcripts; write clips_plan.json. Returns the plan."""
    from explainer import clipfinder as cf
    pdir = proj_dir(project_id)
    with store.session() as s:
        draft = latest_draft(s, project_id)
        if not draft:
            raise ValueError(f"no draft for project #{project_id}")
        topic = s.get(store.Topic, s.get(store.Project, project_id).topic_id)
        sources = (topic.sources if topic else None) or []
        script = draft.script or {}
    refs = [x for x in sources if x.get("type") == "youtube"]
    if not refs:
        log("no YouTube reference sources on this topic")
        return {"selections": [], "references": [], "needs": 0}
    log(f"reading {len(refs)} reference transcript(s) + selecting windows …")
    result = cf.plan(script, sources, pdir, model=(model or None))
    with open(os.path.join(pdir, "clips_plan.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"{len(result['selections'])} clip(s) selected for {result['needs']} accent shot(s):")
    for sel in result["selections"]:
        dur = sel["out"] - sel["in"]
        log(f"  shot {sel['shot_index']} ← {sel['channel']}  {sel['in']:.0f}–{sel['out']:.0f}s ({dur:.0f}s)")
    return result


def run_factcheck(project_id, source_text="", model=None, log=print):
    """Extract + label claims from the latest draft; store flags for gate 1."""
    from explainer import factcheck as fc
    with store.session() as s:
        draft = latest_draft(s, project_id)
        if not draft:
            raise ValueError(f"no draft for project #{project_id}")
        log(f"fact-checking project #{project_id} "
            f"({'with sources' if source_text else 'general knowledge, strict'}) …")
        result = fc.factcheck(draft.script or {}, source_text, model=(model or None))
        draft.factcheck = result
        if any(c["label"] != "supported" for c in result["claims"]):
            draft.status = "needs_review"
        s.commit()
    sm = result["summary"]
    log(f"claims: {sm['supported']} supported · {sm['overstated']} overstated · "
        f"{sm['unsupported']} unsupported")
    for c in fc.flags(result):
        mark = "⛔" if c["label"] == "unsupported" else "⚠️"
        log(f"  {mark} [{c['label']}] {c['claim']}")
        if c.get("note"):
            log(f"       ↳ {c['note']}")
    return result


def run_assets(project_id, opts=None, log=print):
    """Build TTS narration, accent clips (guardrails + provenance), b-roll/aids/
    SVGs, and a ducked music bed → assets.json. Sets Project.status='assets'.
    Returns the manifest (incl. clip_flags for gate 1)."""
    opts = opts or AssetOpts()
    from explainer.assets import tts, audio
    from explainer import render as rnd
    from explainer.brand import BRAND
    pdir = proj_dir(project_id)
    with store.session() as s:
        draft = latest_draft(s, project_id)
        if not draft:
            raise ValueError(f"no draft for project #{project_id}")
        script = draft.script or {}
        shots = script.get("shots", [])
        topic = s.get(store.Topic, s.get(store.Project, project_id).topic_id)
        sources = (topic.sources if topic else None) or []
        voice = opts.voice or draft.voice_id or None

        # Mood (draft.script["mood"]) picks the delivery + art direction preset.
        from explainer.brand import mood as _mood
        mood_name = script.get("mood")
        m = _mood(mood_name)
        if mood_name and mood_name != "default":
            log(f"  mood: {mood_name}")
        if opts.tone is None:
            tone = m.get("tts_tone") or BRAND.get("tts_tone")
        elif str(opts.tone).strip().lower() in ("", "none", "off", "neutral"):
            tone = None
        else:
            tone = opts.tone
        if tone:
            log(f"  tone: {tone[:80]}…")

        manifest = {"music": None, "shot_assets": {}, "clip_flags": [], "narration_seconds": 0}

        # 1) Accent clips FIRST (soundbite narration needs the clip durations).
        sa = {}
        if not opts.no_clips:
            from explainer.assets import clips as clp
            plan_path = os.path.join(pdir, "clips_plan.json")
            if os.path.isfile(plan_path):
                with open(plan_path, encoding="utf-8") as pf:
                    sels = (json.load(pf) or {}).get("selections", [])
                if sels:
                    log(f"fetching {len(sels)} clip-finder window(s) …")
                    res = clp.gather_from_plan(s, project_id, sels, pdir)
                    sa = res["shot_assets"]
                    manifest["clip_flags"] = res["flags"]
            elif any(x.get("type") == "youtube" for x in sources):
                log("fetching accent clips (manual timestamps) …")
                res = clp.gather_accent_clips(s, project_id, sources, pdir)
                manifest["clip_flags"] = res["flags"]
                job_id = rnd.job_id_for(project_id)
                sa = rnd.shot_assets_from_clips(shots, res["clips"], job_id)
            for f in manifest["clip_flags"]:
                mark = "⛔" if f["level"] == "block" else "⚠️"
                log(f"  {mark} {f['code']}: {f['message']}")

        # 1b) B-roll for figure/broll shots (real stock by default; AI stills opt-in).
        n_broll = sum(1 for sh in shots if sh.get("visual") == "broll")
        if not opts.no_visuals and n_broll:
            if opts.ai_visuals:
                from explainer.assets import visuals as vis
                log(f"generating AI stills for {n_broll} figure/broll shot(s) …")
                sa = vis.gather_visuals(shots, pdir, sa)
            elif os.environ.get("PIXABAY"):
                from explainer.assets import stock
                log(f"fetching stock b-roll for {n_broll} figure/broll shot(s) …")
                sa, got = stock.gather_stock(shots, pdir, sa, os.environ["PIXABAY"])
                if got:
                    manifest["footage_credit"] = "Pixabay"
                log(f"  stock clips: {got}/{n_broll}")
            else:
                log("  ⚠️ no PIXABAY key — figure/broll shots fall back to text.")

        # 1c) Generated visual-aid clips for `aid` shots (idempotent per clip).
        n_aid = sum(1 for sh in shots if sh.get("visual") == "aid")
        if n_aid and not opts.no_visuals:
            from explainer.assets import aid as aidmod
            made, acost = aidmod.generate_aids(shots, pdir, key=os.environ.get("OPENROUTER"),
                                               style=m.get("aid_style"))
            if made:
                log(f"aid clips: generated {made} (${acost:.2f})")
            sa, wired = aidmod.gather_aids(shots, pdir, sa)
            if wired:
                log(f"aid graphics: {wired}/{n_aid} aid shot(s) wired")

        # 1d) Animated SVG graphics for text beats.
        if not opts.no_svg:
            from explainer.assets import svg as svgmod
            n_text = sum(1 for sh in shots if sh.get("visual") in svgmod._SVG_SHOTS)
            if n_text:
                sa, got = svgmod.gather_svgs(shots, pdir, sa)
                if got:
                    log(f"svg graphics: {got}/{n_text} eligible beat(s)")
        manifest["shot_assets"] = {str(k): v for k, v in sa.items()}

        # 2) Narration (soundbite-mixed timeline when a shot speaks, else a read).
        narration_path = os.path.join(pdir, "narration.wav")
        soundbite_paths = {}
        for i, shot in enumerate(shots):
            if shot.get("speaks") and i in sa:
                ref = sa[i].get("speechUrl") or sa[i].get("videoUrl")
                if ref:
                    soundbite_paths[i] = os.path.join(pdir, os.path.basename(ref))
        log(f"narrating project #{project_id} (voice={voice or 'brand default'}) …")
        if soundbite_paths and audio.has_soundbites(shots):
            _, timeline = audio.assemble(shots, soundbite_paths, narration_path,
                                         tone=tone, speed=opts.speed,
                                         **({"voice": voice} if voice else {}))
            with open(os.path.join(pdir, "timeline.json"), "w", encoding="utf-8") as tf:
                json.dump(timeline, tf, ensure_ascii=False, indent=2)
            secs = (timeline[-1]["end_ms"] / 1000.0) if timeline else 0.0
            log(f"  assembled narration + {len(soundbite_paths)} soundbite(s) → {secs:.1f}s")
        else:
            _, secs = tts.narrate(script, narration_path, tone=tone, speed=opts.speed,
                                  **({"voice": voice} if voice else {}))
            log(f"  narration → {secs:.1f}s")
        manifest["narration_seconds"] = secs

        # 3) Ducked CC0 music bed (optional; never blocks assets).
        if not opts.no_music:
            from explainer.assets import music as mus
            bed = os.path.join(pdir, "music.wav")
            try:
                if mus.build_bed(project_id, narration_path, bed):
                    manifest["music"] = proj_url(project_id, "music.wav")
                    log(f"  music bed → {os.path.basename(bed)} (ducked)")
                else:
                    log("  (no CC0 tracks in library — skipping music)")
            except Exception as e:  # noqa: BLE001
                log(f"  ⚠️ music duck failed (skipping): {e}")

        with open(os.path.join(pdir, "assets.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        s.get(store.Project, project_id).status = "assets"
        s.commit()
    blocks = [f for f in manifest["clip_flags"] if f["level"] == "block"]
    log(f"assets ready → assets.json"
        + (f"  ({len(blocks)} block flag(s) to resolve in gate 1)" if blocks else ""))
    return manifest


def run_align(project_id, log=print):
    """Word-timestamp the narration against the shot list → align.json."""
    from explainer import align as al
    with store.session() as s:
        draft = latest_draft(s, project_id)
        if not draft:
            raise ValueError(f"no draft for project #{project_id}")
        script = draft.script or {}
    pdir = proj_dir(project_id)
    audio_path = os.path.join(pdir, "narration.wav")
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"no narration for project #{project_id} — run `assets` first")
    timeline = None
    tpath = os.path.join(pdir, "timeline.json")
    if os.path.isfile(tpath):
        with open(tpath, encoding="utf-8") as tf:
            timeline = json.load(tf)
    soundbite_clips, soundbite_words = {}, {}
    apath = os.path.join(pdir, "assets.json")
    if os.path.isfile(apath):
        with open(apath, encoding="utf-8") as af:
            sa = (json.load(af) or {}).get("shot_assets", {})
        for i, shot in enumerate(script.get("shots", [])):
            if not shot.get("speaks"):
                continue
            entry = sa.get(str(i)) or {}
            ref = entry.get("speechUrl") or entry.get("videoUrl")
            if ref:
                soundbite_clips[i] = os.path.join(pdir, os.path.basename(ref))
            wu = entry.get("wordsUrl")
            if wu:
                wp = os.path.join(pdir, os.path.basename(wu))
                if os.path.isfile(wp):
                    with open(wp, encoding="utf-8") as wf:
                        soundbite_words[i] = json.load(wf)
    if soundbite_words:
        log(f"  captions: pulled transcript for {len(soundbite_words)} soundbite(s) "
            f"(ASR fallback for the rest)")
    log(f"aligning project #{project_id}{' (soundbite timeline)' if timeline else ''} …")
    alignment = al.align(audio_path, script, timeline=timeline,
                         soundbite_clips=soundbite_clips, soundbite_words=soundbite_words)
    out = os.path.join(pdir, "align.json")
    al.write_alignment(alignment, out)
    log(f"aligned {len(alignment['words'])} words, {len(alignment['shots'])} shots "
        f"({alignment['duration_ms']/1000:.1f}s)")
    return {"words": len(alignment["words"]), "shots": len(alignment["shots"]),
            "duration_ms": alignment["duration_ms"]}


def approve_draft(project_id, log=print):
    """Gate 2: mark the latest draft approved so the scheduler can drip it."""
    with store.session() as s:
        draft = latest_draft(s, project_id)
        if not draft:
            raise ValueError(f"no draft for project #{project_id}")
        draft.status = "approved"
        s.commit()
        did = draft.id
    log(f"project #{project_id} draft #{did} approved")
    return {"project_id": project_id, "draft_id": did, "status": "approved"}


def run_schedule(project_id=None, log=print):
    """Schedule one project now, or drip the next ready one (scheduler tick)."""
    from explainer import schedule as sch
    res = sch.schedule_project(project_id) if project_id else sch.tick()
    if not res:
        log("nothing ready to schedule (need an approved, rendered project)")
        return None
    log(f"scheduled project #{res['project_id']} for {res['due_at']}")
    for r in res.get("results", []):
        ok = "✓" if r.get("ok") else "✗"
        log(f"  {ok} {r['service']}: {r.get('post_id') or r.get('error')}")
    return res


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

    # Mood-aware theme (draft.script["mood"] -> dark palette/highlight).
    theme = None
    with store.session() as s:
        d = latest_draft(s, project_id)
        mood_name = (d.script or {}).get("mood") if d else None
    if mood_name:
        theme = rnd.brand_theme(mood_name)
        log(f"  theme mood: {mood_name}")

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
                     assets=shot_assets, theme=theme, poll=not no_wait,
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
