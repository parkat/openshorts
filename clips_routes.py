"""clips_routes.py — HTTP surface for the clips lane.

Mounted into the main FastAPI app (`app.py`) with:

    from clips_routes import router as clips_router
    app.include_router(clips_router)

Same shape as `explainer_routes.py`: stage-driving routes run their blocking work
(yt-dlp, ffmpeg, whisper, an LLM call, a render poll) on a dedicated single-slot
executor and return a `{job_id}` the frontend polls; read routes call
`clips/service.py` synchronously.

The executor is separate from the explainer lane's but equally single-slot — two
lanes should not both be driving whisper and the render-service at once on one
box, but neither should a long clips batch block the explainer queue outright.
"""
import os
import sys
import time
import contextlib
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store  # noqa: E402
from clips import service  # noqa: E402

store.init_db()

router = APIRouter(prefix="/api/clips", tags=["clips"])

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")

cl_jobs: dict = {}
cl_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clips")


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
    job = cl_jobs[job_id]
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


def _launch(stage, ref, fn, kwargs):
    job_id = f"clips-{stage}-{ref}-{int(time.time())}"
    cl_jobs[job_id] = {"id": job_id, "ref": ref, "stage": stage,
                       "status": "queued", "progress": 0.0, "logs": [],
                       "result": None, "error": None,
                       "created_at": time.time(), "finished_at": None}
    cl_executor.submit(_run_stage, job_id, fn, kwargs)
    return {"job_id": job_id, "status": "queued"}


def _media_url(path):
    """A path under output/ -> the /videos static mount the dashboard can play."""
    if not path:
        return ""
    rel = os.path.relpath(path, OUTPUT_DIR) if os.path.isabs(path) else path
    rel = rel.replace("\\", "/")
    if rel.startswith("output/"):
        rel = rel[len("output/"):]
    return f"/videos/{rel}"


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = cl_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


# --- read-only views ---------------------------------------------------------

@router.get("/sources")
def get_sources():
    """Every ingested long-form source, newest first."""
    return {"sources": service.list_sources()}


@router.get("/candidates")
def get_candidates(source_id: int = 0, status: str = ""):
    rows = service.list_candidates(source_id=source_id or None, status=status)
    for r in rows:
        r["video_url"] = _media_url(r.get("render_path"))
    return {"candidates": rows}


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: int):
    detail = service.candidate_detail(candidate_id)
    if detail is None:
        raise HTTPException(status_code=404,
                            detail=f"candidate #{candidate_id} not found")
    detail["video_url"] = _media_url(detail.get("render_path"))
    detail["clip_url"] = _media_url(detail.get("clip_path"))
    return detail


# --- stage runners (return {job_id}) -----------------------------------------

class IngestBody(BaseModel):
    url: str


class MomentsBody(BaseModel):
    source_id: int
    limit: int = 0
    model: str = ""


class CutBody(BaseModel):
    candidate_id: int


class RenderBody(BaseModel):
    candidate_id: int
    mood: str = ""


class RunBody(BaseModel):
    url: str
    limit: int = 0
    model: str = ""
    mood: str = ""


@router.post("/ingest")
def post_ingest(body: IngestBody):
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="url required")
    return _launch("ingest", 0, service.run_ingest, {"url": body.url.strip()})


@router.post("/moments")
def post_moments(body: MomentsBody):
    return _launch("moments", body.source_id, service.run_moments,
                   {"source_id": body.source_id, "limit": body.limit,
                    "model": body.model or None})


@router.post("/cut")
def post_cut(body: CutBody):
    return _launch("cut", body.candidate_id, service.run_cut,
                   {"candidate_id": body.candidate_id})


@router.post("/render")
def post_render(body: RenderBody):
    return _launch("render", body.candidate_id, service.run_render,
                   {"candidate_id": body.candidate_id, "mood": body.mood or None})


@router.post("/run")
def post_run(body: RunBody):
    """ingest -> moments -> cut -> render as ONE job (the whole batch)."""
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="url required")
    return _launch("run", 0, service.run_all,
                   {"url": body.url.strip(), "limit": body.limit,
                    "model": body.model or None, "mood": body.mood or None})


# --- direct actions ----------------------------------------------------------

@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(candidate_id: int):
    try:
        return service.set_status(candidate_id, "approved")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: int):
    try:
        return service.set_status(candidate_id, "rejected")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int):
    try:
        return service.delete_candidate(candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/sources/{source_id}")
def delete_source(source_id: int):
    try:
        return service.delete_source(source_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
