from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LipSyncParams(BaseModel):
    """Per-request knobs for MuseTalk inference.

    Mirrors the CLI flags of MuseTalk/scripts/inference.py. All fields are
    optional — omitted keys fall back to the server default.
    """

    bbox_shift: int = 0
    extra_margin: int = 10
    parsing_mode: str = "jaw"
    fps: int = 25
    version: Literal["v1", "v15"] = "v15"
    left_cheek_width: int = 90
    right_cheek_width: int = 90
    batch_size: int = Field(default=8, ge=1, le=64)
    use_float16: bool = True
    audio_padding_length_left: int = 2
    audio_padding_length_right: int = 2


class LipSyncError(BaseModel):
    error: str
    detail: str
