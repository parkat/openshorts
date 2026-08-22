"""Cut stage: a candidate window -> the clip, its audio, and word-level captions.

Cuts locally from the ingested download, so this costs nothing and takes about a
second per clip regardless of how many candidates a source produced.

Every boundary is aligned to SENTENCES, not just to words. Windows come from a
transcript, and transcript timings — auto-captions especially — routinely land
mid-word, but landing mid-*sentence* is the worse failure: a Short that opens on
"unleashed AI-powered bots..." is a fragment, and a hard cut from one half-finished
sentence to another reads as a mistake rather than an edit. The aligned values are
what get written back to the candidate: the row must describe what was actually
cut, not what was asked for.

The clip keeps its full 16:9 frame. It is never cropped to 9:16 — the render lays
it over a blurred, zoomed copy of itself, so nobody gets cut out of frame (a
face-centred reframe was tried and abandoned: on a panel it centres on whoever is
largest, not whoever is talking).

`edit="loop"` assembles the window as a **rotation** about the payoff point: the
punchline plays first, then the run-up that led to it, ending on the exact frame
the punchline began. Because the two halves are contiguous in the source, the wrap
from the end back to the start is continuous speech — seamless by construction.
That leaves exactly one hard cut in the clip, where the punchline hands over to
the run-up (source `end` -> source `start`), which is why both outer edges have to
be whole sentences too: it is the one seam a viewer can actually hear.
"""
import os
import re
import json
import tempfile
import subprocess

# The house cut. A payoff-first rotation retains better than a linear clip, and
# every moment carries a payoff point, so this is the path unless something about
# the window makes it impossible — in which case the cut falls back to linear and
# says so rather than producing an awkward open.
DEFAULT_EDIT = "loop"

# Both halves of a rotation need real material; a 3s stub reads as a glitch.
MIN_PART = 3.0

# How far a boundary may travel to reach a sentence. Sentence boundaries are far
# sparser than word boundaries, so this is much larger than a word-level snap.
MAX_SHIFT = 8.0

# A word ending a sentence, allowing for a trailing quote/bracket.
_SENTENCE_END = re.compile(r"[.!?…][\"'\)\]]*$")


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def snap(source_path, start_s, end_s, log=print):
    """Word-level fallback: move a window to clean speech boundaries."""
    from explainer.assets.snap import snap_window
    return snap_window(source_path, float(start_s), float(end_s), log=log)


def _listen(source_path, region_start, region_dur):
    """[(abs_start, abs_end, text)] for a region, via the shared whisper config."""
    from explainer.assets import snap as sn
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "region.wav")
        if not sn._extract_wav(source_path, region_start, region_dur, wav):
            return []
        words = sn._words(wav)
    return [(region_start + ws, region_start + we, txt) for ws, we, txt in words]


def _sentence_edges(words):
    """(starts, ends) — absolute times where sentences begin and end.

    A word begins a sentence when the PREVIOUS word closed one; the region's own
    first word is excluded, since it is mid-sentence by construction.
    """
    starts = [words[i][0] for i in range(1, len(words))
              if _SENTENCE_END.search(words[i - 1][2])]
    ends = [w[1] for w in words if _SENTENCE_END.search(w[2])]
    return starts, ends


def _pick(candidates, want, prefer_earlier, max_shift):
    """Nearest candidate to `want`, trying the preferred side first.

    `prefer_earlier` picks the last candidate at-or-before `want` (used for a clip
    START and the loop split, where going back keeps the sentence's own opening);
    otherwise the first at-or-after (used for a clip END, where going forward
    completes the sentence instead of truncating it).
    """
    tol = 0.25
    before = [c for c in candidates if c <= want + tol]
    after = [c for c in candidates if c >= want - tol]
    first, second = (before[::-1], after) if prefer_earlier else (after, before[::-1])
    for group in (first, second):
        if group and abs(group[0] - want) <= max_shift:
            return group[0]
    return None


def plan_window(source_path, start_s, end_s, payoff_s=0.0, want_loop=False,
                max_shift=MAX_SHIFT, log=print):
    """Align a window (and optionally its loop split) to sentence boundaries.

    One whisper pass over the padded window serves all three boundaries — the
    edges and the split are all just queries against the same word list, and
    re-listening per boundary would triple the slowest part of the cut.

    Returns (start, end, payoff|None). Falls back to word-level snapping if the
    audio cannot be read, and returns payoff=None whenever the split cannot be put
    on a sentence.
    """
    start_s, end_s = float(start_s), float(end_s)
    if os.environ.get("EXPLAINER_SNAP", "1") == "0":
        return start_s, end_s, (float(payoff_s) if want_loop and payoff_s else None)

    pad = max_shift + 3.0
    region_start = max(0.0, start_s - pad)
    words = _listen(source_path, region_start, (end_s + pad) - region_start)
    if len(words) < 2:
        log("  could not re-listen to the window — falling back to word snapping")
        s, e = snap(source_path, start_s, end_s, log=log)
        return s, e, None

    starts, ends = _sentence_edges(words)
    if not starts or not ends:
        log("  no sentence punctuation in this window — falling back to word snapping")
        s, e = snap(source_path, start_s, end_s, log=log)
        return s, e, None

    new_start = _pick(starts, start_s, True, max_shift)
    new_end = _pick(ends, end_s, False, max_shift)
    if new_start is None or new_end is None or new_end - new_start < MIN_PART * 2:
        log("  no usable sentence edges — falling back to word snapping")
        s, e = snap(source_path, start_s, end_s, log=log)
        return s, e, None

    if abs(new_start - start_s) > 0.01 or abs(new_end - end_s) > 0.01:
        log(f"  sentences: {start_s:.2f}-{end_s:.2f} -> {new_start:.2f}-{new_end:.2f}")

    payoff = None
    if want_loop and payoff_s:
        inner = [x for x in starts if new_start + MIN_PART <= x <= new_end - MIN_PART]
        payoff = _pick(inner, float(payoff_s), True, max_shift) if inner else None
        if payoff is None:
            log(f"  no sentence start near the payoff ({float(payoff_s):.2f}) with "
                f"{MIN_PART:.0f}s on both sides — cutting linear")
        elif abs(payoff - float(payoff_s)) > 0.01:
            log(f"  payoff {float(payoff_s):.2f} was mid-sentence -> {payoff:.2f}")

    return new_start, new_end, payoff


