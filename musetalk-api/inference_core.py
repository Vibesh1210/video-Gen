"""Warm in-process MuseTalk inference.

Refactor of MuseTalk/scripts/inference.py's main() into:
  - MuseTalkEngine.__init__(...)  loads models once
  - MuseTalkEngine.generate(face_bytes, face_filename, audio_bytes, params)
    runs a single request and returns MP4 bytes.

Heavy models (VAE, UNet, PE, Whisper, FaceParsing) stay resident on the GPU
across requests. A process-wide lock serialises GPU access.
"""
from __future__ import annotations

import copy
import glob
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
from omegaconf import OmegaConf
from tqdm import tqdm
from transformers import WhisperModel

# PyTorch 2.6+ flipped `torch.load`'s default to weights_only=True. MuseTalk's
# DWPose / SD-VAE / MuseTalk UNet checkpoints predate that and include numpy
# pickled globals that the safe unpickler rejects. These checkpoints come from
# trusted upstream repos; restore the pre-2.6 default here.
_orig_torch_load = torch.load
def _torch_load_full(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_torch_load(*args, **kwargs)
torch.load = _torch_load_full


# --------------------------------------------------------------------------- #
# Sys-path + cwd bootstrap                                                    #
# --------------------------------------------------------------------------- #
# MuseTalk's `musetalk.utils.preprocessing` and a couple of its config files
# use RELATIVE paths resolved at import time (e.g. `./musetalk/utils/dwpose/
# rtmpose-l_...py`). We therefore chdir into the MuseTalk directory BEFORE
# importing these modules, and stay there for the lifetime of the process.
# This matches app.py's own behaviour.

_THIS_DIR = Path(__file__).resolve().parent
_MUSETALK_DIR = (_THIS_DIR.parent / "MuseTalk").resolve()

if str(_MUSETALK_DIR) not in sys.path:
    sys.path.insert(0, str(_MUSETALK_DIR))

os.chdir(str(_MUSETALK_DIR))

from musetalk.utils.audio_processor import AudioProcessor  # noqa: E402
from musetalk.utils.blending import get_image  # noqa: E402
from musetalk.utils.face_parsing import FaceParsing  # noqa: E402
from musetalk.utils.preprocessing import (  # noqa: E402
    coord_placeholder,
    get_landmark_and_bbox,
    read_imgs,
)
from musetalk.utils.utils import (  # noqa: E402
    datagen,
    get_file_type,
    get_video_fps,
    load_all_model,
)


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #

class LipSyncError(Exception):
    code = "inference_failed"

    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code


class NoFaceDetected(LipSyncError):
    code = "no_face_detected"


class BadInput(LipSyncError):
    code = "bad_input"


# --------------------------------------------------------------------------- #
# Engine                                                                      #
# --------------------------------------------------------------------------- #

@dataclass
class EngineConfig:
    musetalk_dir: Path = _MUSETALK_DIR
    version: str = "v15"
    gpu_id: int = 0
    use_float16: bool = True
    # Model paths (resolved relative to musetalk_dir if not absolute)
    unet_model_path: str = "models/musetalkV15/unet.pth"
    unet_config: str = "models/musetalkV15/musetalk.json"
    vae_type: str = "sd-vae"
    whisper_dir: str = "models/whisper"
    # Default FaceParsing cheek widths — re-init only if a request differs.
    default_left_cheek_width: int = 90
    default_right_cheek_width: int = 90


@dataclass
class InferenceParams:
    bbox_shift: int = 0
    extra_margin: int = 10
    parsing_mode: str = "jaw"
    fps: int = 25
    version: str = "v15"
    left_cheek_width: int = 90
    right_cheek_width: int = 90
    batch_size: int = 8
    audio_padding_length_left: int = 2
    audio_padding_length_right: int = 2


class MuseTalkEngine:
    """Loads MuseTalk models once, exposes `generate(...)` per request."""

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self.device = torch.device(
            f"cuda:{cfg.gpu_id}" if torch.cuda.is_available() else "cpu"
        )
        self._lock = threading.Lock()

        self._musetalk_dir = cfg.musetalk_dir

        # Resolve weights relative to the MuseTalk directory.
        unet_path = self._abs(cfg.unet_model_path)
        unet_config = self._abs(cfg.unet_config)
        whisper_dir = self._abs(cfg.whisper_dir)

        # MuseTalk's load_all_model() uses relative paths for the VAE. Running
        # it from inside the MuseTalk directory avoids surprises.
        with _chdir(self._musetalk_dir):
            vae, unet, pe = load_all_model(
                unet_model_path=str(unet_path),
                vae_type=cfg.vae_type,
                unet_config=str(unet_config),
                device=self.device,
            )

        self.vae = vae
        self.unet = unet
        self.pe = pe

        self.weight_dtype = torch.float16 if cfg.use_float16 else torch.float32
        if cfg.use_float16:
            self.pe = self.pe.half()
            self.vae.vae = self.vae.vae.half()
            self.unet.model = self.unet.model.half()

        self.pe = self.pe.to(self.device)
        self.vae.vae = self.vae.vae.to(self.device)
        self.unet.model = self.unet.model.to(self.device)
        self._timesteps = torch.tensor([0], device=self.device)

        # Whisper audio encoder.
        self.audio_processor = AudioProcessor(feature_extractor_path=str(whisper_dir))
        self.whisper = WhisperModel.from_pretrained(str(whisper_dir))
        self.whisper = self.whisper.to(device=self.device, dtype=self.weight_dtype).eval()
        self.whisper.requires_grad_(False)

        # Face parser — cheek widths rarely change; cache by (l,r) pair.
        self._fp_cache: dict[tuple[int, int], FaceParsing] = {}
        self._fp_default_key = (
            cfg.default_left_cheek_width,
            cfg.default_right_cheek_width,
        )
        with _chdir(self._musetalk_dir):
            self._fp_cache[self._fp_default_key] = FaceParsing(
                left_cheek_width=cfg.default_left_cheek_width,
                right_cheek_width=cfg.default_right_cheek_width,
            )

    # -- helpers ----------------------------------------------------------- #

    def _abs(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else (self._musetalk_dir / p).resolve()

    def _get_face_parser(self, left: int, right: int) -> FaceParsing:
        key = (int(left), int(right))
        if key in self._fp_cache:
            return self._fp_cache[key]
        with _chdir(self._musetalk_dir):
            self._fp_cache[key] = FaceParsing(
                left_cheek_width=key[0], right_cheek_width=key[1]
            )
        return self._fp_cache[key]

    def health(self) -> dict:
        return {
            "status": "ok",
            "model": f"musetalk-{self.cfg.version}",
            "device": str(self.device),
            "dtype": str(self.weight_dtype),
        }

    # -- inference --------------------------------------------------------- #

    @torch.no_grad()
    def generate(
        self,
        face_bytes: bytes,
        face_filename: str,
        audio_bytes: bytes,
        params: InferenceParams | None = None,
    ) -> bytes:
        params = params or InferenceParams()
        face_ext = Path(face_filename).suffix.lower() or ".bin"
        if get_file_type(face_filename) not in {"image", "video"}:
            raise BadInput(
                f"Unsupported face file extension {face_ext!r}. "
                "Expected image (.jpg/.png) or video (.mp4/.mov/...)."
            )

        # Serialise GPU access — the UNet/VAE state is not safe for concurrent
        # forward passes from multiple Python threads.
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="musetalk_") as td:
                return self._generate_in(
                    Path(td), face_bytes, face_ext, audio_bytes, params
                )

    # -- internals --------------------------------------------------------- #

    def _generate_in(
        self,
        work: Path,
        face_bytes: bytes,
        face_ext: str,
        audio_bytes: bytes,
        p: InferenceParams,
    ) -> bytes:
        face_path = work / f"face{face_ext}"
        face_path.write_bytes(face_bytes)

        audio_path = work / "audio.wav"
        audio_path.write_bytes(audio_bytes)

        frames_dir = work / "frames"
        frames_dir.mkdir()
        res_dir = work / "res"
        res_dir.mkdir()

        # 1. Expand input into a list of frame image paths + determine fps.
        file_kind = get_file_type(str(face_path))
        if file_kind == "video":
            # Use ffmpeg to dump frames (same as scripts/inference.py:123).
            ret = subprocess.run(
                [
                    "ffmpeg", "-v", "fatal", "-y",
                    "-i", str(face_path),
                    "-start_number", "0",
                    str(frames_dir / "%08d.png"),
                ],
                capture_output=True,
            )
            if ret.returncode != 0:
                raise BadInput(
                    f"ffmpeg failed to decode input video: "
                    f"{ret.stderr.decode(errors='replace')[:500]}"
                )
            input_img_list = sorted(
                glob.glob(str(frames_dir / "*.[jpJP][pnPN]*[gG]"))
            )
            try:
                fps = get_video_fps(str(face_path)) or p.fps
            except Exception:
                fps = p.fps
        else:  # image
            input_img_list = [str(face_path)]
            fps = p.fps

        if not input_img_list:
            raise BadInput("No frames extracted from input face media.")

        # 2. Whisper audio features.
        try:
            whisper_feats, librosa_length = self.audio_processor.get_audio_feature(
                str(audio_path)
            )
        except Exception as e:
            raise LipSyncError(
                f"audio_decode_failed: {e}", code="audio_decode_failed"
            ) from e

        whisper_chunks = self.audio_processor.get_whisper_chunk(
            whisper_feats,
            self.device,
            self.weight_dtype,
            self.whisper,
            librosa_length,
            fps=fps,
            audio_padding_length_left=p.audio_padding_length_left,
            audio_padding_length_right=p.audio_padding_length_right,
        )

        # 3. Face landmarks + bboxes.
        with _chdir(self._musetalk_dir):
            coord_list, frame_list = get_landmark_and_bbox(
                input_img_list, p.bbox_shift
            )

        valid_coords = [c for c in coord_list if c != coord_placeholder]
        if not valid_coords:
            raise NoFaceDetected(
                "No face detected in the input image/video. "
                "Provide a frontal face with clear lighting."
            )

        # 4. Encode each crop to a VAE latent.
        version = p.version or self.cfg.version
        input_latent_list = []
        frame_h_ref = None
        for bbox, frame in zip(coord_list, frame_list):
            if bbox == coord_placeholder:
                continue
            x1, y1, x2, y2 = bbox
            if version == "v15":
                y2 = min(y2 + p.extra_margin, frame.shape[0])
            frame_h_ref = frame.shape[0]
            crop = frame[y1:y2, x1:x2]
            crop = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4)
            input_latent_list.append(self.vae.get_latents_for_unet(crop))

        # Ping-pong to avoid a visible seam when audio is longer than video.
        frame_list_cycle = frame_list + frame_list[::-1]
        coord_list_cycle = coord_list + coord_list[::-1]
        input_latent_list_cycle = input_latent_list + input_latent_list[::-1]

        # 5. UNet inference, batch by batch.
        video_num = len(whisper_chunks)
        gen = datagen(
            whisper_chunks=whisper_chunks,
            vae_encode_latents=input_latent_list_cycle,
            batch_size=p.batch_size,
            delay_frame=0,
            device=self.device,
        )
        res_frames: list[np.ndarray] = []
        total = int(np.ceil(float(video_num) / p.batch_size))
        for whisper_batch, latent_batch in tqdm(gen, total=total, desc="UNet"):
            audio_feat = self.pe(whisper_batch)
            latent_batch = latent_batch.to(dtype=self.unet.model.dtype)
            pred_latents = self.unet.model(
                latent_batch, self._timesteps, encoder_hidden_states=audio_feat
            ).sample
            recon = self.vae.decode_latents(pred_latents)
            for f in recon:
                res_frames.append(f)

        # 6. Blend each generated face back into the original frame.
        fp = self._get_face_parser(p.left_cheek_width, p.right_cheek_width)
        for i, res_frame in enumerate(res_frames):
            bbox = coord_list_cycle[i % len(coord_list_cycle)]
            ori_frame = copy.deepcopy(frame_list_cycle[i % len(frame_list_cycle)])
            x1, y1, x2, y2 = bbox
            if version == "v15":
                y2 = min(y2 + p.extra_margin, frame_h_ref or ori_frame.shape[0])
            try:
                res = cv2.resize(res_frame.astype(np.uint8), (x2 - x1, y2 - y1))
            except Exception:
                continue
            if version == "v15":
                combined = get_image(
                    ori_frame, res, [x1, y1, x2, y2], mode=p.parsing_mode, fp=fp
                )
            else:
                combined = get_image(ori_frame, res, [x1, y1, x2, y2], fp=fp)
            cv2.imwrite(str(res_dir / f"{i:08d}.png"), combined)

        # 7. Encode frames → MP4, then mux audio.
        silent_mp4 = work / "silent.mp4"
        ret = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "warning",
                "-r", str(int(fps)),
                "-f", "image2",
                "-i", str(res_dir / "%08d.png"),
                "-vcodec", "libx264",
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p",
                "-crf", "18",
                str(silent_mp4),
            ],
            capture_output=True,
        )
        if ret.returncode != 0:
            raise LipSyncError(
                f"ffmpeg image2video failed: "
                f"{ret.stderr.decode(errors='replace')[:500]}"
            )

        out_mp4 = work / "out.mp4"
        ret = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "warning",
                "-i", str(audio_path),
                "-i", str(silent_mp4),
                "-map", "1:v:0", "-map", "0:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(out_mp4),
            ],
            capture_output=True,
        )
        if ret.returncode != 0:
            raise LipSyncError(
                f"ffmpeg mux failed: {ret.stderr.decode(errors='replace')[:500]}"
            )

        return out_mp4.read_bytes()


# --------------------------------------------------------------------------- #
# Small helpers                                                               #
# --------------------------------------------------------------------------- #

class _chdir:
    """Context manager: temporarily chdir to `path`."""

    def __init__(self, path: Path):
        self._target = Path(path)
        self._prev: str | None = None

    def __enter__(self):
        self._prev = os.getcwd()
        os.chdir(self._target)
        return self

    def __exit__(self, *exc):
        if self._prev is not None:
            os.chdir(self._prev)
