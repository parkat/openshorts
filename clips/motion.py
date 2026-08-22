"""Signal layer: find where something HAPPENS, without understanding it.

The clips lane reads transcripts, so on footage whose content is visual — dashcam,
sport, bodycam, anything where the interesting part is not spoken — it finds
nothing but the talking at the end. This module supplies the missing half: cheap,
frame-accurate signals that say *when* the video changes, leaving *what it means*
to the model in `clips/vision.py`.

Three signals, all derived from the local download so they cost nothing:

  motion  mean absolute difference between consecutive sampled frames. A crash, a
          swerve, a fall — anything sudden — is a spike here.
  audio   RMS energy per bucket. Impacts, horns, screams and shouted reactions all
          land as transients, and audio often leads the picture (tyres screech
          before the collision is visible).
  cuts    PySceneDetect shot boundaries. Meaningless on continuous dashcam footage,
          decisive on edited footage where the editor already marked the moments.

Both series are decoded through a single ffmpeg pipe at low resolution rather than
seeking with OpenCV frame by frame: a 25-minute source is thousands of frames, and
seeking each one is minutes of work where streaming greyscale 160x90 is seconds.

Peaks are deliberately NOT thresholded against an absolute value. What counts as a
lot of motion in a locked-off interview is nothing in a dashcam, so everything is
scored in standard deviations above that video's own baseline.
"""
import os
import math
import subprocess

# Sampling grid for the motion signal. 4fps is enough to catch a collision while
# keeping a long source's decode cheap.
FPS = 4.0
W, H = 160, 90

# Audio buckets per second — matched to the motion grid so the two series align.
AUDIO_HZ = 8000

# A window is grown around each peak: enough lead-in to see what caused it, and
# enough tail to see the consequence. Action needs the aftermath more than speech.
LEAD_S = 6.0
TAIL_S = 10.0


def _ffmpeg_frames(video_path):
    """Greyscale WxH frames at FPS, as a flat byte stream."""
    cmd = ["ffmpeg", "-v", "error", "-i", video_path,
           "-vf", f"fps={FPS},scale={W}:{H},format=gray",
           "-f", "rawvideo", "-"]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def _ffmpeg_audio(video_path):
    """Mono 16-bit PCM at AUDIO_HZ, as a flat byte stream (empty if no audio)."""
    cmd = ["ffmpeg", "-v", "error", "-i", video_path, "-vn",
           "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(AUDIO_HZ), "-"]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def _zscores(values):
    """Standard deviations above this series' own mean. Flat series -> all zero."""
    n = len(values)
    if n == 0:
        return []
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    sd = math.sqrt(var)
    if sd < 1e-9:
        return [0.0] * n
    return [(v - mean) / sd for v in values]


def motion_series(video_path):
    """[(t_seconds, energy)] — mean absolute frame-to-frame difference."""
    import numpy as np
    raw = _ffmpeg_frames(video_path)
    frame_bytes = W * H
    count = len(raw) // frame_bytes
    if count < 2:
        return []
    frames = np.frombuffer(raw[:count * frame_bytes], dtype=np.uint8)
    frames = frames.reshape(count, H * W).astype(np.int16)
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=1)
    # Difference i sits BETWEEN sample i and i+1; attribute it to the later one.
    return [((i + 1) / FPS, float(d)) for i, d in enumerate(diffs)]


def audio_series(video_path, hz=FPS):
    """[(t_seconds, rms)] — loudness on the same grid as the motion series."""
    import numpy as np
    raw = _ffmpeg_audio(video_path)
    if len(raw) < 2:
        return []
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    per_bucket = int(AUDIO_HZ / hz)
    n = len(samples) // per_bucket
    if n < 1:
        return []
    buckets = samples[:n * per_bucket].reshape(n, per_bucket)
    rms = np.sqrt((buckets ** 2).mean(axis=1))
    return [(i / hz, float(v)) for i, v in enumerate(rms)]


def scene_cuts(video_path, log=print):
    """[t_seconds] of shot boundaries, or [] if detection is unavailable."""
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
        video = open_video(video_path)
        mgr = SceneManager()
        mgr.add_detector(ContentDetector())
        mgr.detect_scenes(video=video)
        return [s.get_seconds() for s, _e in mgr.get_scene_list()]
    except Exception as e:  # noqa: BLE001 — a missing detector must not kill the scan
        log(f"  scene detection unavailable ({e}) — continuing on motion + audio")
        return []


def combined(video_path, log=print):
    """All three signals on one timeline.

    Returns {"t", "motion", "audio", "score", "cuts", "duration_s"} where `score`
    is the per-sample max of the two z-scored series: a moment counts if EITHER the
    picture or the sound spikes, because an impact heard off-camera matters as much
    as one seen, and requiring both would miss each.
    """
    mot = motion_series(video_path)
    if not mot:
        log("  could not read frames — no visual signal available")
        return {"t": [], "motion": [], "audio": [], "score": [], "cuts": [],
                "duration_s": 0.0}
    aud = audio_series(video_path)
    log(f"  signals: {len(mot)} motion samples, {len(aud)} audio samples")

    times = [t for t, _ in mot]
    mz = _zscores([v for _, v in mot])
    amap = {round(t, 3): v for t, v in aud}
    az_raw = [amap.get(round(t, 3), 0.0) for t in times]
    az = _zscores(az_raw) if any(az_raw) else [0.0] * len(times)

    score = [max(m, a) for m, a in zip(mz, az)]
    cuts = scene_cuts(video_path, log=log)
    if cuts:
        log(f"  {len(cuts)} shot boundaries")
    return {"t": times, "motion": mz, "audio": az, "score": score, "cuts": cuts,
            "duration_s": (times[-1] if times else 0.0)}


def peaks(sig, min_z=1.8, min_gap_s=20.0, limit=12):
    """Local maxima of the combined score, strongest first.

    `min_z` is in standard deviations of THIS video, so the threshold means the
    same thing on a locked-off interview and on a dashcam. `min_gap_s` keeps one
    event from being reported as several.
    """
    times, score = sig.get("t") or [], sig.get("score") or []
    if not times:
        return []
    ranked = sorted((s, t) for t, s in zip(times, score) if s >= min_z)
    ranked.reverse()
    kept = []
    for s, t in ranked:
        if any(abs(t - kt) < min_gap_s for _, kt in kept):
            continue
        kept.append((s, t))
        if len(kept) >= limit:
            break
    return [{"t": t, "z": round(s, 2)} for s, t in kept]


def windows(sig, min_z=1.8, min_gap_s=20.0, limit=12, lead=LEAD_S, tail=TAIL_S):
    """Peaks grown into reviewable [in, out] windows, clamped to the video.

    A window is snapped outward to the surrounding shot boundaries when there are
    any: on edited footage the editor's own cuts are better boundaries than a fixed
    number of seconds either side of a spike.
    """
    duration = sig.get("duration_s") or 0.0
    cuts = sig.get("cuts") or []
    out = []
    for p in peaks(sig, min_z=min_z, min_gap_s=min_gap_s, limit=limit):
        t = p["t"]
        a, b = max(0.0, t - lead), min(duration, t + tail)
        if cuts:
            before = [c for c in cuts if a - lead <= c <= t]
            after = [c for c in cuts if t <= c <= b + tail]
            if before:
                a = before[-1]
            if after:
                b = after[0]
        if b - a >= 5.0:
            out.append({"in": round(a, 2), "out": round(b, 2),
                        "peak": round(t, 2), "z": p["z"]})
    return sorted(out, key=lambda w: w["in"])
