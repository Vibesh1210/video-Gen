"""FastAPI wrapper for MuseTalk.

Endpoints:
  POST /lipsync     multipart(face, audio, params?) -> video/mp4
  GET  /healthz     liveness + model info

Contract lives in /home/vibesh/museTalk/docs/API_CONTRACT.md §2.
"""
from __future__ import annotations

# --- Import shim -- must run before transformers / diffusers ---------------- #
# The host machine has a flash_attn / PEFT install in /TOOLS that is ABI-
# incompatible with the torch we ship. Block these modules at import time so
# transformers falls back to its pure-torch path.
import importlib.util as _iu
import sys as _sys

_BLOCKED = ("flash_attn", "peft")
_orig_find_spec = _iu.find_spec

def _patched_find_spec(name, package=None):
    if name in _BLOCKED or any(name.startswith(p + ".") for p in _BLOCKED):
        return None
    return _orig_find_spec(name, package)

_iu.find_spec = _patched_find_spec
for _m in _BLOCKED:
    _sys.modules[_m] = None
# --- End shim --------------------------------------------------------------- #

import asyncio
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from inference_core import (
    BadInput,
    EngineConfig,
    InferenceParams,
    LipSyncError,
    MuseTalkEngine,
    NoFaceDetected,
)
from schemas import LipSyncParams


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("musetalk-api")


def _engine_config_from_env() -> EngineConfig:
    cfg = EngineConfig()
    if v := os.getenv("MUSETALK_GPU_ID"):
        cfg.gpu_id = int(v)
    if v := os.getenv("MUSETALK_USE_FLOAT16"):
        cfg.use_float16 = v.lower() in {"1", "true", "yes"}
    if v := os.getenv("MUSETALK_VERSION"):
        cfg.version = v
    if v := os.getenv("MUSETALK_UNET_MODEL"):
        cfg.unet_model_path = v
    if v := os.getenv("MUSETALK_UNET_CONFIG"):
        cfg.unet_config = v
    if v := os.getenv("MUSETALK_WHISPER_DIR"):
        cfg.whisper_dir = v
    return cfg


_engine: MuseTalkEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    cfg = _engine_config_from_env()
    log.info(
        "Loading MuseTalk models: version=%s device=cuda:%s fp16=%s",
        cfg.version, cfg.gpu_id, cfg.use_float16,
    )
    _engine = await asyncio.to_thread(MuseTalkEngine, cfg)
    log.info("MuseTalk ready: %s", _engine.health())
    yield
    log.info("Shutting down MuseTalk API")


app = FastAPI(
    title="MuseTalk API",
    description="Lip-sync video generation (face + audio → MP4).",
    version="1.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #

@app.get("/healthz")
async def healthz():
    if _engine is None:
        raise HTTPException(503, detail={"error": "not_ready", "detail": "engine still loading"})
    return _engine.health()


def _parse_params(raw: Optional[str]) -> InferenceParams:
    if not raw:
        return InferenceParams()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            400,
            detail={"error": "bad_input", "detail": f"Invalid `params` JSON: {e}"},
        )
    try:
        validated = LipSyncParams(**parsed)
    except Exception as e:
        raise HTTPException(
            400, detail={"error": "bad_input", "detail": str(e)}
        )
    # Pydantic → dataclass. Only copy overlapping fields.
    d = validated.model_dump()
    allowed = {f for f in InferenceParams.__dataclass_fields__.keys()}
    return InferenceParams(**{k: v for k, v in d.items() if k in allowed})


@app.post("/lipsync")
async def lipsync(
    face: UploadFile = File(...),
    audio: UploadFile = File(...),
    params: Optional[str] = Form(None),
):
    if _engine is None:
        raise HTTPException(
            503, detail={"error": "not_ready", "detail": "engine still loading"}
        )

    inference_params = _parse_params(params)

    face_bytes = await face.read()
    audio_bytes = await audio.read()
    if not face_bytes:
        raise HTTPException(400, detail={"error": "bad_input", "detail": "empty face upload"})
    if not audio_bytes:
        raise HTTPException(400, detail={"error": "bad_input", "detail": "empty audio upload"})

    face_filename = face.filename or "face.bin"

    try:
        mp4 = await asyncio.to_thread(
            _engine.generate,
            face_bytes,
            face_filename,
            audio_bytes,
            inference_params,
        )
    except NoFaceDetected as e:
        return JSONResponse(
            status_code=422,
            content={"error": e.code, "detail": e.detail},
        )
    except BadInput as e:
        return JSONResponse(
            status_code=400,
            content={"error": e.code, "detail": e.detail},
        )
    except LipSyncError as e:
        log.exception("lipsync failed")
        return JSONResponse(
            status_code=422,
            content={"error": e.code, "detail": e.detail},
        )
    except Exception as e:
        log.exception("unexpected error")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(e)},
        )

    return StreamingResponse(
        io.BytesIO(mp4),
        media_type="video/mp4",
        headers={"Content-Length": str(len(mp4))},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=os.getenv("MUSETALK_HOST", "0.0.0.0"),
        port=int(os.getenv("MUSETALK_PORT", "8081")),
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
