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
    """Narration TTS for the project's latest draft -> narration.wav on disk."""
    store.init_db()
    from explainer.assets import tts
    with store.session() as s:
        draft = _latest_draft(s, args.project_id)
        if not draft:
            print(f"no draft for project #{args.project_id}")
            return
        script = draft.script or {}
        voice = args.voice or draft.voice_id or None
        out = os.path.join(_proj_dir(args.project_id), "narration.wav")
        print(f"narrating project #{args.project_id} (voice={voice or 'brand default'}) …", flush=True)
        path, secs = tts.narrate(script, out, **({"voice": voice} if voice else {}))
        s.get(store.Project, args.project_id).status = "assets"
        s.commit()
        print(f"narration → {path}  ({secs:.1f}s)")


def cmd_align(args):
    """Word-timestamp the narration against the shot list -> align.json."""
    store.init_db()
    from explainer import align as al
    with store.session() as s:
        draft = _latest_draft(s, args.project_id)
        if not draft:
            print(f"no draft for project #{args.project_id}")
            return
        audio = os.path.join(_proj_dir(args.project_id), "narration.wav")
        if not os.path.isfile(audio):
            print(f"no narration at {audio} — run `assets` first")
            return
        print(f"aligning project #{args.project_id} …", flush=True)
        alignment = al.align(audio, draft.script or {})
        out = os.path.join(_proj_dir(args.project_id), "align.json")
        al.write_alignment(alignment, out)
        print(f"aligned {len(alignment['words'])} words, {len(alignment['shots'])} shots "
              f"({alignment['duration_ms']/1000:.1f}s) → {out}")


def cmd_render(args):
    """Render the project (align.json + narration + assets) -> 9:16 MP4."""
    store.init_db()
    from explainer import render as rnd
    align_path = os.path.join(_proj_dir(args.project_id), "align.json")
    if not os.path.isfile(align_path):
        print(f"no {align_path} — run `align` first")
        return
    with open(align_path, encoding="utf-8") as f:
        alignment = json.load(f)
    narration_url = _proj_url(args.project_id, "narration.wav")
    with store.session() as s:
        s.get(store.Project, args.project_id).status = "render"
        s.commit()
    print(f"rendering project #{args.project_id} via {rnd.RENDER_SERVICE_URL} …", flush=True)
    job = rnd.render(alignment, narration_url, args.project_id, poll=not args.no_wait,
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


def _stub(name):
    def _f(args):
        print(f"[{name}] not implemented yet — Phase 2 (see HANDOFF-explainer-pipeline.md).")
    return _f


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

    ap = sub.add_parser("assets", help="narrate the draft (TTS) into narration.wav")
    ap.add_argument("--project-id", type=int, required=True)
    ap.add_argument("--voice", default="", help="override the TTS voice")
    ap.set_defaults(func=cmd_assets)

    lp = sub.add_parser("align", help="word-timestamp the narration -> align.json")
    lp.add_argument("--project-id", type=int, required=True)
    lp.set_defaults(func=cmd_align)

    rp = sub.add_parser("render", help="render the explainer 9:16 MP4")
    rp.add_argument("--project-id", type=int, required=True)
    rp.add_argument("--no-wait", action="store_true", help="submit without polling")
    rp.add_argument("--service-url", default="", help="override RENDER_SERVICE_URL")
    rp.set_defaults(func=cmd_render)

    pp = sub.add_parser("approve", help="gate-2 approve a rendered draft")
    pp.add_argument("--project-id", type=int, required=True)
    pp.set_defaults(func=cmd_approve)

    cp = sub.add_parser("schedule", help="drip the next ready project (or --project-id)")
    cp.add_argument("--project-id", type=int, default=0, help="schedule a specific project")
    cp.set_defaults(func=cmd_schedule)

    sub.add_parser("factcheck", help="factcheck (Phase 2)").set_defaults(func=_stub("factcheck"))

    sub.add_parser("worker", help="run the background worker loop").set_defaults(func=cmd_worker)

    args = p.parse_args()
    args.func(args)
