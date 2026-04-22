"""Orchestrator FastAPI app.

Public endpoints documented in docs/API_CONTRACT.md §1.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Path as PathParam, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from adapters import AdapterError, build_tts
from config import CONFIG
from jobs import JobStore
from schemas import (
    ErrorResponse,
    JobCreatedResponse,
    JobStatusResponse,
    ModelGroup,
    ModelsResponse,
    VoiceInfo,
    VoicesResponse,
)
from storage import face_path, pick_face_ext, save_bytes
from worker import Worker


logging.basicConfig(
    level=CONFIG.log_level.upper(),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("orchestrator")


_store: JobStore | None = None
_worker: Worker | None = None
_resolved_default_voice: str | None = None


async def _first_available_voice() -> str:
    """Return a default voice id. Cached after the first successful lookup."""
    global _resolved_default_voice
    if _resolved_default_voice:
        return _resolved_default_voice
    tts = build_tts(CONFIG)
    voices = await tts.list_voices()
    if not voices:
        return ""
    _resolved_default_voice = voices[0].get("voice_id", "")
    return _resolved_default_voice


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store, _worker
    CONFIG.ensure_dirs()
    _store = JobStore(CONFIG.job_store_path)
    _worker = Worker(CONFIG, _store)
    log.info(
        "orchestrator ready tts=%s lipsync=%s tts_url=%s musetalk_url=%s max_conc=%d",
        CONFIG.tts_adapter, CONFIG.lipsync_adapter,
        CONFIG.tts_url, CONFIG.musetalk_url, CONFIG.max_concurrent_jobs,
    )
    try:
        yield
    finally:
        log.info("shutting down orchestrator")
        if _worker is not None:
            await _worker.shutdown()
        if _store is not None:
            _store.close()


app = FastAPI(
    title="MuseTalk Orchestrator",
    description="Text + face → lip-synced video job queue.",
    version="1.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _require_store() -> JobStore:
    if _store is None:
        raise HTTPException(503, detail={"error": "not_ready", "detail": "orchestrator starting"})
    return _store


def _require_worker() -> Worker:
    if _worker is None:
        raise HTTPException(503, detail={"error": "not_ready", "detail": "orchestrator starting"})
    return _worker


def _status_response(job) -> JobStatusResponse:
    progress = {"queued": 0, "running": 50 if job.stage == "tts" else 80, "done": 100, "failed": 0}.get(job.status, 0)
    stage = None if job.stage in (None, "") else job.stage
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        stage=stage,
        progress=progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        preview_url=f"/api/v1/jobs/{job.id}/preview",
        download_url=f"/api/v1/jobs/{job.id}/download",
        error=job.error,
    )


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok" if _store is not None and _worker is not None else "starting",
        "tts_adapter": CONFIG.tts_adapter,
        "lipsync_adapter": CONFIG.lipsync_adapter,
    }


@app.post(
    "/api/v1/jobs",
    status_code=201,
    response_model=JobCreatedResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def create_job(
    text: str = Form(...),
    face: UploadFile = File(...),
    voice: Optional[str] = Form(None),
    tts_model: Optional[str] = Form(None),
    lipsync_model: Optional[str] = Form(None),
    params: Optional[str] = Form(None),
):
    store = _require_store()
    worker = _require_worker()

    if not text.strip():
        raise HTTPException(400, detail={"error": "bad_request", "detail": "empty text"})

    voice = (voice or "").strip() or CONFIG.default_voice
    if not voice:
        try:
            voice = await _first_available_voice()
        except AdapterError as e:
            raise HTTPException(502, detail={"error": e.code, "detail": e.detail})
        if not voice:
            raise HTTPException(
                400,
                detail={"error": "no_voice_available",
                        "detail": "Client omitted `voice` and no DEFAULT_VOICE is set "
                                  "and the TTS adapter returned no voices."},
            )

    try:
        ext = pick_face_ext(face)
    except ValueError as e:
        raise HTTPException(400, detail={"error": "bad_request", "detail": str(e)})

    params_obj: Optional[dict] = None
    if params:
        try:
            params_obj = json.loads(params)
            if not isinstance(params_obj, dict):
                raise ValueError("params must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(400, detail={"error": "bad_request", "detail": f"Invalid params JSON: {e}"})

    face_bytes = await face.read()
    if not face_bytes:
        raise HTTPException(400, detail={"error": "bad_request", "detail": "empty face upload"})

    # tts_model / lipsync_model overrides are deferred to Phase 3+. Today we
    # honor them only when they match the active adapter name; otherwise the
    # active adapter is used and the override is recorded for audit.
    job = store.create(
        text=text,
        voice=voice,
        face_path="",  # filled below
        face_ext=ext,
        tts_model=tts_model,
        lipsync_model=lipsync_model,
        params=params_obj,
    )
    fpath = face_path(CONFIG.storage_root, job.id, ext)
    await asyncio.to_thread(save_bytes, fpath, face_bytes)
    store.update(job.id, face_path=str(fpath))
    job = store.get(job.id)  # refresh

    worker.submit(job)
    return JobCreatedResponse(job_id=job.id, status="queued")


@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_job_status(job_id: str = PathParam(...)):
    store = _require_store()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"error": "not_found", "detail": f"no job {job_id}"})
    return _status_response(job)


def _done_file(job) -> FileResponse | None:
    if job.status != "done" or not job.output_path:
        return None
    return job.output_path


@app.get("/api/v1/jobs/{job_id}/preview")
async def job_preview(job_id: str = PathParam(...)):
    store = _require_store()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"error": "not_found", "detail": f"no job {job_id}"})
    if job.status != "done" or not job.output_path:
        raise HTTPException(409, detail={"error": "not_ready", "detail": f"job status={job.status}"})
    return FileResponse(job.output_path, media_type="video/mp4")


@app.get("/api/v1/jobs/{job_id}/download")
async def job_download(job_id: str = PathParam(...)):
    store = _require_store()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"error": "not_found", "detail": f"no job {job_id}"})
    if job.status != "done" or not job.output_path:
        raise HTTPException(409, detail={"error": "not_ready", "detail": f"job status={job.status}"})
    return FileResponse(
        job.output_path,
        media_type="video/mp4",
        filename=f"lipsync_{job_id}.mp4",
    )


@app.get("/api/v1/jobs/{job_id}/audio")
async def job_audio(job_id: str = PathParam(...)):
    store = _require_store()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"error": "not_found", "detail": f"no job {job_id}"})
    if not job.audio_path:
        raise HTTPException(409, detail={"error": "not_ready", "detail": f"job status={job.status}"})
    return FileResponse(
        job.audio_path,
        media_type="audio/wav",
        filename=f"tts_{job_id}.wav",
    )


@app.delete("/api/v1/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str = PathParam(...)):
    from storage import delete_job_files  # local to avoid cycle at import time

    store = _require_store()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"error": "not_found", "detail": f"no job {job_id}"})
    delete_job_files(CONFIG.storage_root, job.id, job.face_ext)
    store.delete(job.id)
    return None


@app.get(
    "/api/v1/voices",
    response_model=VoicesResponse,
    responses={502: {"model": ErrorResponse}},
)
async def list_voices():
    try:
        tts = build_tts(CONFIG)
        voices = await tts.list_voices()
    except AdapterError as e:
        return JSONResponse(status_code=502, content={"error": e.code, "detail": e.detail})
    # Accept voices in the adapter's raw shape; require voice_id + name + language_code.
    cleaned: list[VoiceInfo] = []
    for v in voices:
        try:
            cleaned.append(VoiceInfo(**v))
        except Exception:
            log.warning("dropping malformed voice entry: %r", v)
    return VoicesResponse(voices=cleaned)


@app.get("/api/v1/models", response_model=ModelsResponse)
async def list_models():
    from adapters import LIPSYNC_ADAPTERS, TTS_ADAPTERS

    return ModelsResponse(
        tts=ModelGroup(active=CONFIG.tts_adapter, available=sorted(TTS_ADAPTERS)),
        lipsync=ModelGroup(active=CONFIG.lipsync_adapter, available=sorted(LIPSYNC_ADAPTERS)),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=CONFIG.host,
        port=CONFIG.port,
        reload=False,
        log_level=CONFIG.log_level.lower(),
    )
