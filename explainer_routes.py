"""explainer_routes.py — HTTP surface for the explainer lane.

Mounted into the main FastAPI app (`app.py`) with:

    from explainer_routes import router as explainer_router
    app.include_router(explainer_router)

All routes sit behind Cloudflare Access like the rest of the dashboard. Stage-
driving routes (script/assets/render/…) run their blocking work on a dedicated
single-slot executor and return a `{job_id}` the frontend polls; read routes call
`explainer/service.py` synchronously (cheap SQLite reads).

Grows one build-step at a time. Step 1 = read-only queue/detail/cache-stats.
"""
import os
import sys

from fastapi import APIRouter, HTTPException

# The repo root (store.py, explainer/) is already importable from app.py's cwd,
# but be defensive if this module is imported standalone.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store  # noqa: E402
from explainer import service  # noqa: E402
from explainer import cache as cache_mod  # noqa: E402

store.init_db()

router = APIRouter(prefix="/api/explainer", tags=["explainer"])


# --- read-only views ---------------------------------------------------------

@router.get("/queue")
def get_queue():
    """All projects, newest-updated first (the queue view)."""
    return {"projects": service.list_queue()}


@router.get("/projects/{project_id}")
def get_project(project_id: int):
    """Full studio detail for one project (project + draft + assets + render +
    flags + post kit)."""
    detail = service.project_detail(project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"project #{project_id} not found")
    return detail


@router.get("/projects/{project_id}/postkit")
def get_postkit(project_id: int):
    detail = service.project_detail(project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"project #{project_id} not found")
    if not detail.get("post_kit"):
        raise HTTPException(status_code=409, detail="no script yet — run script first")
    return detail["post_kit"]


# --- content cache -----------------------------------------------------------

@router.get("/cache/stats")
def get_cache_stats():
    """Per-kind counts/bytes/reuses + totals for the cache-size readout."""
    return cache_mod.stats()
