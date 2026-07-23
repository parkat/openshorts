"""Stock-footage stage: real, commercial-safe b-roll from Pixabay (no AI label).

Figure/broll shots use GENUINE footage instead of AI-generated visuals, so the
Shorts don't trip platform AI-disclosure labels (which throttle reach). Pixabay
Content License = free for commercial use, no attribution required. Needs a free
`PIXABAY` key in openshorts/.env.

Keyword comes from the shot's visual_note; we prefer vertical clips and fall back
to landscape (the composition cover-crops to 9:16).
"""
import os
import re
import requests

API = "https://pixabay.com/api/videos/"
_STOP = set(
    "a an the of to in on and or for with is are was were be been being this that "
    "these those it its his her their our your my as at by from into over under "
    "then than so but not no yes he she they we you i him them us".split()
)


def keywords(shot, limit=4):
    """A concise Pixabay query from the shot's visual note (drops stop-words)."""
    note = (shot.get("visual_note") or shot.get("narration") or "").lower()
    words = [w for w in re.findall(r"[a-z]{3,}", note) if w not in _STOP]
    return " ".join(words[:limit]) or "technology abstract"


def search(query, key, per_page=20):
    # video_type=film = REAL camera footage only. Pixabay's library is now heavily
    # polluted with AI-generated "animation" clips (bad, dated-looking) — film is the
    # strongest available filter to keep them out. The cost: abstract concepts don't
    # exist as real film, so the script must request FILMABLE real-world scenes.
    # q is URL-encoded by requests (<=100 chars); safesearch on.
    r = requests.get(API, params={"key": key, "q": query[:100], "per_page": per_page,
                                  "video_type": "film", "safesearch": "true"}, timeout=30)
    r.raise_for_status()
    return r.json().get("hits", [])


def best_clip(hits):
    """Pick a download URL. Per the docs, `large` can come back empty (url="",
    size 0) while `medium` is available for ALL videos — so take the biggest
    NON-EMPTY stream per hit, then prefer vertical clips and higher resolution."""
    best, best_score = None, -1
    for h in hits:
        vids = h.get("videos") or {}
        stream = next((vids[s] for s in ("large", "medium", "small", "tiny")
                       if (vids.get(s) or {}).get("url") and vids[s].get("size")), None)
        if not stream:
            continue
        w, ht = stream.get("width", 0), stream.get("height", 0)
        score = (10000 if ht > w else 0) + min(ht, 2160)
        if score > best_score:
            best, best_score = stream["url"], score
    return best


def download(url, out_path):
    with requests.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return out_path


def fetch_for_shot(shot, out_dir, index, key):
    """Search + download one stock clip for a shot; return its /output URL or None."""
    hits = search(keywords(shot), key)
    url = best_clip(hits)
    if not url:
        return None
    out = os.path.join(out_dir, f"broll_{index}.mp4")
    download(url, out)
    return f"/output/{os.path.basename(out_dir)}/{os.path.basename(out)}"


def gather_stock(shots, out_dir, shot_assets, key):
    """Fetch stock b-roll for figure/broll shots not already covered by a clip or
    stills. Merges {shot_index: {"videoUrl": ...}} into a copy of shot_assets."""
    merged = {int(k): dict(v) for k, v in (shot_assets or {}).items()}
    got = 0
    for i, shot in enumerate(shots):
        # Only broll wants stock footage; figure = an on-screen stat/label (text),
        # accent_clip = reference footage. Stock for a stat -> irrelevant clips.
        if shot.get("visual") != "broll":
            continue
        if merged.get(i, {}).get("videoUrl") or merged.get(i, {}).get("images"):
            continue
        try:
            url = fetch_for_shot(shot, out_dir, i, key)
        except Exception:  # noqa: BLE001 — a missing clip just falls back to text
            url = None
        if url:
            merged.setdefault(i, {})["videoUrl"] = url
            got += 1
    return merged, got
