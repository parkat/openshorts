"""Moments stage: a long video's transcript -> the windows worth cutting.

Selection is tuned for VIRAL potential, not coverage and not education. The
tempting failure mode is picking the best-explained segment — a model asked for
"good moments" reliably returns lecture-shaped clips, because those read as
high-quality prose. Those do not travel. The prompt therefore names the triggers
that do travel (conflict, a shocking number, an admission, a strong flat opinion)
and explicitly rejects the ones that do not (definitions, context-setting,
balanced takes), and demands the window OPEN on the punch rather than the setup.

This is the one judgement call in the lane, so its output is an inspectable plan
(every candidate carries the quote it is built on and why it was picked) and
nothing is cut until a human has looked.

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

MIN_SECONDS = 12.0
MAX_SECONDS = 60.0

SYSTEM = """You are a short-form editor hunting a long video for clips that will GO VIRAL.

You get a timestamped transcript, each line prefixed with its start time in seconds
like "[123] ...". You are not summarising this video and you are not teaching anyone
anything. You are looking for the handful of moments that would stop a stranger's
thumb mid-scroll and get sent to a friend.

WHAT GOES VIRAL — hunt for these:
- a claim someone would argue with, or that sounds wrong until it lands;
- a number, stat or comparison that is genuinely shocking;
- a confession, admission, or something the speaker probably should not have said;
- conflict — disagreement, a challenge, someone getting called out, real tension;
- a story with a turn: setup, then a reveal you did not see coming;
- a strong opinion stated flatly, with no hedging;
- something funny, absurd, or so blunt it is quotable;
- stakes that touch the viewer: money, health, their job, their kids, their future.

WHAT DIES — do not return these, however well said:
- definitions, explanations of how something works, "let me walk you through";
- background, context-setting, credentials, throat-clearing, thanking anyone;
- balanced both-sides answers, hedged takes, "it depends";
- anything whose appeal is that it is INFORMATIVE. Useful is not viral;
- anything that needs the rest of the video to make sense.

OPEN ON THE PUNCH. Set `in` so the very first sentence is the most arresting line in
the window — never on the setup that leads to it. If the payoff needs one sentence of
setup, keep that sentence and cut everything before it. A viewer decides in about one
second; a clip that opens on "so, what is a neural network" is already dead.
END ON THE LANDING. Set `out` right after the payoff, not on whatever came next.

MARK THE PAYOFF. Also return `payoff`: the exact second the punchline STARTS — the
reveal, the number, the admission, the line the whole window exists to deliver.
Everything before it is the run-up. This lets the editor rotate the clip so it opens
on the punchline and loops back into it, so be precise: `payoff` must fall on a
sentence boundary strictly between `in` and `out`, with at least 3 seconds of run-up
before it and at least 3 seconds of punchline after it. If the window has no such
single moment — the whole thing is one continuous build — return `payoff: 0`.

Hard constraints:
- each window is 12-60 seconds; the best are 20-40;
- `in` and `out` are seconds from the transcript timestamps, on sentence boundaries;
- windows must not overlap each other;
- return only what would ACTUALLY travel. Two great clips beat ten decent ones. If
  the video genuinely has nothing viral in it, return {"moments":[]} rather than
  padding the list with the least boring educational segments.

For each moment return:
- "title": a scroll-stopping publish title, under 80 chars. Lead with the surprising
  part. Do not describe the topic ("How neural networks learn"); state the hook
  ("He built the thing he now says could kill us"). No ALL CAPS, no "you won't believe".
- "hook": the line to burn on screen at the open, under 60 chars — a curiosity gap or
  a bold claim, in the speaker's own framing where possible.
- "quote": the actual words spoken in the window (trimmed is fine).
- "why": one sentence naming the specific reason it travels — which trigger above it
  hits, not a summary of the content.
- "score": 0-1, your honest estimate it gets watched to the end AND shared. Be harsh.
  0.9 means you would bet on it. Most segments of most videos are below 0.5.
- "payoff": the second the punchline starts (see MARK THE PAYOFF), or 0 if there is
  no single such moment.

Return ONLY valid JSON (no markdown):
{"moments":[{"in":<sec>,"out":<sec>,"payoff":<sec>,"title":"...","hook":"...","quote":"...","why":"...","score":<0-1>}]}"""


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


# A loop edit needs real material on both sides of the split — a 1s run-up or a
# 1s punchline reads as a glitch, not a hook.
MIN_LOOP_PART = 3.0


def clean_payoff(m):
    """Zero out a payoff that can't produce a sane rotation. Mutates and returns m.

    A moment with an unusable payoff point is still a perfectly good linear clip,
    so this drops the payoff rather than the moment.
    """
    try:
        p = float(m.get("payoff") or 0)
        a, b = float(m["in"]), float(m["out"])
    except (TypeError, ValueError, KeyError):
        m["payoff"] = 0.0
        return m
    if not (a + MIN_LOOP_PART <= p <= b - MIN_LOOP_PART):
        p = 0.0
    m["payoff"] = p
    return m


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
        keep = [clean_payoff(m) for m in got if valid(m, duration_s)]
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
