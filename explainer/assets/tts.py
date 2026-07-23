"""Narration stage: a draft shot-list -> narration audio via OpenRouter TTS.

Gemini TTS returns 24kHz 16-bit mono PCM; we wrap it to a WAV. Voice is the A/B
knob (brand default 'Puck'). The align stage (faster-whisper) then word-timestamps
this narration against the shots to drive captions + shot timing.
"""
import os
import wave

import openrouter_client as orc
from explainer.brand import BRAND

SAMPLE_RATE = 24000            # Gemini TTS PCM
SAMPLE_WIDTH = 2               # 16-bit
DEFAULT_VOICE = BRAND.get("voice", "Orus")


def narration_text(script):
    """Join the shot narrations into one spoken script."""
    return " ".join(
        (shot.get("narration") or "").strip()
        for shot in (script.get("shots") or [])
        if (shot.get("narration") or "").strip()
    )


def narrate(script, out_path, voice=DEFAULT_VOICE, model=None, key=None):
    """Render the narration WAV for a shot-list script. Returns (path, seconds)."""
    text = narration_text(script)
    if not text:
        raise ValueError("script has no narration lines")
    pcm = orc.tts(text, voice=voice, model=model, response_format="pcm", key=key)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    seconds = len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)
    return out_path, seconds
