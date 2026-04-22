"""SQLite-backed job store.

One table, one row per job. All access is synchronous — SQLite writes are
microseconds; the orchestrator will wrap calls in `asyncio.to_thread` if it
matters. A single connection is reused per-process (SQLite is thread-safe
when `check_same_thread=False` and we serialize with a lock).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id            TEXT PRIMARY KEY,
  status        TEXT NOT NULL,
  stage         TEXT,
  text          TEXT NOT NULL,
  voice         TEXT NOT NULL,
  face_path     TEXT NOT NULL,
  face_ext      TEXT NOT NULL,
  audio_path    TEXT,
  output_path   TEXT,
  tts_model     TEXT,
  lipsync_model TEXT,
  params_json   TEXT,
  error         TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Job:
    id: str
    status: str
    stage: Optional[str]
    text: str
    voice: str
    face_path: str
    face_ext: str
    audio_path: Optional[str]
    output_path: Optional[str]
    tts_model: Optional[str]
    lipsync_model: Optional[str]
    params_json: Optional[str]
    error: Optional[str]
    created_at: str
    updated_at: str

    @property
    def params(self) -> dict:
        if not self.params_json:
            return {}
        try:
            return json.loads(self.params_json)
        except json.JSONDecodeError:
            return {}


class JobStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------- writes --------

    def create(
        self,
        *,
        text: str,
        voice: str,
        face_path: str,
        face_ext: str,
        tts_model: Optional[str],
        lipsync_model: Optional[str],
        params: Optional[dict],
    ) -> Job:
        job_id = str(uuid.uuid4())
        now = _now()
        params_json = json.dumps(params) if params else None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (id, status, stage, text, voice, face_path, face_ext,
                                  audio_path, output_path, tts_model, lipsync_model,
                                  params_json, error, created_at, updated_at)
                VALUES (?, 'queued', NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, NULL, ?, ?)
                """,
                (job_id, text, voice, face_path, face_ext,
                 tts_model, lipsync_model, params_json, now, now),
            )
            self._conn.commit()
        return self.get(job_id)  # type: ignore[return-value]

    def update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [job_id]
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", values)
            self._conn.commit()

    def delete(self, job_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # -------- reads --------

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _row_to_job(row) if row else None

    def list_queued_and_running(self) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status IN ('queued', 'running') ORDER BY created_at"
            ).fetchall()
        return [_row_to_job(r) for r in rows]


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(**{k: row[k] for k in row.keys()})
