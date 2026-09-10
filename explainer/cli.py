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
    from explainer import service
    try:
        service.run_script(args.topic_id, model=(args.model or None))
    except ValueError as e:
        print(str(e))


def cmd_assets(args):
    """Build the project's assets: narration TTS, accent clips (guardrails +
    provenance), and a ducked CC0 music bed. Writes an assets.json manifest that
    `render` consumes. Skips clips (--no-clips) or music (--no-music) on request."""
    store.init_db()
    from explainer import service
    opts = service.AssetOpts(
        voice=args.voice or None, tone=args.tone, speed=args.speed,
        no_clips=args.no_clips, no_visuals=args.no_visuals,
        ai_visuals=args.ai_visuals, no_svg=args.no_svg, no_music=args.no_music,
        aid_mode=(args.aid_mode or None))
    try:
        service.run_assets(args.project_id, opts)
    except ValueError as e:
        print(str(e))


def cmd_align(args):
    """Word-timestamp the narration against the shot list -> align.json."""
    store.init_db()
    from explainer import service
    try:
        service.run_align(args.project_id)
    except (ValueError, FileNotFoundError) as e:
        print(str(e))


def cmd_clipfind(args):
    """Read the reference videos' transcripts and pick the best accent-clip window
    for each accent_clip shot; write an inspectable clips_plan.json."""
    store.init_db()
    from explainer import service
    try:
        service.run_clipfind(args.project_id, model=(args.model or None))
    except ValueError as e:
        print(str(e))


def cmd_factcheck(args):
    """Extract atomic claims from the latest draft and label them against sources;
    store the flags on the draft for gate 1."""
    store.init_db()
    from explainer import service
    source_text = ""
    if args.source_file and os.path.isfile(args.source_file):
        with open(args.source_file, encoding="utf-8") as f:
            source_text = f.read()
    try:
        service.run_factcheck(args.project_id, source_text, model=(args.model or None))
    except ValueError as e:
        print(str(e))


def cmd_render(args):
    """Render the project (align.json + narration + assets) -> 9:16 MP4."""
    store.init_db()
    from explainer import service
    try:
        service.run_render(args.project_id, force=args.force, no_wait=args.no_wait,
                           service_url=(args.service_url or None))
    except FileNotFoundError as e:
        print(str(e))


def cmd_approve(args):
    """Gate-2 approve: mark the latest draft approved so the scheduler can drip it."""
    store.init_db()
    from explainer import service
    try:
        service.approve_draft(args.project_id)
    except ValueError as e:
        print(str(e))


def cmd_schedule(args):
    """Schedule a project now, or drip the next ready one (1/day, 06:00 LA)."""
    store.init_db()
    from explainer import service
    try:
        service.run_schedule(args.project_id or None)
    except Exception as e:  # noqa: BLE001 — surface the failure to the driver
        print(f"schedule error: {e}")


def cmd_cache(args):
    """Inspect / seed the persistent content cache (transcripts, generated videos,
    accent clips, SVGs) — reusable across videos."""
    store.init_db()
    from explainer import cache as cch
    if args.action == "backfill":
        made = cch.backfill()
        print(f"backfilled {made} item(s) into the content cache")
    elif args.action == "list":
        rows = cch.find(kind=args.kind or None, label=args.label or None,
                        text=args.text or None)
        for r in rows:
            print(f"  [{r.kind:9}] {r.path}  {cch.human_bytes(r.bytes)}  "
                  f"x{r.use_count}  labels={r.labels}  src={(r.source or '')[:48]}")
        print(f"{len(rows)} item(s)")
    else:  # stats (default)
        s = cch.stats()
        print(f"content cache: {s['total_items']} items, "
              f"{cch.human_bytes(s['total_bytes'])} total")
        for kind, d in sorted(s["by_kind"].items()):
            print(f"  {kind:10} {d['count']:4}  {cch.human_bytes(d['bytes']):>9}"
                  f"   ({d['reuses']} reuse(s))")


def cmd_worker(args):
    """Background loop: drip each lane's approved work into the publishing calendar.

    Both lanes tick on the same pass so they compete for slots through one shared
    calendar rather than two schedulers racing each other. Each lane's tick is a
    no-op unless its auto-drip is on (see publishing.py) — the clips lane ships
    with it OFF, because a batch of ten from one source is meant to be released
    deliberately.
    """
    store.init_db()
    from explainer import schedule as sch
    from clips import publish as clips_publish
    interval = int(os.environ.get("SCHEDULER_INTERVAL", "900"))
    print(f"worker alive — publishing tick every {interval}s", flush=True)
    while True:
        try:
            res = sch.tick()
            if res:
                print(f"[worker] scheduled project #{res['project_id']} "
                      f"for {res['due_at']}", flush=True)
        except Exception as e:  # noqa: BLE001 — a bad tick must not kill the loop
            print(f"[worker] explainer tick failed: {e}", flush=True)
        try:
            res = clips_publish.tick(log=lambda m: None)
            if res:
                print(f"[worker] queued clip #{res['ref_id']} "
                      f"for {res['due_at']}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] clips tick failed: {e}", flush=True)
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
    ap.add_argument("--no-svg", action="store_true", help="skip SVG graphics on text beats")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="narration tempo multiplier (e.g. 1.15 = 15%% faster, pitch preserved)")
    ap.add_argument("--no-music", action="store_true", help="skip the music bed")
    ap.add_argument("--aid-mode", default="", choices=["", "motion", "video", "motion-then-video"],
                    help="how to make `aid` visuals: motion = LLM-authored Remotion "
                         "component (default, ~$0.04); video = paid clips from the "
                         "video model; motion-then-video = fall back per shot")
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

    chp = sub.add_parser("cache", help="inspect/seed the persistent content cache")
    chp.add_argument("action", nargs="?", default="stats",
                     choices=["stats", "list", "backfill"])
    chp.add_argument("--kind", default="", help="filter: video|image|transcript|clip|svg|youtube|audio|code")
    chp.add_argument("--label", default="", help="filter by a concept/keyword label")
    chp.add_argument("--text", default="", help="filter by substring in source/labels")
    chp.set_defaults(func=cmd_cache)

    sub.add_parser("worker", help="run the background worker loop").set_defaults(func=cmd_worker)

    args = p.parse_args()
    args.func(args)
