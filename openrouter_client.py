"""OpenRouter client — one key (env `OPENROUTER`) for the whole explainer pipeline:
text/LLM now; image, video, and TTS added with the Phase-1 asset stages (those use
OpenRouter's dedicated image/video/audio endpoints, not /chat/completions).

OpenAI-compatible. Model IDs are the swappable knob — override per call, or edit
MODELS. IDs below verified live 2026-07 (342 models). Docs:
https://openrouter.ai/docs  ·  multimodal: /docs/guides/overview/multimodal
"""
import os
import base64
import requests

BASE = "https://openrouter.ai/api/v1"

# Swappable defaults (confirmed present on the account's model list).
MODELS = {
    "draft":     "google/gemini-3.5-flash",       # cheap, high-volume script drafting
    "polish":    "anthropic/claude-sonnet-5",      # hook + final script polish
    "factcheck": "anthropic/claude-sonnet-5",      # claim verification
    "image":     "google/gemini-3.1-flash-image",  # slides / figures / visuals
    "tts":       "google/gemini-3.1-flash-tts-preview",  # narration (/audio/speech, PCM 24kHz)
    # video set against the dedicated /videos endpoint in the render stage:
    "video":     "kwaivgi/kling-v3.0-std",         # 9:16 b-roll — confirm slug at build
}


class OpenRouterError(Exception):
    pass


def _key(key=None):
    k = key or os.environ.get("OPENROUTER")
    if not k:
        raise OpenRouterError("OPENROUTER key not set (env or arg).")
    return k


def _headers(key=None):
    return {
        "Authorization": f"Bearer {_key(key)}",
        "Content-Type": "application/json",
        # OpenRouter attribution headers (optional but recommended).
        "HTTP-Referer": "https://openshorts.parkat.us",
        "X-Title": "OpenShorts Explainer",
    }


def key_info(key=None):
    """{label, usage, limit, is_free_tier, ...} — credit balance / limits."""
    r = requests.get(f"{BASE}/key", headers=_headers(key), timeout=20)
    r.raise_for_status()
    return r.json().get("data", {})


def list_models(key=None):
    r = requests.get(f"{BASE}/models", headers=_headers(key), timeout=25)
    r.raise_for_status()
    return r.json().get("data", [])


def chat(messages, model=None, temperature=0.7, max_tokens=None, key=None, **kw):
    """LLM completion (OpenAI-compatible). `messages`=[{"role","content"}].
    Returns the assistant text. Use for script draft/polish and fact-check.

    For the Claude-Code-driven flow, a CC session can bypass this entirely and do
    polish/fact-check with its own Max-plan Claude, then write results back via the
    CLI — so no OpenRouter spend on reasoning when a human is in the loop.
    """
    body = {"model": model or MODELS["polish"], "messages": messages, "temperature": temperature}
    if max_tokens:
        body["max_tokens"] = max_tokens
    body.update(kw)
    r = requests.post(f"{BASE}/chat/completions", headers=_headers(key), json=body, timeout=180)
    if r.status_code == 429:
        raise OpenRouterError(f"OpenRouter rate limited (retry after {r.headers.get('Retry-After','?')}s).")
    try:
        d = r.json()
    except ValueError:
        raise OpenRouterError(f"Non-JSON from OpenRouter ({r.status_code}): {r.text[:200]}")
    if d.get("error"):
        raise OpenRouterError(str(d["error"]))
    r.raise_for_status()
    return d["choices"][0]["message"]["content"]


