"""Cut stage: a candidate window -> the clip, its audio, and word-level captions.

Cuts locally from the ingested download, so this costs nothing and takes about a
second per clip regardless of how many candidates a source produced.

Windows come from a transcript, and transcript timings — auto-captions especially —
routinely land mid-word. Every window is therefore re-listened to and snapped to
real speech boundaries first, and the SNAPPED values are what get written back to
the candidate: the row must describe what was actually cut, not what was asked for.

The clip keeps its full 16:9 frame. It is never cropped to 9:16 — the render lays
it over a blurred, zoomed copy of itself, so nobody gets cut out of frame (a
face-centred reframe was tried and abandoned: on a panel it centres on whoever is
largest, not whoever is talking).

`edit="loop"` assembles the window as a **rotation** about the payoff point: the
punchline plays first, then the run-up that led to it, ending on the exact frame
the punchline began. Because the two halves are contiguous in the source, the
wrap from the end back to the start is continuous speech — the loop is seamless
by construction rather than by careful trimming, and a viewer who lets it repeat
slides back into the punchline without a seam to notice.
"""
import os
import re
import json
import tempfile
import subprocess

# Both halves of a rotation need real material; a 3s stub reads as a glitch.
MIN_PART = 3.0


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def snap(source_path, start_s, end_s, log=print):
    """Move a window to clean speech boundaries. Returns (start, end) unchanged on
    any failure, and never shifts a boundary more than ~2s."""
    if os.environ.get("EXPLAINER_SNAP", "1") == "0":
        return float(start_s), float(end_s)
    from explainer.assets.snap import snap_window
    return snap_window(source_path, float(start_s), float(end_s), log=log)


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


# A word ending a sentence, allowing for a trailing quote/bracket.
_SENTENCE_END = re.compile(r"[.!?…][\"'\)\]]*$")


def snap_point(source_path, t, max_shift=8.0, log=print):
    """Move the loop split to the start of a SENTENCE, or refuse.

    A word boundary is not good enough here. The split becomes the first frame of
    the Short, so landing inside a sentence opens the video on a fragment
    ("unleashed AI-powered bots...") — grammatically broken and a weak hook.

    Preference is the start of the sentence CONTAINING `t`, not the nearest
    boundary in either direction: the model points at where the punchline lands,
    so the sentence it points into is the punchline, and opening at that
    sentence's start keeps its subject. Only if that is out of reach do we take
    the next sentence forward.

    Returns None when no sentence start is within `max_shift` — the caller then
    cuts linear, because an awkward open is worse than no loop.
    """
    try:
        from explainer.assets import snap as sn
        pad = max_shift + 3.0
        region_start = max(0.0, float(t) - pad)
        with tempfile.TemporaryDirectory() as td:
            wav = os.path.join(td, "region.wav")
            if not sn._extract_wav(source_path, region_start, pad * 2, wav):
                return None
            words = sn._words(wav)
        if len(words) < 2:
            return None

        # A word starts a sentence when the PREVIOUS word closed one. The region's
        # own first word is excluded — it is mid-sentence by construction.
        starts = [region_start + words[i][0] for i in range(1, len(words))
                  if _SENTENCE_END.search(words[i - 1][2])]
        if not starts:
            return None

        t = float(t)
        before = [x for x in starts if x <= t + 0.25]
        after = [x for x in starts if x > t + 0.25]
        pick = None
        if before and (t - before[-1]) <= max_shift:
            pick = before[-1]          # start of the sentence t falls inside
        elif after and (after[0] - t) <= max_shift:
            pick = after[0]            # else the next sentence along
        if pick is None:
            return None
        if pick != t:
            log(f"  payoff {t:.2f} was mid-sentence -> sentence start {pick:.2f}")
        return pick
    except Exception:  # noqa: BLE001 — snapping must never break the cut
        return None


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


def build(source_path, start_s, end_s, out_dir, payoff_s=0.0, edit="linear",
          log=print):
    """Snap -> cut -> (rotate) -> extract audio -> caption. Returns the manifest.

    Captions are always transcribed from the FINAL assembled audio, so a rotated
    clip's captions follow the rotated order automatically — there is no separate
    timeline to keep in step.
    """
    os.makedirs(out_dir, exist_ok=True)
    s, e = snap(source_path, start_s, end_s, log=log)
    if (s, e) != (float(start_s), float(end_s)):
        log(f"  snapped {float(start_s):.2f}-{float(end_s):.2f} -> {s:.2f}-{e:.2f}")

    clip_path = os.path.join(out_dir, "clip.mp4")
    payoff = float(payoff_s or 0.0)
    looped = False
    if edit == "loop" and s < payoff < e:
        snapped = snap_point(source_path, payoff, log=log)
        if snapped is None:
            log(f"  no sentence boundary near the payoff ({payoff:.2f}) — cutting linear "
                "rather than opening on a fragment")
            payoff = 0.0
        elif not (s + MIN_PART <= snapped <= e - MIN_PART):
            log(f"  sentence start {snapped:.2f} leaves under {MIN_PART:.0f}s on one "
                "side — cutting linear")
            payoff = 0.0
        else:
            payoff = snapped
            linear = cut_window(source_path, s, e, os.path.join(out_dir, "linear.mp4"))
            split = payoff - s
            rotate(linear, split, clip_path)
            os.remove(linear)
            looped = True
            log(f"  loop: opens on payoff at {payoff:.2f} "
                f"({e - payoff:.1f}s punchline + {split:.1f}s run-up)")
    elif edit == "loop":
        log(f"  no usable payoff point for #loop ({payoff:.2f} outside "
            f"{s:.2f}-{e:.2f}) — cutting linear")

    if not looped:
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
