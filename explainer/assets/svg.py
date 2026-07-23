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

# Canonical concept -> the many words (synonyms) that should select it. Shared by
# the built-in graphics AND user files (a user's warning.svg matches "danger",
# "threat", "extinction", ... not just the literal filename). Add synonyms freely;
# good labeling here is what makes the SVG library actually get used.
CONCEPTS = {
    "network": ["network", "neural", "node", "connect", "connection", "model", "learn",
                "learning", "intelligence", "deep", "layer", "algorithm", "system"],
    "warning": ["warning", "danger", "dangerous", "risk", "threat", "alarm", "alert",
                "fear", "scary", "wipe", "extinction", "extinct", "catastrophe", "doom",
                "apocalypse", "existential", "kill", "destroy", "harm", "unsafe"],
    "bars": ["chart", "graph", "growth", "grow", "increase", "percent", "percentage",
             "stat", "statistic", "rise", "rising", "data", "number", "odds", "trend",
             "metric", "measure", "double", "billion", "trillion"],
    "chip": ["chip", "cpu", "gpu", "processor", "silicon", "hardware", "circuit",
             "compute", "transistor", "semiconductor", "board", "microchip"],
    "robot": ["robot", "machine", "android", "automation", "automated", "bot",
              "humanoid", "mechanical", "cyborg"],
    "globe": ["globe", "world", "earth", "global", "planet", "worldwide", "humanity",
              "nations", "countries", "international", "society", "civilization"],
    "lock": ["lock", "security", "secure", "safety", "safe", "encryption", "encrypt",
             "protect", "protection", "privacy", "guard", "shield", "defense"],
    "clock": ["clock", "time", "timer", "urgent", "urgency", "soon", "deadline",
              "countdown", "fast", "speed", "quick", "hurry", "moment", "future", "now"],
    # Concepts WITHOUT a built-in graphic yet — still matchable if the user supplies
    # a file named for them (e.g. brain.svg, server.svg).
    "brain": ["brain", "mind", "cognition", "cognitive", "neuron", "consciousness",
              "thought", "think", "thinking", "human", "smart", "genius"],
    "server": ["server", "servers", "datacenter", "cloud", "rack", "infrastructure",
               "database", "storage", "farm"],
    "eye": ["eye", "surveillance", "watch", "watching", "monitor", "spy", "spying",
            "tracking", "track", "observe", "see", "vision", "camera"],
    "money": ["money", "cost", "dollar", "invest", "investment", "profit", "economy",
              "economic", "expensive", "fund", "funding", "wealth", "market", "cash"],
    "rocket": ["rocket", "launch", "accelerate", "acceleration", "breakthrough",
               "race", "advance", "advancement", "boom", "surge", "explode"],
    "human": ["human", "humans", "people", "person", "worker", "job", "jobs",
              "workforce", "society", "population", "everyone"],
    "scale": ["scale", "balance", "ethics", "ethical", "fair", "fairness", "justice",
              "weigh", "regulation", "regulate", "law", "policy", "govern", "government"],
}
# Concepts that have a built-in animated React graphic (must match SvgGraphics.tsx).
BUILTIN = {"network", "warning", "bars", "chip", "robot", "globe", "lock", "clock"}
_SYN2CONCEPT = {syn: c for c, syns in CONCEPTS.items() for syn in syns}
_STOP = set("a an the of to in on and or for with is are it its this that then than "
            "he she they we you his her their our about into over".split())


def _stem(w):
    """Light variants so plurals/gerunds hit singular synonyms (machines->machine)."""
    out = {w}
    if len(w) > 3 and w.endswith("s"):
        out.add(w[:-1])
    if len(w) > 6 and w.endswith("ing"):
        out.add(w[:-3])
    if len(w) > 5 and w.endswith("ed"):
        out.add(w[:-2])
    return out


def _keywords(text):
    out = set()
    for w in re.findall(r"[a-z]{3,}", (text or "").lower()):
        if w not in _STOP:
            out |= _stem(w)
    return list(out)


def _file_concept(path):
    """Canonical concept a user file covers: map its filename to a known concept if
    any filename word is a synonym, else the literal filename word."""
    words = _keywords(os.path.splitext(os.path.basename(path))[0].replace("-", " ").replace("_", " "))
    for w in words:
        if w in _SYN2CONCEPT:
            return _SYN2CONCEPT[w]
    return words[0] if words else None


def library(svg_dir=None):
    """{concept: filepath} for the user SVG folder, concepts canonicalized."""
    out = {}
    for f in sorted(glob.glob(os.path.join(svg_dir or SVG_DIR, "*.svg"))):
        c = _file_concept(f)
        if c:
            out.setdefault(c, f)
    return out


def _synonyms(concept):
    return CONCEPTS.get(concept, [concept])


def match(shot, files=None):
    """Best SVG for a shot: ('file', path) or ('kind', concept), or None. Scores
    each available concept by how many of its synonyms appear in the visual_note;
    user files beat built-ins on ties."""
    words = set(_keywords(shot.get("visual_note") or shot.get("narration") or ""))
    files = library() if files is None else files
    # available concept -> (is_file, source_tuple)
    avail = {c: (True, ("file", p)) for c, p in files.items()}
    for c in BUILTIN:
        avail.setdefault(c, (False, ("kind", c)))

    best, best_key = None, (0, 0)
    for concept, (is_file, source) in avail.items():
        score = len(words.intersection(_synonyms(concept)))
        if score == 0:
            continue
        key = (score, 1 if is_file else 0)   # prefer more hits, then user files
        if key > best_key:
            best, best_key = source, key
    return best


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
