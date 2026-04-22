# VoxCPM TTS Service — Implementation Spec

Drop-in replacement for Svara TTS. Wraps the VoxCPM2 model in a FastAPI
service that exposes the **same** HTTP contract as Svara so the
orchestrator can switch providers by flipping `TTS_BASE_URL` — no adapter
code changes.

Weights already downloaded: `/DATA/USERS/vibesh/models/VoxCPM2/` (4.7 GB).

---

## 1. Scope

**In scope**
- New service `voxcpm-tts-inference/` (sibling of `svara-tts-inference/`).
- HTTP endpoints matching `docs/API_CONTRACT.md §3` (Svara contract).
- Voice catalog built from (a) bundled reference clips and/or
  (b) natural-language voice-design presets.
- WAV output at 48 kHz (VoxCPM2 native) or transcoded on request.
- Dockerfile + docker-compose entry.

**Out of scope (v1)**
- Streaming / chunked audio (`stream: true`). Return 501 if requested.
- Fine-tuning, LoRA swapping at runtime.
- User-uploaded reference clips via API (only preset voices for now).
- Nano-vLLM / vLLM-Omni acceleration (optimization, not correctness).

---

## 2. Contract — must match Svara byte-for-byte

The orchestrator's `SvaraTTSAdapter` (`orchestrator/adapters/tts_svara.py`)
must work against this service unmodified. That means:

### 2.1 `POST /v1/audio/speech`

Request (JSON):
```json
{
  "model": "voxcpm-v2",
  "input": "Hello world",
  "voice": "en_female_warm",
  "response_format": "wav",
  "stream": false
}
```

Response: raw audio bytes. `Content-Type` = `audio/wav` (or
`audio/mpeg`, `audio/opus`, `audio/aac`, `audio/pcm`).

Errors: `{"error":"<code>","detail":"..."}`, status 4xx/5xx. `404` for
unknown voice — the adapter maps that to `unknown_voice`.

### 2.2 `GET /v1/voices`

```json
{ "voices": [
    { "voice_id": "en_female_warm",
      "name":     "English — warm female",
      "language_code": "en",
      "gender":   "female",
      "style":    "neutral",
      "sample_rate": 48000,
      "mode":     "clone"          // clone | design
    },
    ...
]}
```

`voice_id`, `name`, `language_code` are **required** (orchestrator
`VoiceInfo` schema). Extra keys are allowed and pass through.

### 2.3 `GET /healthz`

`200 {"status":"ok","model_loaded":true}` once warm.

---

## 3. Voice strategy

VoxCPM is a cloning/design model, not a multi-speaker catalog. We expose a
fixed inventory mapped to either a **reference clip** or a **design
prompt**, configured via a YAML file:

```yaml
# voxcpm-tts-inference/voices.yaml
- voice_id: en_female_warm
  name: "English — warm female"
  language_code: en
  gender: female
  mode: clone
  reference_wav: voices/en_female_warm.wav
  prompt_text: null

- voice_id: en_male_news
  name: "English — news anchor"
  language_code: en
  gender: male
  mode: design
  design_prompt: "A middle-aged male news anchor, clear and authoritative"
```

`GET /v1/voices` reads this file and returns the catalog. `POST /v1/audio/speech`
looks up the `voice_id` and invokes `model.generate()` accordingly:

- `mode: clone` → `reference_wav_path=<file>` (plus optional
  `prompt_text` for ultimate-cloning mode).
- `mode: design` → text prefixed with `"(<design_prompt>)"`.

**v1 ships with 4–6 preset voices** covering en / hi plus one male + one
female per language. Reference clips live under `voices/` in the repo.

---

## 4. Architecture

