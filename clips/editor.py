"""Make a clips candidate legible to the original project's clip editor.

The subtitle burner, the hook/text overlay and the AI-effects endpoints in
`app.py` all work, and rebuilding them for this lane would be three
reimplementations of solved problems. What they need is not a new API but a
familiar one: they read `output/<job_id>/*_metadata.json` for a `shorts` list and
a word-level `transcript`, and operate on files in that same directory.

A clips candidate already renders into `output/clips-<id>/` and already carries
word-level captions, so the entire adapter is one JSON file describing the render
as a one-clip job. No editor code changes, and the chain-of-edits behaviour comes
for free — those endpoints write the new filename back into `shorts[0].video_url`
after every pass, so the shim tracks the current file on its own.

Times in the shim are clip-relative with the clip spanning 0..duration. The
editor subtracts `shorts[0].start` from every word, so a zero start means the
captions it derives line up with the render rather than with the source video the
window was taken from.
"""
import os
import json
import glob
import subprocess

import store
from clips.render import job_id_for, cand_dir


def base_name(candidate_id):
    """Filename stem the editor derives its default clip names from."""
    return f"clip{candidate_id}"


def metadata_path(candidate_id):
    return os.path.join(cand_dir(candidate_id),
                        f"{base_name(candidate_id)}_metadata.json")


def _words(captions):
    """[{text,startMs,endMs}] -> the editor's [{word,start,end}] in seconds."""
    out = []
    for c in captions or []:
        try:
            start = float(c.get("startMs", 0)) / 1000.0
            end = float(c.get("endMs", 0)) / 1000.0
        except (TypeError, ValueError):
            continue
        text = (c.get("text") or "").strip()
        if not text or end <= start:
            continue
        out.append({"word": text, "start": round(start, 3), "end": round(end, 3)})
    return out


def current_file(candidate_id):
    """Basename the editor should treat as the current video for this candidate.

    Prefers what the shim last recorded (the newest link in the edit chain) and
    falls back to the row's render_path, so opening the editor after a re-render
    picks up the new file rather than an orphaned edit of the old one.
    """
    path = metadata_path(candidate_id)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            url = ((data.get("shorts") or [{}])[0]).get("video_url") or ""
            name = os.path.basename(url)
            if name and os.path.isfile(os.path.join(cand_dir(candidate_id), name)):
                return name
        except (ValueError, OSError):
            pass
    with store.session() as s:
        cand = s.get(store.ClipCandidate, candidate_id)
        return os.path.basename(cand.render_path) if cand and cand.render_path else ""


