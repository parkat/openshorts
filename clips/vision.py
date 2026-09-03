"""Meaning layer: judge what the signal layer found.

`clips/motion.py` says *when* the video changes; it cannot tell a crash from a
camera knock. This module shows those windows to a vision model and asks the only
question that matters — would a stranger stop scrolling for this — returning the
same moment shape the transcript path produces, so everything downstream is
unchanged.

Only the peak windows are shown, never the whole video. That is the point of the
split: the signal layer has already thrown away the 95% of a source where nothing
happens, so the model spends its attention (and the budget) on the candidates.
Uniform sampling of a long video reliably misses the exact frames that matter,
which is the failure this pipeline is built to avoid.

Frames go in as JPEG data URLs alongside whatever was being said at the time. The
words are supplied as CONTEXT, not as the subject: a narrator saying "and then it
happened" is worthless on its own but tells the model what it is looking at.
"""
import os
import re
import json
import base64
import shutil
import subprocess
import tempfile

import openrouter_client as orc

# Frames sampled per window. Four is enough to read a before/during/after arc
# without turning one scan into a hundred images.
FRAMES_PER_WINDOW = 4

# Long edge of each frame. Big enough to read a car's motion and a road sign,
# small enough that a dozen windows stay cheap.
FRAME_W = 512

MAX_TOKENS = 8000

SYSTEM = """You are a short-form editor reviewing security/dashcam/action footage for
clips that will GO VIRAL.

You are shown several candidate WINDOWS from one video. Each comes with a few frames
in time order and whatever was being said during it. The frames were chosen because
something physically happened there — a spike in motion or sound — but that could be
anything: a real incident, a camera knock, a hard edit, a loud noise over nothing.
Your job is to tell which windows contain something worth watching.

WHAT TRAVELS in this kind of footage:
- a genuine incident with a visible outcome — a crash, a near miss, a vehicle losing
  control, someone doing something reckless and it going wrong;
- an escalation you can SEE building, then resolving;
- a shocking scale cue — extreme speed, the size of an impact, how close it came;
- authority or consequence made visible — the arrest, the aftermath, the moment of
  realisation.

WHAT DOES NOT:
- talking heads, interviews, someone explaining what happened (that is not action);
- maps, title cards, graphics, text-on-screen, channel branding;
- ordinary driving, ordinary traffic, a camera bump, a scene transition;
- an "incident" you cannot actually make out in the frames. If you cannot see it,
  the viewer cannot either.

For each window that is worth cutting, return:
- "window": its index as given.
- "in"/"out": seconds. Start where the action reads and end after its outcome — you
  may tighten the given window, and may extend it by a few seconds if the outcome
  clearly needs longer. Stay inside the video.
- "payoff": the second the DECISIVE thing happens — the impact, the loss of control,
  the reveal. This becomes the first frame of the Short, so it must be the moment
  itself, not the run-up to it.
- "title": a scroll-stopping publish title under 80 chars, leading with the shocking
  part. Describe what HAPPENS, not what the video is about.
- "hook": the on-screen opening line, under 60 chars.
- "why": one sentence naming what makes it travel.
- "score": 0-1, honest estimate it is watched to the end AND shared. Be harsh — most
  candidate windows are not viral, they are just motion. An empty list is a valid
  and useful answer.

Return ONLY valid JSON (no markdown):
{"moments":[{"window":<int>,"in":<sec>,"out":<sec>,"payoff":<sec>,"title":"...","hook":"...","why":"...","score":<0-1>}]}"""


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON object in model output: {text[:200]}")
    return json.loads(m.group(0))


def frame_at(video_path, t, out_path, width=FRAME_W):
    """Single JPEG at `t` seconds, scaled to `width`."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, float(t)):.2f}",
         "-i", video_path, "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "5", out_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out_path if r.returncode == 0 and os.path.isfile(out_path) else None


def window_frames(video_path, in_s, out_s, out_dir, n=FRAMES_PER_WINDOW, tag=""):
    """`n` JPEGs spread across a window, in time order. Returns [(t, path)]."""
    span = max(0.1, float(out_s) - float(in_s))
    shots = []
    for i in range(n):
        t = float(in_s) + span * (i + 0.5) / n
        p = frame_at(video_path, t, os.path.join(out_dir, f"w{tag}_{i}.jpg"))
        if p:
            shots.append((t, p))
    return shots


def _data_url(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def _spoken_during(segments, in_s, out_s):
    """Whatever the transcript has for a window — context, not subject."""
    txt = " ".join(s.get("text", "") for s in (segments or [])
                   if s.get("end", s.get("start", 0)) >= in_s and s.get("start", 0) <= out_s)
    return txt.strip()[:600]


def judge(video_path, windows, segments=None, title="", model=None, key=None,
          log=print):
    """Show the candidate windows to the model; return the ones worth cutting.

    One request for all windows, deliberately: the model ranks them against each
    other, which is what "be harsh, most of these are just motion" requires. Per
    window it would only ever see one candidate and grade on a curve of one.
    """
    if not windows:
        return []

    tmp = tempfile.mkdtemp(prefix="clipframes-")
    try:
        content = [{"type": "text", "text":
                    f"Video: {title or '(untitled)'}\n"
                    f"{len(windows)} candidate windows follow, each with frames in "
                    f"time order.\n"}]
        shown = 0
        for i, w in enumerate(windows):
            shots = window_frames(video_path, w["in"], w["out"], tmp, tag=str(i))
            if not shots:
                continue
            said = _spoken_during(segments, w["in"], w["out"])
            head = (f"\n--- WINDOW {i}: {w['in']:.1f}s to {w['out']:.1f}s "
                    f"(spike at {w.get('peak', w['in']):.1f}s, z={w.get('z', 0)})")
            if said:
                head += f"\nSaid during it: \"{said}\""
            head += f"\nFrames at: {', '.join(f'{t:.1f}s' for t, _ in shots)}"
            content.append({"type": "text", "text": head})
            for _t, p in shots:
                content.append({"type": "image_url",
                                "image_url": {"url": _data_url(p)}})
            shown += 1

        if not shown:
            log("  could not extract frames from any window")
            return []
        content.append({"type": "text", "text":
                        "\nJudge the windows now. JSON only."})
        log(f"  showing {shown} window(s) x {FRAMES_PER_WINDOW} frames to the model")

        out = orc.chat([{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": content}],
                       model=model or orc.MODELS["polish"], temperature=0.3,
                       max_tokens=MAX_TOKENS, key=key)
        found = _extract_json(out).get("moments") or []
        log(f"  model kept {len(found)} of {shown} window(s)")
        return found
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
