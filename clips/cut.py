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
"""
import os
import json
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


def build(source_path, start_s, end_s, out_dir, log=print):
    """Snap -> cut -> extract audio -> caption. Returns the manifest dict."""
    os.makedirs(out_dir, exist_ok=True)
    s, e = snap(source_path, start_s, end_s, log=log)
    if (s, e) != (float(start_s), float(end_s)):
        log(f"  snapped {float(start_s):.2f}-{float(end_s):.2f} -> {s:.2f}-{e:.2f}")

    clip = cut_window(source_path, s, e, os.path.join(out_dir, "clip.mp4"))
    audio = extract_audio(clip, os.path.join(out_dir, "audio.wav"))
    dur = duration_s(clip) or (e - s)
    words = captions(audio, log=log)

    manifest = {"start_s": s, "end_s": e, "duration_s": dur,
                "clip": clip, "audio": audio, "captions": words}
    with open(os.path.join(out_dir, "cut.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