def cut_window(source_path, start_s, end_s, out_path):
    """ffmpeg-cut [start_s, end_s] out of the local source as H.264/AAC."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    dur = max(0.1, float(end_s) - float(start_s))
    r = _run(["ffmpeg", "-y", "-ss", f"{float(start_s):.2f}", "-i", source_path,
              "-t", f"{dur:.2f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
              "-c:a", "aac", "-movflags", "+faststart", out_path])
    if r.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"ffmpeg cut failed: {r.stderr.decode(errors='replace')[-300:]}")
    return out_path


def rotate(clip_path, split_s, out_path):
    """Reorder a clip to [split..end] + [start..split].

    Done with trim/concat filters on the already-cut window rather than two cuts
    of the original: the window is seconds long, so this is fast and frame-exact,
    where seeking a 25-minute source twice is neither.
    """
    fc = (
        f"[0:v]trim=start={split_s:.3f},setpts=PTS-STARTPTS[v0];"
        f"[0:a]atrim=start={split_s:.3f},asetpts=PTS-STARTPTS[a0];"
        f"[0:v]trim=start=0:end={split_s:.3f},setpts=PTS-STARTPTS[v1];"
        f"[0:a]atrim=start=0:end={split_s:.3f},asetpts=PTS-STARTPTS[a1];"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    r = _run(["ffmpeg", "-y", "-i", clip_path, "-filter_complex", fc,
              "-map", "[v]", "-map", "[a]",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
              "-c:a", "aac", "-movflags", "+faststart", out_path])
    if r.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"ffmpeg rotate failed: {r.stderr.decode(errors='replace')[-300:]}")
    return out_path


def extract_audio(clip_path, out_path):
    """Pull the clip's audio out as the render's master track.

    The Remotion accent-clip scene renders its video muted (the explainer lane
    plays narration over it), so the speaker is only audible if their audio is
    handed in separately. Same cut, same file — so it stays in sync by construction.
    """
    r = _run(["ffmpeg", "-y", "-i", clip_path, "-vn",
              "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", out_path])
    if r.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"ffmpeg audio extract failed: {r.stderr.decode(errors='replace')[-300:]}")
    return out_path


def duration_s(path):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(r.stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


def captions(audio_path, log=print):
    """Word-level captions for the cut, by ASR on the clip's own audio.

    Deliberately not the source's auto-captions: those drop words and drift, and on
    a multi-speaker source they are bad enough to be unusable. Whisper on a short,
    already-trimmed clip is both accurate and quick.
    """
    import subtitles
    result = subtitles.transcribe_audio(audio_path)
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            text = (w.get("word") or "").strip()
            if not text:
                continue
            words.append({"text": text,
                          "startMs": int(round(float(w["start"]) * 1000)),
                          "endMs": int(round(float(w["end"]) * 1000))})
    log(f"  captions: {len(words)} words")
    return words


def build(source_path, start_s, end_s, out_dir, payoff_s=0.0, edit=DEFAULT_EDIT,
          log=print):
    """Plan -> cut -> (rotate) -> extract audio -> caption. Returns the manifest.

    Captions are always transcribed from the FINAL assembled audio, so a rotated
    clip's captions follow the rotated order automatically — there is no separate
    timeline to keep in step.
    """
    os.makedirs(out_dir, exist_ok=True)
    want_loop = edit == "loop"
    s, e, payoff = plan_window(source_path, start_s, end_s, payoff_s=payoff_s,
                               want_loop=want_loop, log=log)

    clip_path = os.path.join(out_dir, "clip.mp4")
    looped = False
    if want_loop and payoff is not None:
        linear = cut_window(source_path, s, e, os.path.join(out_dir, "linear.mp4"))
        split = payoff - s
        rotate(linear, split, clip_path)
        os.remove(linear)
        looped = True
        log(f"  loop: opens on the payoff at {payoff:.2f} "
            f"({e - payoff:.1f}s punchline + {split:.1f}s run-up)")
    else:
        cut_window(source_path, s, e, clip_path)

    audio = extract_audio(clip_path, os.path.join(out_dir, "audio.wav"))
    dur = duration_s(clip_path) or (e - s)
    words = captions(audio, log=log)

    manifest = {"start_s": s, "end_s": e, "duration_s": dur,
                "payoff_s": payoff if looped else 0.0,
                "edit": "loop" if looped else "linear",
                "clip": clip_path, "audio": audio, "captions": words}
    with open(os.path.join(out_dir, "cut.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
