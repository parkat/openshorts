"""Lane-neutral publishing: what goes out, where, and when.

Both content lanes finish the same way — an MP4 under `output/<job_id>/` — so
neither of them needs its own scheduler. This module owns the single publishing
calendar and the settings that govern it, and `explainer/schedule.py` and
`clips/publish.py` are reduced to deciding WHICH file to hand over.

Two rules shape the design:

  One calendar.  Slots are exclusive across lanes. An explainer and a clip that
  both want 17:00 on Thursday would otherwise be scheduled independently and land
  on top of each other, which reads to a viewer (and to a ranking algorithm) as a
  double post. `next_slot` therefore takes every live row, not just the caller's.

  Defaults live in brand.py, overrides live in the DB.  `brand.py` is
  version-controlled and reviewable; the settings row holds only what a human has
  since changed from the dashboard. An untouched install behaves exactly like the
  brand file, and changing the cadence does not produce a code diff.

Nothing here reaches Buffer directly: posting goes through the backend's
`/api/buffer/*` endpoints, which own the media-token hosting that Buffer needs to
fetch the video by URL. That keeps one implementation of the tricky part.
"""
import os
import copy
import datetime
from zoneinfo import ZoneInfo

import requests

import store
from explainer.brand import BRAND

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))

SETTINGS_KEY = "publishing"
PLATFORMS = ("youtube", "tiktok", "instagram")
LANES = ("explainer", "clips")
SCHEDULING_MODES = ("automatic", "notification")


def defaults():
    """Settings as the brand file specifies them — the base every override sits on."""
    times = BRAND.get("publish_times") or [BRAND.get("publish_time", "06:00")]
    return {
        # Master hold. Nothing is queued while true — the switch to reach for when
        # something is wrong, because it stops the worker without stopping the box.
        "paused": False,
        "timezone": BRAND.get("timezone", "America/Los_Angeles"),
        "publish_times": [str(t) for t in times],
        "platforms": list(PLATFORMS),
        # automatic = Buffer publishes it; notification = Buffer reminds you to.
        "scheduling": "automatic",
        "channels": dict(BRAND.get("channels", {})),
        "lanes": {
            # `auto` is what the background worker is allowed to do on its own.
            # The explainer lane is a daily drip and has always run unattended;
            # clips arrive in bursts of 5-10 from one source, so its default is
            # hand-queued — you decide which of the batch is worth a slot.
            "explainer": {"enabled": True, "auto": True, "per_day": 1},
            "clips": {"enabled": True, "auto": False, "per_day": 2},
        },
    }


def _merge(base, patch):
    """Recursive dict merge — a patch may name one leaf without resending the rest."""
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _clean_time(t):
    """'7' / '7:5' / '07:05' -> '07:05'. Raises ValueError on anything else."""
    hh, mm = (str(t).strip().split(":") + ["0"])[:2]
    h, m = int(hh), int(mm)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"{t!r} is not a time of day")
    return f"{h:02d}:{m:02d}"


def validate(s):
    """Normalise a settings dict, raising ValueError on anything unusable.

    Runs on save rather than on read: a bad value should be refused at the point
    someone typed it, while it can still be reported back to them, not silently
    tolerated until the worker trips over it at 4am.
    """
    s = copy.deepcopy(s)
    s["paused"] = bool(s.get("paused"))

    try:
        ZoneInfo(s.get("timezone") or "")
    except Exception:
        raise ValueError(f"unknown timezone {s.get('timezone')!r}")

    times = sorted({_clean_time(t) for t in (s.get("publish_times") or [])})
    if not times:
        raise ValueError("at least one publish time is required")
    s["publish_times"] = times

    plats = [p for p in (s.get("platforms") or []) if p in PLATFORMS]
    if not plats:
        raise ValueError("at least one platform is required")
    s["platforms"] = plats

    if s.get("scheduling") not in SCHEDULING_MODES:
        raise ValueError(f"scheduling must be one of {SCHEDULING_MODES}")

    lanes = {}
    for name in LANES:
        cfg = dict((s.get("lanes") or {}).get(name) or {})
        per_day = int(cfg.get("per_day", 1))
        # A lane may not claim more slots per day than the day actually has —
        # silently capping is kinder than scheduling into a slot that cannot exist.
        cfg["per_day"] = max(0, min(per_day, len(times)))
        cfg["enabled"] = bool(cfg.get("enabled", True))
        cfg["auto"] = bool(cfg.get("auto", False))
        lanes[name] = cfg
    s["lanes"] = lanes
    s["channels"] = {k: str(v) for k, v in (s.get("channels") or {}).items()
                     if k in PLATFORMS}
    return s


