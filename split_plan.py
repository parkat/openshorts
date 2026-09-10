"""Split-into-parts planning: boundaries, sequential naming, poster frames.

Split mode is the only clip mode whose cut list is fully determined before any
expensive work happens — it's arithmetic on the duration, not an LLM call. That
makes a *plan* possible: compute the parts in a second or two, show them with a
poster frame each, let the editor retitle / renumber / nudge boundaries, and only
then hand the approved list to the renderer. For a two-hour source that's the
difference between reviewing 40 parts up front and re-titling 40 finished files
one at a time.

`build_parts` is the single source of truth for the boundaries — main.py's
`build_split_clips` delegates here, so the preview and the render can't drift.
"""

import json
import os
import subprocess

# Metadata keys the rest of the stack reads off a clip. Keep these exact: the
# publish flow, the editor and the S3 gallery all index into them.
TITLE_KEY = "video_title_for_youtube_short"
HOOK_KEY = "viral_hook_text"
TIKTOK_KEY = "video_description_for_tiktok"
INSTAGRAM_KEY = "video_description_for_instagram"

DEFAULT_TITLE_TEMPLATE = "{name} — Part {n}/{total}"
DEFAULT_HOOK_TEMPLATE = "Part {n}"
DEFAULT_DESCRIPTION_TEMPLATE = ""


def probe_duration(path):
    """Duration in seconds via ffprobe, or 0.0.

    ffprobe rather than cv2's frame_count/fps: on a long recording the frame count
    in the container header is routinely wrong (or zero for VFR/streamed files),
    and at two hours a 1% error is a whole missing part.
    """
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stderr=subprocess.PIPE,
        )
        return float(out.decode().strip())
    except Exception:
        return 0.0


def build_parts(video_duration, part_length):
    """Consecutive [start, end) windows covering the whole video.

    A trailing stub shorter than 20% of a part is absorbed into the part before it,
    so a 2h05m source at 3-minute parts ends on one 8-minute-ish part rather than a
    5-second orphan.
    """
    try:
        video_duration = float(video_duration or 0)
    except (TypeError, ValueError):
        video_duration = 0.0
    if video_duration <= 0:
        return []

    if not part_length or part_length <= 0:
        part_length = int(video_duration)

    parts = []
    start = 0.0
    idx = 1
    min_tail = max(1.0, part_length * 0.2)
    while start < video_duration:
        end = min(start + part_length, video_duration)
        remainder = video_duration - end
        if 0 < remainder < min_tail:
            end = video_duration
        parts.append({
            "index": idx,
            "start": round(start, 3),
            "end": round(end, 3),
        })
        idx += 1
        if end >= video_duration:
            break
        start = end

    if not parts:
        parts = [{"index": 1, "start": 0.0, "end": round(video_duration, 3)}]
    return parts


def timecode(seconds):
    """H:MM:SS for a source offset (drops the hour when there isn't one)."""
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _fill(template, part, total, name):
    """Expand {n} {nn} {total} {name} {start} {end} {duration} in a template."""
    if not template:
        return ""
    n = part.get("index", 1)
    pad = len(str(total))
    length = max(0, (part.get("end") or 0) - (part.get("start") or 0))
    values = {
        "n": n,
        "nn": str(n).zfill(pad),
        "total": total,
        "name": name,
        "start": timecode(part.get("start")),
        "end": timecode(part.get("end")),
        "duration": timecode(length),
    }
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        # An unknown or malformed placeholder shouldn't sink the whole plan —
        # the editor sees the raw template and can fix it in the preview.
        return template


def apply_templates(parts, source_name, title_template=None, hook_template=None,
                    description_template=None):
    """Fill in sequential title / hook / description for every part.

    Only fills what the editor hasn't overridden: a part carrying `title_locked`
    (etc.) keeps its hand-typed text through a re-numbering.
    """
    total = len(parts)
    title_template = DEFAULT_TITLE_TEMPLATE if title_template is None else title_template
    hook_template = DEFAULT_HOOK_TEMPLATE if hook_template is None else hook_template
    description_template = (
        DEFAULT_DESCRIPTION_TEMPLATE if description_template is None else description_template
    )

    for part in parts:
        if not part.get("title_locked"):
            part["title"] = _fill(title_template, part, total, source_name)
        if not part.get("hook_locked"):
            part["hook"] = _fill(hook_template, part, total, source_name)
        if not part.get("description_locked"):
            part["description"] = _fill(description_template, part, total, source_name)
    return parts


def renumber(parts):
    """Re-index parts 1..N after a delete or a reorder."""
    for i, part in enumerate(parts, start=1):
        part["index"] = i
    return parts


def to_shorts(parts):
    """Plan parts -> the `shorts` metadata shape main.py and the API expect."""
    shorts = []
    for part in parts:
        description = part.get("description") or ""
        shorts.append({
            "start": round(float(part["start"]), 3),
            "end": round(float(part["end"]), 3),
            TITLE_KEY: part.get("title") or f"Part {part.get('index', 1)}",
            TIKTOK_KEY: description,
            INSTAGRAM_KEY: description,
            HOOK_KEY: part.get("hook") or "",
        })
    return shorts


def load_plan(path):
    """Read a plan.json written by the API. Returns (shorts, options)."""
    with open(path, "r", encoding="utf-8") as f:
        plan = json.load(f)
    parts = plan.get("parts") or []
    options = plan.get("options") or {}
    return to_shorts(parts), options


def thumbnail_path(out_dir, index):
    return os.path.join(out_dir, f"part_{index}.jpg")


def make_thumbnail(source_path, part, out_dir, height=360):
    """One poster frame for a part, grabbed a beat after its in-point.

    `-ss` before `-i` so ffmpeg seeks the container instead of decoding up to the
    timestamp — on a multi-GB file that's the difference between ~0.2s and minutes
    per frame.
    """
    os.makedirs(out_dir, exist_ok=True)
    start = float(part.get("start") or 0)
    end = float(part.get("end") or start)
    # A second in, so we don't land on a cut-to-black at the boundary.
    offset = start + min(1.0, max(0.0, (end - start) / 4))
    out_path = thumbnail_path(out_dir, part.get("index", 1))
    cmd = [
        "ffmpeg", "-y", "-ss", f"{offset:.3f}", "-i", source_path,
        "-frames:v", "1", "-vf", f"scale=-2:{height}", "-q:v", "4",
        out_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0 or not os.path.exists(out_path):
        return None
    return out_path


def make_thumbnails(source_path, parts, out_dir, progress=None):
    """Poster frames for every part. `progress(done, total)` between frames."""
    total = len(parts)
    made = []
    for i, part in enumerate(parts, start=1):
        made.append(make_thumbnail(source_path, part, out_dir))
        if progress:
            progress(i, total)
    return made
