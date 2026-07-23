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

    for name in ["script", "factcheck", "assets", "render", "approve", "schedule"]:
        sub.add_parser(name, help=f"{name} (Phase 1)").set_defaults(func=_stub(name))

    sub.add_parser("worker", help="run the background worker loop").set_defaults(func=cmd_worker)

    args = p.parse_args()
    args.func(args)
