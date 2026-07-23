"""Persistent content cache for the explainer lane.

Keeps everything reusable across videos — transcripts, generated videos/images,
full YouTube downloads, trimmed accent clips, and SVGs — content-addressed on disk
and indexed in SQLite (`cache_items`), each row LABELED (concept tags/keywords) and
ENRICHED (model, prompt/url, size, duration, cost, channel, in/out) so a later video
can classify and reuse content instead of regenerating it.

Two dedupe axes:
  - `sha256`  : identical BYTES (never store the same file twice).
  - `ref_key` : identical MEANING (a generated clip by model+prompt+size+duration; a
                transcript by video id). `reuse(ref_key)` returns a hit WITHOUT
                spending — this is what stops us re-paying OpenRouter for a clip we
                already made.

Files live under EXPLAINER_CACHE (default `cache/`) in per-kind subdirs, named by
hash. `put()` copies the bytes in and upserts the row; `materialize()` copies a hit
back out to a project dir. A future dashboard reads `stats()` for a size readout and
`find()` for a file explorer (see HANDOFF / memory note — UI is not built here).
"""
import os
import json
import shutil
import hashlib
import datetime

import store

CACHE_DIR = os.environ.get("EXPLAINER_CACHE") or "cache"
KINDS = ("video", "image", "transcript", "youtube", "clip", "svg", "audio")

_MIME = {"video": "video/mp4", "image": "image/png", "transcript": "application/json",
         "youtube": "video/mp4", "clip": "video/mp4", "svg": "image/svg+xml",
         "audio": "audio/wav"}
_EXT = {"video": "mp4", "image": "png", "transcript": "json", "youtube": "mp4",
        "clip": "mp4", "svg": "svg", "audio": "wav"}


def _now():
    return datetime.datetime.utcnow()


def _kind_dir(kind):
    d = os.path.join(CACHE_DIR, kind)
    os.makedirs(d, exist_ok=True)
    return d


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def ref_for_video(model, prompt, size, duration):
    """Semantic key for a generated video — same prompt+model+size+duration reuses."""
    h = hashlib.sha1(f"{model}|{size}|{duration}|{prompt}".encode("utf-8")).hexdigest()[:16]
    return f"video:{h}"


def ref_for_transcript(video_id):
    return f"transcript:{video_id}"


def ref_for_youtube(video_id):
    return f"youtube:{video_id}"


def ref_for_clip(url, start_s, end_s):
    return f"clip:{url}#{float(start_s):.2f}-{float(end_s):.2f}"


def _get_row(session, ref_key=None, sha256=None):
    q = session.query(store.CacheItem)
    if ref_key:
        row = q.filter(store.CacheItem.ref_key == ref_key).first()
        if row:
            return row
    if sha256:
        return q.filter(store.CacheItem.sha256 == sha256).first()
    return None


