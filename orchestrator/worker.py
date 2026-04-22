"""Async job runner.

One coroutine per job. Concurrency is bounded by an asyncio.Semaphore so the
GPU isn't flooded when requests arrive in bursts.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from adapters import AdapterError, build_lipsync, build_tts
from config import Config
from jobs import Job, JobStore
from storage import output_path, save_bytes, tts_path


log = logging.getLogger("orchestrator.worker")


class Worker:
    def __init__(self, cfg: Config, store: JobStore):
        self._cfg = cfg
        self._store = store
        self._sem = asyncio.Semaphore(cfg.max_concurrent_jobs)
        self._tasks: set[asyncio.Task] = set()

    def submit(self, job: Job) -> None:
        task = asyncio.create_task(self._run(job.id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        """Wait for in-flight jobs to finish, or cancel after grace."""
        if not self._tasks:
            return
        log.info("Waiting on %d in-flight job(s)…", len(self._tasks))
        try:
            await asyncio.wait_for(asyncio.gather(*self._tasks, return_exceptions=True), timeout=5)
        except asyncio.TimeoutError:
            log.warning("Shutdown grace expired; cancelling jobs")
            for t in self._tasks:
                t.cancel()

    async def _run(self, job_id: str) -> None:
        async with self._sem:
            job = self._store.get(job_id)
            if job is None:
                log.error("job %s vanished before start", job_id)
                return
            await self._run_stages(job)

    async def _run_stages(self, job: Job) -> None:
        cfg = self._cfg
        log.info("job %s start text=%r voice=%r", job.id, job.text[:60], job.voice)

        try:
            tts = build_tts(cfg)
            lipsync = build_lipsync(cfg)
        except AdapterError as e:
            self._fail(job.id, e.code, e.detail)
            return

        self._store.update(job.id, status="running", stage="tts",
                           tts_model=tts.name, lipsync_model=lipsync.name)

        # --- TTS ------------------------------------------------------------
        try:
            audio_bytes, _mime = await tts.synthesize(job.text, job.voice, "wav")
        except AdapterError as e:
            log.warning("job %s tts failed: %s", job.id, e)
            self._fail(job.id, e.code, e.detail)
            return
        except Exception as e:
            log.exception("job %s tts crashed", job.id)
            self._fail(job.id, "tts_failed", str(e))
            return

        wav_path = tts_path(cfg.storage_root, job.id)
        await asyncio.to_thread(save_bytes, wav_path, audio_bytes)
        self._store.update(job.id, audio_path=str(wav_path), stage="lipsync")

        # --- Lip-sync -------------------------------------------------------
        face_bytes = await asyncio.to_thread(Path(job.face_path).read_bytes)
        face_filename = f"face{job.face_ext}"

        try:
            mp4 = await lipsync.generate(face_bytes, face_filename, audio_bytes, job.params)
        except AdapterError as e:
            log.warning("job %s lipsync failed: %s", job.id, e)
            self._fail(job.id, e.code, e.detail)
            return
        except Exception as e:
            log.exception("job %s lipsync crashed", job.id)
            self._fail(job.id, "lipsync_failed", str(e))
            return

        out_path = output_path(cfg.storage_root, job.id)
        await asyncio.to_thread(save_bytes, out_path, mp4)
        self._store.update(job.id, output_path=str(out_path), stage="done",
                           status="done", error=None)
        log.info("job %s done out=%s (%d bytes)", job.id, out_path, out_path.stat().st_size)

    def _fail(self, job_id: str, code: str, detail: str) -> None:
        msg = f"{code}: {detail}"[:1000]
        self._store.update(job_id, status="failed", error=msg)
