"""Clip-finder stage: choose the RIGHT accent-clip moment from a reference video's
own transcript, instead of hand-entered timestamps.

For each reference YouTube URL we pull the timed auto-captions (yt-dlp VTT, no full
download), reconstruct a clean running transcript (auto-subs roll/repeat, so we
de-duplicate by suffix/prefix overlap), and hand it — with timestamps — to the LLM,
which picks the best 6–15s window to illustrate each `accent_clip` shot. Output is
an inspectable plan ({shot_index, url, in, out, quote, why}) so the choice can be
reviewed before anything is fetched/rendered (review-gate philosophy).

The plan feeds `assets/clips.py` (fetch that exact window → guardrails → provenance).
"""
import os
import re
import glob
import json
import subprocess

import openrouter_client as orc

_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")
_TAG = re.compile(r"<[^>]+>")            # inline <00:00:01><c> word timings / tags
_CUE_SETTING = re.compile(r"\s+(align|position|line|size):\S+")


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def video_meta(url):
    """(id, duration_s, uploader, title) for a URL via yt-dlp --print."""
    r = subprocess.run(
        ["yt-dlp", "--skip-download", "--no-playlist", "--print",
         "%(id)s\t%(duration)s\t%(uploader)s\t%(title)s", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    line = (r.stdout.decode(errors="replace").strip().splitlines() or [""])[0]
    parts = line.split("\t")
    if len(parts) < 4:
        return None
    vid, dur, uploader, title = parts[0], parts[1], parts[2], parts[3]
    try:
        dur = float(dur)
    except ValueError:
        dur = 0.0
    return vid, dur, uploader, title


def fetch_vtt(url, workdir, vid=None):
    """Download English auto-captions and return THIS video's VTT path (or None).

    Matched by video id so a multi-reference run never grabs another video's file;
    prefers the plain `en` track over `en-orig` (either parses fine)."""
    os.makedirs(workdir, exist_ok=True)
    tmpl = os.path.join(workdir, "ref_%(id)s")
    subprocess.run(
        ["yt-dlp", "--skip-download", "--no-playlist",
         "--write-auto-subs", "--write-subs", "--sub-langs", "en.*,en",
         "--sub-format", "vtt", "-o", tmpl, url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pat = f"ref_{vid}" if vid else "ref_"
    cands = sorted(glob.glob(os.path.join(workdir, f"{pat}*.vtt")))
    if not cands:
        return None
    # Prefer "<id>.en.vtt" over "<id>.en-orig.vtt".
    plain = [c for c in cands if c.endswith(".en.vtt")]
    return (plain or cands)[0]


def _clean(text):
    text = _TAG.sub("", text)
    text = _CUE_SETTING.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_vtt(path):
    """VTT (incl. rolling auto-subs) -> clean [{start, end, text}] segments (~one
    sentence-ish per ~10s), timestamps in seconds."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    cues = []  # (start, text)
    block = raw.split("\n")
    i = 0
    while i < len(block):
        m = _TS.search(block[i])
        if m and "-->" in block[i]:
            start = _sec(*m.groups())
            i += 1
            lines = []
            while i < len(block) and block[i].strip() and "-->" not in block[i]:
                lines.append(block[i])
                i += 1
            txt = _clean(" ".join(lines))
            if txt:
                cues.append((start, txt))
        else:
            i += 1

    # Reconstruct a running transcript, dropping the rolling overlap between cues.
    words = []  # (start, word)
    for start, txt in cues:
        toks = txt.split()
        max_o = min(len(words), len(toks))
        overlap = 0
        for o in range(max_o, 0, -1):
            if [w for _, w in words[-o:]] == toks[:o]:
                overlap = o
                break
        for w in toks[overlap:]:
            words.append((start, w))

    # Bucket into ~10s / ~24-word segments for a compact, timestamped transcript.
    segments, cur, seg_start = [], [], None
    for start, w in words:
        if seg_start is None:
            seg_start = start
        cur.append(w)
        if (start - seg_start) >= 10 or len(cur) >= 24:
            segments.append({"start": round(seg_start, 1), "end": round(start, 1),
                             "text": " ".join(cur)})
            cur, seg_start = [], None
    if cur:
        segments.append({"start": round(seg_start or 0, 1),
                         "end": round(words[-1][0], 1) if words else seg_start,
                         "text": " ".join(cur)})
    return segments


def load_reference(url, workdir):
    """{index-less} reference dict: {url, channel, duration, title, segments}."""
    meta = video_meta(url)
    vid = meta[0] if meta else None
    channel = meta[2] if meta else ""
    title = meta[3] if meta else ""
    duration = meta[1] if meta else 0.0
    vtt = fetch_vtt(url, workdir, vid)
    segments = parse_vtt(vtt) if vtt else []
    return {"url": url, "channel": channel, "title": title,
            "duration": duration, "segments": segments}


SYSTEM = """You are a video editor choosing accent clips for a faceless explainer Short.
You are given (a) the shots that need an ACCENT CLIP (each with the narration line it
must reinforce) and (b) transcripts of reference videos, each line prefixed with its
start time in seconds like "[123] ...".

For EACH need, pick the single best window from ANY reference that a viewer would find
most compelling and on-point — a self-contained soundbite that lands the shot's idea in
the SPEAKER'S OWN VOICE. Constraints:
- window length 6-11 seconds — the SINGLE punchiest self-contained sentence in his own
  voice (short-form retention: tight and quotable, not a paragraph). Snap `in`/`out` to
  the transcript timestamps; start and end on clean sentence boundaries.
- prefer the speaker making the actual claim over throat-clearing/setup.
- one need may reuse the same reference as another, but not the exact same window.
- if nothing in the references fits a need, omit it (do NOT force a bad pick).

Return ONLY valid JSON (no markdown):
{"selections":[
  {"shot_index":<int>,"source_index":<int>,"in":<sec>,"out":<sec>,
   "quote":"<the words spoken in that window>","why":"<one sentence: why this clip>"}
]}"""


def _needs(script):
    """Shots that need a reference-speaker window: every accent_clip (we show them
    talk) AND every speaks:true `aid` (we hear them over the explanatory animation)."""
    out = []
    for i, shot in enumerate(script.get("shots") or []):
        wants_clip = shot.get("visual") == "accent_clip" or (
            shot.get("visual") == "aid" and shot.get("speaks"))
        if wants_clip:
            out.append({"shot_index": i, "role": shot.get("role"),
                        "narration": shot.get("narration"),
                        "visual_note": shot.get("visual_note")})
    return out


def _render_refs(references):
    blocks = []
    for i, r in enumerate(references):
        lines = "\n".join(f"[{int(s['start'])}] {s['text']}" for s in r["segments"])
        blocks.append(f"REFERENCE {i} — {r['channel']} ({int(r['duration'])}s) {r['url']}\n{lines}")
    return "\n\n".join(blocks)


def _needs_text(needs):
    return "\n".join(
        f"NEED shot_index={n['shot_index']} ({n['role']}): says \"{n['narration']}\" "
        f"— wants to show: {n['visual_note']}" for n in needs)


def select_windows(needs, references, model=None, key=None):
    """LLM-pick the best window per need; returns validated selections."""
    if not needs or not any(r["segments"] for r in references):
        return []
    user = (f"SHOTS THAT NEED AN ACCENT CLIP:\n{_needs_text(needs)}\n\n"
            f"REFERENCE TRANSCRIPTS:\n{_render_refs(references)}\n\n"
            "Choose the windows now. JSON only.")
    # The reasoning "polish" model gives the best picks but its extended thinking
    # can eat a small token budget and return null content on multi-need prompts —
    # so give it plenty of room, and fall back to the fast draft model if it still
    # comes back empty.
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    out = ""
    for m in ([model] if model else [orc.MODELS["polish"], orc.MODELS["draft"]]):
        out = (orc.chat(msgs, model=m, temperature=0.2, max_tokens=8000, key=key) or "").strip()
        if out:
            break
    if not out:
        raise ValueError("clip selection returned empty (model truncated) — retry")
    if out.startswith("```"):
        out = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", out).strip()
    m = re.search(r"\{.*\}", out, re.S)
    data = json.loads(m.group(0)) if m else {"selections": []}

    sels = []
    for sel in data.get("selections", []):
        try:
            si = int(sel["source_index"])
            i_s = float(sel["in"])
            o_s = float(sel["out"])
        except (KeyError, ValueError, TypeError):
            continue
        if not (0 <= si < len(references)) or o_s <= i_s:
            continue
        o_s = min(o_s, i_s + 11.0)          # clamp: short punchy soundbites (retention)
        sels.append({"shot_index": int(sel["shot_index"]), "source_index": si,
                     "url": references[si]["url"], "channel": references[si]["channel"],
                     "in": round(i_s, 2), "out": round(o_s, 2),
                     "quote": (sel.get("quote") or "").strip(),
                     "why": (sel.get("why") or "").strip()})
    return sels


def plan(script, sources, workdir, model=None, key=None):
    """Full clip-finder: load reference transcripts for the topic's YouTube sources,
    select windows for the accent-clip shots. Returns {references, selections}."""
    urls = [s.get("url") for s in (sources or []) if s.get("type") == "youtube" and s.get("url")]
    references = [load_reference(u, workdir) for u in urls]
    needs = _needs(script)
    selections = select_windows(needs, references, model=model, key=key)
    return {"references": [{k: r[k] for k in ("url", "channel", "title", "duration")}
                           | {"segments": len(r["segments"])} for r in references],
            "needs": len(needs), "selections": selections}