def get_settings():
    """Brand defaults with any saved overrides applied."""
    with store.session() as s:
        row = s.query(store.Setting).filter(store.Setting.key == SETTINGS_KEY).first()
        saved = dict(row.value or {}) if row else {}
    return _merge(defaults(), saved)


def save_settings(patch):
    """Merge `patch` into the saved settings and return the full validated result."""
    merged = validate(_merge(get_settings(), patch or {}))
    with store.session() as s:
        row = s.query(store.Setting).filter(store.Setting.key == SETTINGS_KEY).first()
        if row is None:
            row = store.Setting(key=SETTINGS_KEY, value={})
            s.add(row)
        row.value = merged
        s.commit()
    return merged


def reset_settings():
    """Drop every override and fall back to brand.py."""
    with store.session() as s:
        row = s.query(store.Setting).filter(store.Setting.key == SETTINGS_KEY).first()
        if row:
            s.delete(row)
            s.commit()
    return get_settings()


# --- the Buffer token -------------------------------------------------------
#
# The token has to live server-side. Publishing is scheduled work done by a
# background worker hours or days after you clicked anything, so a key held only
# in a browser tab — which is where the original lane's Settings field puts it —
# can never drive it.
#
# It is stored under its own settings key, NOT inside the publishing settings
# blob, because that blob is returned wholesale to the dashboard. Keeping the
# secret out of it means no response can leak the token by accident.

TOKEN_KEY = "buffer_token"


def stored_token():
    """The dashboard-supplied token, or '' if none has been saved."""
    with store.session() as s:
        row = s.query(store.Setting).filter(store.Setting.key == TOKEN_KEY).first()
        return ((row.value or {}).get("token") or "") if row else ""


def buffer_key():
    """The token to use: the dashboard override first, then the server .env.

    The override wins so a stale `.env` can be fixed from the UI without an ssh —
    which is exactly the situation this ordering exists for.
    """
    return stored_token() or os.environ.get("BUFFER") or ""


def token_status():
    """Where the token comes from and its last four characters. Never the token."""
    stored = stored_token()
    env = os.environ.get("BUFFER") or ""
    key = stored or env
    return {"has_token": bool(key),
            "source": "settings" if stored else ("env" if env else "none"),
            "hint": f"…{key[-4:]}" if len(key) >= 4 else ""}


def save_token(token):
    """Validate a token against Buffer, then store it. Raises ValueError if it fails.

    Checked before saving, deliberately: storing a token that does not work would
    replace one silent failure with another, and the point of this whole path is
    that a dead token stops being invisible.
    """
    token = (token or "").strip()
    if not token:
        raise ValueError("no token given")
    probe = connection(key=token)
    if not probe["ok"]:
        raise ValueError(probe["error"])
    with store.session() as s:
        row = s.query(store.Setting).filter(store.Setting.key == TOKEN_KEY).first()
        if row is None:
            row = store.Setting(key=TOKEN_KEY, value={})
            s.add(row)
        row.value = {"token": token}
        s.commit()
    return probe


