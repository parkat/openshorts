"""Audio-assembly stage: build the master narration timeline for mixed
narrator + soundbite shorts.

Walks the shot list in order and concatenates, as raw 24kHz mono PCM:
- narrated shots  -> Orus TTS of the line
- soundbite shots -> SILENCE the length of the accent clip (the clip plays its
  OWN audio in the composition, so Hinton actually speaks over the gap)

Returns the WAV path + an authoritative timeline [{shot_index,start_ms,end_ms,kind}]
that `align` uses for shot boundaries (whisper still supplies caption words for the
narrated segments; the silent soundbite gaps simply carry no captions).

Working in PCM means assembly is a pure byte concat — no ffmpeg for the mix — and the
timeline is exact.
"""
import os
import array
import wave
import subprocess

import openrouter_client as orc
from explainer.brand import BRAND
from explainer.assets.tts import styled

SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2               # 16-bit
DEFAULT_VOICE = BRAND.get("voice", "Orus")


def trim_silence(pcm, thresh=500, pad_ms=50):
    """Strip leading/trailing near-silence from a PCM segment (keeps a small pad).
    Tightens the gaps between per-shot narration segments so the read doesn't drag."""
    if len(pcm) & 1:            # drop a stray byte so 16-bit unpacking is aligned
        pcm = pcm[:-1]
    a = array.array("h")
    a.frombytes(pcm)
    n = len(a)
    if not n:
        return pcm
    i = 0
    while i < n and abs(a[i]) < thresh:
        i += 1
    if i >= n:
        return pcm  # all silence — leave as-is
    j = n - 1
    while j > i and abs(a[j]) < thresh:
        j -= 1
    pad = int(pad_ms / 1000 * SAMPLE_RATE)
    return a[max(0, i - pad):min(n, j + 1 + pad)].tobytes()


def atempo(pcm, factor):
    """Speed narration by `factor` (pitch preserved) via ffmpeg atempo. 1.0 = no-op."""
    if not factor or abs(factor - 1.0) < 0.01:
        return pcm
    p = subprocess.run(
        ["ffmpeg", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-af", f"atempo={factor:.3f}", "-f", "s16le", "pipe:1"],
        input=pcm, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.stdout or pcm


def _is_soundbite(shot):
    return bool(shot.get("speaks")) and shot.get("visual") == "accent_clip"


def clip_duration_s(path):
    """Exact duration of a media file via ffprobe (seconds), or 0.0."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(r.stdout.decode().strip())
    except ValueError:
        return 0.0


def _silence(seconds):
    # Compute whole SAMPLES then * width, so the byte count is ALWAYS even. An odd
    # silence length shifts every following 16-bit sample by one byte -> the rest of
    # the track reads as max-volume static (the "blown out after the clip" bug).
    n_samples = int(max(0.0, seconds) * SAMPLE_RATE)
    return b"\x00" * (n_samples * SAMPLE_WIDTH)


def _even(pcm):
    """Drop a stray trailing byte so a segment is always 16-bit sample-aligned."""
    return pcm[:-1] if (len(pcm) & 1) else pcm


def _dur_ms(pcm):
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH) * 1000.0


def assemble(shots, soundbite_paths, out_path, voice=DEFAULT_VOICE,
             model=None, key=None, tts=None, tone=None, speed=1.0):
    """Build the master narration WAV + timeline.

    `soundbite_paths`: {shot_index: local_clip_path} for the shots that speak.
    `tone`: run-level Gemini style directive; a shot may override via shot["tone"].
    `speed`: tempo multiplier applied to NARRATED segments only (the soundbite
    keeps its real pace). `tts`: injectable text->pcm fn for testing.
    Returns (out_path, timeline).
    """
    tts = tts or (lambda text: orc.tts(text, voice=voice, model=model,
                                       response_format="pcm", key=key))
    segments, timeline, cursor = [], [], 0.0
    for i, shot in enumerate(shots):
        if _is_soundbite(shot) and i in soundbite_paths:
            dur = clip_duration_s(soundbite_paths[i])
            if dur <= 0:
                continue
            pcm = _silence(dur)
            kind = "soundbite"
        else:
            text = (shot.get("narration") or "").strip()
            if not text:
                continue
            pcm = atempo(trim_silence(tts(styled(text, shot.get("tone", tone)))), speed)
            kind = "narration"
        pcm = _even(pcm)  # guarantee sample alignment before concatenation
        ms = _dur_ms(pcm)
        timeline.append({"shot_index": i, "start_ms": int(cursor),
                         "end_ms": int(cursor + ms), "kind": kind})
        cursor += ms
        segments.append(pcm)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(segments))
    return out_path, timeline


def has_soundbites(shots):
    return any(_is_soundbite(s) for s in shots)
