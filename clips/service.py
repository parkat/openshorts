"""clips/service.py — store-glue shared by every driver of the clips lane.

Same contract as `explainer/service.py`: each stage takes `log: Callable[[str],
None] = print`, so the CLI prints live while an HTTP caller can capture the same
lines into a job log. Every stage is idempotent — re-running `cut` on a candidate
overwrites its files and rewrites its row, so a partial batch is always safe to
resume rather than restart.
"""
import os
import json

import store

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")


def source_dir(source_id):
    """Filesystem dir for a source's own artifacts (transcript, moments plan)."""
    d = os.path.join(OUTPUT_DIR, f"clips-source-{source_id}")
    os.makedirs(d, exist_ok=True)
    return d


def get_source(s, source_id):
    row = s.get(store.ClipSource, source_id)
    if not row:
        raise ValueError(f"no clip source #{source_id}")
    return row


def get_candidate(s, candidate_id):
    row = s.get(store.ClipCandidate, candidate_id)
    if not row:
        raise ValueError(f"no clip candidate #{candidate_id}")
    return row


# --- stages -----------------------------------------------------------------

def run_ingest(url, log=print):
    """URL -> one cached download + a timed transcript, recorded as a ClipSource.

    Re-ingesting the same URL updates the existing row instead of making a second
    one, so this is safe to re-run after a failure part-way through.
    """
    from clips import ingest
    from explainer import clipfinder as cf

    meta = cf.video_meta(url)
    if not meta:
        raise ValueError(f"could not read video metadata for {url} "
                         "(check the URL, and that yt-dlp can reach it)")
    vid, duration, uploader, title = meta
    log(f"{title}  ({uploader}, {duration / 60:.0f} min)")

    with store.session() as s:
        row = (s.query(store.ClipSource)
               .filter(store.ClipSource.video_id == vid).first())
        if not row:
            row = store.ClipSource(url=url, video_id=vid)
            s.add(row)
        row.title, row.uploader, row.duration_s = title, uploader, duration
        s.commit()
        source_id = row.id

    path = ingest.download(url, vid, log=log)
    segments, kind, vtt = ingest.transcript_segments(url, vid, path, log=log)
    if not segments:
        raise ValueError(f"no transcript could be built for {url} — "
                         "neither auto-captions nor whisper produced anything")

    with open(os.path.join(source_dir(source_id), "transcript.json"), "w",
              encoding="utf-8") as f:
        json.dump({"segments": segments, "source": kind}, f, indent=2)

    with store.session() as s:
        row = get_source(s, source_id)
        row.local_path, row.vtt_path = path, vtt or ""
        row.transcript_source, row.status = kind, "ingested"
        s.commit()
    log(f"ingested source #{source_id}")
    return {"source_id": source_id, "title": title, "duration_s": duration,
            "segments": len(segments), "transcript_source": kind}


def load_transcript(source_id):
    p = os.path.join(source_dir(source_id), "transcript.json")
    if not os.path.isfile(p):
        raise FileNotFoundError(
            f"no transcript for source #{source_id} — run `ingest` first")
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("segments") or []


def find_action(source_id, video_path, segments, title, model=None, log=print):
    """Motion + audio peaks -> vision-judged moments. Returns moment dicts.

    Never fatal: a source with no readable video, or a vision call that fails,
    costs the action half of the scan and leaves the speech half intact.
    """
    from clips import motion, vision, moments as mo

    try:
        log("scanning the picture for where something happens…")
        sig = motion.combined(video_path, log=log)
        wins = motion.windows(sig)
        if not wins:
            log("  nothing in the video spikes above its own baseline")
            return []
        log(f"  {len(wins)} candidate window(s) — judging them")
        found = vision.judge(video_path, wins, segments=segments, title=title,
                             model=model, log=log)
    except Exception as e:  # noqa: BLE001 — the speech pass must still land
        log(f"  action scan failed ({e}) — continuing with the transcript pass")
        return []

    out = []
    for m in found:
        m.pop("window", None)
        m["kind"] = "action"
        m.setdefault("quote", "")
        out.append(m)
    return out


