"""Svara TTS adapter — thin httpx client.

Target: docs/API_CONTRACT.md §3 (POST /v1/audio/speech, GET /v1/voices).
"""
from __future__ import annotations

import httpx

from .base import AdapterError


_FMT_TO_MIME = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "pcm": "audio/pcm",
}


class SvaraTTSAdapter:
    name = "svara-tts-v1"

    def __init__(self, base_url: str, timeout: float = 120.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def synthesize(
        self,
        text: str,
        voice: str,
        fmt: str = "wav",
        **kwargs,
    ) -> tuple[bytes, str]:
        payload = {
            "model": kwargs.pop("model", self.name),
            "input": text,
            "voice": voice,
            "response_format": fmt,
            "stream": False,
        }
        # Pass-through any extra knobs the client sent (temperature, top_p, …).
        payload.update(kwargs)

        url = f"{self._base}/v1/audio/speech"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.post(url, json=payload)
            except httpx.HTTPError as e:
                raise AdapterError("tts_unreachable", str(e)) from e

        if r.status_code >= 400:
            detail = _extract_detail(r)
            code = "unknown_voice" if r.status_code == 404 else "tts_failed"
            raise AdapterError(code, detail)

        mime = r.headers.get("content-type", _FMT_TO_MIME.get(fmt, "application/octet-stream"))
        return r.content, mime.split(";")[0].strip()

    async def list_voices(self) -> list[dict]:
        url = f"{self._base}/v1/voices"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.get(url)
            except httpx.HTTPError as e:
                raise AdapterError("tts_unreachable", str(e)) from e

        if r.status_code >= 400:
            raise AdapterError("tts_failed", _extract_detail(r))

        data = r.json()
        return data.get("voices", data if isinstance(data, list) else [])


def _extract_detail(r: httpx.Response) -> str:
    try:
        j = r.json()
        if isinstance(j, dict):
            return j.get("detail") or j.get("error") or r.text[:300]
    except Exception:
        pass
    return r.text[:300]
