"""Env-driven configuration for the orchestrator.

All configuration comes from environment variables so the same image can run
as dev / staging / prod with only docker-compose differences.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v else default


@dataclass
class Config:
    # Service ports / URLs
    host: str = field(default_factory=lambda: os.getenv("ORCHESTRATOR_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("ORCHESTRATOR_PORT", 8000))

    tts_url: str = field(default_factory=lambda: os.getenv("TTS_URL", "http://localhost:8080"))
    musetalk_url: str = field(default_factory=lambda: os.getenv("MUSETALK_URL", "http://localhost:8081"))

    # Active adapter names — must match keys in adapters/__init__.py registries.
    tts_adapter: str = field(default_factory=lambda: os.getenv("TTS_ADAPTER", "voxcpm"))
    lipsync_adapter: str = field(default_factory=lambda: os.getenv("LIPSYNC_ADAPTER", "musetalk"))

    # Voice used when the client omits `voice` on POST /api/v1/jobs. If unset,
    # the orchestrator falls back to the first voice returned by the active
    # TTS adapter.
    default_voice: str = field(default_factory=lambda: os.getenv("DEFAULT_VOICE", ""))

    # Storage
    job_store_path: Path = field(
        default_factory=lambda: Path(os.getenv("JOB_STORE_PATH", "./data/jobs.db"))
    )
    storage_root: Path = field(
        default_factory=lambda: Path(os.getenv("STORAGE_ROOT", "./data/storage"))
    )

    # Worker
    max_concurrent_jobs: int = field(
        default_factory=lambda: _env_int("MAX_CONCURRENT_JOBS", 1)
    )

    # HTTP client timeouts (seconds). TTS is quick; lip-sync can take minutes.
    tts_timeout: float = field(default_factory=lambda: float(os.getenv("TTS_TIMEOUT", "120")))
    lipsync_timeout: float = field(default_factory=lambda: float(os.getenv("LIPSYNC_TIMEOUT", "900")))

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    def ensure_dirs(self) -> None:
        """Create storage dirs if missing. Safe to call multiple times."""
        (self.storage_root / "inputs").mkdir(parents=True, exist_ok=True)
        (self.storage_root / "tts").mkdir(parents=True, exist_ok=True)
        (self.storage_root / "outputs").mkdir(parents=True, exist_ok=True)
        self.job_store_path.parent.mkdir(parents=True, exist_ok=True)


CONFIG = Config()