def run_moments(source_id, limit=0, model=None, from_file="", mode="auto",
                log=print):
    """Find candidate windows. Replaces any candidates not yet cut.

    `mode` picks the detectors: "speech" reads the transcript, "action" reads the
    picture, "auto" (default) runs both and merges. Auto is the default because
    which one works is a property of the FOOTAGE, not something to ask about — a
    dashcam has no quotable sentences and a podcast has no motion, and neither
    knows which it is until something looks.

    Candidates already cut or rendered are left alone: re-scanning a source must
    not silently throw away work (or files) you have already reviewed.
    """
    from clips import moments as mo

    segments = load_transcript(source_id)
    with store.session() as s:
        src = get_source(s, source_id)
        duration, title, url = src.duration_s, src.title, src.url
        video_path = src.local_path

    if from_file:
        with open(from_file, encoding="utf-8") as f:
            loaded = json.load(f)
        loaded = loaded.get("moments") if isinstance(loaded, dict) else loaded
        found = mo.dedupe([m for m in loaded if mo.valid(m, duration)])
        if len(found) != len(loaded):
            log(f"  dropped {len(loaded) - len(found)} invalid/overlapping window(s)")
        log(f"  {len(found)} moment(s) loaded from {from_file}")
    else:
        found = []
        if mode in ("speech", "auto") and segments:
            spoken = mo.find(segments, duration_s=duration, limit=0,
                             model=model, log=log)
            for m in spoken:
                m["kind"] = "speech"
            found.extend(spoken)
        if mode in ("action", "auto") and video_path and os.path.isfile(video_path):
            acted = find_action(source_id, video_path, segments, title,
                                model=model, log=log)
            acted = [mo.clean_payoff(m) for m in acted
                     if mo.valid(m, duration, min_seconds=mo.MIN_ACTION_SECONDS)]
            found.extend(acted)
        elif mode in ("action", "auto"):
            log("  no local download — skipping the action pass")
        # Both detectors can land on the same event from different evidence; the
        # higher-scored reading wins.
        found = mo.dedupe(found)
        if limit:
            found = sorted(found, key=lambda m: -float(m.get("score") or 0))[:limit]
            found = sorted(found, key=lambda m: float(m["in"]))
        n_action = sum(1 for m in found if m.get("kind") == "action")
        log(f"  {len(found)} moment(s) kept ({len(found) - n_action} spoken, "
            f"{n_action} action)")

    with store.session() as s:
        stale = (s.query(store.ClipCandidate)
                 .filter(store.ClipCandidate.source_id == source_id,
                         store.ClipCandidate.status == "candidate").all())
        for row in stale:
            s.delete(row)
        s.flush()
        kept = (s.query(store.ClipCandidate)
                .filter(store.ClipCandidate.source_id == source_id).count())
        if kept:
            log(f"  keeping {kept} already-cut candidate(s)")
        ids = []
        for m in found:
            row = store.ClipCandidate(
                source_id=source_id, start_s=float(m["in"]), end_s=float(m["out"]),
                title=(m.get("title") or "")[:200], hook=(m.get("hook") or "")[:200],
                quote=m.get("quote") or "", reason=m.get("why") or "",
                score=float(m.get("score") or 0.0),
                kind=m.get("kind") or "speech",
                payoff_s=float(m.get("payoff") or 0.0))
            s.add(row)
            s.flush()
            ids.append(row.id)
        get_source(s, source_id).status = "scanned"
        s.commit()

    with open(os.path.join(source_dir(source_id), "moments.json"), "w",
              encoding="utf-8") as f:
        json.dump({"source_id": source_id, "title": title, "url": url,
                   "moments": found}, f, indent=2)
    log(f"{len(ids)} candidate(s) for source #{source_id}")
    return {"source_id": source_id, "candidate_ids": ids, "count": len(ids)}


