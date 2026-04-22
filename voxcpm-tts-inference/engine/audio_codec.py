"""Encode float32 PCM (numpy) to the formats the Svara contract exposes."""
from __future__ import annotations

import io
import subprocess
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

if TYPE_CHECKING:
    pass


SUPPORTED_FORMATS = {"wav", "pcm", "mp3", "opus", "aac"}

FORMAT_MIME = {
    "wav":  "audio/wav",
    "pcm":  "audio/pcm",
    "mp3":  "audio/mpeg",
    "opus": "audio/opus",
    "aac":  "audio/aac",
}


def encode(pcm: np.ndarray, sample_rate: int, fmt: str) -> tuple[bytes, str]:
    """Return (bytes, mime). `pcm` is float32 mono in [-1, 1]."""
    fmt = fmt.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported response_format: {fmt}")

    # Clip + convert to int16 for everything except native wav (soundfile will
    # handle wav from float32 directly).
    if fmt == "wav":
        buf = io.BytesIO()
        sf.write(buf, pcm, sample_rate, format="WAV", subtype="PCM_16")
        return buf.getvalue(), FORMAT_MIME[fmt]

    pcm16 = _to_int16(pcm)

    if fmt == "pcm":
        return pcm16.tobytes(), FORMAT_MIME[fmt]

    # mp3 / opus / aac via ffmpeg — pipe int16 PCM in, encoded bytes out.
    return _ffmpeg_encode(pcm16.tobytes(), sample_rate, fmt), FORMAT_MIME[fmt]


def _to_int16(pcm: np.ndarray) -> np.ndarray:
    pcm = np.clip(pcm, -1.0, 1.0)
    return (pcm * 32767.0).astype(np.int16)


def _ffmpeg_encode(pcm_bytes: bytes, sample_rate: int, fmt: str) -> bytes:
    out_fmt = {"mp3": "mp3", "opus": "opus", "aac": "adts"}[fmt]
    codec_args = {
        "mp3":  ["-b:a", "128k"],
        "opus": ["-c:a", "libopus", "-b:a", "64k"],
        "aac":  ["-c:a", "aac", "-b:a", "128k"],
    }[fmt]

    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-f", "s16le", "-ar", str(sample_rate), "-ac", "1",
        "-i", "pipe:0",
        *codec_args,
        "-f", out_fmt, "pipe:1",
    ]
    proc = subprocess.run(cmd, input=pcm_bytes, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({fmt}): "
                           f"{proc.stderr.decode(errors='ignore')[:300]}")
    return proc.stdout
