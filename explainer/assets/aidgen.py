"""Author a generated visual aid as a Remotion COMPONENT instead of buying an mp4.

An `aid` beat is an animation that EXPLAINS the point (a concept made visible). It
used to be a clip from a video model — expensive (~$0.20/s, and a spoken aid is a
3-clip montage), slow (submit + poll), opaque (you can't fix an arrow that points
the wrong way), fixed-length (4/6/8s against a beat whose real length align.py only
decides later), and frozen in one palette.

Here the LLM writes a small React component instead. The render-service compiles
and probes it (`POST /aid/compile`, `POST /aid/probe`); `DynamicAid.tsx` runs it.
That makes an aid:
  - ~$0.04 and a few seconds instead of ~$0.80/clip and minutes (measured on
    claude-sonnet-5, one clean attempt; a cheaper model is a per-call override),
  - exactly as long as its beat (it's a function of `progress`, not a fixed clip),
  - re-themeable for free — it draws only from `theme`, so switching a project to
    the `dark` mood re-colours every aid with no regeneration,
  - readable and hand-editable: `aid_<i>.jsx` sits in the project dir.

Failure is safe: if authoring can't produce something that compiles AND visibly
animates, we return None and the caller falls back (Veo, or the SVG/backdrop
downgrade `render.build_scene_list` already performs).
"""
import os
import re

import openrouter_client as orc
from explainer import cache
from explainer.render import RENDER_SERVICE_URL

import requests

# Version of the authoring contract: the system prompt below PLUS the argument
# shape DynamicAid passes down. Bump on any change to either, so cached components
# written against the old runtime stop being reused (see cache.ref_for_code).
CONTRACT = "aid-v1"

ATTEMPTS = int(os.environ.get("EXPLAINER_AID_ATTEMPTS", "3"))
PROBE = os.environ.get("EXPLAINER_AID_PROBE", "1") not in ("0", "false", "no")
# Generous on purpose. A reasoning model spends a good chunk of its budget thinking
# before it writes a line, and a component that runs out of room mid-JSX is wasted
# spend — it fails the compile gate and burns a retry.
MAX_TOKENS = int(os.environ.get("EXPLAINER_AID_MAX_TOKENS", "8000"))

# Default art direction. A mood preset replaces this via brand.MOODS[...]["aid_code_style"].
STYLE = (
    "Flat 2D vector motion graphics in a 1980s retro-tech register (RadioShack + "
    "early-Apple): bold simple shapes, thick strokes, flat fills, no gradients and "
    "no drop shadows. Confident, springy, purposeful motion — something should be "
    "clearly different at the end of the beat than at the start."
)

