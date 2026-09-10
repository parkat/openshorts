"""Reframe a 16:9 talking-head/panel clip to vertical 9:16, CENTERED ON THE SPEAKER
instead of the frame center. Detects the dominant (largest, most-central) face across
sampled frames with MediaPipe, takes the median horizontal position for stability, and
crops a 9:16 window around it. Falls back to a center crop if no face is found.

Used by clips.fetch_clip so every accent clip is speaker-framed, not center-cropped.
"""
import os
import subprocess


def _dims(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        w, h = r.stdout.decode().strip().split(",")[:2]
        return int(w), int(h)
    except ValueError:
        return 0, 0


def _face_center_x(path, samples=14):
    """Median normalized x (0..1) of the dominant face across sampled frames, or None.
    Dominant = largest face, biased toward frame center so a background bystander in a
    wide shot doesn't steal the crop from the person actually being featured."""
    try:
        import cv2
        import mediapipe as mp
    except Exception:
        return None
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if total <= 0:
        cap.release()
        return None
    xs = []
    with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5) as fd:
        for k in range(samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / samples))
            ok, frame = cap.read()
            if not ok:
                continue
            res = fd.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if not res.detections:
                continue

            def score(d):
                b = d.location_data.relative_bounding_box
                area = max(0.0, b.width) * max(0.0, b.height)
                cx = b.xmin + b.width / 2.0
                return area * (1.0 - 0.35 * abs(cx - 0.5))  # bigger + more central wins

            best = max(res.detections, key=score)
            b = best.location_data.relative_bounding_box
            xs.append(min(1.0, max(0.0, b.xmin + b.width / 2.0)))
    cap.release()
    if not xs:
        return None
    xs.sort()
    return xs[len(xs) // 2]


def reframe_to_vertical(in_path, out_path, W=720, H=1280):
    """Crop `in_path` to a 9:16 window centered on the speaker's face, scaled to WxH.
    Returns out_path on success, else None (caller keeps the original)."""
    sw, sh = _dims(in_path)
    if not sw or not sh:
        return None
    if abs(sw / sh - W / H) < 0.02:   # already ~vertical, nothing to crop
        return None
    cx = _face_center_x(in_path)
    if cx is None:
        cx = 0.5
    crop_w = min(sw, int(round(sh * W / H)))
    x0 = int(round(cx * sw - crop_w / 2.0))
    x0 = max(0, min(sw - crop_w, x0))
    vf = f"crop={crop_w}:{sh}:{x0}:0,scale={W}:{H}"
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", in_path, "-vf", vf, "-c:v", "libx264", "-preset",
         "veryfast", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", out_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out_path if (r.returncode == 0 and os.path.isfile(out_path)) else None
