"""Publish stage: an approved clip -> the Buffer queue.

Thin by design. `publishing.py` owns the calendar, the settings and the Buffer
call; this module only answers the two questions that are specific to the clips
lane — which candidates are ready, and what text goes out with them.

Readiness is deliberately narrow: approved, rendered, and not already holding a
slot. Approval is the human gate, so nothing reaches Buffer that someone has not
watched, and the already-queued check means a re-run of the drip cannot post the
same clip twice.
"""
import os

import store
import publishing
import hashtags as tags_mod

LANE = "clips"


def caption_body(cand):
    """The prose half of the caption, before any hashtags.

    A hand-written caption wins; otherwise the publish title, with the on-screen
    hook appended when it says something the title does not. The hook is the line
    written to stop a scroll, so it is usually the better first sentence — but
    repeating the title verbatim reads like a bug, hence the containment check.
    """
    hand = (cand.caption or "").strip()
    if hand:
        return hand
    title = (cand.title or "").strip()
    hook = (cand.hook or "").strip()
    if hook and hook.lower() not in title.lower():
        return f"{hook}\n\n{title}" if title else hook
    return title


def captions_for(cand, settings=None):
    """{platform: final caption} — body, this clip's tags, then the platform's.

    Composed at post time rather than stored, so editing your default tags in the
    Publishing tab changes every future post without rewriting anything.
    """
    st = settings or publishing.get_settings()
    body = caption_body(cand)
    if not (st.get("hashtags") or {}).get("enabled", True):
        return {p: body for p in publishing.PLATFORMS}
    content = list(cand.hashtags or [])
    return {p: tags_mod.compose(body, content, p, st) for p in publishing.PLATFORMS}


def caption_for(cand, platform="youtube", settings=None):
    """One platform's finished caption."""
    return captions_for(cand, settings).get(platform, caption_body(cand))


def captions_for_id(candidate_id, settings=None):
    """{platform: caption} for a stored candidate — what would actually be posted."""
    with store.session() as s:
        cand = s.get(store.ClipCandidate, candidate_id)
        if not cand:
            raise ValueError(f"candidate #{candidate_id} not found")
        return captions_for(cand, settings)


def generate_hashtags(candidate_id, count=None, model=None, log=print):
    """Write this clip's content tags from what it is about, and store them.

    Only the content tags are generated. The platform tags are appended from
    settings at post time, so a model is never asked to rediscover "#shorts".
    """
    st = publishing.get_settings()
    n = count or (st.get("hashtags") or {}).get("count") or tags_mod.DEFAULT_COUNT
    with store.session() as s:
        cand = s.get(store.ClipCandidate, candidate_id)
        if not cand:
            raise ValueError(f"candidate #{candidate_id} not found")
        title, hook, quote = cand.title or "", cand.hook or "", cand.quote or ""
    log(f"writing hashtags for #{candidate_id} …")
    tags, error = tags_mod.generate(title=title, hook=hook, quote=quote, count=n,
                                    model=model, log=log)
    # Only overwrite on success. A failed call must not wipe tags you already had.
    if tags:
        with store.session() as s:
            s.get(store.ClipCandidate, candidate_id).hashtags = tags
            s.commit()
    return {"candidate_id": candidate_id, "hashtags": tags, "error": error,
            "captions": captions_for_id(candidate_id, st)}


def _render_filename(cand):
    """Basename of the render, or '' — the file the queue will hand to Buffer."""
    return os.path.basename(cand.render_path) if cand.render_path else ""


def scheduled_ref_ids():
    """Candidate ids that already hold (or held) a live slot."""
    with store.session() as s:
        rows = s.query(store.ScheduleItem.project_id, store.ScheduleItem.lane,
                       store.ScheduleItem.status).all()
    return {rid for rid, lane, status in rows
            if (lane or "explainer") == LANE and status in ("queued", "posted")}


def ready_candidate_ids():
    """Approved + rendered + unqueued candidate ids, oldest first."""
    taken = scheduled_ref_ids()
    with store.session() as s:
        rows = (s.query(store.ClipCandidate)
                .filter(store.ClipCandidate.status == "approved")
                .order_by(store.ClipCandidate.id.asc()).all())
        return [c.id for c in rows
                if c.id not in taken and c.render_path
                and os.path.isfile(c.render_path)]


def publish_candidate(candidate_id, due=None, log=print):
    """Queue one approved candidate to every enabled platform."""
    from clips.render import job_id_for
    with store.session() as s:
        cand = s.get(store.ClipCandidate, candidate_id)
        if not cand:
            raise ValueError(f"candidate #{candidate_id} not found")
        if cand.status not in ("approved", "rendered"):
            raise ValueError(f"candidate #{candidate_id} is {cand.status} — "
                             "render and approve it first")
        filename = _render_filename(cand)
        if not filename:
            raise ValueError(f"candidate #{candidate_id} has no render")
        title = (cand.title or "").strip() or f"Clip #{candidate_id}"
        texts = captions_for(cand)

    if candidate_id in scheduled_ref_ids():
        raise ValueError(f"candidate #{candidate_id} is already in the queue")

    res = publishing.queue(LANE, candidate_id, job_id_for(candidate_id), filename,
                           title, text_by_service=texts, due=due, log=log)
    if any(r.get("ok") for r in res.get("results", [])):
        with store.session() as s:
            cand = s.get(store.ClipCandidate, candidate_id)
            cand.status = "scheduled"
            s.commit()
    return res


def tick(log=print):
    """One drip pass for this lane: queue at most one ready clip.

    Returns the queue summary, or None when there is nothing to do — including
    when auto-publishing is off, which is the default for clips. A batch of ten
    from one source is meant to be released deliberately, not emptied into the
    calendar the moment it renders.
    """
    st = publishing.get_settings()
    cfg = (st.get("lanes") or {}).get(LANE) or {}
    if st.get("paused") or not cfg.get("enabled", True) or not cfg.get("auto"):
        return None
    ready = ready_candidate_ids()
    if not ready:
        return None
    return publish_candidate(ready[0], log=log)
