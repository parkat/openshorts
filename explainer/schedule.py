"""Schedule stage: drip approved explainer renders 1/day at 06:00 America/Los_Angeles.

Reuses the verified Buffer + media.parkat.us path: we POST to the backend's
`/api/buffer/*` endpoints (internal docker network, bypassing Cloudflare Access),
which host the render by tokenized media URL and createPost per channel. The
`due_at` is a computed 06:00-LA slot (customScheduled), so Buffer publishes at the
brand's daily time regardless of when the worker ticks.

Cadence is one project per calendar day: a day that already has a scheduled item
is skipped when picking the next slot.

Pure helpers (`next_slot`, `build_descriptions`, `match_channels`, `latest_render`)
are unit-testable; the HTTP + store writes live in `schedule_project` / `tick`.
"""
import os
import glob
import json
import datetime
from zoneinfo import ZoneInfo

import requests

import store
from explainer.brand import BRAND

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))
PLATFORMS = ("youtube", "tiktok", "instagram")


def _tz():
    return ZoneInfo(BRAND.get("timezone", "America/Los_Angeles"))


def _publish_times():
    """The brand's daily publish slots as [(hh, mm), ...], earliest first.
    `publish_times` (list) wins; falls back to the legacy single `publish_time`."""
    raw = BRAND.get("publish_times") or [BRAND.get("publish_time", "06:00")]
    out = []
    for t in raw:
        hh, mm = (str(t).split(":") + ["0"])[:2]
        out.append((int(hh), int(mm)))
    return sorted(set(out))


def next_slot(taken_slots, now=None):
    """Next free publish slot (tz-aware) in the brand timezone.

    Supports N slots per day (e.g. 04:00 + 17:00): walks forward through
    day x slot-time and returns the first candidate that is in the future and
    not already taken.

    `taken_slots`: iterable of datetimes already scheduled — tz-aware, or naive
    which is read as UTC (that's how ScheduleItem.due_at is persisted). `now`:
    tz-aware datetime, injectable for tests.
    """
    tz = _tz()
    now = now or datetime.datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    now = now.astimezone(tz)

    taken = set()
    for d in (taken_slots or []):
        if d is None:
            continue
        if isinstance(d, datetime.datetime):
            if d.tzinfo is None:                      # stored naive-UTC
                d = d.replace(tzinfo=datetime.timezone.utc)
            taken.add(d.astimezone(tz).replace(second=0, microsecond=0))

    times = _publish_times()
    for day_offset in range(0, 120):
        day = (now + datetime.timedelta(days=day_offset)).date()
        for hh, mm in times:
            cand = datetime.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            if cand <= now or cand in taken:
                continue
            return cand
    raise RuntimeError("no free publish slot in the next 120 days")


def _credits(script):
    """Distinct on-screen source credits from the shot list -> 'via A · via B'."""
    seen, out = set(), []
    for shot in (script.get("shots") or []):
        src = (shot.get("source") or "").strip()
        if src and src.lower() != "general" and src not in seen:
            seen.add(src)
            out.append(f"via {src}")
    return " · ".join(out)


def build_descriptions(script, footage_credit=None):
    """Per-platform caption text (from the script's captions) + a credits line.

    Falls back to the title when a platform caption is missing so we never post
    an empty description. `footage_credit` (e.g. "Pixabay") is appended per that
    provider's attribution request."""
    caps = script.get("captions") or {}
    title = script.get("title") or ""
    credits = _credits(script)
    parts = ([f"Credits: {credits}"] if credits else []) + (
        [f"Footage: {footage_credit}"] if footage_credit else [])
    out = {}
    for p in PLATFORMS:
        text = (caps.get(p) or title).strip()
        if parts:
            text = (text + "\n\n" + "  ·  ".join(parts)).strip()
        out[p] = text
    return out


def match_channels(buffer_channels):
    """Map the brand's configured platforms to Buffer channel ids.

    Prefer a name/handle match against BRAND['channels']; else the first channel
    of that service. Returns [{id, service}] for platforms that resolved."""
    want = BRAND.get("channels", {})
    resolved = []
    for service in PLATFORMS:
        handle = (want.get(service) or "").lower()
        cands = [c for c in buffer_channels if c.get("service") == service]
        if not cands:
            continue
        pick = next(
            (c for c in cands if handle and handle in (c.get("name", "").lower())),
            cands[0],
        )
        resolved.append({"id": pick["id"], "service": service})
    return resolved


def latest_render(project_id, output_dir=None):
    """Newest rendered MP4 basename under output/explainer-<id>/, or None."""
    from explainer.render import job_id_for
    d = os.path.join(output_dir or OUTPUT_DIR, job_id_for(project_id))
    files = sorted(glob.glob(os.path.join(d, "*.mp4")), key=os.path.getmtime)
    return os.path.basename(files[-1]) if files else None


