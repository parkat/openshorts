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


def _stub(name):
    def _f(args):
        print(f"[{name}] not implemented yet — Phase 1 (see HANDOFF-explainer-pipeline.md).")
    return _f


def cmd_worker(args):
    """P0 skeleton loop. Phase 2 ticks the scheduler + (optional) radar here."""
    store.init_db()
    print("explainer worker alive (P0 skeleton) — scheduler/radar wired in Phase 2", flush=True)
    while True:
        time.sleep(60)


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

    for name in ["factcheck", "assets", "render", "approve", "schedule"]:
        sub.add_parser(name, help=f"{name} (Phase 1)").set_defaults(func=_stub(name))

    sub.add_parser("worker", help="run the background worker loop").set_defaults(func=cmd_worker)

    args = p.parse_args()
    args.func(args)
