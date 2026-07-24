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


# --- topics ------------------------------------------------------------------

class TopicBody(BaseModel):
    title: str
    summary: str = ""
    angle: str = ""
    sources: list = []


class ApproveTopicBody(BaseModel):
    accent_sources: list = []


@router.get("/topics")
def get_topics():
    return {"topics": service.list_topics()}


@router.post("/topics")
def post_topic(body: TopicBody):
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="title required")
    return service.add_topic(body.title, body.summary, body.angle, body.sources)


@router.post("/topics/{topic_id}/approve")
def post_topic_approve(topic_id: int, body: ApproveTopicBody):
    try:
        return service.approve_topic(topic_id, body.accent_sources or None)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- gate 1: edit script + resolve flags -------------------------------------

class ScriptSaveBody(BaseModel):
    script: dict


class ResolveBody(BaseModel):
    kind: str            # 'clip' | 'claim'
    target: dict         # the flag/claim object


@router.put("/drafts/{project_id}/script")
def put_draft_script(project_id: int, body: ScriptSaveBody):
    try:
        return service.save_draft_script(project_id, body.script)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/flags/{project_id}/resolve")
def post_resolve_flag(project_id: int, body: ResolveBody):
    try:
        return service.resolve_flag(project_id, body.kind, body.target)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schedule")
def get_schedule():
    return service.list_schedule()


@router.get("/projects/{project_id}/postkit")
def get_postkit(project_id: int):
    detail = service.project_detail(project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"project #{project_id} not found")
    if not detail.get("post_kit"):
        raise HTTPException(status_code=409, detail="no script yet — run script first")
    return detail["post_kit"]


# --- pipeline stages (job-backed) --------------------------------------------

class ScriptBody(BaseModel):
    topic_id: int
    model: str | None = None


class ProjectBody(BaseModel):
    project_id: int
    model: str | None = None


class FactcheckBody(BaseModel):
    project_id: int
    source_text: str = ""
    model: str | None = None


class AssetsBody(BaseModel):
    project_id: int
    voice: str | None = None
    tone: str | None = None
    speed: float = 1.0
    no_clips: bool = False
    no_visuals: bool = False
    ai_visuals: bool = False
    no_svg: bool = False
    no_music: bool = False


class RenderBody(BaseModel):
    project_id: int
    force: bool = False
    no_wait: bool = False


class ScheduleBody(BaseModel):
    project_id: int | None = None


@router.post("/script")
def post_script(body: ScriptBody):
    return _launch("script", body.topic_id, service.run_script,
                   {"topic_id": body.topic_id, "model": body.model})


@router.post("/clipfind")
def post_clipfind(body: ProjectBody):
    return _launch("clipfind", body.project_id, service.run_clipfind,
                   {"project_id": body.project_id, "model": body.model})


@router.post("/factcheck")
def post_factcheck(body: FactcheckBody):
    return _launch("factcheck", body.project_id, service.run_factcheck,
                   {"project_id": body.project_id, "source_text": body.source_text,
                    "model": body.model})


@router.post("/assets")
def post_assets(body: AssetsBody):
    opts = service.AssetOpts(
        voice=body.voice, tone=body.tone, speed=body.speed,
        no_clips=body.no_clips, no_visuals=body.no_visuals,
        ai_visuals=body.ai_visuals, no_svg=body.no_svg, no_music=body.no_music)
    return _launch("assets", body.project_id, service.run_assets,
                   {"project_id": body.project_id, "opts": opts})


@router.post("/align")
def post_align(body: ProjectBody):
    return _launch("align", body.project_id, service.run_align,
                   {"project_id": body.project_id})


@router.post("/render")
def post_render(body: RenderBody):
    return _launch("render", body.project_id, service.run_render,
                   {"project_id": body.project_id, "force": body.force,
                    "no_wait": body.no_wait})


@router.post("/schedule")
def post_schedule(body: ScheduleBody):
    return _launch("schedule", body.project_id or 0, service.run_schedule,
                   {"project_id": body.project_id})


@router.post("/drafts/{project_id}/approve")
def post_approve(project_id: int):
    try:
        return service.approve_draft(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- content cache -----------------------------------------------------------

@router.get("/cache/stats")
def get_cache_stats():
    """Per-kind counts/bytes/reuses + totals for the cache-size readout."""
    return cache_mod.stats()


@router.get("/cache/items")
def get_cache_items(kind: str | None = None, label: str | None = None,
                    text: str | None = None):
    """Browse cache rows (filter by kind/label/substring), newest first."""
    with store.session() as s:
        rows = cache_mod.find(kind=kind or None, label=label or None,
                              text=text or None, session=s)
        return {"items": [service.cache_item_dict(r) for r in rows]}


@router.delete("/cache/items/{item_id}")
def delete_cache_item(item_id: int):
    if not cache_mod.delete(item_id):
        raise HTTPException(status_code=404, detail="cache item not found")
    return {"ok": True}
