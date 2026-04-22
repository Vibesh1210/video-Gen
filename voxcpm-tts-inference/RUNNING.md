# Running the VoxCPM TTS Service

Runbook for the VoxCPM TTS microservice. Mirrors Svara's HTTP contract so
the orchestrator picks it up by flipping `TTS_URL` — no adapter code
changes.

- Design doc: `docs/VOXCPM_TTS_SPEC.md`
- Model card: <https://huggingface.co/openbmb/VoxCPM2>
- Endpoints: `POST /v1/audio/speech`, `GET /v1/voices`, `GET /healthz`

---

## 0. Prerequisites

| Thing | What you need |
|---|---|
| GPU | NVIDIA with ≥ 8 GB VRAM, CUDA 12.x drivers |
| Python | 3.10 – 3.12 (VoxCPM requires `>=3.10,<3.13`) |
| ffmpeg | on `$PATH` (needed for mp3/opus/aac output) |
| Weights | `/DATA/USERS/vibesh/models/VoxCPM2` (4.7 GB — already downloaded) |
| Disk | **do not use `/home`**, it is 100 % full. Stay on `/DATA`. |

Check in one go:

```bash
nvidia-smi | head -5                 # driver + CUDA
python3 --version                    # 3.10–3.12
ffmpeg -version | head -1            # present
ls /DATA/USERS/vibesh/models/VoxCPM2 # model.safetensors + audiovae.pth
df -h /DATA                          # plenty of space
```

---

## 1. Local (bare-metal) run

Best for iterating. Uses your existing Python environment.

### 1.1 One-time setup

```bash
cd /home/vibesh/museTalk/voxcpm-tts-inference

# Use a venv on /DATA so /home doesn't fill up
python3 -m venv /DATA/USERS/vibesh/venvs/voxcpm
source /DATA/USERS/vibesh/venvs/voxcpm/bin/activate

# torch first (needs the CUDA 12.1 wheel index)
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121

# then VoxCPM + this service's deps
pip install voxcpm
pip install -r requirements.txt
```

### 1.2 Start the server

```bash
source /DATA/USERS/vibesh/venvs/voxcpm/bin/activate
cd /home/vibesh/museTalk/voxcpm-tts-inference

export VOXCPM_MODEL_PATH=/DATA/USERS/vibesh/models/VoxCPM2
export VOXCPM_DEVICE=cuda
export LOG_LEVEL=INFO

uvicorn api.server:app --host 0.0.0.0 --port 8080
```

First boot takes ~15–30 s: model load + a one-shot warmup synth. When you
see `Warmup complete.` you're ready.

### 1.3 Environment knobs

| Variable | Default | Purpose |
|---|---|---|
| `VOXCPM_MODEL_PATH` | `/DATA/USERS/vibesh/models/VoxCPM2` | where the weights live |
| `VOXCPM_DEVICE` | `cuda` | `cuda` / `cpu` / `mps` / `auto` |
| `VOXCPM_VOICES_FILE` | `./voices.yaml` | voice catalog path |
| `VOXCPM_CFG_VALUE` | `2.0` | default guidance scale |
| `VOXCPM_TIMESTEPS` | `10` | default diffusion steps |
| `VOXCPM_LOAD_DENOISER` | `0` | set to `1` to enable input-denoiser (pulls a ModelScope model) |
| `VOXCPM_WARMUP` | `1` | set to `0` to skip warmup (faster boot, slower first request) |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8080` | bind |
| `LOG_LEVEL` | `INFO` | — |

---

## 2. Docker run

### 2.1 Build

```bash
cd /home/vibesh/museTalk
docker compose build voxcpm-tts
```

### 2.2 Start the full stack (VoxCPM is the default TTS)

```bash
docker compose up voxcpm-tts musetalk-api orchestrator frontend
```

The compose entry mounts weights read-only from the host:

```
/DATA/USERS/vibesh/models/VoxCPM2  →  /models/VoxCPM2  (ro)
```

Override the host path via `VOXCPM_WEIGHTS_HOST` in `.env` if yours are
elsewhere.

### 2.3 Switch back to Svara

Svara lives behind a compose profile so it doesn't bind port 8080 by
default. To use it instead of VoxCPM:

```bash
docker compose down voxcpm-tts
docker compose --profile svara up tts musetalk-api orchestrator frontend
# and point the orchestrator at it:
TTS_URL=http://tts:8080 docker compose up -d orchestrator
```

Only one of `tts` / `voxcpm-tts` should be running at any time — both
claim port 8080.

---

## 3. Smoke tests

Run these against whichever instance is live (local or Docker).

```bash
# 1. Health — should return {"status":"ok","model_loaded":true,...}
curl -s localhost:8080/healthz | jq

# 2. Voice catalog — should list 4 voices
curl -s localhost:8080/v1/voices | jq