def clear_token():
    """Drop the override and fall back to the server .env."""
    with store.session() as s:
        row = s.query(store.Setting).filter(store.Setting.key == TOKEN_KEY).first()
        if row:
            s.delete(row)
            s.commit()
    return token_status()


# --- Buffer connection ------------------------------------------------------


def connection(key=None):
    """{ok, channels, error} — is the token live, and what can it post to?

    Never raises: a dead token is the normal state to render, not an exception.
    It is the first thing the dashboard shows because every other failure in this
    module looks identical from the outside once the token has expired.
    """
    import buffer_client
    key = key or buffer_key()
    if not key:
        return {"ok": False, "channels": [],
                "error": "No Buffer API key — set BUFFER in the server .env."}
    try:
        channels = buffer_client.list_channels(key)
    except buffer_client.BufferError as e:
        return {"ok": False, "channels": [], "error": str(e)}
    except Exception as e:  # noqa: BLE001 — a status probe must never 500
        return {"ok": False, "channels": [], "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "error": "", "channels": [
        {"id": c.get("id"), "name": c.get("name", ""), "service": c.get("service", ""),
         "type": c.get("type", "")} for c in channels]}


def resolve_channels(buffer_channels, settings=None):
    """Map the enabled platforms to Buffer channel ids -> [{id, service, name}].

    Prefers a handle match from settings["channels"]; falls back to the first
    channel of that service, so an account with one channel per platform needs no
    configuration at all.
    """
    st = settings or get_settings()
    want = st.get("channels") or {}
    resolved = []
    for service in st.get("platforms") or []:
        handle = (want.get(service) or "").lower()
        cands = [c for c in buffer_channels if c.get("service") == service]
        if not cands:
            continue
        pick = next((c for c in cands if handle and handle in (c.get("name") or "").lower()),
                    cands[0])
        resolved.append({"id": pick["id"], "service": service,
                         "name": pick.get("name", "")})
    return resolved


# --- the calendar -----------------------------------------------------------

def _tz(settings=None):
    return ZoneInfo((settings or get_settings()).get("timezone", "America/Los_Angeles"))