```
voxcpm-tts-inference/
├── api/
│   ├── server.py          # FastAPI app, endpoints, lifespan
│   └── models.py          # Pydantic request/response schemas
├── engine/
│   ├── voxcpm_engine.py   # VoxCPM wrapper: load once, synth many
│   ├── voice_catalog.py   # voices.yaml loader + lookup
│   └── audio_codec.py     # float32 numpy → wav/mp3/opus/aac bytes
├── voices/                # bundled reference clips (git-lfs or external)
├── voices.yaml            # voice catalog
├── requirements.txt
├── Dockerfile
└── README.md
```

**Process model**: single FastAPI process. VoxCPM loaded once at startup
into a module-global (mirrors `musetalk-api` warm engine pattern).
Synthesis calls are serialized on a `threading.Lock` since VoxCPM is not
thread-safe for concurrent GPU use. Async endpoint `await`s a
`run_in_executor` call to keep the event loop free.

**No streaming in v1.** `stream: true` → `501 Not Implemented`.

---

## 5. Engine wrapper (core.py sketch)

```python
# engine/voxcpm_engine.py
import threading, io
import soundfile as sf
from voxcpm import VoxCPM

class VoxCPMEngine:
    def __init__(self, model_path: str, device: str = "cuda"):
        self._lock = threading.Lock()
        self._model = VoxCPM.from_pretrained(model_path, load_denoiser=False)
        self._sr = self._model.tts_model.sample_rate  # 48000

    @property
    def sample_rate(self) -> int:
        return self._sr

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
        if design_prompt:
            text = f"({design_prompt}){text}"
        with self._lock:
            return self._model.generate(
                text=text,
                reference_wav_path=reference_wav,
                prompt_wav_path=reference_wav if prompt_text else None,
                prompt_text=prompt_text,
                cfg_value=cfg_value,
                inference_timesteps=inference_timesteps,
            )
```

---

## 6. Audio format handling

VoxCPM returns `numpy.float32` PCM at 48 kHz. The service must serve
whatever `response_format` the client asked for:

| format | transform | library |
|--------|-----------|---------|
| `wav`  | `soundfile.write(BytesIO, wav, sr, subtype="PCM_16")` | soundfile |
| `pcm`  | raw int16 bytes, no header                            | numpy |
| `mp3`  | pipe PCM → ffmpeg `-f mp3 -b:a 128k`                  | ffmpeg-python or subprocess |
| `opus` | pipe PCM → ffmpeg `-c:a libopus -b:a 64k`             | ffmpeg |
| `aac`  | pipe PCM → ffmpeg `-c:a aac -b:a 128k`                | ffmpeg |

MuseTalk expects 16 kHz WAV. The orchestrator requests `response_format: wav`
from TTS — we return 48 kHz WAV. MuseTalk resamples internally, so no
special handling needed here (verify in acceptance test).

---

## 7. Configuration (env vars)

| Variable              | Default                                  | Purpose |
|-----------------------|------------------------------------------|---------|
| `VOXCPM_MODEL_PATH`   | `/DATA/USERS/vibesh/models/VoxCPM2`      | Weights dir |
| `VOXCPM_DEVICE`       | `cuda`                                   | `cuda` / `cpu` |
| `VOXCPM_VOICES_FILE`  | `./voices.yaml`                          | Catalog |
| `VOXCPM_CFG_VALUE`    | `2.0`                                    | Default CFG scale |
| `VOXCPM_TIMESTEPS`    | `10`                                     | Diffusion steps |
| `API_HOST`            | `0.0.0.0`                                | Bind host |
| `API_PORT`            | `8080`                                   | **Same as Svara** so the orchestrator flips with one env var |
| `LOG_LEVEL`           | `INFO`                                   | — |

---

## 8. Dependencies

`requirements.txt`:
```
voxcpm>=2.0
torch>=2.5.0
fastapi>=0.110
uvicorn[standard]>=0.29
soundfile>=0.12
pyyaml>=6.0
ffmpeg-python>=0.2   # for mp3/opus/aac transcode
python-dotenv>=1.0
```

**Incompatibility risk**: VoxCPM requires `torch ≥ 2.5`; MuseTalk's
environment uses `torch 2.0.1`. These two services **must** run in
separate processes / containers / conda envs. This is the main argument
against running VoxCPM in-process with the orchestrator or MuseTalk.

