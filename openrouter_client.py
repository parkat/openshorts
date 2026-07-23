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
    # video + tts are set in Phase 1 against the dedicated endpoints:
    "video":     "kwaivgi/kling-v3.0-std",         # 9:16 b-roll (video endpoint) — confirm slug at build
    "tts":       "openai/tts-1",                    # narration (/audio/speech) — confirm at build
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


# --- Phase 1 (asset stages) — dedicated endpoints, wired when built ---
# generate_video(prompt, ...)  -> POST {BASE}/videos (async; poll for the result)
# tts(text, voice, ...)        -> POST {BASE}/audio/speech (OpenAI-compatible bytes)