def generate_image(prompt, model=None, out_path=None, aspect_ratio=None, key=None, **kw):
    """Generate an image via the Unified Image API (POST /images). Returns raw PNG
    bytes, or writes to out_path and returns it. `aspect_ratio` e.g. "1:1","9:16"."""
    body = {"model": model or MODELS["image"], "prompt": prompt}
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    body.update(kw)
    r = requests.post(f"{BASE}/images", headers=_headers(key), json=body, timeout=240)
    if r.status_code == 429:
        raise OpenRouterError(f"OpenRouter rate limited (retry after {r.headers.get('Retry-After','?')}s).")
    try:
        d = r.json()
    except ValueError:
        raise OpenRouterError(f"Non-JSON from OpenRouter images ({r.status_code}): {r.text[:200]}")
    if d.get("error"):
        raise OpenRouterError(str(d["error"]))
    r.raise_for_status()
    data = d.get("data") or []
    if not data or not data[0].get("b64_json"):
        raise OpenRouterError(f"No image returned: {str(d)[:200]}")
    raw = base64.b64decode(data[0]["b64_json"])
    if out_path:
        with open(out_path, "wb") as f:
            f.write(raw)
        return out_path
    return raw


def tts(text, voice="Puck", model=None, out_path=None, response_format="pcm",
        instructions=None, key=None):
    """Text-to-speech via /audio/speech. Default (Gemini TTS) returns raw 24kHz
    16-bit mono PCM bytes; the narration stage wraps it to WAV. Voice is the A/B
    knob (Gemini voices: Puck, Kore, Fenrir, Charon, …). Returns bytes or out_path."""
    body = {"model": model or MODELS["tts"], "input": text, "voice": voice,
            "response_format": response_format}
    if instructions:
        body["instructions"] = instructions
    r = requests.post(f"{BASE}/audio/speech", headers=_headers(key), json=body, timeout=240)
    if r.status_code == 429:
        raise OpenRouterError(f"OpenRouter rate limited (retry after {r.headers.get('Retry-After','?')}s).")
    if r.status_code >= 400:
        try:
            raise OpenRouterError(str(r.json().get("error", r.text[:200])))
        except ValueError:
            raise OpenRouterError(f"TTS {r.status_code}: {r.text[:200]}")
    raw = r.content
    if out_path:
        with open(out_path, "wb") as f:
            f.write(raw)
        return out_path
    return raw


# --- video generation: dedicated async /videos endpoint (submit -> poll -> pull) ---
import time

VIDEO_MODEL = "google/veo-3.1-fast"   # Veo 3.1 Fast (720p ~$0.08/s no-audio; durations 4/6/8)


def generate_video(prompt, out_path, model=None, size="720x1280", duration=4,
                   generate_audio=False, key=None, poll_interval=15, timeout=900, **kw):
    """Text->video via the /videos endpoint. Submits the job, polls until it
    completes, then downloads the mp4 to out_path. Returns {"path", "cost", "id"}.

    `size` is exact WIDTHxHEIGHT (720x1280 = our vertical 9:16). `duration` seconds —
    Veo 3.1 Lite supports 4/6/8 (default 4, i.e. <=5). We request `generate_audio`
    False: the composition mutes all video and drives sound from the narration/
    soundbite master, and no-audio is the cheaper SKU."""
    body = {"model": model or VIDEO_MODEL, "prompt": prompt, "size": size,
            "duration": int(duration), "generate_audio": bool(generate_audio)}
    body.update(kw)
    r = requests.post(f"{BASE}/videos", headers=_headers(key), json=body, timeout=60)
    try:
        job = r.json()
    except ValueError:
        raise OpenRouterError(f"Non-JSON from /videos ({r.status_code}): {r.text[:200]}")
    if job.get("error") or not job.get("id"):
        raise OpenRouterError(f"video submit failed ({r.status_code}): {str(job)[:200]}")
    jid = job["id"]
    poll_url = job.get("polling_url") or f"{BASE}/videos/{jid}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll_interval)
        pr = requests.get(poll_url, headers=_headers(key), timeout=30)
        d = pr.json()
        status = d.get("status")
        if status == "completed":
            url = (d.get("unsigned_urls") or [f"{BASE}/videos/{jid}/content?index=0"])[0]
            vr = requests.get(url, headers=_headers(key), timeout=180)
            vr.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(vr.content)
            return {"path": out_path, "cost": (d.get("usage") or {}).get("cost"), "id": jid}
        if status in ("failed", "cancelled", "expired"):
            raise OpenRouterError(f"video job {jid} {status}: {str(d)[:200]}")
    raise OpenRouterError(f"video job {jid} did not finish within {timeout}s")
