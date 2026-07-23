"""Script stage: topic + sources -> a 30-45s hype hot-take **shot list**.

Voice: bold-claim hooks, confident, punchy — but honest. Every factual line
carries a `source` pointer for the fact-check stage. Output is structured JSON the
Remotion `ExplainerShort` composition renders. Runs via OpenRouter (headless) or a
Claude Code session (`manual_prompt()` returns the exact task to fill, $0 API).
"""
import json
import re

import openrouter_client as orc

SYSTEM = """You are the head writer for "Scientific Awareness", a faceless AI-education
Shorts channel. Write a 30-45 second vertical Short in a HYPE HOT-TAKE voice:
- THE HOOK IS EVERYTHING. The first shot must stop the scroll in ~1.5 seconds: a
  shocking claim, a scary number, or a pattern-interrupt question that opens a
  curiosity gap the viewer NEEDS closed. Front-load the most stunning fact — never
  warm up. It must be true and defensible from the sources. Make hook `seconds` 2-3.
- Fast retention pacing for goldfish attention spans: 9-13 SHORT shots, each 2-4s,
  so the visual cuts constantly. One idea per shot. Never let a beat run long.
- Arc: hook -> escalate the stakes -> the thing -> why it matters -> button (a
  memorable close / mic-drop). Keep momentum; every line earns the next.
- LENGTH & BALANCE. Narration reads ~2.3 words/sec. If the topic has a talking-head
  source (interview/talk/podcast), this is a SOUNDBITE-LED piece: the real speaker's
  OWN voice must carry MORE of the runtime than the AI narrator. Target 45-60s with
  3-4 speaks:true soundbites (~28-40s of the speaker) + a punchy narrator hook and
  SHORT connective bridges only — keep narrator words to ~45-60 total. The narrator
  sets up and stitches; the SUBJECT delivers the substance in their own voice.
  Without talking-head sources, 30-45s and ~80-100 narrator words. Be lean either way.
- Concrete and punchy. No "in this video", no filler, no hedging padding.
- Any shot that states a fact carries a "source" pointer (the source label). Use
  null for pure framing/opinion lines.
- Pick a "visual" per shot. CRITICAL — match the type to where the footage comes from:
  * accent_clip = the SPECIFIC reference speaker's own footage (e.g. Hinton from the
    pasted videos). Use it for the hook (their face while you narrate) and for
    speaks:true soundbites where we SEE them talk. A NAMED person or specific show
    ONLY ever goes here.
  * aid = a GENERATED, animated VISUAL AID (we make it with a video model) that
    VISUALLY EXPLAINS the current point — a concept made visible, a metaphor in
    motion. It must TEACH the idea, not just decorate. Examples: "a human silhouette
    beside an AI silhouette that keeps growing taller, surpassing the human — showing
    AI overtaking human intelligence"; "one glowing node multiplying into a dense
    network — showing capability compounding"; "two curves on a graph, the AI curve
    bending sharply upward past the human line". visual_note = describe the animation
    AND the single idea it makes the viewer understand. Abstract/conceptual is GOOD
    here (this is the channel's primary explanatory visual now). PREFER `aid` over a
    plain text beat whenever a point can be shown.
  * broll = a REAL, FILMABLE stock scene, ONLY for a literal real-world thing a camera
    shoots (e.g. "data center server racks", "hands on a keyboard"). Use sparingly; if
    the point is a concept, use `aid` instead. NEVER a named person / specific show.
  * figure = a striking NUMBER shown huge (percent, year, count, money) — e.g. 20%,
    2023, 100 TRILLION. Use it only for a real number; NOT for label phrases.
  * motion_text / slide = a text-only beat with NO footage (animated brand backdrop).
    Use RARELY — prefer an `aid` that shows the idea. Do NOT write a headline; the
    yellow captions already carry the words.
  visual_note is the direction; for `aid` describe the explanatory animation, for
  broll keep it to plain real-stock keywords.
- "on_screen" is the ACTUAL big text to burn on screen for slide/motion_text shots:
  a punchy 2-5 word distillation of the line. NOT a stage direction, NOT quotes,
  NOT "text:"/"split screen:" prefixes. For a figure shot, on_screen is the EXACT
  number to show huge (e.g. "20%", "2023", "100 TRILLION"). Null for everything else
  (slide/motion_text/accent_clip/broll) — captions carry those words.
- SOUNDBITES (the backbone of a soundbite-led piece): make 3-4 speaks:true shots
  where the reference speaker's OWN words carry the beat — "narration" MUST be "" and
  the narrator does NOT talk over it. A speaks:true shot runs ~8-14s. Two flavors:
  * speaks:true + visual "accent_clip" = we SEE the speaker say it (their face).
  * speaks:true + visual "aid" = we HEAR the speaker while an explanatory `aid`
    animation shows WHAT they're describing (their voice narrates the visual aid).
    Use this to illustrate a claim as they make it — powerful and on-brand.
  Structure: narrator hook -> speaker soundbite (their face) -> narrator one-line
  bridge -> speaker soundbite over an `aid` -> ... The subject's voice should be the
  spine; the narrator is the connective tissue. If there are no talking-head sources,
  use no soundbites.

Return ONLY valid JSON (no markdown, no prose) matching exactly:
{
  "title": "<punchy YouTube title, <=70 chars>",
  "hook": "<the opening spoken line>",
  "shots": [
    {"role":"hook|setup|thing|why|button","narration":"<spoken line, or \\"\\" if speaks:true>",
     "visual":"slide|motion_text|figure|accent_clip|aid|broll","visual_note":"<direction>",
     "on_screen":"<2-5 word on-screen headline, or null>","speaks":<true|false>,
     "source":"<source label or null>","seconds":<int>}
  ],
  "estimated_seconds": <int>,
  "captions": {"youtube":"<desc + #hashtags>","tiktok":"<caption + #hashtags>","instagram":"<caption + #hashtags>"}
}"""


def _user_prompt(title, summary, sources):
    if sources:
        src_lines = "\n".join(
            f"- [{s.get('label') or s.get('type', 'source')}] {s.get('url', '')} {s.get('note', '')}".rstrip()
            for s in sources
        )
    else:
        src_lines = '(none — draft from general knowledge; mark factual lines source: "general")'
    return (
        f"TOPIC: {title}\n\n"
        f"SUMMARY / ANGLE: {summary or '(none — use your knowledge, stay accurate)'}\n\n"
        f"SOURCES (cite these as `source` labels):\n{src_lines}\n\n"
        "Write the Short now. JSON only."
    )


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON object in model output: {text[:200]}")
    return json.loads(m.group(0))


def generate_script(title, summary="", sources=None, model=None, key=None):
    """Return the shot-list dict for a topic via OpenRouter."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _user_prompt(title, summary, sources or [])},
    ]
    out = orc.chat(messages, model=model or orc.MODELS["polish"],
                   temperature=0.8, max_tokens=3000, key=key)
    return _extract_json(out)


def manual_prompt(title, summary="", sources=None):
    """The exact task a Claude Code session should run with its own Claude when
    driving with --provider manual; write the resulting JSON back to the store."""
    return SYSTEM + "\n\n" + _user_prompt(title, summary, sources or [])
