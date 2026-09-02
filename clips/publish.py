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

LANE = "clips"


def caption_for(cand):
    """The text posted alongside the video.

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
        text = caption_for(cand)

    if candidate_id in scheduled_ref_ids():
        raise ValueError(f"candidate #{candidate_id} is already in the queue")

    res = publishing.queue(LANE, candidate_id, job_id_for(candidate_id), filename,
                           title, text_by_service={p: text for p in publishing.PLATFORMS},
                           due=due, log=log)
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
