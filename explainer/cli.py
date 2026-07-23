"""`python -m explainer <command>` — the scriptable driver for the explainer lane.

One of the two control surfaces (the other is the dashboard); both operate on the
same SQLite store. A Claude Code session (Max plan) can drive the whole pipeline
here and do the reasoning-heavy steps itself, writing results back to the store.

Phase 0: initdb, topics (list/add), queue, worker. Stage commands (script,
factcheck, assets, render, approve, schedule) are stubs wired in Phase 1+.
"""
import os
import sys
import json
import time
import argparse

# Ensure the repo root (where store.py lives) is importable when run as a module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()  # so the CLI has OPENROUTER/BUFFER when run via `docker exec`
except Exception:
    pass
import store  # noqa: E402

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")


def _proj_dir(project_id):
    """Filesystem asset dir for a project (shared ./output volume)."""
    from explainer.render import job_id_for
    d = os.path.join(OUTPUT_DIR, job_id_for(project_id))
    os.makedirs(d, exist_ok=True)
    return d


def _proj_url(project_id, filename):
    """Renderer-relative URL for an asset (render-service rewrites /output/...)."""
    from explainer.render import job_id_for
    return f"/output/{job_id_for(project_id)}/{filename}"


def _latest_draft(s, project_id):
    return (s.query(store.Draft)
            .filter(store.Draft.project_id == project_id)
            .order_by(store.Draft.id.desc()).first())


def cmd_initdb(args):
    path = store.init_db()
    print(f"DB initialized: {path}")


def cmd_topics(args):
    store.init_db()
    with store.session() as s:
        if args.action == "add":
            if not args.title:
                print("error: --title required for `topics add`")
                return
            sources = json.loads(args.sources) if args.sources else []
            t = store.Topic(title=args.title, origin="manual", angle=args.angle or "",
                            summary=args.summary or "", sources=sources)
            s.add(t)
            s.commit()
            print(f"added topic #{t.id}: {t.title}")
        else:
            rows = s.query(store.Topic).order_by(store.Topic.created_at.desc()).all()
            if not rows:
                print("(no topics)")
                return
            for t in rows:
                n = len(t.sources or [])
                print(f"#{t.id} [{t.status}] {t.title}  ({t.origin}, {n} source(s))")


def cmd_queue(args):
    store.init_db()
    with store.session() as s:
        rows = s.query(store.Project).order_by(store.Project.updated_at.desc()).all()
        if not rows:
            print("(queue empty — add a topic with `topics add`, then Phase 1 builds projects)")
            return
        for p in rows:
            print(f"#{p.id} [{p.status}] {p.title or '(untitled)'}  topic={p.topic_id}  updated={p.updated_at:%Y-%m-%d %H:%M}")


def cmd_script(args):
    store.init_db()
    from explainer import script as scr
    with store.session() as s:
        topic = s.get(store.Topic, args.topic_id)
        if not topic:
            print(f"topic #{args.topic_id} not found")
            return
        print(f"drafting script for topic #{topic.id}: {topic.title} …", flush=True)
        sl = scr.generate_script(topic.title, topic.summary, topic.sources or [],
                                 model=(args.model or None))
        proj = store.Project(topic_id=topic.id, title=sl.get("title") or topic.title, status="review")
        s.add(proj)
        s.flush()
        draft = store.Draft(project_id=proj.id, script=sl, status="needs_review")
        s.add(draft)
        s.commit()
        print(f"\n=== {sl.get('title')}  (~{sl.get('estimated_seconds')}s) ===")
        for shot in sl.get("shots", []):
            print(f"[{str(shot.get('role','?')):6}] {shot.get('seconds','?')}s  {shot.get('narration','')}")
            print(f"         · {shot.get('visual','?')}: {shot.get('visual_note','')}  (src: {shot.get('source')})")
        caps = sl.get("captions", {})
        if caps:
            print("\ncaptions:")
            for k in ("youtube", "tiktok", "instagram"):
                if caps.get(k):
                    print(f"  {k}: {caps[k]}")
        print(f"\nstored → project #{proj.id}, draft #{draft.id} (status: needs_review)")


