"""Pydantic schemas for the orchestrator's public API.

These mirror the shapes documented in docs/API_CONTRACT.md §1.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


JobStatus = Literal["queued", "running", "done", "failed"]
JobStage = Literal["tts", "lipsync", "done"]


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus = "queued"


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    stage: Optional[JobStage] = None
    progress: int = 0
    created_at: datetime
    updated_at: datetime
    preview_url: str
    download_url: str
    error: Optional[str] = None


class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    model_id: Optional[str] = None
    gender: Optional[str] = None
    language_code: Optional[str] = None
    description: Optional[str] = None


class VoicesResponse(BaseModel):
    voices: list[VoiceInfo]


class ModelGroup(BaseModel):
    active: str
    available: list[str]


class ModelsResponse(BaseModel):
    tts: ModelGroup
    lipsync: ModelGroup


class ErrorResponse(BaseModel):
    error: str
    detail: str