def _as_local(dt, tz):
    """A stored due_at -> tz-aware local. Naive values are UTC (that's how they persist)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(tz)


def live_slots(lane=None):
    """Due-times of rows still holding a slot. Cancelled/failed ones free theirs."""
    with store.session() as s:
        q = s.query(store.ScheduleItem.due_at, store.ScheduleItem.status,
                    store.ScheduleItem.lane, store.ScheduleItem.platform)
        rows = q.all()
    out = []
    for due, status, row_lane, _platform in rows:
        if due is None or status not in ("queued", "posted"):
            continue
        if lane and (row_lane or "explainer") != lane:
            continue
        out.append(due)
    return out


def next_slot(taken, now=None, settings=None, lane_taken=None, per_day=None):
    """The next free publish slot, tz-aware, in the configured timezone.

    `taken` is every live due-time across ALL lanes — slots are exclusive, so one
    lane's booking blocks the other's. `lane_taken` + `per_day` add the second
    constraint: how many of a day's slots this one lane may occupy, which is what
    keeps a 10-clip batch from swallowing the whole week in one tick.
    """
    st = settings or get_settings()
    tz = _tz(st)
    now = (now or datetime.datetime.now(tz))
    now = (now.replace(tzinfo=tz) if now.tzinfo is None else now).astimezone(tz)

    booked = {d.replace(second=0, microsecond=0)
              for d in (_as_local(x, tz) for x in (taken or [])) if d}
    mine = [d for d in (_as_local(x, tz) for x in (lane_taken or [])) if d]

    times = [tuple(int(x) for x in t.split(":")) for t in st["publish_times"]]
    for day_offset in range(0, 120):
        day = (now + datetime.timedelta(days=day_offset)).date()
        if per_day is not None:
            if per_day <= 0:
                continue
            if sum(1 for d in mine if d.date() == day) >= per_day:
                continue
        for hh, mm in times:
            cand = datetime.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            if cand <= now or cand in booked:
                continue
            return cand
    raise RuntimeError("no free publish slot in the next 120 days")


def plan_slot(lane, now=None, settings=None):
    """The slot `lane` would get if something were queued right now."""
    st = settings or get_settings()
    cfg = (st.get("lanes") or {}).get(lane) or {}
    return next_slot(live_slots(), now=now, settings=st,
                     lane_taken=live_slots(lane), per_day=cfg.get("per_day"))


# --- posting ----------------------------------------------------------------

def _post_to_buffer(job_id, filename, title, channels, due_iso, backend_url=None):
    body = {"job_id": job_id, "clip_index": 0, "filename": filename,
            "title": title, "channels": channels,
            "schedule_iso": due_iso, "scheduling": (get_settings()
                                                    .get("scheduling", "automatic"))}
    # Send the resolved key explicitly. The backend would otherwise fall back to
    # its own env, so a dashboard-supplied token could report "connected" on the
    # status panel and then post with the stale one.
    headers = {}
    key = buffer_key()
    if key:
        headers["X-Buffer-Key"] = key
    r = requests.post(f"{(backend_url or BACKEND_URL).rstrip('/')}/api/buffer/post",
                      json=body, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()


def queue(lane, ref_id, job_id, filename, title, text_by_service=None,
          due=None, backend_url=None, settings=None, log=print):
    """Queue one finished MP4 to every enabled platform, and record it.

    This is the single door to Buffer for both lanes. Returns a summary dict;
    raises ValueError with a human-readable reason when it cannot proceed, so a
    caller can put that string straight in front of someone.
    """
    st = settings or get_settings()
    if st.get("paused"):
        raise ValueError("publishing is paused — turn it back on in Publishing settings")
    lane_cfg = (st.get("lanes") or {}).get(lane) or {}
    if not lane_cfg.get("enabled", True):
        raise ValueError(f"the {lane} lane is switched off for publishing")

    path = os.path.join(OUTPUT_DIR, job_id, os.path.basename(filename))
    if not os.path.isfile(path):
        raise ValueError(f"no such render: {job_id}/{os.path.basename(filename)}")

    conn = connection()
    if not conn["ok"]:
        raise ValueError(f"Buffer is not connected: {conn['error']}")
    channels = resolve_channels(conn["channels"], st)
    if not channels:
        raise ValueError("no Buffer channel matches the enabled platforms")

    slot = due or next_slot(live_slots(), settings=st, lane_taken=live_slots(lane),
                            per_day=lane_cfg.get("per_day"))
    due_iso = slot.isoformat()

    payload = []
    for ch in channels:
        payload.append({"id": ch["id"], "service": ch["service"],
                        "text": (text_by_service or {}).get(ch["service"]) or title or ""})
    log(f"queueing {lane} #{ref_id} to {len(payload)} channel(s) for {due_iso}")
    result = _post_to_buffer(job_id, os.path.basename(filename), title, payload,
                             due_iso, backend_url)

    by_service = {r["service"]: r for r in result.get("results", [])}
    due_utc = slot.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    with store.session() as s:
        for ch in channels:
            res = by_service.get(ch["service"], {})
            s.add(store.ScheduleItem(project_id=ref_id, lane=lane,
                                     platform=ch["service"], due_at=due_utc,
                                     status="queued" if res.get("ok") else "failed",
                                     buffer_post_id=res.get("post_id") or ""))
            if res.get("ok"):
                s.add(store.Post(project_id=ref_id, lane=lane, platform=ch["service"],
                                 buffer_post_id=res.get("post_id") or ""))
        s.commit()

    for r in result.get("results", []):
        log(f"  {'OK ' if r.get('ok') else 'FAIL'} {r['service']}: "
            f"{r.get('post_id') or r.get('error')}")
    return {"lane": lane, "ref_id": ref_id, "due_at": due_iso,
            "video_url": result.get("video_url"), "results": result.get("results", [])}


# --- queue views ------------------------------------------------------------

def _title_for(lane, ref_id, cache):
    """Human label for a queue row, looked up once per (lane, id)."""
    hit = cache.get((lane, ref_id))
    if hit is not None:
        return hit
    title = ""
    with store.session() as s:
        if lane == "clips":
            row = s.get(store.ClipCandidate, ref_id)
            title = (row.title if row else "") or ""
        else:
            row = s.get(store.Project, ref_id)
            title = (row.title if row else "") or ""
    cache[(lane, ref_id)] = title
    return title


def list_queue(limit_posts=50):
    """The publishing calendar + recent publish log, both lanes, soonest first."""
    cache = {}
    with store.session() as s:
        items = (s.query(store.ScheduleItem)
                 .order_by(store.ScheduleItem.due_at.asc()).all())
        posts = (s.query(store.Post)
                 .order_by(store.Post.posted_at.desc()).limit(limit_posts).all())
        scheduled = [{"id": it.id, "lane": it.lane or "explainer",
                      "ref_id": it.project_id, "platform": it.platform,
                      "status": it.status,
                      "due_at": it.due_at.isoformat() if it.due_at else None,
                      "buffer_post_id": it.buffer_post_id or "",
                      "title": _title_for(it.lane or "explainer", it.project_id, cache)}
                     for it in items]
        log = [{"id": p.id, "lane": p.lane or "explainer", "ref_id": p.project_id,
                "platform": p.platform, "url": p.url or "",
                "buffer_post_id": p.buffer_post_id or "",
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                "title": _title_for(p.lane or "explainer", p.project_id, cache)}
               for p in posts]
    return {"scheduled": scheduled, "posts": log}


def cancel(item_id, log=print):
    """Pull a queued post back out of Buffer and mark the row cancelled.

    The Buffer delete happens FIRST: if it fails we leave the row queued, because
    a row that says "cancelled" while the post is still live in Buffer is the one
    state that would actually publish something behind your back.
    """
    import buffer_client
    with store.session() as s:
        it = s.get(store.ScheduleItem, item_id)
        if not it:
            raise ValueError(f"schedule item #{item_id} not found")
        bpid = (it.buffer_post_id or "").strip()
        if bpid:
            key = buffer_key()
            if not key:
                raise ValueError("no Buffer API key on the server")
            buffer_client.delete_post(key, bpid)
            log(f"removed Buffer post {bpid}")
            for p in s.query(store.Post).filter(store.Post.buffer_post_id == bpid).all():
                s.delete(p)
        it.status = "cancelled"
        s.commit()
    log(f"cancelled schedule item #{item_id}")
    return {"ok": True, "id": item_id, "status": "cancelled"}


def clear_failed(lane=None):
    """Drop `failed` rows so the calendar reflects reality. Returns how many went."""
    with store.session() as s:
        q = s.query(store.ScheduleItem).filter(store.ScheduleItem.status == "failed")
        if lane:
            q = q.filter(store.ScheduleItem.lane == lane)
        rows = q.all()
        n = len(rows)
        for r in rows:
            s.delete(r)
        s.commit()
    return {"cleared": n}


def status():
    """Everything the Publishing dashboard needs in one call."""
    st = get_settings()
    conn = connection()
    q = list_queue(limit_posts=10)
    queued = [r for r in q["scheduled"] if r["status"] == "queued"]
    out = {"settings": st, "connection": conn, "token": token_status(),
           "queued": len(queued),
           "failed": len([r for r in q["scheduled"] if r["status"] == "failed"]),
           "next_due": queued[0]["due_at"] if queued else None,
           "next_slot": {}}
    for lane in LANES:
        try:
            out["next_slot"][lane] = plan_slot(lane, settings=st).isoformat()
        except (RuntimeError, ValueError):
            out["next_slot"][lane] = None
    return out
