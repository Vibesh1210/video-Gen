"""Adapter Protocols — the pluggability boundary.

The orchestrator never imports TTS or lip-sync implementations directly. It
only calls objects conforming to these Protocols. See
docs/API_CONTRACT.md §4 for the contract.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSAdapter(Protocol):
    """Text → audio bytes."""

    name: str  # e.g. "svara-tts-v1", "mock"

    async def synthesize(
        self,
        text: str,
        voice: str,
        fmt: str = "wav",
        **kwargs,
    ) -> tuple[bytes, str]:
        """Return (audio_bytes, mime_type)."""
        ...

    async def list_voices(self) -> list[dict]:
        """Return voices in the shape documented in API_CONTRACT.md §1.6."""
        ...


@runtime_checkable
class LipSyncAdapter(Protocol):
    """(face + audio) → MP4 bytes."""

    name: str  # e.g. "musetalk-v1.5", "mock"

    async def generate(
        self,
        face: bytes,
        face_filename: str,
        audio_wav: bytes,
        params: dict | None = None,
    ) -> bytes:
        """Return the MP4 bytes (audio already muxed in)."""
        ...


class AdapterError(Exception):
    """Raised by adapters on unrecoverable errors. `code` is a short
    machine-readable tag surfaced to the client."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
