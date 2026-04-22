"""Request / response schemas — mirror Svara's public contract."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class OpenAISpeechRequest(BaseModel):
    """POST /v1/audio/speech body — Svara/OpenAI-compatible."""
    model: Optional[str] = Field(None, description="Ignored; accepted for OpenAI SDK compat.")
    input: str = Field(..., description="Text to synthesize.")
    voice: str = Field(..., description="voice_id from GET /v1/voices, or a free-form design prompt.")
    response_format: str = Field("wav", description="wav | pcm | mp3 | opus | aac")
    stream: bool = False

    # VoxCPM-specific knobs (optional; clients can pass via extra_body).
    cfg_value: Optional[float] = None
    inference_timesteps: Optional[int] = None


class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    language_code: str
    gender: Optional[str] = None
    mode: Optional[str] = None          # clone | design
    sample_rate: Optional[int] = None


class VoicesResponse(BaseModel):
    voices: list[VoiceInfo]


class ErrorResponse(BaseModel):
    error: str
    detail: str
