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


def _publish_hm():
    hh, mm = (BRAND.get("publish_time", "06:00").split(":") + ["0"])[:2]
    return int(hh), int(mm)


def next_slot(taken_dates, now=None):
    """Next 06:00-LA datetime (tz-aware) whose *date* isn't already taken.

    `taken_dates`: iterable of `date` objects already scheduled. `now`: tz-aware
    datetime (defaults to now in the brand tz) — injectable for tests.
    """
    tz = _tz()
    now = now or datetime.datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    now = now.astimezone(tz)
    hh, mm = _publish_hm()
    taken = set(taken_dates or [])

    cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= now:
        cand += datetime.timedelta(days=1)
    while cand.date() in taken:
        cand += datetime.timedelta(days=1)
    return cand


def _credits(script):
    """Distinct on-screen source credits from the shot list -> 'via A · via B'."""
    seen, out = set(), []
    for shot in (script.get("shots") or []):
        src = (shot.get("source") or "").strip()
        if src and src.lower() != "general" and src not in seen:
            seen.add(src)
            out.append(f"via {src}")
    return " · ".join(out)


def build_descriptions(script):
    """Per-platform caption text (from the script's captions) + a credits line.

    Falls back to the title when a platform caption is missing so we never post
    an empty description."""
    caps = script.get("captions") or {}
    title = script.get("title") or ""
    credits = _credits(script)
    out = {}
    for p in PLATFORMS:
        text = (caps.get(p) or title).strip()
        if credits:
            text = f"{text}\n\nCredits: {credits}".strip()
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

        taken = {d for (d,) in s.query(store.ScheduleItem.due_at).all() if d}
        slot = next_slot({d.date() for d in taken}, now=now)
        due_iso = slot.isoformat()

        channels = match_channels(_get_channels(backend_url))
        if not channels:
            raise ValueError("no Buffer channels resolved for the brand platforms")

        descriptions = build_descriptions(draft.script or {})
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