---

## 9. Deployment

### Local (dev)
```bash
cd voxcpm-tts-inference
pip install -r requirements.txt
VOXCPM_MODEL_PATH=/DATA/USERS/vibesh/models/VoxCPM2 \
  uvicorn api.server:app --host 0.0.0.0 --port 8080
```

### Docker
`Dockerfile` based on `nvidia/cuda:12.1-runtime-ubuntu22.04`, installs
ffmpeg + python deps, mounts weights and voices at runtime.

`docker-compose.yml` — add alongside existing services:
```yaml
voxcpm-tts:
  build: ./voxcpm-tts-inference
  environment:
    VOXCPM_MODEL_PATH: /models/VoxCPM2
  volumes:
    - /DATA/USERS/vibesh/models/VoxCPM2:/models/VoxCPM2:ro
    - ./voxcpm-tts-inference/voices:/app/voices:ro
  ports: ["8080:8080"]
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            capabilities: [gpu]
```

Switching providers is then: stop `svara-tts`, start `voxcpm-tts`,
orchestrator keeps `TTS_BASE_URL=http://voxcpm-tts:8080`.

---

## 10. Acceptance tests

Each must pass before declaring v1 done:

1. **Health**: `curl :8080/healthz` → 200 within 120 s of container start.
2. **Voices**: `curl :8080/v1/voices` returns ≥ 4 voices, each with
   `voice_id`, `name`, `language_code`.
3. **Synthesize**: `POST /v1/audio/speech` with a known voice_id returns
   a non-empty WAV that plays and matches the requested content (manual
   listen).
4. **Unknown voice**: `POST` with bogus voice → `404
   {"error":"unknown_voice", ...}`.
5. **Orchestrator swap**: point orchestrator `TTS_BASE_URL` at
   `http://voxcpm-tts:8080`, submit a lip-sync job via existing API, get
   an MP4 back that has audio and lip movement.
6. **Svara round-trip**: flip `TTS_BASE_URL` back to Svara, verify
   orchestrator still works unchanged.

---

## 11. Phased plan

1. **Scaffold** — directory, requirements, voices.yaml with 2 presets,
   stub endpoints returning 501. Confirm starts and responds.
2. **Engine integration** — load VoxCPM in lifespan, wire `/v1/audio/speech`
   for WAV only. Acceptance tests 1–4.
3. **Voice catalog** — ship 4–6 reference clips, finalize `voices.yaml`.
4. **Format transcode** — add mp3/opus/aac paths via ffmpeg.
5. **Dockerize** — Dockerfile + compose entry. Acceptance test 5.
6. **Swap validation** — run both Svara and VoxCPM behind a compose
   profile, confirm `TTS_BASE_URL` flip works both directions
   (acceptance test 6).
7. **Doc updates** — append entry to `docs/PLAN_AND_EXECUTION.md §4`,
   add VoxCPM row to `docs/PLUGGING_NEW_MODELS.md` examples.

---

## 12. Known risks

- **Voice inventory is curated, not arbitrary.** Svara exposes a catalog
  of pre-trained speakers; VoxCPM clones from clips. If the user expects
  "pick any of 20 voices," we need to record/license 20 reference clips.
- **48 kHz vs 16 kHz.** MuseTalk whisper-encodes audio internally;
  verify that serving 48 kHz WAV doesn't break its preprocessing. If it
  does, resample to 16 kHz in the adapter or in this service.
- **GPU contention.** VoxCPM2 uses ~8 GB VRAM, MuseTalk another ~4–6 GB.
  Single-GPU deployments may OOM; document minimum as 16 GB or split
  across GPUs.
- **First-request cold start.** Model load is ~15–30 s. Include a
  warm-up synth in the lifespan so the first real request is fast.
- **Disk.** `/home` is 100% full. Weights stay on `/DATA`, mounted
  read-only into the container.
