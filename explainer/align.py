"""Align stage: narration audio + shot-list -> word-level captions + shot timing.

The narration WAV (from `assets/tts.py`) is transcribed with faster-whisper (reusing
`subtitles.transcribe_audio`) to get real word timestamps against the *spoken* audio.
We then align those words back onto the script's shots so the Remotion `ExplainerShort`
knows exactly when to switch visuals — captions ride the actual audio, shot cuts land
on word boundaries.

Alignment is a greedy sequential match of normalized whisper words against the
script's reference tokens (we know the exact text — TTS read it), tolerant of
whisper drops/insertions. If transcription yields nothing usable, we fall back to
proportional timing from each shot's estimated `seconds`.

Output (also what `render.py` consumes):
    {
      "duration_ms": int,
      "words": [{"text", "startMs", "endMs"}, ...],   # -> Remotion captions
      "shots": [{...shot, "index", "startMs", "endMs"}, ...],
    }
"""
import os
import re
import json
import wave

import subtitles

# How far ahead in the reference token stream to look for a whisper word before
# giving up and treating it as an insertion. Big enough to skip a dropped word or
# two, small enough not to jump across a repeated word.
_LOOKAHEAD = 6


def _norm(word):
    """Lowercase, strip everything but alphanumerics (drops punctuation/spacing)."""
    return re.sub(r"[^a-z0-9]", "", (word or "").lower())


def _flatten_words(transcript):
    """faster-whisper transcript -> flat [{text, startMs, endMs}] in spoken order."""
    out = []
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []):
            text = (w.get("word") or "").strip()
            if not text:
                continue
            start = float(w.get("start") or 0.0)
            end = float(w.get("end") or start)
            out.append({"text": text, "startMs": int(start * 1000),
                        "endMs": int(max(end, start) * 1000)})
    return out


def _audio_duration_ms(audio_path, words):
    """Prefer the real WAV length; fall back to the last spoken word end."""
    try:
        with wave.open(audio_path, "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 1
            return int(frames / rate * 1000)
    except (wave.Error, EOFError, FileNotFoundError, OSError):
        return words[-1]["endMs"] if words else 0


def _reference_tokens(shots):
    """[(shot_index, normalized_token)] over every narration word, in order."""
    ref = []
    for i, shot in enumerate(shots):
        for tok in (shot.get("narration") or "").split():
            n = _norm(tok)
            if n:
                ref.append((i, n))
    return ref


def _assign_shots(words, ref):
    """Greedy align whisper `words` to `ref` tokens; return a shot index per word."""
    assignments = []
    ptr = 0
    last_shot = ref[0][0] if ref else 0
    for w in words:
        nw = _norm(w["text"])
        if not nw:
            assignments.append(last_shot)
            continue
        hit = None
        for j in range(ptr, min(ptr + _LOOKAHEAD, len(ref))):
            if ref[j][1] == nw:
                hit = j
                break
        if hit is not None:
            last_shot = ref[hit][0]
            ptr = hit + 1
        # else: whisper heard an extra/misrecognized word — keep the current shot.
        assignments.append(last_shot)
    return assignments


def _shot_boundaries(shots, words, assignments, duration_ms):
    """Contiguous per-shot [startMs, endMs) from the first word assigned to each
    shot; a shot with no words inherits the running cursor (zero-length)."""
    first_ms = {}
    for k, sidx in enumerate(assignments):
        first_ms.setdefault(sidx, words[k]["startMs"])

    n = len(shots)
    # Forward pass: a shot's start is its first spoken word, or where the last one ended.
    starts = []
    cursor = 0
    for i in range(n):
        start = first_ms.get(i, cursor)
        start = max(start, cursor)          # never travel backwards
        starts.append(start)
        cursor = start
    # End = next shot's start; last shot runs to the audio end.
    out = []
    for i, shot in enumerate(shots):
        start = starts[i]
        end = starts[i + 1] if i + 1 < n else duration_ms
        end = max(end, start)
        s = dict(shot)
        s["index"] = i
        s["startMs"] = start
        s["endMs"] = end
        out.append(s)
    return out


def _proportional_fallback(shots, duration_ms):
    """No usable transcript: split the audio by each shot's estimated `seconds`
    (equal weight if unset). Captions come back empty — the render still works,
    it just won't have word-level highlighting."""
    weights = [max(0.1, float(s.get("seconds") or 0) or 1.0) for s in shots]
    total = sum(weights) or 1.0
    out = []
    cursor = 0
    for i, (shot, wgt) in enumerate(zip(shots, weights)):
        span = int(duration_ms * wgt / total)
        s = dict(shot)
        s["index"] = i
        s["startMs"] = cursor
        s["endMs"] = duration_ms if i == len(shots) - 1 else cursor + span
        cursor = s["endMs"]
        out.append(s)
    return out


def align(audio_path, script):
    """Transcribe the narration and map it onto the script's shots.

    Returns {"duration_ms", "words", "shots"} — ready for `render.py` to turn into
    a Remotion scene list. Pure with respect to the store; the CLI persists it.
    """
    shots = script.get("shots") or []
    if not shots:
        raise ValueError("script has no shots to align")

    transcript = subtitles.transcribe_audio(audio_path)
    words = _flatten_words(transcript)
    duration_ms = _audio_duration_ms(audio_path, words)

    ref = _reference_tokens(shots)
    if words and ref:
        assignments = _assign_shots(words, ref)
        aligned = _shot_boundaries(shots, words, assignments, duration_ms)
    else:
        aligned = _proportional_fallback(shots, duration_ms)

    return {"duration_ms": duration_ms, "words": words, "shots": aligned}


def write_alignment(alignment, out_path):
    """Persist the alignment JSON next to the render assets."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(alignment, f, ensure_ascii=False, indent=2)
    return out_path
