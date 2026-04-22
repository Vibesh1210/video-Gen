"""MuseTalk lip-sync adapter — thin httpx client.

Target: docs/API_CONTRACT.md §2 (POST /lipsync).
"""
from __future__ import annotations

import json
import mimetypes

import httpx

from .base import AdapterError


class MuseTalkLipSyncAdapter:
    name = "musetalk-v1.5"

    def __init__(self, base_url: str, timeout: float = 900.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def generate(
        self,
        face: bytes,
        face_filename: str,
        audio_wav: bytes,
        params: dict | None = None,
    ) -> bytes:
        face_mime = mimetypes.guess_type(face_filename)[0] or "application/octet-stream"
        files = {
            "face": (face_filename, face, face_mime),
            "audio": ("audio.wav", audio_wav, "audio/wav"),
        }
        data = {}
        if params:
            data["params"] = json.dumps(params)

        url = f"{self._base}/lipsync"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.post(url, files=files, data=data)
            except httpx.HTTPError as e:
                raise AdapterError("lipsync_unreachable", str(e)) from e

        if r.status_code >= 400:
            code, detail = _extract_error(r)
            raise AdapterError(code, detail)

        return r.content


def _extract_error(r: httpx.Response) -> tuple[str, str]:
    try:
        j = r.json()
    except Exception:
        return "lipsync_failed", r.text[:300]
    if isinstance(j, dict):
        if "detail" in j and isinstance(j["detail"], dict):
            d = j["detail"]
            return d.get("error", "lipsync_failed"), d.get("detail", str(d))
        return j.get("error", "lipsync_failed"), j.get("detail", str(j))[:300]
    return "lipsync_failed", str(j)[:300]
