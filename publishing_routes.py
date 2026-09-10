"""publishing_routes.py — HTTP surface for the publishing calendar.

Mounted into the main FastAPI app (`app.py`) with:

    from publishing_routes import router as publishing_router
    app.include_router(publishing_router)

Every route is synchronous. Nothing here is long-running — the slowest call is a
handful of Buffer requests — and the caller needs the failure text (an expired
token, a paused calendar, no matching channel) rather than a job id to poll: a
publishing action that quietly went to a log would be exactly the wrong shape.
"""
import os
import sys

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store  # noqa: E402
import publishing  # noqa: E402

store.init_db()

router = APIRouter(prefix="/api/publishing", tags=["publishing"])


@router.get("/status")
def get_status():
    """Connection + settings + queue counts + the next slot each lane would get."""
    return publishing.status()


@router.get("/settings")
def get_settings():
    return {"settings": publishing.get_settings(),
            "defaults": publishing.defaults(),
            "platforms": list(publishing.PLATFORMS),
            "lanes": list(publishing.LANES),
            "scheduling_modes": list(publishing.SCHEDULING_MODES)}


class SettingsPatch(BaseModel):
    paused: bool | None = None
    timezone: str | None = None
    publish_times: list[str] | None = None
    platforms: list[str] | None = None
    scheduling: str | None = None
    channels: dict | None = None
    lanes: dict | None = None
    hashtags: dict | None = None


@router.put("/settings")
def put_settings(body: SettingsPatch):
    """Merge a partial update into the saved settings and return the result."""
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return {"settings": publishing.save_settings(patch)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/settings/reset")
def reset_settings():
    """Drop every override and go back to what brand.py specifies."""
    return {"settings": publishing.reset_settings()}


@router.get("/connection")
def get_connection(api_key: str = Header(None, alias="X-Buffer-Key")):
    """Probe a Buffer token and list what it can post to.

    An `X-Buffer-Key` header tests THAT key without storing it, which is what the
    dashboard's Test button uses — you find out whether a token works before it
    replaces one that might still be good.
    """
    out = publishing.connection(key=(api_key or None))
    out["token"] = publishing.token_status()
    return out


class TokenBody(BaseModel):
    token: str


@router.post("/token")
def set_token(body: TokenBody):
    """Store a Buffer token server-side, after checking that it actually works.

    Server-side is the only place it can live usefully: the drip runs in a
    background worker, so a token held in browser storage could never publish
    anything on a schedule.
    """
    try:
        conn = publishing.save_token(body.token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "connection": conn, "token": publishing.token_status()}


@router.delete("/token")
def delete_token():
    """Drop the stored token and fall back to the server's .env."""
    return {"ok": True, "token": publishing.clear_token(),
            "connection": publishing.connection()}


@router.get("/queue")
def get_queue():
    """The whole calendar, both lanes, soonest first, plus the publish log."""
    return publishing.list_queue()


@router.delete("/queue/{item_id}")
def cancel_item(item_id: int):
    """Pull one queued post back out of Buffer."""
    try:
        return publishing.cancel(item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — Buffer refused the delete
        raise HTTPException(status_code=502, detail=f"Buffer: {e}")


class ClearBody(BaseModel):
    lane: str | None = None


@router.post("/queue/clear-failed")
def clear_failed(body: ClearBody):
    """Drop failed rows so the calendar reflects reality."""
    return publishing.clear_failed(body.lane)


class PublishBody(BaseModel):
    lane: str
    ref_id: int
    due_at: str | None = None


@router.post("/publish")
def publish_now(body: PublishBody):
    """Queue one item by lane + id — the manual counterpart to the auto drip."""
    import datetime
    due = None
    if body.due_at:
        try:
            due = datetime.datetime.fromisoformat(body.due_at)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"bad due_at: {body.due_at}")
    try:
        if body.lane == "clips":
            from clips import publish as clips_publish
            return clips_publish.publish_candidate(body.ref_id, due=due)
        if body.lane == "explainer":
            from explainer import schedule as sch
            return sch.schedule_project(body.ref_id)
        raise HTTPException(status_code=400, detail=f"unknown lane {body.lane!r}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ready")
def ready():
    """What each lane is holding that could be queued right now."""
    out = {}
    try:
        from clips import publish as clips_publish
        from clips import service as clips_service
        ids = set(clips_publish.ready_candidate_ids())
        out["clips"] = [{"ref_id": r["id"], "title": r["title"],
                         "score": r.get("score", 0)}
                        for r in clips_service.list_candidates() if r["id"] in ids]
    except Exception as e:  # noqa: BLE001 — one lane's failure must not blank the view
        out["clips"] = []
        out["clips_error"] = str(e)
    try:
        from explainer import schedule as sch
        with store.session() as s:
            ids = sch._ready_project_ids(s)
            out["explainer"] = [{"ref_id": pid,
                                 "title": (s.get(store.Project, pid).title
                                           if s.get(store.Project, pid) else "")}
                                for pid in ids]
    except Exception as e:  # noqa: BLE001
        out["explainer"] = []
        out["explainer_error"] = str(e)
    return out