def run_cut(candidate_id, edit=None, log=print):
    """Snap, cut, extract audio and caption one candidate.

    `edit` overrides the candidate's stored assembly ("linear" or "loop"); the
    stored value is used when it is None, so re-cutting keeps whatever you chose.
    """
    from clips import cut as ct
    from clips.cut import DEFAULT_EDIT
    from clips.render import cand_dir

    with store.session() as s:
        cand = get_candidate(s, candidate_id)
        src = get_source(s, cand.source_id)
        start, end = cand.start_s, cand.end_s
        payoff = cand.payoff_s or 0.0
        kind = cand.kind or "speech"
        edit = edit or cand.edit or DEFAULT_EDIT
        source_path, uploader = src.local_path, src.uploader
        title = cand.title
    if not source_path or not os.path.isfile(source_path):
        raise FileNotFoundError(
            f"source download missing ({source_path or 'unset'}) — re-run `ingest`")

    log(f"cutting #{candidate_id} [{kind}/{edit}]: {title or '(untitled)'}")
    man = ct.build(source_path, start, end, cand_dir(candidate_id),
                   payoff_s=payoff, edit=edit, kind=kind, log=log)

    with store.session() as s:
        cand = get_candidate(s, candidate_id)
        cand.start_s, cand.end_s = man["start_s"], man["end_s"]
        cand.payoff_s, cand.edit = man["payoff_s"], man["edit"]
        cand.clip_path, cand.audio_path = man["clip"], man["audio"]
        cand.captions = man["captions"]
        cand.status = "cut"
        s.commit()
    log(f"  cut {man['duration_s']:.1f}s -> {man['clip']}")
    return {"candidate_id": candidate_id, "duration_s": man["duration_s"],
            "words": len(man["captions"]), "edit": man["edit"],
            "uploader": uploader}


def run_render(candidate_id, mood=None, no_wait=False, service_url=None,
               with_captions=True, log=print):
    """Cut clip + captions -> a finished 9:16 MP4.

    `with_captions=False` leaves the words off, for when the clip editor's own
    subtitle pass will burn them instead (see clips/editor.py).
    """
    from clips import render as rnd
    from clips.cut import duration_s

    with store.session() as s:
        cand = get_candidate(s, candidate_id)
        if cand.status == "candidate":
            raise ValueError(f"candidate #{candidate_id} has not been cut yet — "
                             "run `cut` first")
        src = get_source(s, cand.source_id)
        captions = list(cand.captions or [])
        clip_path = cand.clip_path
        mood = mood or cand.mood or None
        attribution = f"via {src.uploader}" if src.uploader else ""

    duration_ms = int(round(duration_s(clip_path) * 1000))
    if duration_ms <= 0:
        raise ValueError(f"could not read a duration from {clip_path!r} — re-run `cut`")

    log(f"rendering #{candidate_id} ({duration_ms / 1000:.1f}s) "
        f"via {rnd.RENDER_SERVICE_URL} …")
    if not with_captions:
        log("  rendering without captions (the editor will burn its own)")
    job = rnd.render(candidate_id, duration_ms, captions, attribution=attribution,
                     mood=mood, service_url=(service_url or None), poll=not no_wait,
                     with_captions=with_captions)
    if no_wait:
        log(f"  submitted render {job['renderId']} (not waiting)")
        return job

    out = job.get("output_basename")
    with store.session() as s:
        cand = get_candidate(s, candidate_id)
        cand.render_path = os.path.join(rnd.cand_dir(candidate_id), out) if out else ""
        cand.status = "rendered"
        if mood:
            cand.mood = mood
        s.commit()
    log(f"  rendered -> {out}")
    return {"candidate_id": candidate_id, "output": out, "status": "rendered"}


def run_all(url, limit=0, model=None, mood=None, edit=None, mode="auto", log=print):
    """ingest -> moments -> cut -> render, for a source you already trust.

    One failing candidate does not abandon the rest — a bad window should cost
    that clip, not the batch.
    """
    res = run_ingest(url, log=log)
    source_id = res["source_id"]
    found = run_moments(source_id, limit=limit, model=model, mode=mode, log=log)
    done, failed = [], []
    for cid in found["candidate_ids"]:
        try:
            run_cut(cid, edit=edit, log=log)
            run_render(cid, mood=mood, log=log)
            done.append(cid)
        except Exception as e:  # noqa: BLE001 — one bad window must not kill the batch
            log(f"  ✗ #{cid}: {e}")
            failed.append(cid)
    log(f"done: {len(done)} rendered, {len(failed)} failed")
    return {"source_id": source_id, "rendered": done, "failed": failed}


# --- review -----------------------------------------------------------------

def set_status(candidate_id, status, log=print):
    """Approve or reject a rendered candidate (gate 2)."""
    if status not in ("approved", "rejected"):
        raise ValueError(f"status must be approved|rejected, not {status!r}")
    with store.session() as s:
        get_candidate(s, candidate_id).status = status
        s.commit()
    log(f"candidate #{candidate_id} -> {status}")
    return {"candidate_id": candidate_id, "status": status}


