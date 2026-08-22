"""Moments stage: a long video's transcript -> the windows worth cutting.

The model reads the whole timestamped transcript and returns self-contained
moments — the bits that land without the surrounding hour of context. This is the
one judgement call in the lane, so its output is an inspectable plan (every
candidate carries the quote it is built on and why it was picked) and nothing is
cut until a human has looked.

Long sources are chunked with overlap: a three-hour podcast does not fit one
sensible request, and a moment that straddles a chunk edge would otherwise be
lost. Overlapping windows are merged back by `dedupe`.
"""
import re
import json

import openrouter_client as orc

MAX_TOKENS = 16000

# One request covers roughly this much transcript. Well inside context; the real
# limit is output quality — a model asked to rank 40k words picks blandly.
CHUNK_CHARS = 40000
CHUNK_OVERLAP_S = 120.0

MIN_SECONDS = 15.0
MAX_SECONDS = 75.0

SYSTEM = """You are a short-form video editor mining a long video for standalone Shorts.

You get a timestamped transcript, each line prefixed with its start time in seconds
like "[123] ...". Find the moments that would hold a stranger's attention with NO
context from the rest of the video.

What makes a moment worth cutting:
- it states one complete, surprising or useful idea, and finishes it;
- it would make a viewer who knows nothing about this video stop scrolling;
- it stands alone — no "as I mentioned", no answering a question we never heard;
- the speaker says something specific. Vague enthusiasm is not a moment.

Hard constraints:
- each window is 15-75 seconds; the best are 25-45;
- `in` and `out` are seconds from the transcript timestamps, on sentence boundaries;
- windows must not overlap each other;
- return the STRONGEST moments only. Returning 3 great ones beats 10 padded ones —
  if the video only has 2, return 2.

For each moment return:
- "title": the publish title, under 80 chars, concrete and specific. No clickbait
  punctuation, no "you won't believe".
- "hook": the single line to burn on screen at the open, under 60 chars.
- "quote": the actual words spoken in the window (trimmed is fine).
- "why": one sentence on why this lands as a Short.
- "score": 0-1, your honest confidence a stranger watches it to the end.

Return ONLY valid JSON (no markdown):
{"moments":[{"in":<sec>,"out":<sec>,"title":"...","hook":"...","quote":"...","why":"...","score":<0-1>}]}"""


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON object in model output: {text[:200]}")
    return json.loads(m.group(0))


def render_transcript(segments):
    """Segments -> the "[start] text" lines the prompt is specified against."""
    return "\n".join(f"[{int(s['start'])}] {s['text']}" for s in segments if s.get("text"))


def chunk(segments, chunk_chars=CHUNK_CHARS, overlap_s=CHUNK_OVERLAP_S):
    """Split segments into overlapping runs, each about `chunk_chars` of text.

    The overlap means a moment sitting on a boundary appears whole in one of the
    two chunks; `dedupe` then drops the duplicate.
    """
    if not segments:
        return []
    runs, cur, size = [], [], 0
    for seg in segments:
        cur.append(seg)
        size += len(seg.get("text") or "")
        if size >= chunk_chars:
            runs.append(cur)
            back = cur[-1]["start"] - overlap_s
            cur = [s for s in cur if s["start"] >= back]
            size = sum(len(s.get("text") or "") for s in cur)
    # `cur` is now the tail after the last flush (its leading overlap included), or
    # the whole transcript if we never flushed. Skip it when it is ONLY that
    # overlap — i.e. nothing new arrived after the last run ended.
    if cur and (not runs or cur[-1] is not runs[-1][-1]):
        runs.append(cur)
    return runs


def valid(m, duration_s):
    try:
        a, b = float(m.get("in")), float(m.get("out"))
    except (TypeError, ValueError):
        return False
    if not (0 <= a < b):
        return False
    if duration_s and b > duration_s + 1:
        return False
    return MIN_SECONDS <= (b - a) <= MAX_SECONDS


def dedupe(moments, min_gap_s=1.0):
    """Drop overlapping windows, keeping the higher-scored one.

    Chunk overlap produces near-duplicates of the same moment with slightly
    different edges, and the prompt forbids overlap within a chunk anyway — so any
    overlap that survives is a duplicate, not two moments.
    """
    out = []
    for m in sorted(moments, key=lambda x: (-float(x.get("score") or 0), float(x["in"]))):
        a, b = float(m["in"]), float(m["out"])
        if any(a < float(k["out"]) + min_gap_s and float(k["in"]) - min_gap_s < b for k in out):
            continue
        out.append(m)
    return sorted(out, key=lambda x: float(x["in"]))


def find(segments, duration_s=0.0, limit=0, model=None, key=None, log=print):
    """Transcript segments -> ranked, non-overlapping candidate moments."""
    runs = chunk(segments)
    log(f"  scanning {len(segments)} segments in {len(runs)} pass(es)")
    found = []
    for i, run in enumerate(runs, 1):
        user = (
            f"TRANSCRIPT (part {i} of {len(runs)}, times are absolute seconds into the video):\n"
            f"{render_transcript(run)}\n\n"
            "Find the standalone moments now. JSON only."
        )
        out = orc.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            model=model or orc.MODELS["polish"], temperature=0.4,
            max_tokens=MAX_TOKENS, key=key)
        got = _extract_json(out).get("moments") or []
        keep = [m for m in got if valid(m, duration_s)]
        if len(keep) != len(got):
            log(f"  pass {i}: dropped {len(got) - len(keep)} out-of-bounds window(s)")
        log(f"  pass {i}: {len(keep)} moment(s)")
        found.extend(keep)

    moments = dedupe(found)
    if limit:
        moments = sorted(moments, key=lambda m: -float(m.get("score") or 0))[:limit]
        moments = sorted(moments, key=lambda m: float(m["in"]))
    log(f"  {len(moments)} moment(s) after dedupe")
    return moments


def manual_prompt(segments):
    """The exact task a Claude Code session can run with its own Claude instead of
    spending on OpenRouter; write the resulting JSON back with `moments --from-file`."""
    return SYSTEM + "\n\nTRANSCRIPT:\n" + render_transcript(segments)
