"""FastAPI server for VoxCPM TTS — Svara-contract compatible.

Env vars:
  VOXCPM_MODEL_PATH    path to the local VoxCPM2 snapshot (required-ish:
                       defaults to /DATA/USERS/vibesh/models/VoxCPM2).
  VOXCPM_DEVICE        cuda | cpu | mps | auto. Default: cuda.
  VOXCPM_VOICES_FILE   path to voices.yaml. Default: ./voices.yaml.
  VOXCPM_CFG_VALUE     default CFG scale. Default: 2.0.
  VOXCPM_TIMESTEPS     default diffusion steps. Default: 10.
  API_HOST / API_PORT  bind. Defaults 0.0.0.0:8080 (same as Svara).
  LOG_LEVEL            INFO.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="[%(asctime)s] %(levelname)s %(filename)s:%(lineno)d: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Make `engine.*` importable when running as `uvicorn api.server:app` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, Response  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from api.models import (  # noqa: E402
    ErrorResponse,
    OpenAISpeechRequest,
    VoiceInfo,
    VoicesResponse,
)
from engine.audio_codec import SUPPORTED_FORMATS, encode  # noqa: E402
from engine.voice_catalog import VoiceCatalog  # noqa: E402
from engine.voxcpm_engine import VoxCPMEngine  # noqa: E402


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VOXCPM_MODEL_PATH = os.getenv(
    "VOXCPM_MODEL_PATH", "/DATA/USERS/vibesh/models/VoxCPM2"
)
VOXCPM_DEVICE = os.getenv("VOXCPM_DEVICE", "cuda")
VOXCPM_VOICES_FILE = os.getenv(
    "VOXCPM_VOICES_FILE",
    str(Path(__file__).resolve().parent.parent / "voices.yaml"),
)
DEFAULT_CFG = float(os.getenv("VOXCPM_CFG_VALUE", "2.0"))
DEFAULT_TIMESTEPS = int(os.getenv("VOXCPM_TIMESTEPS", "10"))
LOAD_DENOISER = os.getenv("VOXCPM_LOAD_DENOISER", "0").lower() in ("1", "true", "yes")
WARMUP = os.getenv("VOXCPM_WARMUP", "1").lower() in ("1", "true", "yes")


# Globals initialised in lifespan.
engine: Optional[VoxCPMEngine] = None
catalog: Optional[VoiceCatalog] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, catalog

    logger.info("Starting VoxCPM TTS API")
    logger.info("  model_path=%s  device=%s", VOXCPM_MODEL_PATH, VOXCPM_DEVICE)
    logger.info("  voices_file=%s", VOXCPM_VOICES_FILE)

    catalog = VoiceCatalog(VOXCPM_VOICES_FILE)
    logger.info("Loaded %d voices", len(catalog.list()))

    engine = VoxCPMEngine(
        model_path=VOXCPM_MODEL_PATH,
        device=VOXCPM_DEVICE,
        load_denoiser=LOAD_DENOISER,
    )

    if WARMUP:
        try:
            engine.warmup()
        except Exception as e:  # pragma: no cover
            logger.warning("Warmup failed (continuing): %s", e)

    yield
    logger.info("Shutting down VoxCPM TTS API")


app = FastAPI(
    title="VoxCPM TTS API",
    description="Svara-contract-compatible TTS powered by VoxCPM2.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Error shape — match Svara's {"error","detail"} contract.
# ---------------------------------------------------------------------------

def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(error=code, detail=detail).model_dump(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "model_loaded": engine is not None,
        "voices": len(catalog.list()) if catalog else 0,
    }


@app.get("/health")
async def health_alias():
    return await healthz()


@app.get("/v1/voices", response_model=VoicesResponse)
async def list_voices():
    if catalog is None:
        return _err(503, "not_ready", "service still warming up")
    return VoicesResponse(voices=[VoiceInfo(**v.to_public()) for v in catalog.list()])


@app.post("/v1/audio/speech")
async def speech(req: OpenAISpeechRequest):
    if engine is None or catalog is None:
        return _err(503, "not_ready", "service still warming up")

    if req.stream:
        return _err(501, "streaming_unsupported",
                    "stream=true is not implemented in v1")

    fmt = (req.response_format or "wav").lower()
    if fmt not in SUPPORTED_FORMATS:
        return _err(400, "bad_format",
                    f"response_format must be one of {sorted(SUPPORTED_FORMATS)}")

    text = (req.input or "").strip()
    if not text:
        return _err(400, "empty_input", "'input' must be non-empty text")

    voice = catalog.get(req.voice)
    if voice is None:
        return _err(404, "unknown_voice",
                    f"unknown voice '{req.voice}'. See GET /v1/voices.")

    cfg_value = req.cfg_value if req.cfg_value is not None else DEFAULT_CFG
    timesteps = req.inference_timesteps if req.inference_timesteps is not None else DEFAULT_TIMESTEPS

    # Run the (blocking, GPU-bound) synth off the event loop.
    try:
        pcm = await asyncio.to_thread(
            engine.synthesize,
            text,
            reference_wav=voice.reference_wav if voice.mode == "clone" else None,
            prompt_text=voice.prompt_text if voice.mode == "clone" else None,
            design_prompt=voice.design_prompt if voice.mode == "design" else None,
            cfg_value=cfg_value,
            inference_timesteps=timesteps,
        )
    except FileNotFoundError as e:
        return _err(500, "reference_missing", str(e))
    except Exception as e:  # pragma: no cover
        logger.exception("synthesis failed")
        return _err(500, "tts_failed", str(e))

    try:
        audio_bytes, mime = encode(pcm, engine.sample_rate, fmt)
    except Exception as e:  # pragma: no cover
        logger.exception("encoding failed")
        return _err(500, "encode_failed", str(e))

    return Response(content=audio_bytes, media_type=mime)
