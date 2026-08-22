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
import json
import tempfile
import subprocess


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


def snap_point(source_path, t, max_shift=1.5, log=print):
    """Move a mid-window split point to the nearest word start after a pause.

    The rotation cuts here twice — it opens the clip AND closes it — so landing
    mid-syllable is heard twice. Returns `t` unchanged on any failure.
    """
    try:
        from explainer.assets import snap as sn
        region_start = max(0.0, float(t) - sn.PAD)
        with tempfile.TemporaryDirectory() as td:
            wav = os.path.join(td, "region.wav")
            if not sn._extract_wav(source_path, region_start, sn.PAD * 2, wav):
                return float(t)
            words = sn._words(wav)
        if not words:
            return float(t)
        rel = sn._best_start(words, float(t) - region_start)
        if rel is None:
            return float(t)
        # No EDGE_PAD here. At an outer edge that pad keeps a sliver of silence
        # around the speech we kept; at an internal split the SAME instant is both
        # the run-up's end and the punchline's start, so padding it backwards
        # leaves the word's onset at the head of the punchline while its full
        # self ends the run-up — an audible stutter across the loop seam.
        snapped = region_start + rel
        if abs(snapped - float(t)) > max_shift:
            return float(t)
        return snapped
    except Exception:  # noqa: BLE001 — snapping must never break the cut
        return float(t)


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
        payoff = snap_point(source_path, payoff, log=log)
        # Re-check after snapping — it can drift toward an edge.
        if not (s + 1.0 < payoff < e - 1.0):
            log(f"  payoff {payoff:.2f} too close to an edge after snapping — cutting linear")
        else:
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
