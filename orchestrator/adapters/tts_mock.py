"""Mock TTS adapter — generates a short silent WAV.

Used for pipeline testing without a real TTS service. Selected by setting
`TTS_ADAPTER=mock`.
"""
from __future__ import annotations

import io
import struct
import wave

from .base import TTSAdapter


def _silent_wav(duration_s: float = 2.0, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        n = int(duration_s * sample_rate)
        w.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return buf.getvalue()


class MockTTSAdapter:
    name = "mock"

    async def synthesize(
        self,
        text: str,
        voice: str,
        fmt: str = "wav",
        **kwargs,
    ) -> tuple[bytes, str]:
        # Scale duration loosely with text length so downstream FPS math is sane.
        duration = max(1.0, min(30.0, len(text) / 15.0))
        return _silent_wav(duration_s=duration), "audio/wav"

    async def list_voices(self) -> list[dict]:
        return [
            {
                "voice_id": "mock_en",
                "name": "Mock English",
                "model_id": "mock",
                "gender": "neutral",
                "language_code": "en",
                "description": "Silent WAV for testing.",
            },
            {
                "voice_id": "mock_hi",
                "name": "Mock Hindi",
                "model_id": "mock",
                "gender": "neutral",
                "language_code": "hi",
                "description": "Silent WAV for testing.",
            },
        ]