def write_shim(candidate_id, filename=None):
    """Write/refresh the metadata file the editor endpoints read.

    Returns {job_id, clip_index, filename, video_url, words, duration_s}.
    Raises ValueError when the candidate has no render to edit.
    """
    from clips.cut import duration_s

    with store.session() as s:
        cand = s.get(store.ClipCandidate, candidate_id)
        if not cand:
            raise ValueError(f"candidate #{candidate_id} not found")
        render_path = cand.render_path or ""
        captions = list(cand.captions or [])
        title = cand.title or ""
        hook = cand.hook or ""

    job_id = job_id_for(candidate_id)
    name = os.path.basename(filename or "") or current_file(candidate_id) \
        or os.path.basename(render_path)
    if not name:
        raise ValueError(f"candidate #{candidate_id} has no render yet — render it first")
    path = os.path.join(cand_dir(candidate_id), name)
    if not os.path.isfile(path):
        raise ValueError(f"render file missing: {job_id}/{name}")

    words = _words(captions)
    duration = duration_s(path) or (words[-1]["end"] if words else 0.0)
    data = {
        "shorts": [{
            "start": 0.0,
            "end": round(float(duration), 3),
            "title": title,
            "hook": hook,
            "video_url": f"/videos/{job_id}/{name}",
        }],
        # The editor walks segments->words; one segment holding every word is the
        # shape it expects and the clip is short enough that grouping adds nothing.
        "transcript": {"segments": [{"start": 0.0, "end": round(float(duration), 3),
                                     "words": words}]},
        "source": {"lane": "clips", "candidate_id": candidate_id},
    }
    with open(metadata_path(candidate_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return {"job_id": job_id, "clip_index": 0, "filename": name,
            "video_url": f"/videos/{job_id}/{name}", "words": len(words),
            "duration_s": round(float(duration), 3)}


def adopt(candidate_id, filename):
    """Point the candidate's render_path at an edited file and refresh the shim.

    Called after the editor produces a new video so the card, the download and
    anything queued to Buffer all follow the edit instead of silently publishing
    the pre-edit render.
    """
    name = os.path.basename(filename or "")
    path = os.path.join(cand_dir(candidate_id), name)
    if not name or not os.path.isfile(path):
        raise ValueError(f"no such file for candidate #{candidate_id}: {name!r}")
    with store.session() as s:
        cand = s.get(store.ClipCandidate, candidate_id)
        if not cand:
            raise ValueError(f"candidate #{candidate_id} not found")
        cand.render_path = path
        # An edit lands on a rendered clip; keep an approval if one was already
        # given, but a scheduled clip must not silently swap its file underneath
        # a queued post — that is what the queue's cancel is for.
        if cand.status in ("cut", "rendered"):
            cand.status = "rendered"
        s.commit()
    write_shim(candidate_id, filename=name)
    return {"candidate_id": candidate_id, "filename": name,
            "video_url": f"/videos/{job_id_for(candidate_id)}/{name}"}


def thumbnail(candidate_id, at_s=1.0, width=320):
    """A JPEG still of the current render, built once and cached beside it.

    The review list showed one <video> per candidate. Twenty of those on a page
    is twenty media elements, each with a decoder, a connection and GPU buffers,
    all to display a poster frame nobody had pressed play on. An <img> costs
    almost nothing, so the list uses this and only mounts a real player when you
    click one.

    Rebuilt when the render is newer than the thumb, so an edit is reflected
    rather than showing the pre-edit frame forever. Returns a path, or None when
    there is nothing to grab a frame from.
    """
    name = current_file(candidate_id)
    if not name:
        return None
    d = cand_dir(candidate_id)
    video = os.path.join(d, name)
    if not os.path.isfile(video):
        return None
    thumb = os.path.join(d, "thumb.jpg")
    if os.path.isfile(thumb) and os.path.getmtime(thumb) >= os.path.getmtime(video):
        return thumb
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, float(at_s)):.2f}",
         "-i", video, "-frames:v", "1", "-vf", f"scale={int(width)}:-2",
         "-q:v", "6", thumb],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0 or not os.path.isfile(thumb):
        # A clip shorter than `at_s` has no frame there — fall back to the first.
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", video, "-frames:v", "1",
             "-vf", f"scale={int(width)}:-2", "-q:v", "6", thumb],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return thumb if os.path.isfile(thumb) else None


# Pipeline working files, not versions of the Short. `clip.mp4` is the raw 16:9
# cut the renderer consumes — offering it as something to revert to would hand
# you a horizontal video with no captions and call it an earlier edit.
INTERMEDIATES = {"clip.mp4"}


def history(candidate_id):
    """Every version of the Short in the candidate's output dir, newest first.

    Editing is additive (`subtitled_`, `hooked_`, `edited_` prefixes stack), so
    the directory listing IS the undo history; surfacing it lets you step back to
    any earlier version without re-rendering.
    """
    d = cand_dir(candidate_id)
    files = [p for p in sorted(glob.glob(os.path.join(d, "*.mp4")),
                               key=os.path.getmtime, reverse=True)
             if os.path.basename(p) not in INTERMEDIATES]
    cur = current_file(candidate_id)
    return [{"filename": os.path.basename(p),
             "video_url": f"/videos/{job_id_for(candidate_id)}/{os.path.basename(p)}",
             "bytes": os.path.getsize(p),
             "current": os.path.basename(p) == cur} for p in files]
