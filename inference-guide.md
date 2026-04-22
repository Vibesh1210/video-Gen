# MuseTalk Inference Guide — Lip‑Synced Video from Audio

End-to-end recipe for running MuseTalk inference and producing a lip-synced
output video for a given (face video, driving audio) pair.

Repo root used below: `/home/vibesh/museTalk/MuseTalk`.

---

## 1. Prerequisites

### 1.1 System

- Linux with an NVIDIA GPU + CUDA 11.7/11.8 driver
- `ffmpeg` available on `PATH` (`ffmpeg -version` should work)
  - Install on Ubuntu/Debian: `sudo apt-get install -y ffmpeg`
- Python 3.10 (conda recommended)

### 1.2 Python environment

```bash
cd /home/vibesh/museTalk/MuseTalk

conda create -n MuseTalk python=3.10 -y
conda activate MuseTalk

# PyTorch 2.0.1 + CUDA 11.8
pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 \
    --index-url https://download.pytorch.org/whl/cu118

# Project deps
pip install -r requirements.txt

# MMLab stack (for DWPose face landmarks)
pip install --no-cache-dir -U openmim
mim install mmengine
mim install "mmcv==2.0.1"
mim install "mmdet==3.1.0"
mim install "mmpose==1.1.0"
```

---

## 2. Download model weights

The repo currently has no `models/` directory. Run the bundled download
script — it pulls MuseTalk v1.0 + v1.5, SD‑VAE, Whisper‑tiny, DWPose,
SyncNet and face‑parse weights into `./models`.

```bash
cd /home/vibesh/museTalk/MuseTalk
sh ./download_weights.sh
```

After it finishes you should have:

```
models/
├── musetalk/        # v1.0 unet + config
├── musetalkV15/     # v1.5 unet + config (recommended)
├── sd-vae/          # image VAE
├── whisper/         # whisper-tiny audio encoder
├── dwpose/          # face landmark detector
├── face-parse-bisent/
└── syncnet/
```

> If `huggingface-cli` rate-limits you, re-run the script — it resumes.

---

## 3. Pick / prepare your inputs

Sample assets shipped in the repo:

| Type  | Path                          |
|-------|-------------------------------|
| Video | `data/video/yongen.mp4`, `data/video/sun.mp4` |
| Audio | `data/audio/yongen.wav`, `data/audio/eng.wav`, `data/audio/sun.wav` |

For your own inputs:

- **Face video**: short clip with a clearly visible single face, 25 fps works
  best. A still image also works (the script will tile it).
- **Driving audio**: 16‑bit PCM `.wav` is safest. Any sample rate is fine —
  Whisper handles resampling.

---

## 4. Configure the inference task

Inference is driven by a YAML config. Edit
`configs/inference/test.yaml` (normal mode) to point at your files:

```yaml
task_0:
  video_path: "data/video/yongen.mp4"
  audio_path: "data/audio/yongen.wav"

task_1:
  video_path: "data/video/yongen.mp4"
  audio_path: "data/audio/eng.wav"
  bbox_shift: -7        # tweak vertical lip region; negative = move up
```

You can list as many `task_N` blocks as you want; each produces one output
video.

`bbox_shift` is the main knob for lip alignment quality — try values in
`[-9, +9]` if the mouth looks off.

---

## 5. Run inference

### 5.1 Normal (offline) mode — recommended for first run

Produces a finished `.mp4` per task in `./results/test/`.

```bash
cd /home/vibesh/museTalk/MuseTalk

# v1.5 (recommended)
sh inference.sh v1.5 normal

# or v1.0
sh inference.sh v1.0 normal
```

Under the hood this runs:

```bash
python3 -m scripts.inference \
    --inference_config ./configs/inference/test.yaml \
    --result_dir       ./results/test \
    --unet_model_path  ./models/musetalkV15/unet.pth \
    --unet_config      ./models/musetalkV15/musetalk.json \
    --version          v15
```

### 5.2 Realtime mode — for the streaming pipeline

Uses a pre-prepared "avatar" cache so each new audio clip renders fast.
Edit `configs/inference/realtime.yaml` first to set your avatar's video
and the audio clips you want to drive it with:

```yaml
avator_1:
  preparation: True       # set False after the first run to skip prep
  bbox_shift: 5
  video_path: "data/video/yongen.mp4"
  audio_clips:
    audio_0: "data/audio/yongen.wav"
    audio_1: "data/audio/eng.wav"
```

Then:

```bash
sh inference.sh v1.5 realtime
```

Outputs land in `./results/realtime/`.

---

## 6. View the output

```bash
ls results/test/v15/
# e.g. yongen_yongen.mp4, yongen_eng.mp4

# Local playback
xdg-open results/test/v15/yongen_yongen.mp4

# Or copy to your machine
scp <host>:/home/vibesh/museTalk/MuseTalk/results/test/v15/yongen_yongen.mp4 .
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg not found` | `sudo apt-get install ffmpeg`, or pass `--ffmpeg_path /path/to/ffmpeg/bin` to `scripts.inference`. |
| `mmcv` build errors | Make sure PyTorch 2.0.1 + CUDA 11.8 are installed *before* `mim install`. |
| Lips drift / look offset | Adjust `bbox_shift` in the YAML by ±2 and re-run. |
| OOM on small GPUs | Add `--use_float16` to the python command (already half on most paths). |
| Wrong GPU used | Add `--gpu_id 1` (or whichever index). |
| `huggingface-cli` 403 | The script sets `HF_ENDPOINT=https://hf-mirror.com`; unset it if you're outside CN: `unset HF_ENDPOINT`. |

---

## 8. One-shot quickstart (TL;DR)

```bash
cd /home/vibesh/museTalk/MuseTalk
conda activate MuseTalk
sh ./download_weights.sh        # once
sh inference.sh v1.5 normal     # uses configs/inference/test.yaml
ls results/test/v15/            # your lip-synced mp4s
```
