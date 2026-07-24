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
import time
import contextlib
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# The repo root (store.py, explainer/) is already importable from app.py's cwd,
# but be defensive if this module is imported standalone.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store  # noqa: E402
from explainer import service  # noqa: E402
from explainer import cache as cache_mod  # noqa: E402

store.init_db()

router = APIRouter(prefix="/api/explainer", tags=["explainer"])


# --- job runner --------------------------------------------------------------
# Stage functions are blocking (OpenRouter HTTP, ffmpeg, whisper, render poll).
# A dedicated single-slot executor runs them off the event loop and serializes
# them (only one heavy stage on the one GPU at a time; also makes the stdout
# sweep safe). State lives in-memory; durable state is in SQLite + output/.
ex_jobs: dict = {}
ex_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="explainer")


class _Tee:
    """File-like that forwards whole lines written to stdout into a job's log."""
    def __init__(self, log):
        self._log = log
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._log(line)
        return len(s)

    def flush(self):
        if self._buf.strip():
            self._log(self._buf.strip())
        self._buf = ""


def _run_stage(job_id, fn, kwargs):
    """Worker-thread entrypoint: run one stage, capturing logs + result."""
    job = ex_jobs[job_id]
    job["status"] = "running"

    def log(msg, pct=None):
        job["logs"].append(str(msg))
        if pct is not None:
            job["progress"] = float(pct)

    try:
        with contextlib.redirect_stdout(_Tee(log)):
            result = fn(log=log, **kwargs)
        job["result"] = result
        job["status"] = "done"
        job["progress"] = 1.0
    except Exception as e:  # noqa: BLE001 — surface any failure as a job error
        job["error"] = str(e)
        job["status"] = "error"
        job["logs"].append(f"error: {e}")
    finally:
        job["finished_at"] = time.time()


def _launch(stage, project_id, fn, kwargs):
    job_id = f"{stage}-{project_id}-{int(time.time())}"
    ex_jobs[job_id] = {"id": job_id, "project_id": project_id, "stage": stage,
                       "status": "queued", "progress": 0.0, "logs": [],
                       "result": None, "error": None,
                       "created_at": time.time(), "finished_at": None}
    ex_executor.submit(_run_stage, job_id, fn, kwargs)
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = ex_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


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


# --- pipeline stages (job-backed) --------------------------------------------

class RenderBody(BaseModel):
    project_id: int
    force: bool = False
    no_wait: bool = False


@router.post("/render")
def post_render(body: RenderBody):
    return _launch("render", body.project_id, service.run_render,
                   {"project_id": body.project_id, "force": body.force,
                    "no_wait": body.no_wait})


# --- content cache -----------------------------------------------------------

@router.get("/cache/stats")
def get_cache_stats():
    """Per-kind counts/bytes/reuses + totals for the cache-size readout."""
    return cache_mod.stats()