EDITABLE_FIELDS = ("title", "hook", "caption", "mood", "captions")


def update_candidate(candidate_id, log=print, **fields):
    """Edit a candidate's text — title, hook, caption, mood, or its captions.

    Only the fields actually passed are written, so a form that sends one input
    cannot blank the rest. Nothing here re-encodes anything: `captions` is the
    word list the next render or subtitle burn will use, which is how a fix typed
    into the editor survives into the file rather than living in the preview.
    """
    changed = {k: v for k, v in fields.items()
               if k in EDITABLE_FIELDS and v is not None}
    if not changed:
        return candidate_detail(candidate_id)
    with store.session() as s:
        cand = get_candidate(s, candidate_id)
        for k, v in changed.items():
            setattr(cand, k, v)
        s.commit()
    log(f"candidate #{candidate_id}: updated {', '.join(sorted(changed))}")
    return candidate_detail(candidate_id)


def candidate_detail(candidate_id):
    """Everything the studio view needs for one candidate, or None."""
    with store.session() as s:
        c = s.get(store.ClipCandidate, candidate_id)
        if not c:
            return None
        src = s.get(store.ClipSource, c.source_id)
        return {
            "id": c.id, "source_id": c.source_id, "status": c.status,
            "start_s": c.start_s, "end_s": c.end_s,
            "seconds": round(c.end_s - c.start_s, 1),
            "title": c.title, "hook": c.hook, "quote": c.quote,
            "caption": c.caption or "",
            "reason": c.reason, "score": c.score, "mood": c.mood,
            "payoff_s": c.payoff_s or 0.0, "edit": c.edit or "linear",
            "kind": c.kind or "speech",
            "clip_path": c.clip_path, "render_path": c.render_path,
            "caption_words": len(c.captions or []),
            "source": {"id": src.id, "title": src.title, "uploader": src.uploader,
                       "url": src.url} if src else None,
        }


def delete_source(source_id, log=print):
    """Drop a source and every candidate under it (rows only).

    Rendered files under output/ are left alone deliberately — this is a queue
    cleanup, not a file purge, and an already-published render must not vanish
    because someone tidied the list.
    """
    with store.session() as s:
        src = get_source(s, source_id)
        rows = (s.query(store.ClipCandidate)
                .filter(store.ClipCandidate.source_id == source_id).all())
        n = len(rows)
        for r in rows:
            s.delete(r)
        s.delete(src)
        s.commit()
    log(f"deleted source #{source_id} and {n} candidate(s)")
    return {"source_id": source_id, "deleted_candidates": n}


def delete_candidate(candidate_id, log=print):
    """Drop one candidate row (its files stay on disk)."""
    with store.session() as s:
        s.delete(get_candidate(s, candidate_id))
        s.commit()
    log(f"deleted candidate #{candidate_id}")
    return {"candidate_id": candidate_id}


def list_sources():
    with store.session() as s:
        rows = (s.query(store.ClipSource)
                .order_by(store.ClipSource.created_at.desc()).all())
        out = []
        for r in rows:
            n = (s.query(store.ClipCandidate)
                 .filter(store.ClipCandidate.source_id == r.id).count())
            out.append({"id": r.id, "title": r.title, "uploader": r.uploader,
                        "duration_s": r.duration_s, "status": r.status,
                        "transcript_source": r.transcript_source, "candidates": n})
        return out


def list_candidates(source_id=None, status=""):
    with store.session() as s:
        q = s.query(store.ClipCandidate)
        if source_id:
            q = q.filter(store.ClipCandidate.source_id == source_id)
        if status:
            q = q.filter(store.ClipCandidate.status == status)
        rows = q.order_by(store.ClipCandidate.source_id,
                          store.ClipCandidate.start_s).all()
        return [{"id": r.id, "source_id": r.source_id, "status": r.status,
                 "start_s": r.start_s, "end_s": r.end_s,
                 "seconds": round(r.end_s - r.start_s, 1),
                 "title": r.title, "hook": r.hook, "score": r.score,
                 "reason": r.reason, "quote": r.quote,
                 "payoff_s": r.payoff_s or 0.0, "edit": r.edit or "linear",
                 "kind": r.kind or "speech", "caption": r.caption or "",
                 "render_path": r.render_path} for r in rows]
