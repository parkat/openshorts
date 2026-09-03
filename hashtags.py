"""Hashtags: tags earned from the content, plus the ones each platform expects.

Two kinds of tag do two different jobs, and conflating them is how caption blocks
end up as noise:

  CONTENT tags describe this particular video. They are what a person searching
  for the subject would type, so they have to be generated from the clip — a
  fixed list would describe nothing. Mixed niche/descriptive/broad, because a
  block of only-broad tags competes with everything on the platform and a block
  of only-niche tags reaches nobody.

  PLATFORM tags are constants that route the video into a surface: #shorts on
  YouTube, #fyp on TikTok, #reels on Instagram. They say nothing about the
  content and never change, so they belong in settings, not in a model call —
  paying an LLM to rediscover "#shorts" on every clip would be absurd.

The content tags are therefore generated once per clip and stored (editable, and
never regenerated behind your back), while the platform tags are appended at post
time from the publishing settings. Changing your default tags re-composes every
future post without touching a single stored clip.

Order is content-first, platform-last: the caption reads as a sentence followed by
what it is about, and the routing tags sit at the end where they look like
plumbing rather than the point.
"""
import re
import json

import openrouter_client as orc

# What each platform expects, out of the box. These are the tags that decide
# which surface a video is eligible for, not preferences.
DEFAULT_PLATFORM_TAGS = {
    "youtube": ["#shorts"],
    "tiktok": ["#fyp", "#foryou", "#foryoupage"],
    "instagram": ["#reels", "#reel", "#instareels"],
}

# How many CONTENT tags to generate. Ten is the house number (see the post-kit
# convention in explainer/service.py) — enough to span niche to broad without
# reading as a keyword dump.
DEFAULT_COUNT = 10

# Per-platform ceiling on the FINAL block. Instagram allows 30 and rewards more;
# the other two treat a long block as noise.
PLATFORM_LIMIT = {"youtube": 12, "tiktok": 12, "instagram": 20}

# Ten hashtags is ~100 tokens of output, but the draft model reasons before it
# writes and that thinking comes out of the same budget — at 600 it spent the lot
# on reasoning and returned nothing. Sized like the rest of the codebase instead.
MAX_TOKENS = 4000

_TAG_RE = re.compile(r"#?([A-Za-z0-9_]+)")

SYSTEM = """You write hashtags for short-form video. Given one clip, return the tags a
real person might search or follow to end up watching it.

Return a MIX, roughly:
- 3-4 NICHE: the specific subject, person, place, event, or product in this clip.
  These are what someone already interested would follow.
- 3-4 DESCRIPTIVE: the format or the reaction — what kind of thing this is.
- 2-3 BROAD: the large category it sits in. These reach far but compete hard, so
  they support the others rather than carrying the post.

Rules:
- lowercase, no spaces, no punctuation, letters and digits only, each starting '#'
- no platform-routing tags (#shorts #fyp #foryou #reels #viral #trending) — those
  are added separately and wasting a slot on them helps nobody
- nothing misleading: a tag must describe what is actually in THIS clip
- no banned//shadowbanned-adjacent or engagement-bait tags (#follow4follow etc.)
- prefer tags a human would plausibly type over invented compounds

Return ONLY valid JSON: {"hashtags":["#one","#two", ...]}"""


def normalize(tag):
    """Anything tag-shaped -> '#lowercasealnum', or '' if there is nothing left."""
    m = _TAG_RE.search(str(tag or ""))
    if not m:
        return ""
    body = m.group(1).lower()
    return f"#{body}" if body else ""


def dedupe(tags):
    """Normalised, first-seen order, no repeats and no empties."""
    seen, out = set(), []
    for t in tags or []:
        n = normalize(t)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def platform_tags(platform, settings=None):
    """The always-on tags for one platform, from settings or the defaults."""
    cfg = ((settings or {}).get("hashtags") or {}).get("defaults") or {}
    if platform in cfg:
        return dedupe(cfg.get(platform) or [])
    return dedupe(DEFAULT_PLATFORM_TAGS.get(platform, []))


def compose(text, content_tags, platform, settings=None):
    """The final caption for one platform: body, then content tags, then platform tags.

    Deduped across both groups, so a generated '#reels' cannot appear twice, and
    capped per platform. Tags already written into the body are respected — if you
    hand-wrote a caption ending in tags, they are not repeated below it.

    When the cap bites it is the CONTENT tags that get trimmed, never the platform
    ones: the platform tags decide which surface the video is eligible for, so
    dropping '#fyp' to make room for a tenth descriptive tag would cost reach to
    buy nothing. They are reserved first and still printed last.
    """
    st = settings or {}
    body = (text or "").strip()
    in_body = {normalize(m) for m in re.findall(r"#[A-Za-z0-9_]+", body)}
    limit = PLATFORM_LIMIT.get(platform, 12)

    plat = [t for t in platform_tags(platform, st) if t not in in_body][:limit]
    content = [t for t in dedupe(content_tags)
               if t not in in_body and t not in plat][:max(0, limit - len(plat))]

    tags = content + plat
    if not tags:
        return body
    return f"{body}\n\n{' '.join(tags)}".strip()


def _extract(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in model output: {text[:200]}")
    return json.loads(m.group(0)).get("hashtags") or []


def generate(title="", hook="", quote="", extra="", count=DEFAULT_COUNT,
             model=None, key=None, log=print):
    """Content tags for one clip -> (tags, error). One cheap model call.

    Returns rather than raises: hashtags enhance a post that is otherwise ready,
    so a model hiccup must not block publishing — the platform tags still get
    appended either way. The reason comes back with the empty list so a caller
    can put it in front of someone, instead of leaving "no tags" to be explained
    by reading a container log.
    """
    parts = [p for p in (f"Title: {title}" if title else "",
                         f"On-screen hook: {hook}" if hook else "",
                         f"What is said: {quote[:1200]}" if quote else "",
                         extra) if p]
    if not parts:
        return [], "nothing to describe — this clip has no title, hook or transcript"
    prompt = "\n".join(parts) + f"\n\nReturn exactly {count} hashtags."
    try:
        out = orc.chat([{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt}],
                       model=model or orc.MODELS["draft"], temperature=0.4,
                       max_tokens=MAX_TOKENS, key=key)
        tags = dedupe(_extract(out))
    except Exception as e:  # noqa: BLE001 — never block a post on a tag call
        msg = str(e)
        log(f"  hashtag generation failed ({msg}) — continuing without content tags")
        return [], msg
    # Drop anything the model returned that is really a platform tag; those are
    # appended from settings and would otherwise take a slot twice.
    routing = {t for tags_ in DEFAULT_PLATFORM_TAGS.values() for t in tags_}
    routing |= {"#viral", "#trending", "#foryou", "#fy"}
    tags = [t for t in tags if t not in routing][:count]
    log(f"  {len(tags)} content hashtag(s): {' '.join(tags)}")
    return tags, ""
