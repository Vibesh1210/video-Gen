"""Thin wrapper around VoxCPM.from_pretrained().

Load once at startup, synthesize many times. Synthesis is serialized via a
threading lock because VoxCPM is not thread-safe for concurrent GPU use.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


logger = logging.getLogger(__name__)


class VoxCPMEngine:
    def __init__(
        self,
        model_path: str,
        device: str | None = "cuda",
        load_denoiser: bool = False,
    ):
        from voxcpm import VoxCPM  # lazy import so unit tests don't need it

        # Installed voxcpm has no `device` kwarg — it picks CUDA when
        # available. Use CUDA_VISIBLE_DEVICES (or VOXCPM_DEVICE=cpu →
        # CUDA_VISIBLE_DEVICES="") to steer it.
        if device and device.lower() == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = ""

        # `optimize=True` triggers torch.compile + CUDA graphs, which use
        # thread-local state. Warmup runs on the main thread but synth runs
        # on an asyncio worker thread, hitting an inductor TLS assertion.
        # Default OFF; opt back in via VOXCPM_OPTIMIZE=1 if you pin synth
        # to the load thread.
        optimize = os.environ.get("VOXCPM_OPTIMIZE", "0") == "1"

        logger.info("Loading VoxCPM from %s (device=%s, denoiser=%s, optimize=%s)",
                    model_path, device, load_denoiser, optimize)
        self._model = VoxCPM.from_pretrained(
            hf_model_id=model_path,
            load_denoiser=load_denoiser,
            optimize=optimize,
        )
        self._sr = int(self._model.tts_model.sample_rate)
        self._lock = threading.Lock()
        logger.info("VoxCPM loaded (sample_rate=%d)", self._sr)

    @property
    def sample_rate(self) -> int:
        return self._sr

    def warmup(self, text: str = "Warm up.") -> None:
        """Run a tiny synth so the first real request is fast (compile graphs)."""
        logger.info("Warming up VoxCPM…")
        self.synthesize(text=text)
        logger.info("Warmup complete.")

    def synthesize(
        self,
        text: str,
        *,
        reference_wav: str | None = None,
        prompt_text: str | None = None,
        design_prompt: str | None = None,
        cfg_value: float = 2.0,
        inference_timesteps: int = 10,
    ) -> "np.ndarray":
        """Return float32 PCM at self.sample_rate."""
        if design_prompt:
            text = f"({design_prompt}){text}"

        kwargs: dict = {
            "text": text,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
        }
        if reference_wav is not None:
            kwargs["reference_wav_path"] = reference_wav
            if prompt_text is not None:
                # Ultimate-cloning mode — same clip as both prompt and ref.
                kwargs["prompt_wav_path"] = reference_wav
                kwargs["prompt_text"] = prompt_text

        with self._lock:
            return self._model.generate(**kwargs)
