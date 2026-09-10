"""Snap a requested clip window to real speech boundaries.

A window chosen from a transcript (especially YouTube auto-captions, whose timings
drift and whose text drops words) routinely starts or ends mid-word. This module
re-listens to a padded region around the request with whisper and moves the cut to
the nearest genuine sentence/word edge, preferring a boundary that sits inside a
pause so the cut lands in silence rather than on a syllable.

Used by `clips.fetch_clip`; best-effort — any failure returns the original window.
"""
import os
import subprocess
import tempfile

PAD = 2.5          # seconds of context to transcribe on each side
MIN_GAP = 0.18     # a pause this long counts as a breath we can cut in
EDGE_PAD = 0.10    # keep a sliver of silence around the speech we keep


def _extract_wav(video, start_s, dur_s, out_wav):
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{max(0.0, start_s):.2f}", "-i", video,
         "-t", f"{dur_s:.2f}", "-vn", "-ac", "1", "-ar", "16000", out_wav],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode == 0 and os.path.isfile(out_wav)


def _words(wav_path):
    """[(start, end, text)] via the shared whisper config (medium/cuda + VAD)."""
    from subtitles import transcribe_audio
    tr = transcribe_audio(wav_path)
    out = []
    for seg in tr.get("segments", []):
        for w in seg.get("words", []):
            if w.get("word", "").strip():
                out.append((float(w["start"]), float(w["end"]), w["word"].strip()))
    return out


def _best_start(words, want_rel):
    """Word start nearest `want_rel` that follows a pause (or the first word)."""
    best, best_d = None, 1e9
    for i, (ws, _we, _t) in enumerate(words):
        prev_end = words[i - 1][1] if i else None
        in_pause = prev_end is None or (ws - prev_end) >= MIN_GAP
        d = abs(ws - want_rel)
        # Prefer pause-preceded starts; allow a non-pause word only if much closer.
        score = d if in_pause else d + 0.75
        if score < best_d:
            best, best_d = ws, score
    return best


def _best_end(words, want_rel):
    """Word end nearest `want_rel` that is followed by a pause (or the last word)."""
    best, best_d = None, 1e9
    for i, (_ws, we, _t) in enumerate(words):
        nxt_start = words[i + 1][0] if i + 1 < len(words) else None
        in_pause = nxt_start is None or (nxt_start - we) >= MIN_GAP
        d = abs(we - want_rel)
        score = d if in_pause else d + 0.75
        if score < best_d:
            best, best_d = we, score
    return best


def snap_window(video_path, start_s, end_s, max_shift=2.0, log=print):
    """Return (start, end) moved to the nearest clean speech boundaries.

    Listens to [start-PAD, end+PAD] and picks a word start near `start_s` that
    follows a pause, and a word end near `end_s` that precedes one. Refuses to move
    a boundary more than `max_shift` seconds so a bad match can't rewrite the window.
    Returns the original values unchanged on any failure.
    """
    try:
        if not os.path.isfile(video_path):
            return start_s, end_s
        region_start = max(0.0, float(start_s) - PAD)
        region_dur = (float(end_s) + PAD) - region_start
        if region_dur <= 0:
            return start_s, end_s

        with tempfile.TemporaryDirectory() as td:
            wav = os.path.join(td, "region.wav")
            if not _extract_wav(video_path, region_start, region_dur, wav):
                return start_s, end_s
            words = _words(wav)
        if not words:
            return start_s, end_s

        # Requested cuts, relative to the extracted region.
        s_rel = float(start_s) - region_start
        e_rel = float(end_s) - region_start
        s_new = _best_start(words, s_rel)
        e_new = _best_end(words, e_rel)
        if s_new is None or e_new is None:
            return start_s, end_s

        snapped_start = region_start + s_new - EDGE_PAD
        snapped_end = region_start + e_new + EDGE_PAD

        # Guard: never shift a boundary wildly, and never invert the window.
        if abs(snapped_start - float(start_s)) > max_shift:
            snapped_start = float(start_s)
        if abs(snapped_end - float(end_s)) > max_shift:
            snapped_end = float(end_s)
        if snapped_end - snapped_start < 0.5:
            return start_s, end_s

        ds, de = snapped_start - float(start_s), snapped_end - float(end_s)
        if abs(ds) > 0.02 or abs(de) > 0.02:
            log(f"    snap: in {ds:+.2f}s, out {de:+.2f}s "
                f"({float(start_s):.1f}-{float(end_s):.1f} -> {snapped_start:.1f}-{snapped_end:.1f})")
        return max(0.0, snapped_start), snapped_end
    except Exception as e:  # noqa: BLE001 — snapping must never break a fetch
        log(f"    snap skipped: {e}")
        return start_s, end_s