_SYSTEM = """You write ONE small React component that visually explains a single idea \
for a 9:16 short. Output is rendered by Remotion at 1080x1920.

Return ONLY the component source. No prose, no markdown fences, no exports, no imports.

CONTRACT — declare exactly this, named exactly `Aid`:

const Aid = ({ theme, frame, fps, durationInFrames, progress, lib, props }) => {
  // ...compute from `progress` / `frame`...
  return (/* JSX */);
};

Arguments:
  theme.bg          background colour (already painted behind you)
  theme.ink         foreground/outline colour
  theme.rainbow     array of 6 accent colours, theme.rainbow[0..5]
  theme.highlight   the caption highlight colour
  frame             current frame number
  fps               frames per second
  durationInFrames  length of this beat
  progress          0 -> 1 across the whole beat  <-- ANIMATE ON THIS
  lib.interpolate(input, [inRange], [outRange], opts?)
  lib.spring({ frame, config?, durationInFrames? })  // fps is pre-bound
  lib.Easing        // lib.Easing.out(lib.Easing.cubic), etc.
  lib.interpolateColors(input, [inRange], [colours])
  lib.random(seed)
  props             extra data (usually empty — do not rely on it)

HARD RULES:
1. `Aid` must be a PURE FUNCTION of its arguments. No React hooks of any kind.
2. No imports, no require, no fetch, no document/window access.
3. NEVER hardcode a colour. No hex literals at all. Every colour must come from
   `theme`. Translucent scrims via rgba(...) are fine. This is what lets a mood
   preset re-colour the animation without regenerating it.
4. NO TEXT. No words, letters, digits, or numerals anywhere — no <text> elements,
   no labels, no axis numbers. Burned-in captions are the only words on screen.
   Show quantity with the SIZE, COUNT or POSITION of shapes instead.
5. It must visibly CHANGE across the beat. A static picture is a failure.
6. Fill the frame: a root <svg viewBox="0 0 1080 1920" width="100%" height="100%">
   is the easiest way. Keep the important action between y=400 and y=1250 — the top
   is platform UI and captions sit low.
7. Keep it bold and legible on a phone: few elements, thick strokes (12-28), large
   shapes. Simple and clear beats intricate.

EXAMPLE of the expected shape and level of detail:

const Aid = ({ theme, progress, lib }) => {
  const rise = lib.interpolate(progress, [0, 0.85], [0, 1], {
    extrapolateRight: "clamp",
    easing: lib.Easing.out(lib.Easing.cubic),
  });
  const bars = [0.35, 0.55, 0.8, 1];
  return (
    <svg viewBox="0 0 1080 1920" width="100%" height="100%">
      <line x1={140} y1={1240} x2={940} y2={1240}
            stroke={theme.ink} strokeWidth={16} strokeLinecap="round" />
      {bars.map((h, i) => {
        const full = h * 620 * rise;
        return (
          <rect key={i} x={190 + i * 180} y={1240 - full} width={130} height={full}
                rx={16} fill={theme.rainbow[i % 6]}
                stroke={theme.ink} strokeWidth={12} />
        );
      })}
    </svg>
  );
};
"""

_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def _strip_fences(text):
    """Models wrap code in markdown fences no matter how firmly you ask them not to."""
    t = (text or "").strip()
    if "```" in t:
        blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", t, flags=re.S)
        if blocks:
            t = max(blocks, key=len)
    return _FENCE.sub("", t).strip()


def _service(service_url=None):
    return (service_url or RENDER_SERVICE_URL).rstrip("/")


