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
- Open with a bold, scroll-stopping claim (the hook). Confident, punchy, a little
  cocky — but NEVER fabricate; every factual claim must be defensible from the sources.
- Arc: hook -> setup -> the thing -> why it matters -> button (a memorable close).
- 5-9 shots; ~30-45s read aloud (~2.6 words/sec, so ~80-115 words total). Single idea.
- Concrete and punchy. No "in this video", no filler, no hedging padding.
- Any shot that states a fact carries a "source" pointer (the source label). Use
  null for pure framing/opinion lines.
- Suggest a "visual" per shot: slide | motion_text | figure | accent_clip | broll,
  plus a short visual_note (the DIRECTION — what to show, for asset selection).
- "on_screen" is the ACTUAL big text to burn on screen for slide/motion_text shots:
  a punchy 2-5 word distillation of the line. NOT a stage direction, NOT quotes,
  NOT "text:"/"split screen:" prefixes. e.g. narration "bigger models are hitting a
  wall" -> on_screen "SIZE HIT A WALL". Use null for figure/accent_clip/broll shots.

Return ONLY valid JSON (no markdown, no prose) matching exactly:
{
  "title": "<punchy YouTube title, <=70 chars>",
  "hook": "<the opening spoken line>",
  "shots": [
    {"role":"hook|setup|thing|why|button","narration":"<spoken line>",
     "visual":"slide|motion_text|figure|accent_clip|broll","visual_note":"<direction>",
     "on_screen":"<2-5 word on-screen headline, or null>",
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
