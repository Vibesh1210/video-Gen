"""Filesystem helpers for per-job inputs/outputs.

Layout under STORAGE_ROOT:
  inputs/{job_id}.{ext}   — uploaded face image or video
  tts/{job_id}.wav        — TTS output
  outputs/{job_id}.mp4    — final lip-synced video
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import UploadFile


ALLOWED_FACE_EXTS = {".jpg", ".jpeg", ".png", ".mp4"}
ALLOWED_FACE_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "video/mp4",
}


def pick_face_ext(upload: UploadFile) -> str:
    """Determine an extension for a face upload. Raises ValueError if unknown."""
    name = (upload.filename or "").lower()
    for ext in ALLOWED_FACE_EXTS:
        if name.endswith(ext):
            return ext if ext != ".jpeg" else ".jpg"

    mime = (upload.content_type or "").lower()
    guessed = mimetypes.guess_extension(mime) if mime else None
    if guessed in ALLOWED_FACE_EXTS:
        return guessed
    if mime == "image/jpeg":
        return ".jpg"
    if mime == "image/png":
        return ".png"
    if mime == "video/mp4":
        return ".mp4"
    raise ValueError(
        f"Unsupported face upload: filename={upload.filename!r} content_type={upload.content_type!r}"
    )


def face_path(storage_root: Path, job_id: str, ext: str) -> Path:
    return storage_root / "inputs" / f"{job_id}{ext}"


def tts_path(storage_root: Path, job_id: str) -> Path:
    return storage_root / "tts" / f"{job_id}.wav"


def output_path(storage_root: Path, job_id: str) -> Path:
    return storage_root / "outputs" / f"{job_id}.mp4"


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def delete_job_files(storage_root: Path, job_id: str, face_ext: str | None) -> None:
    """Best-effort cleanup. Never raises."""
    candidates = [
        tts_path(storage_root, job_id),
        output_path(storage_root, job_id),
    ]
    if face_ext:
        candidates.append(face_path(storage_root, job_id, face_ext))
    else:
        candidates.extend((storage_root / "inputs").glob(f"{job_id}.*"))

    for p in candidates:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
