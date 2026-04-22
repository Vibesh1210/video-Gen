"""Adapter registry.

Add a new model:
  1. Implement `TTSAdapter` or `LipSyncAdapter` (see base.py) in a new file
     `tts_<name>.py` or `lipsync_<name>.py`.
  2. Register a factory in `TTS_ADAPTERS` or `LIPSYNC_ADAPTERS` below.
  3. Set `TTS_ADAPTER=<name>` or `LIPSYNC_ADAPTER=<name>` in env.

The factory takes the orchestrator Config so adapters can read URLs/timeouts
from env without importing config directly.
"""
from __future__ import annotations

from typing import Callable

from config import Config

from .base import AdapterError, LipSyncAdapter, TTSAdapter
from .lipsync_mock import MockLipSyncAdapter
from .lipsync_musetalk import MuseTalkLipSyncAdapter
from .tts_mock import MockTTSAdapter
from .tts_svara import SvaraTTSAdapter


TTS_ADAPTERS: dict[str, Callable[[Config], TTSAdapter]] = {
    "svara": lambda cfg: SvaraTTSAdapter(cfg.tts_url, timeout=cfg.tts_timeout),
    "mock":  lambda cfg: MockTTSAdapter(),
}

LIPSYNC_ADAPTERS: dict[str, Callable[[Config], LipSyncAdapter]] = {
    "musetalk": lambda cfg: MuseTalkLipSyncAdapter(cfg.musetalk_url, timeout=cfg.lipsync_timeout),
    "mock":     lambda cfg: MockLipSyncAdapter(),
}


def build_tts(cfg: Config) -> TTSAdapter:
    try:
        return TTS_ADAPTERS[cfg.tts_adapter](cfg)
    except KeyError:
        raise AdapterError(
            "unknown_model",
            f"No TTS adapter '{cfg.tts_adapter}'. Known: {sorted(TTS_ADAPTERS)}",
        )


def build_lipsync(cfg: Config) -> LipSyncAdapter:
    try:
        return LIPSYNC_ADAPTERS[cfg.lipsync_adapter](cfg)
    except KeyError:
        raise AdapterError(
            "unknown_model",
            f"No lip-sync adapter '{cfg.lipsync_adapter}'. Known: {sorted(LIPSYNC_ADAPTERS)}",
        )


__all__ = [
    "AdapterError",
    "TTSAdapter",
    "LipSyncAdapter",
    "TTS_ADAPTERS",
    "LIPSYNC_ADAPTERS",
    "build_tts",
    "build_lipsync",
]