def cmd_assets(args):
    """Build the project's assets: narration TTS, accent clips (guardrails +
    provenance), and a ducked CC0 music bed. Writes an assets.json manifest that
    `render` consumes. Skips clips (--no-clips) or music (--no-music) on request."""
    store.init_db()
    from explainer.assets import tts, audio
    from explainer import render as rnd
    proj_dir = _proj_dir(args.project_id)
    with store.session() as s:
        draft = _latest_draft(s, args.project_id)
        if not draft:
            print(f"no draft for project #{args.project_id}")
            return
        script = draft.script or {}
        shots = script.get("shots", [])
        topic = s.get(store.Topic, s.get(store.Project, args.project_id).topic_id)
        sources = (topic.sources if topic else None) or []
        voice = args.voice or draft.voice_id or None
        # Tone: --tone overrides; default = brand tone; "none"/"off"/"" disables.
        from explainer.brand import BRAND
        if args.tone is None:
            tone = BRAND.get("tts_tone")
        elif args.tone.strip().lower() in ("", "none", "off", "neutral"):
            tone = None
        else:
            tone = args.tone
        if tone:
            print(f"  tone: {tone}")

        manifest = {"music": None, "shot_assets": {}, "clip_flags": [], "narration_seconds": 0}

        # 1) Accent clips FIRST (soundbite narration needs the clip durations).
        #    Prefer a clip-finder plan (transcript-selected windows tied to shots);
        #    else fall back to the topic's manual in/out timestamps.
        sa = {}
        if not args.no_clips:
            from explainer.assets import clips as clp
            plan_path = os.path.join(proj_dir, "clips_plan.json")
            if os.path.isfile(plan_path):
                with open(plan_path, encoding="utf-8") as pf:
                    sels = (json.load(pf) or {}).get("selections", [])
                if sels:
                    print(f"fetching {len(sels)} clip-finder window(s) …", flush=True)
                    res = clp.gather_from_plan(s, args.project_id, sels, proj_dir)
                    sa = res["shot_assets"]
                    manifest["clip_flags"] = res["flags"]
            elif any(x.get("type") == "youtube" for x in sources):
                print("fetching accent clips (manual timestamps) …", flush=True)
                res = clp.gather_accent_clips(s, args.project_id, sources, proj_dir)
                manifest["clip_flags"] = res["flags"]
                job_id = rnd.job_id_for(args.project_id)
                sa = rnd.shot_assets_from_clips(shots, res["clips"], job_id)
            for f in manifest["clip_flags"]:
                mark = "⛔" if f["level"] == "block" else "⚠️"
                print(f"  {mark} {f['code']}: {f['message']}")

        # 1b) B-roll for figure/broll shots. Default: REAL stock footage (Pixabay,
        #     commercial-safe, no AI-disclosure label). AI stills only with
        #     --ai-visuals. Either way, Ken Burns / jump-cuts apply in the render.
        n_broll = sum(1 for sh in shots if sh.get("visual") in ("figure", "broll"))
        if not args.no_visuals and n_broll:
            if args.ai_visuals:
                from explainer.assets import visuals as vis
                print(f"generating AI stills for {n_broll} figure/broll shot(s) …", flush=True)
                sa = vis.gather_visuals(shots, proj_dir, sa)
            elif os.environ.get("PIXABAY"):
                from explainer.assets import stock
                print(f"fetching stock b-roll for {n_broll} figure/broll shot(s) …", flush=True)
                sa, got = stock.gather_stock(shots, proj_dir, sa, os.environ["PIXABAY"])
                print(f"  stock clips: {got}/{n_broll}"
                      + ("" if got == n_broll else "  (unmatched shots fall back to text)"))
            else:
                print("  ⚠️ no PIXABAY key in .env — figure/broll shots fall back to text "
                      "(add PIXABAY, or use --ai-visuals).")
        manifest["shot_assets"] = {str(k): v for k, v in sa.items()}

        # 2) Narration. Soundbite shorts assemble a mixed timeline (Orus + silence
        #    gaps where the clip speaks); otherwise a single continuous TTS read.
        narration_path = os.path.join(proj_dir, "narration.wav")
        soundbite_paths = {
            i: os.path.join(proj_dir, os.path.basename(sa[i]["videoUrl"]))
            for i, shot in enumerate(shots)
            if shot.get("speaks") and i in sa
        }
        print(f"narrating project #{args.project_id} (voice={voice or 'brand default'}) …", flush=True)
        if soundbite_paths and audio.has_soundbites(shots):
            _, timeline = audio.assemble(shots, soundbite_paths, narration_path,
                                         tone=tone, speed=args.speed,
                                         **({"voice": voice} if voice else {}))
            with open(os.path.join(proj_dir, "timeline.json"), "w", encoding="utf-8") as tf:
                json.dump(timeline, tf, ensure_ascii=False, indent=2)
            secs = (timeline[-1]["end_ms"] / 1000.0) if timeline else 0.0
            print(f"  assembled narration + {len(soundbite_paths)} soundbite(s) → {secs:.1f}s")
        else:
            _, secs = tts.narrate(script, narration_path, tone=tone, speed=args.speed,
                                  **({"voice": voice} if voice else {}))
            print(f"  narration → {secs:.1f}s")
        manifest["narration_seconds"] = secs

        # 3) Ducked CC0 music bed
        if not args.no_music:
            from explainer.assets import music as mus
            bed = os.path.join(proj_dir, "music.wav")
            try:
                if mus.build_bed(args.project_id, narration_path, bed):
                    manifest["music"] = _proj_url(args.project_id, "music.wav")
                    print(f"  music bed → {os.path.basename(bed)} (ducked)")
                else:
                    print("  (no CC0 tracks in library — skipping music)")
            except Exception as e:  # noqa: BLE001 — music is optional, never block assets
                print(f"  ⚠️ music duck failed (skipping): {e}")

        with open(os.path.join(proj_dir, "assets.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        s.get(store.Project, args.project_id).status = "assets"
        s.commit()
    blocks = [f for f in manifest["clip_flags"] if f["level"] == "block"]
    print(f"assets ready → {proj_dir}/assets.json"
          + (f"  ({len(blocks)} block flag(s) to resolve in gate 1)" if blocks else ""))


def cmd_align(args):
    """Word-timestamp the narration against the shot list -> align.json."""
    store.init_db()
    from explainer import align as al
    with store.session() as s:
        draft = _latest_draft(s, args.project_id)
        if not draft:
            print(f"no draft for project #{args.project_id}")
            return
        proj_dir = _proj_dir(args.project_id)
        audio = os.path.join(proj_dir, "narration.wav")
        if not os.path.isfile(audio):
            print(f"no narration at {audio} — run `assets` first")
            return
        timeline = None
        tpath = os.path.join(proj_dir, "timeline.json")
        if os.path.isfile(tpath):
            with open(tpath, encoding="utf-8") as tf:
                timeline = json.load(tf)
        print(f"aligning project #{args.project_id}{' (soundbite timeline)' if timeline else ''} …", flush=True)
        alignment = al.align(audio, draft.script or {}, timeline=timeline)
        out = os.path.join(_proj_dir(args.project_id), "align.json")
        al.write_alignment(alignment, out)
        print(f"aligned {len(alignment['words'])} words, {len(alignment['shots'])} shots "
              f"({alignment['duration_ms']/1000:.1f}s) → {out}")


def cmd_clipfind(args):
    """Read the reference videos' transcripts and pick the best accent-clip window
    for each accent_clip shot; write an inspectable clips_plan.json."""
    store.init_db()
    from explainer import clipfinder as cf
    proj_dir = _proj_dir(args.project_id)
    with store.session() as s:
        draft = _latest_draft(s, args.project_id)
        if not draft:
            print(f"no draft for project #{args.project_id}")
            return
        topic = s.get(store.Topic, s.get(store.Project, args.project_id).topic_id)
        sources = (topic.sources if topic else None) or []
        script = draft.script or {}
    refs = [x for x in sources if x.get("type") == "youtube"]
    if not refs:
        print("no YouTube reference sources on this topic")
        return
    print(f"reading {len(refs)} reference transcript(s) + selecting windows …", flush=True)
    result = cf.plan(script, sources, proj_dir, model=(args.model or None))
    with open(os.path.join(proj_dir, "clips_plan.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\nreferences:")
    for r in result["references"]:
        print(f"  {r['channel']} — {r['title'][:60]} ({int(r['duration'])}s, {r['segments']} segs)")
    print(f"\n{len(result['selections'])} clip(s) selected for {result['needs']} accent shot(s):")
    for sel in result["selections"]:
        dur = sel["out"] - sel["in"]
        print(f"  shot {sel['shot_index']} ← {sel['channel']}  {sel['in']:.0f}–{sel['out']:.0f}s ({dur:.0f}s)")
        print(f"     “{sel['quote']}”")
        print(f"     ↳ {sel['why']}")
    print(f"\nplan → {proj_dir}/clips_plan.json  (assets will fetch these; edit to curate)")


def cmd_factcheck(args):
    """Extract atomic claims from the latest draft and label them against sources;
    store the flags on the draft for gate 1."""
    store.init_db()
    from explainer import factcheck as fc
    source_text = ""
    if args.source_file and os.path.isfile(args.source_file):
        with open(args.source_file, encoding="utf-8") as f:
            source_text = f.read()
    with store.session() as s:
        draft = _latest_draft(s, args.project_id)
        if not draft:
            print(f"no draft for project #{args.project_id}")
            return
        print(f"fact-checking project #{args.project_id} "
              f"({'with sources' if source_text else 'general knowledge, strict'}) …", flush=True)
        result = fc.factcheck(draft.script or {}, source_text, model=(args.model or None))
        draft.factcheck = result
        if any(c["label"] != "supported" for c in result["claims"]):
            draft.status = "needs_review"
        s.commit()
        sm = result["summary"]
        print(f"\nclaims: {sm['supported']} supported · {sm['overstated']} overstated · {sm['unsupported']} unsupported")
        for c in fc.flags(result):
            mark = "⛔" if c["label"] == "unsupported" else "⚠️"
            print(f"  {mark} [{c['label']}] {c['claim']}")
            if c.get("note"):
                print(f"       ↳ {c['note']}")
        if not fc.flags(result):
            print("  ✓ no flags — all claims supported")


def cmd_render(args):
    """Render the project (align.json + narration + assets) -> 9:16 MP4."""
    store.init_db()
    from explainer import render as rnd
    proj_dir = _proj_dir(args.project_id)
    align_path = os.path.join(proj_dir, "align.json")
    if not os.path.isfile(align_path):
        print(f"no {align_path} — run `align` first")
        return
    with open(align_path, encoding="utf-8") as f:
        alignment = json.load(f)
    # Optional asset manifest from `assets` (music bed + accent-clip shot map).
    music_url, shot_assets, clip_flags = None, None, []
    apath = os.path.join(proj_dir, "assets.json")
    if os.path.isfile(apath):
        with open(apath, encoding="utf-8") as f:
            man = json.load(f)
        music_url = man.get("music")
        shot_assets = {int(k): v for k, v in (man.get("shot_assets") or {}).items()}
        clip_flags = man.get("clip_flags") or []
    blocks = [f for f in clip_flags if f.get("level") == "block"]
    if blocks and not args.force:
        print(f"⛔ {len(blocks)} unresolved guardrail block(s) — fix or re-run with --force:")
        for f in blocks:
            print(f"   {f['code']}: {f['message']}")
        return
    narration_url = _proj_url(args.project_id, "narration.wav")
    # Honest narration-dominance signal (§5), from displayed (not fetched) durations.
    scenes = rnd.build_scene_list(alignment, shot_assets)
    frac = rnd.accent_display_fraction(scenes)
    if frac > 0.4:
        print(f"⚠️ accent footage is {frac*100:.0f}% of runtime — keep original ≥60% (§5).")
    with store.session() as s:
        s.get(store.Project, args.project_id).status = "render"
        s.commit()
    print(f"rendering project #{args.project_id} via {rnd.RENDER_SERVICE_URL} …", flush=True)
    job = rnd.render(alignment, narration_url, args.project_id, music_url=music_url,
                     assets=shot_assets, poll=not args.no_wait,
                     service_url=(args.service_url or None))
    if args.no_wait:
        print(f"submitted render {job['renderId']} (job {job['job_id']})")
    else:
        with store.session() as s:
            s.get(store.Project, args.project_id).status = "review"
            s.commit()
        print(f"rendered → output/{job['job_id']}/{job.get('output_basename')}")


def cmd_approve(args):
    """Gate-2 approve: mark the latest draft approved so the scheduler can drip it."""
    store.init_db()
    with store.session() as s:
        draft = _latest_draft(s, args.project_id)
        if not draft:
            print(f"no draft for project #{args.project_id}")
            return
        draft.status = "approved"
        s.commit()
        print(f"project #{args.project_id} draft #{draft.id} approved")


def cmd_schedule(args):
    """Schedule a project now, or drip the next ready one (1/day, 06:00 LA)."""
    store.init_db()
    from explainer import schedule as sch
    try:
        if args.project_id:
            res = sch.schedule_project(args.project_id)
        else:
            res = sch.tick()
    except Exception as e:  # noqa: BLE001 — surface the failure to the driver
        print(f"schedule error: {e}")
        return
    if not res:
        print("nothing ready to schedule (need an approved, rendered project)")
        return
    print(f"scheduled project #{res['project_id']} for {res['due_at']}")
    print(f"  media: {res.get('video_url')}")
    for r in res.get("results", []):
        ok = "✓" if r.get("ok") else "✗"
        print(f"  {ok} {r['service']}: {r.get('post_id') or r.get('error')}")


def cmd_worker(args):
    """Background loop: tick the 1/day scheduler. (Optional radar lands in Phase 3.)"""
    store.init_db()
    from explainer import schedule as sch
    interval = int(os.environ.get("SCHEDULER_INTERVAL", "900"))
    print(f"explainer worker alive — scheduler tick every {interval}s", flush=True)
    while True:
        try:
            res = sch.tick()
            if res:
                print(f"[worker] scheduled project #{res['project_id']} for {res['due_at']}", flush=True)
        except Exception as e:  # noqa: BLE001 — a bad tick must not kill the loop
            print(f"[worker] scheduler tick failed: {e}", flush=True)
        time.sleep(interval)


def main():
    p = argparse.ArgumentParser(prog="explainer", description="OpenShorts explainer-lane driver")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("initdb", help="create/upgrade the SQLite schema").set_defaults(func=cmd_initdb)
    sub.add_parser("queue", help="list projects in the pipeline").set_defaults(func=cmd_queue)

    tp = sub.add_parser("topics", help="list or add topics")
    tp.add_argument("action", nargs="?", default="list", choices=["list", "add"])
    tp.add_argument("--title", default="")
    tp.add_argument("--summary", default="")
    tp.add_argument("--angle", default="")
    tp.add_argument("--sources", default="", help='JSON list, e.g. \'[{"type":"youtube","url":"..."}]\'')
    tp.set_defaults(func=cmd_topics)

    sp = sub.add_parser("script", help="draft a shot-list script for a topic")
    sp.add_argument("--topic-id", type=int, required=True)
    sp.add_argument("--model", default="", help="override the OpenRouter model")
    sp.set_defaults(func=cmd_script)

    ap = sub.add_parser("assets", help="build assets: narration, accent clips, music bed")
    ap.add_argument("--project-id", type=int, required=True)
    ap.add_argument("--voice", default="", help="override the TTS voice")
    ap.add_argument("--tone", default=None,
                    help="TTS delivery tone (default: brand; 'none' to disable)")
    ap.add_argument("--no-clips", action="store_true", help="skip accent-clip fetch")
    ap.add_argument("--no-visuals", action="store_true", help="skip b-roll for figure/broll shots")
    ap.add_argument("--ai-visuals", action="store_true",
                    help="use AI-generated stills instead of real stock footage (adds AI label)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="narration tempo multiplier (e.g. 1.15 = 15%% faster, pitch preserved)")
    ap.add_argument("--no-music", action="store_true", help="skip the music bed")
    ap.set_defaults(func=cmd_assets)

    fp = sub.add_parser("factcheck", help="claim-check the draft against sources")
    fp.add_argument("--project-id", type=int, required=True)
    fp.add_argument("--source-file", default="", help="path to source text to verify against")
    fp.add_argument("--model", default="", help="override the OpenRouter model")
    fp.set_defaults(func=cmd_factcheck)

    cfp = sub.add_parser("clipfind", help="pick accent-clip windows from reference transcripts")
    cfp.add_argument("--project-id", type=int, required=True)
    cfp.add_argument("--model", default="", help="override the OpenRouter model")
    cfp.set_defaults(func=cmd_clipfind)

    lp = sub.add_parser("align", help="word-timestamp the narration -> align.json")
    lp.add_argument("--project-id", type=int, required=True)
    lp.set_defaults(func=cmd_align)

    rp = sub.add_parser("render", help="render the explainer 9:16 MP4")
    rp.add_argument("--project-id", type=int, required=True)
    rp.add_argument("--no-wait", action="store_true", help="submit without polling")
    rp.add_argument("--force", action="store_true", help="render despite guardrail block flags")
    rp.add_argument("--service-url", default="", help="override RENDER_SERVICE_URL")
    rp.set_defaults(func=cmd_render)

    pp = sub.add_parser("approve", help="gate-2 approve a rendered draft")
    pp.add_argument("--project-id", type=int, required=True)
    pp.set_defaults(func=cmd_approve)

    cp = sub.add_parser("schedule", help="drip the next ready project (or --project-id)")
    cp.add_argument("--project-id", type=int, default=0, help="schedule a specific project")
    cp.set_defaults(func=cmd_schedule)

    sub.add_parser("worker", help="run the background worker loop").set_defaults(func=cmd_worker)

    args = p.parse_args()
    args.func(args)
