"""`python -m clips <command>` — the scriptable driver for the clips lane.

Mines one long-form video for many standalone Shorts. Stages run independently so
you can stop and look at any point (the whole design assumes you will):

    python -m clips ingest  --url https://youtu.be/...      # one download + transcript
    python -m clips moments --source-id 1 --limit 8         # LLM -> candidate windows
    python -m clips queue   --source-id 1                   # read them before spending
    python -m clips cut     --source-id 1 --all             # local cuts + captions
    python -m clips render  --source-id 1 --all             # finished 9:16 MP4s
    python -m clips approve --candidate-id 3

`run` chains all of it for a source you already trust.

Costs: only `moments` spends (one LLM call per ~40k chars of transcript). `ingest`
spends bandwidth once; `cut` and `render` are local and free.
"""
import os
import sys
import json
import argparse

# Ensure the repo root (where store.py lives) is importable when run as a module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()  # so the CLI has OPENROUTER when run via `docker exec`
except Exception:
    pass
import store  # noqa: E402


def _fmt_hms(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _candidate_ids(args, service, need_cut=False):
    """Resolve --candidate-id / --source-id --all into a list of ids."""
    if args.candidate_id:
        return [args.candidate_id]
    if not args.source_id:
        raise SystemExit("error: pass --candidate-id, or --source-id with --all")
    rows = service.list_candidates(source_id=args.source_id)
    if need_cut:
        rows = [r for r in rows if r["status"] in ("cut", "rendered")]
    else:
        rows = [r for r in rows if r["status"] == "candidate"]
    if not rows:
        raise SystemExit(f"no matching candidates for source #{args.source_id}")
    return [r["id"] for r in rows]


def cmd_ingest(args):
    store.init_db()
    from clips import service
    res = service.run_ingest(args.url)
    print(f"source #{res['source_id']}: {res['segments']} transcript segments "
          f"({res['transcript_source']})")


def cmd_moments(args):
    store.init_db()
    from clips import service
    if args.prompt:
        from clips import moments as mo
        print(mo.manual_prompt(service.load_transcript(args.source_id)))
        return
    res = service.run_moments(args.source_id, limit=args.limit,
                              model=(args.model or None), from_file=args.from_file)
    for c in service.list_candidates(source_id=res["source_id"]):
        loop = f" ⟲{_fmt_hms(c['payoff_s'])}" if c.get('payoff_s') else ""
        print(f"  #{c['id']} [{c['score']:.2f}] {_fmt_hms(c['start_s'])}"
              f"-{_fmt_hms(c['end_s'])} ({c['seconds']}s){loop}  {c['title']}")


def cmd_cut(args):
    store.init_db()
    from clips import service
    for cid in _candidate_ids(args, service):
        try:
            service.run_cut(cid, edit=(args.edit or None))
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            print(f"  ✗ #{cid}: {e}")


def cmd_render(args):
    store.init_db()
    from clips import service
    for cid in _candidate_ids(args, service, need_cut=True):
        try:
            service.run_render(cid, mood=(args.mood or None),
                               no_wait=args.no_wait,
                               service_url=(args.service_url or None))
        except (ValueError, FileNotFoundError, RuntimeError, TimeoutError) as e:
            print(f"  ✗ #{cid}: {e}")


def cmd_run(args):
    """ingest -> moments -> cut -> render, for a source you already trust."""
    store.init_db()
    from clips import service
    res = service.run_ingest(args.url)
    sid = res["source_id"]
    got = service.run_moments(sid, limit=args.limit, model=(args.model or None))
    if not got["candidate_ids"]:
        print("no moments found — nothing to cut")
        return
    for cid in got["candidate_ids"]:
        try:
            service.run_cut(cid, edit=(args.edit or None))
            service.run_render(cid, mood=(args.mood or None))
        except (ValueError, FileNotFoundError, RuntimeError, TimeoutError) as e:
            print(f"  ✗ #{cid}: {e}")
    cmd_queue(argparse.Namespace(source_id=sid, status="", json=False))


def cmd_sources(args):
    store.init_db()
    from clips import service
    rows = service.list_sources()
    if not rows:
        print("(no sources — add one with `ingest --url ...`)")
        return
    for r in rows:
        print(f"#{r['id']} [{r['status']}] {r['title']}  "
              f"({r['uploader']}, {_fmt_hms(r['duration_s'])}, "
              f"{r['candidates']} candidate(s), transcript={r['transcript_source']})")


def cmd_queue(args):
    store.init_db()
    from clips import service
    rows = service.list_candidates(source_id=args.source_id or None,
                                   status=args.status)
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("(no candidates — run `moments --source-id N`)")
        return
    for c in rows:
        print(f"#{c['id']} [{c['status']}] src={c['source_id']} "
              f"{_fmt_hms(c['start_s'])}-{_fmt_hms(c['end_s'])} ({c['seconds']}s) "
              f"score={c['score']:.2f}  {c['title']}")


def cmd_show(args):
    store.init_db()
    from clips import service
    rows = [c for c in service.list_candidates() if c["id"] == args.candidate_id]
    if not rows:
        print(f"no clip candidate #{args.candidate_id}")
        return
    c = rows[0]
    print(f"#{c['id']} [{c['status']}] source #{c['source_id']}")
    print(f"  window : {_fmt_hms(c['start_s'])}-{_fmt_hms(c['end_s'])} ({c['seconds']}s)")
    print(f"  title  : {c['title']}")
    print(f"  hook   : {c['hook']}")
    print(f"  score  : {c['score']:.2f}")
    print(f"  edit   : {c.get('edit', 'linear')}"
          + (f" (payoff at {_fmt_hms(c['payoff_s'])})" if c.get('payoff_s') else ""))
    print(f"  why    : {c['reason']}")
    print(f"  quote  : {c['quote']}")
    if c["render_path"]:
        print(f"  render : {c['render_path']}")


def cmd_approve(args):
    store.init_db()
    from clips import service
    service.set_status(args.candidate_id, "approved")


def cmd_reject(args):
    store.init_db()
    from clips import service
    service.set_status(args.candidate_id, "rejected")


def main():
    p = argparse.ArgumentParser(prog="clips", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    ip = sub.add_parser("ingest", help="download a long video once + build its transcript")
    ip.add_argument("--url", required=True)
    ip.set_defaults(func=cmd_ingest)

    mp = sub.add_parser("moments", help="find candidate windows in an ingested source")
    mp.add_argument("--source-id", type=int, required=True)
    mp.add_argument("--limit", type=int, default=0, help="keep only the top N by score")
    mp.add_argument("--model", default="", help="override the OpenRouter model")
    mp.add_argument("--from-file", default="",
                    help="load moments JSON instead of calling the LLM "
                         "(pairs with --prompt for a $0 Claude Code pass)")
    mp.add_argument("--prompt", action="store_true",
                    help="print the task for a Claude Code session and exit")
    mp.set_defaults(func=cmd_moments)

    cp = sub.add_parser("cut", help="cut + caption candidates (local, free)")
    cp.add_argument("--candidate-id", type=int, default=0)
    cp.add_argument("--source-id", type=int, default=0)
    cp.add_argument("--all", action="store_true", help="every uncut candidate of --source-id")
    cp.add_argument("--edit", default="", choices=["", "linear", "loop"],
                    help="loop (DEFAULT) = open on the payoff, then the run-up, "
                         "ending where the payoff began (seamless repeat); "
                         "linear = play the window straight through")
    cp.set_defaults(func=cmd_cut)

    rp = sub.add_parser("render", help="render cut candidates to 9:16 MP4")
    rp.add_argument("--candidate-id", type=int, default=0)
    rp.add_argument("--source-id", type=int, default=0)
    rp.add_argument("--all", action="store_true", help="every cut candidate of --source-id")
    rp.add_argument("--mood", default="", help="brand.py mood preset (e.g. dark, teach)")
    rp.add_argument("--no-wait", action="store_true", help="submit without polling")
    rp.add_argument("--service-url", default="", help="override RENDER_SERVICE_URL")
    rp.set_defaults(func=cmd_render)

    ap = sub.add_parser("run", help="ingest -> moments -> cut -> render in one go")
    ap.add_argument("--url", required=True)
    ap.add_argument("--limit", type=int, default=0, help="keep only the top N by score")
    ap.add_argument("--model", default="", help="override the OpenRouter model")
    ap.add_argument("--mood", default="", help="brand.py mood preset")
    ap.add_argument("--edit", default="", choices=["", "linear", "loop"],
                    help="loop (DEFAULT) = payoff-first cold open that repeats "
                         "seamlessly; linear = straight through")
    ap.set_defaults(func=cmd_run)

    sub.add_parser("sources", help="list ingested long-form sources").set_defaults(
        func=cmd_sources)

    qp = sub.add_parser("queue", help="list candidates")
    qp.add_argument("--source-id", type=int, default=0)
    qp.add_argument("--status", default="",
                    help="candidate|cut|rendered|approved|rejected")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(func=cmd_queue)

    sp = sub.add_parser("show", help="full detail for one candidate")
    sp.add_argument("--candidate-id", type=int, required=True)
    sp.set_defaults(func=cmd_show)

    pp = sub.add_parser("approve", help="approve a rendered candidate")
    pp.add_argument("--candidate-id", type=int, required=True)
    pp.set_defaults(func=cmd_approve)

    xp = sub.add_parser("reject", help="reject a candidate")
    xp.add_argument("--candidate-id", type=int, required=True)
    xp.set_defaults(func=cmd_reject)

    args = p.parse_args()
    args.func(args)
