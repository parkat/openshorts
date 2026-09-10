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


def _stream(hit):
    """The biggest NON-EMPTY stream of a hit (large can be empty; medium always
    exists), or None. Returns (score, url) — score prefers vertical + resolution."""
    vids = hit.get("videos") or {}
    stream = next((vids[s] for s in ("large", "medium", "small", "tiny")
                   if (vids.get(s) or {}).get("url") and vids[s].get("size")), None)
    if not stream:
        return None
    w, ht = stream.get("width", 0), stream.get("height", 0)
    return ((10000 if ht > w else 0) + min(ht, 2160), stream["url"])


def top_clips(hits, n):
    """Up to n DISTINCT download URLs, best first — so a b-roll shot can cut between
    different clips instead of skipping around inside one."""
    scored = sorted((s for s in (_stream(h) for h in hits) if s), key=lambda x: -x[0])
    out, seen = [], set()
    for _, url in scored:
        if url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= n:
            break
    return out


def download(url, out_path):
    with requests.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return out_path


CLIPS_PER_SHOT = int(os.environ.get("EXPLAINER_STOCK_CLIPS", "3"))


def fetch_for_shot(shot, out_dir, index, key, n=CLIPS_PER_SHOT):
    """Search + download up to n DISTINCT stock clips for a shot; return their
    /output URLs (the render cuts between them). Empty if nothing downloads."""
    urls = top_clips(search(keywords(shot), key), n)
    out_urls = []
    for j, url in enumerate(urls):
        out = os.path.join(out_dir, f"broll_{index}_{j}.mp4")
        try:
            download(url, out)
            out_urls.append(f"/output/{os.path.basename(out_dir)}/{os.path.basename(out)}")
        except Exception:  # noqa: BLE001 — skip a clip that won't download
            continue
    return out_urls


def gather_stock(shots, out_dir, shot_assets, key):
    """Fetch stock b-roll for broll shots not already covered. Merges {shot_index:
    {"videos": [...]}} into a copy of shot_assets (multiple clips per shot so the
    render cuts between distinct footage, not around one clip)."""
    merged = {int(k): dict(v) for k, v in (shot_assets or {}).items()}
    got = 0
    for i, shot in enumerate(shots):
        # Only broll wants stock footage; figure = a big number (text), accent_clip
        # = reference footage.
        if shot.get("visual") != "broll":
            continue
        e = merged.get(i, {})
        if e.get("videos") or e.get("videoUrl") or e.get("images"):
            continue
        try:
            urls = fetch_for_shot(shot, out_dir, i, key)
        except Exception:  # noqa: BLE001 — a missing shot just falls back to backdrop
            urls = []
        if urls:
            merged.setdefault(i, {})["videos"] = urls
            got += 1
    return merged, got