# 3. Synthesize with the default (cloned) voice
curl -s -X POST localhost:8080/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello from VoxCPM.","voice":"default","response_format":"wav"}' \
  --output /tmp/voxcpm_test.wav
file /tmp/voxcpm_test.wav    # should say "RIFF ... WAVE audio"

# 4. Synthesize with a design voice
curl -s -X POST localhost:8080/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"News at eleven.","voice":"en_male_news","response_format":"wav"}' \
  --output /tmp/voxcpm_news.wav

# 5. Unknown voice — should return 404 {"error":"unknown_voice",...}
curl -si -X POST localhost:8080/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"x","voice":"does_not_exist","response_format":"wav"}'

# 6. End-to-end through the orchestrator (expects orchestrator on 8000)
curl -sS -X POST http://localhost:8000/api/v1/jobs \
  -F text="end to end check" \
  -F voice=default \
  -F face=@/path/to/any_face.jpg | jq
```

---

## 4. Voice catalog — adding / editing voices

Edit `voxcpm-tts-inference/voices.yaml`. Two modes:

```yaml
# 1. Clone — provide a .wav clip under voices/
- voice_id: my_voice
  name: "My recorded voice"
  language_code: en
  gender: male
  mode: clone
  reference_wav: voices/my_clip.wav
  prompt_text: null               # optional: transcript → "ultimate cloning"

# 2. Design — describe the voice in natural language, no audio needed
- voice_id: custom_designer
  name: "Elderly storyteller"
  language_code: en
  gender: male
  mode: design
  design_prompt: "An elderly male storyteller, slow and warm"
```

Restart the service after editing (the catalog is read at startup).

Tips:
- 5–20 s of clean, mono 16 kHz+ audio works best for `clone`.
- `prompt_text` is optional but improves cloning fidelity significantly
  when you have the exact transcript.
- `design` mode output varies run-to-run; regenerate 1–3× to pick the
  best take.

---

## 5. Troubleshooting

### "CUDA out of memory" on boot
VoxCPM2 needs ~8 GB VRAM. If MuseTalk is sharing the same GPU, it will
also want ~4–6 GB. Either:
- Put each service on a separate GPU (`CUDA_VISIBLE_DEVICES=0` for one,
  `=1` for the other), or
- Run VoxCPM on CPU with `VOXCPM_DEVICE=cpu` (slow — minutes per utterance).

### Import errors on boot
```
ModuleNotFoundError: No module named 'voxcpm'
```
You forgot `pip install voxcpm` in the active environment. The Docker
image handles this; bare-metal needs the venv activated.

### `/home` fills up during install
Pip caches wheels in `~/.cache/pip`. Redirect it:
```bash
export PIP_CACHE_DIR=/DATA/USERS/vibesh/pip-cache
```

### `ffmpeg: command not found`
Only needed for mp3/opus/aac. WAV and PCM work without it. Install:
```bash
sudo apt-get install -y ffmpeg
```

### Orchestrator returns `unknown_voice`
The orchestrator resolves `voice` against the **active** TTS service's
catalog. After switching from Svara → VoxCPM, valid voice IDs change:
```bash
curl -s localhost:8080/v1/voices | jq '.voices[].voice_id'
```
Update the frontend / any saved job templates to use these IDs.

### Synthesis works but lip-sync has no sound
VoxCPM emits 48 kHz WAV; MuseTalk expects 16 kHz. Current pipeline relies
on MuseTalk's internal resample — if you see silent MP4 output, confirm
by probing the intermediate WAV via the orchestrator's saved audio
artifact (see `docs/API_CONTRACT.md §2` on audio persistence).

### Warmup hangs
First run also compiles torch graphs and may take 60+ s. If it truly
hangs (> 3 min), set `VOXCPM_WARMUP=0` and let the first real request
pay the cost.

---

## 6. Useful file paths

| What | Where |
|---|---|
| Service code | `voxcpm-tts-inference/` |
| Entry point | `voxcpm-tts-inference/api/server.py` |
| Voice catalog | `voxcpm-tts-inference/voices.yaml` |
| Bundled reference clips | `voxcpm-tts-inference/voices/` |
| Design spec | `docs/VOXCPM_TTS_SPEC.md` |
| Model weights | `/DATA/USERS/vibesh/models/VoxCPM2` |
| HF cache | `/DATA/USERS/vibesh/hf-cache` |
| Docker compose | `docker-compose.yml` (services `voxcpm-tts` + `tts`) |
| Orchestrator adapter (unchanged) | `orchestrator/adapters/tts_svara.py` |

---

## 7. Uninstall / cleanup

```bash
# Remove the venv
rm -rf /DATA/USERS/vibesh/venvs/voxcpm

# Remove the Docker image
docker rmi voxcpm-tts-api:latest

# Remove weights (only if you really want to re-download 4.7 GB later)
rm -rf /DATA/USERS/vibesh/models/VoxCPM2
```
