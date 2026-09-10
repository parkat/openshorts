"""Schedule stage: drip approved explainer renders into the publishing calendar.

The cadence, the platforms, the timezone and the pause switch all live in
`publishing.py` now (defaults from brand.py, overrides from the dashboard), and
so does the Buffer call and the slot arithmetic — this module is left with the
part that is genuinely explainer-specific: finding the newest render for a
project and writing the per-platform captions from its script.

`next_slot` and `match_channels` remain as thin delegates so existing callers and
tests keep working against one implementation rather than a copy of it.
"""
import os
import glob
import json

import store
import publishing

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.getcwd(), "output"))
PLATFORMS = ("youtube", "tiktok", "instagram")


def next_slot(taken_slots, now=None):
    """Next free publish slot in the configured timezone.

    Delegates to `publishing.next_slot` so the explainer lane and the clips lane
    cannot disagree about when the slots are — see publishing.py for why the
    calendar is shared.
    """
    return publishing.next_slot(taken_slots, now=now)


def _credits(script):
    """Distinct on-screen source credits from the shot list -> 'via A · via B'."""
    seen, out = set(), []
    for shot in (script.get("shots") or []):
        src = (shot.get("source") or "").strip()
        if src and src.lower() != "general" and src not in seen:
            seen.add(src)
            out.append(f"via {src}")
    return " · ".join(out)


def build_descriptions(script, footage_credit=None, settings=None):
    """Per-platform caption text (from the script's captions) + a credits line.

    Falls back to the title when a platform caption is missing so we never post
    an empty description. `footage_credit` (e.g. "Pixabay") is appended per that
    provider's attribution request.

    The platform's always-on tags (#shorts / #fyp / #reels) are appended last from
    the publishing settings, the same ones the clips lane uses — the script author
    writes tags about the subject, and the routing tags are not its job."""
    import hashtags as tags_mod
    caps = script.get("captions") or {}
    title = script.get("title") or ""
    credits = _credits(script)
    parts = ([f"Credits: {credits}"] if credits else []) + (
        [f"Footage: {footage_credit}"] if footage_credit else [])
    st = settings if settings is not None else publishing.get_settings()
    tag_cfg = (st.get("hashtags") or {}) if st else {}
    out = {}
    for p in PLATFORMS:
        text = (caps.get(p) or title).strip()
        if parts:
            text = (text + "\n\n" + "  ·  ".join(parts)).strip()
        # compose() skips any tag the caption already contains, so a script that
        # wrote "#shorts" itself does not get it twice.
        out[p] = tags_mod.compose(text, [], p, st) if tag_cfg.get("enabled", True) else text
    return out


def match_channels(buffer_channels):
    """Map the enabled platforms to Buffer channel ids -> [{id, service}]."""
    return [{"id": c["id"], "service": c["service"]}
            for c in publishing.resolve_channels(buffer_channels)]


def latest_render(project_id, output_dir=None):
    """Newest rendered MP4 basename under output/explainer-<id>/, or None."""
    from explainer.render import job_id_for
    d = os.path.join(output_dir or OUTPUT_DIR, job_id_for(project_id))
    files = sorted(glob.glob(os.path.join(d, "*.mp4")), key=os.path.getmtime)
    return os.path.basename(files[-1]) if files else None


def _captions_for(project_id, draft, proj):
    """Per-platform text + title for one project's post."""
    from explainer.render import job_id_for
    footage_credit = None
    apath = os.path.join(OUTPUT_DIR, job_id_for(project_id), "assets.json")
    if os.path.isfile(apath):
        try:
            with open(apath, encoding="utf-8") as af:
                footage_credit = (json.load(af) or {}).get("footage_credit")
        except (ValueError, OSError):
            pass
    script = draft.script or {}
    return (script.get("title") or proj.title,
            build_descriptions(script, footage_credit))


def schedule_project(project_id, s=None, now=None, backend_url=None):
    """Queue one project's newest render to every enabled platform.

    The slot arithmetic, the Buffer call and the ScheduleItem/Post rows all live
    in `publishing.queue` — shared with the clips lane so one calendar governs
    both. What stays here is the explainer-specific part: which file, what text.
    """
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
        title, descriptions = _captions_for(project_id, draft, proj)
    finally:
        if own:
            s.close()

    from explainer.render import job_id_for
    slot = None
    if now is not None:
        cfg = (publishing.get_settings().get("lanes") or {}).get("explainer") or {}
        slot = publishing.next_slot(publishing.live_slots(), now=now,
                                    lane_taken=publishing.live_slots("explainer"),
                                    per_day=cfg.get("per_day"))
    result = publishing.queue("explainer", project_id, job_id_for(project_id),
                              filename, title, text_by_service=descriptions,
                              due=slot, backend_url=backend_url)

    if any(r.get("ok") for r in result.get("results", [])):
        with store.session() as s2:
            p2 = s2.get(store.Project, project_id)
            if p2:
                p2.status = "scheduled"
                s2.commit()
    return {"project_id": project_id, "due_at": result["due_at"],
            "video_url": result.get("video_url"), "results": result.get("results", [])}


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
    """One scheduler pass: queue at most one ready project.

    Returns the summary dict, or None when there is nothing to do — including
    when publishing is paused or this lane's auto-drip is switched off, which is
    checked here so the worker simply idles instead of logging a failure a
    quarter-hour at a time.
    """
    st = publishing.get_settings()
    cfg = (st.get("lanes") or {}).get("explainer") or {}
    if st.get("paused") or not cfg.get("enabled", True) or not cfg.get("auto", True):
        return None
    s = store.session()
    try:
        ready = _ready_project_ids(s)
        if not ready:
            return None
        return schedule_project(ready[0], s=s, now=now, backend_url=backend_url)
    finally:
        s.close()