def put(kind, src_path, ref_key=None, source="", model="", size="", duration_s=0.0,
        labels=None, meta=None, session=None):
    """Ingest a file into the cache (idempotent). If `ref_key` (or identical bytes)
    already exists, bump use_count and return the existing row. Returns the CacheItem.
    Copies the file to the cache; the caller keeps its own copy."""
    if kind not in KINDS:
        raise ValueError(f"unknown cache kind {kind!r}")
    own = session is None
    session = session or store.session()
    try:
        with open(src_path, "rb") as f:
            data = f.read()
        digest = _sha256(data)
        row = _get_row(session, ref_key=ref_key, sha256=digest)
        if row:
            row.use_count = (row.use_count or 1) + 1
            row.last_used_at = _now()
            if labels:  # merge any new labels
                row.labels = sorted(set((row.labels or []) + list(labels)))
            session.commit()
            return row
        ext = _EXT.get(kind, "bin")
        rel = os.path.join(kind, f"{digest[:20]}.{ext}")
        dst = os.path.join(CACHE_DIR, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.isfile(dst):
            shutil.copyfile(src_path, dst)
        row = store.CacheItem(
            kind=kind, sha256=digest, ref_key=ref_key or f"sha:{digest[:16]}",
            path=rel, bytes=len(data), mime=_MIME.get(kind, ""), source=source or "",
            model=model or "", size=size or "", duration_s=float(duration_s or 0.0),
            labels=sorted(set(labels or [])), meta=meta or {})
        session.add(row)
        session.commit()
        return row
    finally:
        if own:
            session.close()


def reuse(ref_key, session=None):
    """Return the cached row for a semantic key WITHOUT spending, or None. Callers
    (generate_video, transcript, clip fetch) check this before doing paid work."""
    own = session is None
    session = session or store.session()
    try:
        row = _get_row(session, ref_key=ref_key)
        if row:
            row.use_count = (row.use_count or 1) + 1
            row.last_used_at = _now()
            session.commit()
        return row
    finally:
        if own:
            session.close()


def materialize(row, dst_path):
    """Copy a cached hit back out to a project location. Returns dst_path or None."""
    if not row:
        return None
    src = os.path.join(CACHE_DIR, row.path)
    if not os.path.isfile(src):
        return None
    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    shutil.copyfile(src, dst_path)
    return dst_path


def find(kind=None, label=None, text=None, limit=200, session=None):
    """Classify/browse: filter by kind, a label tag, and/or a substring in
    source/labels. Returns rows newest-first (backs a future file explorer)."""
    own = session is None
    session = session or store.session()
    try:
        q = session.query(store.CacheItem)
        if kind:
            q = q.filter(store.CacheItem.kind == kind)
        rows = q.order_by(store.CacheItem.created_at.desc()).all()
        out = []
        for r in rows:
            if label and label.lower() not in [str(x).lower() for x in (r.labels or [])]:
                continue
            if text:
                hay = (r.source or "") + " " + " ".join(str(x) for x in (r.labels or []))
                if text.lower() not in hay.lower():
                    continue
            out.append(r)
            if len(out) >= limit:
                break
        return out
    finally:
        if own:
            session.close()


def stats(session=None):
    """Counts + bytes per kind and totals — for a dashboard cache-size readout."""
    own = session is None
    session = session or store.session()
    try:
        by_kind, total_bytes, total = {}, 0, 0
        for r in session.query(store.CacheItem).all():
            k = by_kind.setdefault(r.kind, {"count": 0, "bytes": 0, "reuses": 0})
            k["count"] += 1
            k["bytes"] += int(r.bytes or 0)
            k["reuses"] += max(0, (r.use_count or 1) - 1)
            total_bytes += int(r.bytes or 0)
            total += 1
        return {"by_kind": by_kind, "total_bytes": total_bytes, "total_items": total}
    finally:
        if own:
            session.close()


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0


# --- backfill: ingest content that already exists on disk (one-time seeding) ---
import re as _re
import glob as _glob

_STOP = set("a an the of to in on and or for with is are it its this that from your you "
            "we they he she his her their our about into over more most some what why how".split())


def _keywords(text):
    return [w for w in _re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _STOP][:12]


def _project_notes(proj_dir):
    """{shot_index: [keywords]} from a project's align.json visual_notes (for labels)."""
    notes = {}
    p = os.path.join(proj_dir, "align.json")
    if os.path.isfile(p):
        try:
            data = json.load(open(p, encoding="utf-8"))
            for sh in data.get("shots", []):
                notes[sh.get("index")] = _keywords(sh.get("visual_note") or "")
        except (ValueError, OSError):
            pass
    return notes


def backfill(output_root="output", svg_root=os.path.join("assets", "svg"), session=None):
    """One-time seed: ingest existing SVGs, generated aid clips, accent clips, and
    reference transcripts across all projects into the cache (idempotent — dedupes by
    bytes). Labels come from the SVG concept / the project's per-shot visual_note."""
    own = session is None
    session = session or store.session()
    made = 0
    try:
        for f in sorted(_glob.glob(os.path.join(svg_root, "*.svg"))):
            concept = os.path.splitext(os.path.basename(f))[0]
            put("svg", f, ref_key=f"svg:{concept}", source=f, labels=[concept], session=session)
            made += 1
        for proj in sorted(_glob.glob(os.path.join(output_root, "explainer-*"))):
            pid = os.path.basename(proj)
            notes = _project_notes(proj)
            for f in sorted(_glob.glob(os.path.join(proj, "aid_*.mp4"))):
                m = _re.match(r"aid_(\d+)_", os.path.basename(f))
                idx = int(m.group(1)) if m else None
                put("video", f, source=os.path.basename(f),
                    labels=(notes.get(idx) or []) + ["aid"], size="720x1280",
                    meta={"project": pid, "shot": idx}, session=session)
                made += 1
            for f in sorted(_glob.glob(os.path.join(proj, "clip*.mp4"))):
                put("clip", f, source=os.path.basename(f), labels=["accent"],
                    meta={"project": pid}, session=session)
                made += 1
            for f in sorted(_glob.glob(os.path.join(proj, "ref_*.vtt"))):
                m = _re.match(r"ref_([A-Za-z0-9_-]+?)\.", os.path.basename(f))
                vid = m.group(1) if m else os.path.basename(f)
                put("transcript", f, ref_key=ref_for_transcript(vid), source=vid,
                    labels=["transcript", vid], session=session)
                made += 1
        return made
    finally:
        if own:
            session.close()