# --- HTTP to the backend's Buffer endpoints (reuses media hosting + BUFFER key) ---

def _get_channels(backend_url=None):
    r = requests.get(f"{(backend_url or BACKEND_URL).rstrip('/')}/api/buffer/channels", timeout=40)
    r.raise_for_status()
    return r.json().get("channels", [])


def _post_buffer(job_id, filename, title, channels, due_iso, backend_url=None):
    body = {
        "job_id": job_id,
        "clip_index": 0,
        "filename": filename,
        "title": title,
        "channels": channels,
        "schedule_iso": due_iso,
        "scheduling": "automatic",
    }
    r = requests.post(f"{(backend_url or BACKEND_URL).rstrip('/')}/api/buffer/post",
                      json=body, timeout=90)
    r.raise_for_status()
    return r.json()


def schedule_project(project_id, s=None, now=None, backend_url=None):
    """Schedule one project's render to all resolved platforms at the next slot.

    Records ScheduleItem + Post rows and flips the project to 'scheduled'. Returns
    a summary dict. Raises if there's no render or no channels resolve."""
    from explainer.render import job_id_for
    own = s is None
    s = s or store.session()
    try:
        proj = s.get(store.Project, project_id)
        if not proj:
            raise ValueError(f"project #{project_id} not found")
        draft = (s.query(store.Draft)
                 .filter(store.Draft.project_id == project_id)
                 .order_by(store.Draft.id.desc()).first())
        if not draft:
            raise ValueError(f"project #{project_id} has no draft")

        filename = latest_render(project_id)
        if not filename:
            raise ValueError(f"project #{project_id} has no render yet")

        # Only live rows hold a slot — cancelled/failed ones free theirs back up.
        taken = [d for (d, st) in s.query(store.ScheduleItem.due_at,
                                          store.ScheduleItem.status).all()
                 if d and st in ("queued", "posted")]
        slot = next_slot(taken, now=now)
        due_iso = slot.isoformat()

        channels = match_channels(_get_channels(backend_url))
        if not channels:
            raise ValueError("no Buffer channels resolved for the brand platforms")

        # Footage attribution (e.g. Pixabay) recorded by the assets stage.
        footage_credit = None
        apath = os.path.join(OUTPUT_DIR, job_id_for(project_id), "assets.json")
        if os.path.isfile(apath):
            try:
                with open(apath, encoding="utf-8") as af:
                    footage_credit = (json.load(af) or {}).get("footage_credit")
            except (ValueError, OSError):
                pass
        descriptions = build_descriptions(draft.script or {}, footage_credit)
        title = (draft.script or {}).get("title") or proj.title
        # Attach per-service text.
        for ch in channels:
            ch["text"] = descriptions.get(ch["service"], title)

        result = _post_buffer(job_id_for(project_id), filename, title, channels,
                              due_iso, backend_url)

        by_service = {r["service"]: r for r in result.get("results", [])}
        for ch in channels:
            res = by_service.get(ch["service"], {})
            s.add(store.ScheduleItem(project_id=project_id, platform=ch["service"],
                                     due_at=slot.astimezone(datetime.timezone.utc).replace(tzinfo=None),
                                     status="queued" if res.get("ok") else "failed",
                                     buffer_post_id=res.get("post_id") or ""))
            if res.get("ok"):
                s.add(store.Post(project_id=project_id, platform=ch["service"],
                                 buffer_post_id=res.get("post_id") or ""))
        proj.status = "scheduled"
        s.commit()
        return {"project_id": project_id, "due_at": due_iso,
                "video_url": result.get("video_url"), "results": result.get("results", [])}
    finally:
        if own:
            s.close()


def _ready_project_ids(s):
    """Projects whose latest draft is approved, not yet scheduled/published, and
    which have a render on disk — the drip candidates, oldest first."""
    ids = []
    projs = (s.query(store.Project)
             .filter(~store.Project.status.in_(["scheduled", "published", "failed"]))
             .order_by(store.Project.created_at.asc()).all())
    for p in projs:
        draft = (s.query(store.Draft)
                 .filter(store.Draft.project_id == p.id)
                 .order_by(store.Draft.id.desc()).first())
        if draft and draft.status == "approved" and latest_render(p.id):
            ids.append(p.id)
    return ids


def tick(now=None, backend_url=None):
    """One scheduler pass: schedule at most one ready project for the next open
    day (enforces 1/day). Returns the summary dict, or None if nothing to do."""
    s = store.session()
    try:
        ready = _ready_project_ids(s)
        if not ready:
            return None
        return schedule_project(ready[0], s=s, now=now, backend_url=backend_url)
    finally:
        s.close()
