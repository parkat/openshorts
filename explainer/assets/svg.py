"""SVG-graphics stage: give text beats (slide/motion_text) an animated vector
instead of a plain backdrop.

Two sources, matched to each shot by its visual_note keywords:
  1. A user-supplied SVG dropped in assets/svg/ (EXPLAINER_SVG_DIR) whose filename
     is the concept, e.g. `neural-network.svg`, `warning.svg`, `server.svg`. The
     matched file is copied into the project output dir and the composition animates
     it generically.
  2. Else a BUILT-IN animated graphic (network | warning | bars) picked by keyword.
  3. Else nothing — the shot falls back to the animated brand backdrop.

Add SVGs to assets/svg/ any time; naming them for the concept is all that's needed.
"""
import os
import re
import glob
import shutil

SVG_DIR = os.environ.get("EXPLAINER_SVG_DIR", os.path.join("assets", "svg"))
_TEXT_SHOTS = {"slide", "motion_text"}

# Built-in animated graphics -> the keywords that select them.
BUILTIN_KEYWORDS = {
    "network": ["network", "neural", "ai", "model", "node", "connect", "brain", "learn", "intelligence"],
    "warning": ["warning", "danger", "risk", "threat", "alarm", "alert", "fear", "scary", "wipe", "extinction", "control"],
    "bars": ["chart", "graph", "growth", "increase", "percent", "stat", "rise", "data", "number", "odds", "scale"],
}
_STOP = set("a an the of to in on and or for with is are it its this that then than "
            "he she they we you his her their our about into over".split())


def _keywords(text):
    return [w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP]


def library(svg_dir=None):
    """{concept_keyword: filepath} for the user SVG folder (filename = concept)."""
    d = svg_dir or SVG_DIR
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*.svg"))):
        for kw in _keywords(os.path.splitext(os.path.basename(f))[0].replace("-", " ").replace("_", " ")):
            out.setdefault(kw, f)
    return out


def match(shot, files=None):
    """Choose an SVG for a shot: ('file', path) from the user folder, ('kind', key)
    from the built-ins, or None. User files win over built-ins."""
    words = set(_keywords(shot.get("visual_note") or shot.get("narration") or ""))
    files = library() if files is None else files
    for kw in words:
        if kw in files:
            return ("file", files[kw])
    for kind, kws in BUILTIN_KEYWORDS.items():
        if words.intersection(kws):
            return ("kind", kind)
    return None


def gather_svgs(shots, out_dir, shot_assets):
    """Assign an SVG to each slide/motion_text shot without other media. Copies a
    matched user file into out_dir. Merges {shot_index: {svgUrl|svgKind}} in."""
    merged = {int(k): dict(v) for k, v in (shot_assets or {}).items()}
    files = library()
    job_id = os.path.basename(out_dir)
    n = 0
    for i, shot in enumerate(shots):
        if shot.get("visual") not in _TEXT_SHOTS:
            continue
        e = merged.get(i, {})
        if any(e.get(k) for k in ("videos", "videoUrl", "images", "svgUrl", "svgKind")):
            continue
        m = match(shot, files)
        if not m:
            continue
        kind, val = m
        if kind == "file":
            dst = os.path.join(out_dir, f"svg_{i}.svg")
            shutil.copyfile(val, dst)
            merged.setdefault(i, {})["svgUrl"] = f"/output/{job_id}/svg_{i}.svg"
        else:
            merged.setdefault(i, {})["svgKind"] = val
        n += 1
    return merged, n