def compile_source(source, service_url=None, timeout=30):
    """Lint + transform TSX -> JS via the render-service. Returns (ok, js, errors)."""
    r = requests.post(f"{_service(service_url)}/aid/compile",
                      json={"source": source}, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    return bool(d.get("ok")), d.get("js") or "", list(d.get("errors") or [])


def probe_js(js, theme, duration_frames, service_url=None, timeout=300):
    """Render the component for real and check it draws something that moves.
    Returns (ok, reason, infrastructure_failure)."""
    r = requests.post(f"{_service(service_url)}/aid/probe",
                      json={"js": js, "theme": theme,
                            "durationInFrames": int(duration_frames)},
                      timeout=timeout)
    d = r.json()
    if r.status_code >= 500 or d.get("infrastructure"):
        return False, d.get("reason") or f"probe HTTP {r.status_code}", True
    return bool(d.get("ok")), d.get("reason") or "", False


def _duration_frames(shot, fps=30):
    secs = 0.0
    try:
        secs = float(shot.get("seconds") or 0)
    except (TypeError, ValueError):
        secs = 0.0
    if secs <= 0:
        secs = 4.0
    return max(30, min(300, int(round(secs * fps))))


def author(shot, theme, style=None, model=None, key=None, log=print,
           attempts=ATTEMPTS, service_url=None, probe=PROBE):
    """Author one aid component for `shot`.

    Returns {"jsx", "js", "cost"} or None if every attempt failed. `theme` is the
    ExplainerTheme dict (render.brand_theme) — the probe renders against it, so a
    component that is invisible in THIS mood is caught here rather than on screen.
    """
    note = (shot.get("visual_note") or shot.get("narration") or "").strip()
    if not note:
        return None

    brief = (
        f"Idea to make visible: {note}\n\n"
        f"Art direction: {style or STYLE}\n\n"
        "Write the `Aid` component."
    )
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": brief}]
    frames = _duration_frames(shot)
    cost = 0.0

    for attempt in range(1, max(1, attempts) + 1):
        try:
            resp = orc.chat_full(messages, model=model or orc.MODELS["polish"],
                                 temperature=0.4, max_tokens=MAX_TOKENS, key=key,
                                 usage={"include": True})
        except Exception as e:  # noqa: BLE001 — one failed aid shouldn't abort the stage
            log(f"    codegen call failed: {e}")
            return None
        cost += (resp.get("usage") or {}).get("cost") or 0.0
        choice = resp["choices"][0]
        source = _strip_fences(choice["message"].get("content") or "")

        # A truncated answer fails the compile gate with a confusing syntax error (or
        # an empty body, if reasoning ate the whole budget). Name the real problem so
        # the retry writes something shorter instead of re-litigating the syntax.
        if choice.get("finish_reason") == "length":
            log(f"    attempt {attempt}: response truncated at {MAX_TOKENS} tokens")
            messages += [
                {"role": "user",
                 "content": ("Your previous answer was cut off before it finished. "
                             "Write a SHORTER, simpler component — fewer elements and "
                             "less computation — and return only the `Aid` component.")},
            ]
            continue

        ok, js, errors = compile_source(source, service_url=service_url)
        if not ok:
            log(f"    attempt {attempt}: compile rejected — {'; '.join(errors)[:200]}")
            messages += [
                {"role": "assistant", "content": source},
                {"role": "user",
                 "content": ("That was rejected:\n- " + "\n- ".join(errors) +
                             "\n\nFix it and return the corrected `Aid` component only.")},
            ]
            continue

        if not probe:
            return {"jsx": source, "js": js, "cost": cost}

        p_ok, reason, infra = probe_js(js, theme, frames, service_url=service_url)
        if p_ok:
            return {"jsx": source, "js": js, "cost": cost}
        if infra:
            # The probe itself broke (renderer down, Chromium OOM). That's not a
            # verdict on the code — it compiled, and DynamicAid's ErrorBoundary
            # covers us at render time. Ship it rather than burn retries.
            log(f"    probe unavailable ({reason[:120]}) — accepting compiled component")
            return {"jsx": source, "js": js, "cost": cost}

        log(f"    attempt {attempt}: probe rejected — {reason[:200]}")
        messages += [
            {"role": "assistant", "content": source},
            {"role": "user",
             "content": (f"It compiled but was rejected on render: {reason}\n\n"
                         "Return a corrected `Aid` component only.")},
        ]

    return None


def author_cached(shot, theme, style=None, model=None, key=None, log=print,
                  labels=None, jsx_path=None, js_path=None, service_url=None):
    """`author` with the content cache in front of it, mirroring how the video path
    reuses clips. Writes both files and returns (made, cost).

    The cache key covers the model, the brief AND the contract version — a component
    is only interchangeable when the runtime it was written against is the same.
    """
    note = (shot.get("visual_note") or shot.get("narration") or "").strip()
    mdl = model or orc.MODELS["polish"]
    prompt = f"{note}||{style or STYLE}"
    rk = cache.ref_for_code(mdl, prompt, CONTRACT)

    hit = cache.reuse(rk)
    if hit and js_path and cache.materialize(hit, js_path):
        src = (hit.meta or {}).get("jsx")
        if src and jsx_path:
            with open(jsx_path, "w", encoding="utf-8") as f:
                f.write(src)
        log("    <- cache reuse (no LLM spend)")
        return 0, 0.0

    out = author(shot, theme, style=style, model=mdl, key=key, log=log,
                 service_url=service_url)
    if not out:
        return 0, 0.0

    with open(js_path, "w", encoding="utf-8") as f:
        f.write(out["js"])
    if jsx_path:
        with open(jsx_path, "w", encoding="utf-8") as f:
            f.write(out["jsx"])

    # The readable source rides along in meta so a cache hit can restore the
    # editable .jsx too, not just the compiled output.
    cache.put("code", js_path, ref_key=rk, source=prompt, model=mdl,
              labels=labels or [], meta={"cost": out["cost"], "jsx": out["jsx"],
                                         "contract": CONTRACT})
    return 1, out["cost"]
