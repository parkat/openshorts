"""Fact-check stage: a drafted shot-list -> atomic claims verified against sources.

Extracts the factual claims from the script and labels each `supported` /
`overstated` / `unsupported` against the supplied source material (the topic's
doc/transcript text, when parkat provides it) — otherwise judged conservatively
from general knowledge with a lower bar for flagging. Flags land in the review
queue (gate 1) for parkat to resolve before assets/render.

Runs via OpenRouter (headless) or a Claude Code session (`manual_prompt()` -> the
driver fills the JSON with its own Claude, $0 API), same pattern as `script.py`.
"""
import json
import re

import openrouter_client as orc

LABELS = ("supported", "overstated", "unsupported")

SYSTEM = """You are a rigorous fact-checker for a science/AI education channel. You are
given a short video SCRIPT (a shot list of spoken lines, each with an optional source
label) and, when available, the SOURCE MATERIAL those lines are supposed to rest on.

Your job: extract every ATOMIC factual claim the narration makes (one verifiable
assertion each — split compound sentences), and judge each against the sources:
- "supported"   — the source material directly backs the claim.
- "overstated"  — directionally true but exaggerated, missing a caveat, or stronger
                  than the source warrants (hype outrunning the evidence).
- "unsupported" — not backed by the sources, or contradicted, or unverifiable.

Rules:
- Only judge FACTUAL claims. Skip pure hype/framing/opinion/hook lines (no claim).
- If there is NO source material, judge from mainstream knowledge and be STRICT:
  anything specific (numbers, benchmarks, "first/best/beats X") that you can't
  vouch for is "overstated" or "unsupported", not "supported".
- Quote the smallest offending span. Keep `note` to one sentence with the fix.

Return ONLY valid JSON (no markdown, no prose) matching exactly:
{
  "claims": [
    {"claim":"<atomic claim>","label":"supported|overstated|unsupported",
     "source":"<source label the line cited, or null>","note":"<one-sentence why/fix>"}
  ],
  "summary": {"supported":<int>,"overstated":<int>,"unsupported":<int>}
}"""


def _script_lines(script):
    out = []
    for i, shot in enumerate(script.get("shots") or []):
        line = (shot.get("narration") or "").strip()
        if line:
            out.append(f"[{i}] ({shot.get('source') or 'no-source'}) {line}")
    return "\n".join(out)


def _user_prompt(script, source_text):
    src = source_text.strip() if source_text else "(no source material provided — judge strictly from general knowledge)"
    return (
        f"SCRIPT (shot list):\n{_script_lines(script)}\n\n"
        f"SOURCE MATERIAL:\n{src}\n\n"
        "Extract and judge the atomic claims now. JSON only."
    )


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON object in model output: {text[:200]}")
    return json.loads(m.group(0))


def _normalize(result):
    """Coerce to the stored shape and recompute the summary from the claims."""
    claims = []
    for c in result.get("claims") or []:
        label = (c.get("label") or "").lower().strip()
        if label not in LABELS:
            label = "unsupported"
        claims.append({
            "claim": (c.get("claim") or "").strip(),
            "label": label,
            "source": c.get("source"),
            "note": (c.get("note") or "").strip(),
        })
    summary = {k: sum(1 for c in claims if c["label"] == k) for k in LABELS}
    return {"claims": claims, "summary": summary}


def factcheck(script, source_text="", model=None, key=None):
    """Return {claims:[...], summary:{...}} for a drafted script via OpenRouter."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _user_prompt(script, source_text)},
    ]
    out = orc.chat(messages, model=model or orc.MODELS["factcheck"],
                   temperature=0.0, max_tokens=2500, key=key)
    return _normalize(_extract_json(out))


def flags(result):
    """The non-'supported' claims — what gate 1 must resolve, worst first."""
    order = {"unsupported": 0, "overstated": 1}
    return sorted((c for c in result.get("claims", []) if c["label"] != "supported"),
                  key=lambda c: order.get(c["label"], 9))


def manual_prompt(script, source_text=""):
    """The exact task a Claude Code session runs to fact-check with its own Claude
    (--provider manual); write the resulting JSON back to the draft ($0 API)."""
    return SYSTEM + "\n\n" + _user_prompt(script, source_text)
