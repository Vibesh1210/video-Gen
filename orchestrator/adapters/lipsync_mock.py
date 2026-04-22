"""Mock lip-sync adapter — produces a tiny valid MP4.

Uses ffmpeg (already installed for MuseTalk) to mux the supplied face and
audio into a stub video. If ffmpeg is unavailable, returns a minimal MP4
header stub (enough to exercise the pipeline, not playable).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import AdapterError, LipSyncAdapter


_FFMPEG = shutil.which("ffmpeg")


class MockLipSyncAdapter:
    name = "mock"

    async def generate(
        self,
        face: bytes,
        face_filename: str,
        audio_wav: bytes,
        params: dict | None = None,
    ) -> bytes:
        if _FFMPEG is None:
            # Minimal fake MP4. Not playable, but enough bytes to prove the
            # pipeline ferries data end-to-end.
            return b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 512

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            face_path = td / face_filename
            audio_path = td / "audio.wav"
            out_path = td / "out.mp4"
            face_path.write_bytes(face)
            audio_path.write_bytes(audio_wav)

            ext = face_path.suffix.lower()
            if ext in {".jpg", ".jpeg", ".png"}:
                cmd = [
                    _FFMPEG, "-y",
                    "-loop", "1", "-i", str(face_path),
                    "-i", str(audio_path),
                    "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest",
                    str(out_path),
                ]
            else:
                cmd = [
                    _FFMPEG, "-y",
                    "-i", str(face_path),
                    "-i", str(audio_path),
                    "-c:v", "copy", "-c:a", "aac", "-shortest",
                    "-map", "0:v:0", "-map", "1:a:0",
                    str(out_path),
                ]

            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0 or not out_path.exists():
                raise AdapterError(
                    "mock_ffmpeg_failed",
                    proc.stderr.decode(errors="ignore")[-500:],
                )
            return out_path.read_bytes()
