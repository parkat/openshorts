"""Pull a YouTube video's OWN timed captions (transcript) so we don't have to run
speech recognition on it. Word-level timings come from the auto-caption VTT's inline
`<timestamp><c>word</c>` tags; ASR (whisper) is only the FALLBACK when the caption
track is missing or malformed (see align.py / clips.py).

We reuse `clipfinder.fetch_vtt` to download the track (English, matched by video id).
The rolling-window auto-subs repeat words across cues, but every word gets exactly one
canonical inline timestamp, so collecting the inline-timed tokens (deduped) yields a
clean word stream. `window_words()` slices a clip's [in,out] range, offset to the
clip start (ms), ready to drop onto the master timeline.
"""
import os
import re
import glob
import json

_WORD = re.compile(r"<(\d{2}):(\d{2}):(\d{2})\.(\d{3})><c[^>]*>\s*([^<]+?)</c>")


def video_id(url):
    """YouTube id from a watch/short/embed/youtu.be URL, or None."""
    m = re.search(r"(?:youtu\.be/|[?&]v=|/shorts/|/embed/)([A-Za-z0-9_-]{6,})", url or "")
    return m.group(1) if m else None


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def find_vtt(workdir, vid):
    """A caption VTT already on disk for this video id (from a prior clipfind), or None."""
    cands = sorted(glob.glob(os.path.join(workdir, f"ref_{vid}*.vtt")))
    plain = [c for c in cands if c.endswith(".en.vtt")]
    return (plain or cands)[0] if cands else None


def ensure_vtt(url, workdir, vid=None):
    """Return this video's caption VTT path — reuse an on-disk one (project dir, then
    the youtube cache), else download it."""
    vid = vid or video_id(url)
    have = find_vtt(workdir, vid) if vid else None
    if have:
        return have
    if vid:  # reuse the cached full-download's captions (no re-fetch)
        cached = sorted(glob.glob(os.path.join(
            os.environ.get("EXPLAINER_CACHE", "cache"), "youtube", vid + "*.vtt")))
        plain = [c for c in cached if c.endswith(".en.vtt")]
        if cached:
            return (plain or cached)[0]
    from explainer.clipfinder import fetch_vtt  # yt-dlp --write-auto-subs, matched by id
    return fetch_vtt(url, workdir, vid)


def word_level(vtt_path):
    """[{text, start, end}] word-level from the VTT's inline timings, deduped. Empty
    list if the track has no usable inline word timestamps (-> caller falls back)."""
    try:
        with open(vtt_path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []
    seen, words = set(), []
    for m in _WORD.finditer(raw):
        t = _sec(*m.groups()[:4])
        w = m.group(5).strip()
        if not w:
            continue
        key = (round(t, 2), w.lower())
        if key in seen:
            continue
        seen.add(key)
        words.append({"start": t, "text": w})
    words.sort(key=lambda x: x["start"])
    for i, w in enumerate(words):
        w["end"] = words[i + 1]["start"] if i + 1 < len(words) else w["start"] + 0.4
    return words


def window_words(vtt_path, start_s, end_s):
    """Words spoken within [start_s, end_s], timestamps relative to start_s (ms)."""
    out = []
    for w in word_level(vtt_path):
        if start_s <= w["start"] < end_s:
            out.append({"text": w["text"],
                        "startMs": int((w["start"] - start_s) * 1000),
                        "endMs": int((min(w["end"], end_s) - start_s) * 1000)})
    return out


def valid(words, start_s=0.0, end_s=0.0, min_words=2):
    """A pulled transcript is usable if it has a sane word count for the window — a
    talking-head clip should yield >~1 word/sec; far fewer means a bad/absent track,
    so ASR takes over."""
    if not words or len(words) < min_words:
        return False
    span = max(0.0, end_s - start_s)
    if span >= 4 and len(words) < span * 0.6:   # <0.6 words/sec -> almost certainly broken
        return False
    return True


def save_window(vtt_path, start_s, end_s, out_json):
    """Extract + persist a clip's window transcript. Returns the word list, or [] if
    the track is missing/malformed (caller then uses ASR)."""
    words = window_words(vtt_path, start_s, end_s) if vtt_path else []
    if not valid(words, start_s, end_s):
        return []
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False)
    return words
