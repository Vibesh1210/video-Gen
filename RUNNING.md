# Running the Lip-Sync Service

From zero to a working `text + face → lip-synced MP4` pipeline.

---

## TL;DR — copy-paste commands

Four terminals, one per service. Run in this order. Exact commands used by
`start.sh`, so this stays in sync with the automation.

### 1. Svara TTS — port 8080 (GPU, conda `base`)

```bash
cd /home/vibesh/museTalk/svara-tts-inference/api
API_HOST=0.0.0.0 API_PORT=8080 \
VLLM_MODEL=kenpath/svara-tts-v1 \
VLLM_GPU_MEMORY_UTILIZATION=0.5 \
VLLM_MAX_MODEL_LEN=4096 \
SNAC_DEVICE=cpu \
CUDA_VISIBLE_DEVICES=0 \
python -m uvicorn server:app --host 0.0.0.0 --port 8080
```

Wait until you see `Application startup complete.` then verify:
```bash
curl -sf http://127.0.0.1:8080/v1/voices | head -c 400
```

### 2. MuseTalk API — port 8081 (GPU, conda env `MuseTalk`)

```bash
source /home/vibesh/miniconda3/etc/profile.d/conda.sh
conda activate MuseTalk

cd /home/vibesh/museTalk/musetalk-api
MUSETALK_HOST=0.0.0.0 MUSETALK_PORT=8081 \
MUSETALK_GPU_ID=0 \
MUSETALK_USE_FLOAT16=1 \
MUSETALK_VERSION=v15 \
python server.py
```

Verify:
```bash
curl -sf http://127.0.0.1:8081/healthz
```

### 3. Orchestrator — port 8000 (CPU, conda `base`)

```bash
cd /home/vibesh/museTalk/orchestrator
ORCHESTRATOR_HOST=0.0.0.0 ORCHESTRATOR_PORT=8000 \
TTS_URL=http://localhost:8080 \
MUSETALK_URL=http://localhost:8081 \
TTS_ADAPTER=svara \
LIPSYNC_ADAPTER=musetalk \
MAX_CONCURRENT_JOBS=1 \
python server.py
```

Verify:
```bash
curl -sf http://127.0.0.1:8000/healthz
curl -sf http://127.0.0.1:8000/api/v1/models | jq
```

### 4. Frontend — port 3000 (Node)

```bash
cd /home/vibesh/museTalk/frontend
[ -d node_modules ] || npm install
ORCHESTRATOR_URL=http://localhost:8000 PORT=3000 npm run dev
```

Open `http://localhost:3000` (tunnel port 3000 from your laptop via SSH
`-L 3000:vision:3000`).

### One-shot (all four in background)

```bash
cd /home/vibesh/museTalk && ./start.sh            # start
./start.sh status                                  # table
./start.sh logs orchestrator                       # tail one log
./start.sh stop                                    # kill all
```

Each service's log is at `/tmp/lipsync-<svara|musetalk|orchestrator|frontend>.log`.

---

Four processes are involved:

| Port | Service         | Role                                 | GPU? |
|-----:|-----------------|--------------------------------------|------|
| 3000 | `frontend/`     | Next.js UI                           | no   |
| 8000 | `orchestrator/` | Public API + job queue               | no   |
| 8080 | `svara-tts-inference/` | Text → audio                  | yes  |
| 8081 | `musetalk-api/` | (image/video + audio) → lip-synced MP4 | yes |

Three ways to run it:

1. **Mocks only** — no GPU. Proves the pipeline, UI, and adapters.
2. **Native (local Python / conda)** — what we've actually used during dev.
3. **Docker Compose** — one command, for deployment.

---

## 0. Prerequisites

- Linux with an NVIDIA GPU (for real TTS + lip-sync). CPU is fine for mocks.
- `ffmpeg` on `PATH` (`sudo apt-get install -y ffmpeg`).
- Python 3.10+ (miniconda recommended).
- Node 20+ (for the frontend).
- Docker + `docker compose` (only for §3).
- MuseTalk model weights already downloaded under
  `MuseTalk/models/` (`musetalkV15/`, `whisper/`, `sd-vae/`, `dwpose/`,
  `face-parse-bisent/`). If missing, follow `inference-guide.md` §2.

---

## 1. Mocks-only (fastest — no GPU)

Proves the full submit → poll → preview → download flow without any model
services running. Great for UI work or demoing the pipeline.

```bash
# Terminal 1 — orchestrator with both adapters mocked
cd /home/vibesh/museTalk/orchestrator
pip install -r requirements.txt
TTS_ADAPTER=mock LIPSYNC_ADAPTER=mock python server.py

# Terminal 2 — frontend
cd /home/vibesh/museTalk/frontend
npm install
ORCHESTRATOR_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:3000`. Pick `Mock English`, type anything, upload any
image, click **Generate**. You'll get a playable MP4 in ~1 s.

---

## 2. Native (local Python + Node)

This is the flow we've been using. Four terminals.

### 2.1 Start Svara TTS (GPU)

```bash
# Terminal 1
cd /home/vibesh/museTalk/svara-tts-inference
docker compose up
# first launch downloads the svara-tts-v1 model from HF (several GB)
```

Verify:
```bash
curl -sf http://localhost:8080/v1/voices | head -c 400
```

### 2.2 Start MuseTalk API (GPU)

```bash
# Terminal 2
conda activate MuseTalk              # the env from inference-guide.md §1.2
cd /home/vibesh/museTalk/musetalk-api
pip install -r requirements.txt      # one-time, fastapi + uvicorn
python server.py                      # or: uvicorn server:app --port 8081
```

Verify:
```bash
curl -sf http://localhost:8081/healthz
# {"status":"ok","model":"musetalk-v15","device":"cuda:0","dtype":"torch.float16"}
```

Startup takes ~10 s (model load). First `/lipsync` call is warmer than
subsequent ones.

### 2.3 Start the Orchestrator

```bash
# Terminal 3
cd /home/vibesh/museTalk/orchestrator
pip install -r requirements.txt

TTS_URL=http://localhost:8080 \
MUSETALK_URL=http://localhost:8081 \
TTS_ADAPTER=svara \
LIPSYNC_ADAPTER=musetalk \
python server.py
```

Verify:
```bash
curl -sf http://localhost:8000/healthz
curl -sf http://localhost:8000/api/v1/models | jq
curl -sf http://localhost:8000/api/v1/voices | jq '.voices | length'
```

### 2.4 Start the Frontend

```bash
# Terminal 4
cd /home/vibesh/museTalk/frontend
npm install                              # one-time
ORCHESTRATOR_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:3000`. Pick a voice, enter text, upload a face, hit
**Generate**. The status dot cycles through `queued → tts → lipsync → done`
and the video auto-plays when ready.

### 2.5 Quick curl end-to-end (no browser)

```bash
JID=$(curl -sS -X POST http://localhost:8000/api/v1/jobs \
  -F text="Hello world from the orchestrator." \
  -F voice=hi_female \
  -F face=@/home/vibesh/museTalk/MuseTalk/data/video/soub.jpg | jq -r .job_id)

until [ "$(curl -sf http://localhost:8000/api/v1/jobs/$JID | jq -r .status)" = "done" ]; do
  sleep 2
done

curl -sS http://localhost:8000/api/v1/jobs/$JID/download -o out.mp4
ffprobe out.mp4
```

---

## 3. Docker Compose (one command, deployable)

Requires:
- Docker + `docker compose`
- NVIDIA Container Toolkit installed on the host
- MuseTalk weights present at `./MuseTalk/models/` on the host (they'll be
  mounted read-only into the `musetalk-api` container)

```bash
cd /home/vibesh/museTalk

# Build images (first time is slow — especially musetalk-api with conda)
docker compose build

# Full stack (GPU)
docker compose up
```

Mock-only (no GPU):

```bash
TTS_ADAPTER=mock LIPSYNC_ADAPTER=mock docker compose up orchestrator frontend
```

Open `http://localhost:3000`.

---

## 4. Environment reference

Only the variables you're likely to touch. Full list per service is in each
service's `README.md`.

| Service      | Var                  | Default                  | Notes                         |
|--------------|----------------------|--------------------------|-------------------------------|
| orchestrator | `TTS_URL`            | `http://localhost:8080`  | Svara base URL                |
| orchestrator | `MUSETALK_URL`       | `http://localhost:8081`  | MuseTalk API base URL         |
| orchestrator | `TTS_ADAPTER`        | `svara`                  | `svara` or `mock`             |
| orchestrator | `LIPSYNC_ADAPTER`    | `musetalk`               | `musetalk` or `mock`          |
| orchestrator | `MAX_CONCURRENT_JOBS`| `1`                      | asyncio.Semaphore width       |
| orchestrator | `LIPSYNC_TIMEOUT`    | `900` s                  | per-request upper bound       |
| musetalk-api | `MUSETALK_GPU_ID`    | `0`                      | picks the CUDA device         |
| musetalk-api | `MUSETALK_USE_FLOAT16`| `1`                     | fp16 inference                |
| frontend     | `ORCHESTRATOR_URL`   | `http://localhost:8000`  | rewrite target for `/api/v1/*`|

---

## 5. Troubleshooting

- **`address already in use: 8000/8081/3000`** — something from a previous
  run is still alive. `pkill -f 'server.py'` for orchestrator/musetalk-api;
  `pkill -f 'next dev'` for the frontend.
- **`tts_unreachable` in a failed job** — Svara isn't up on `$TTS_URL`.
  `curl $TTS_URL/v1/voices` should work.
- **`lipsync_unreachable`** — MuseTalk API isn't up. `curl $MUSETALK_URL/healthz`.
- **`no_face_detected` (422)** — the uploaded image has no detectable face.
  Try another image or a short video.
- **Frontend shows "Failed to load voices"** — `ORCHESTRATOR_URL` is wrong,
  or the orchestrator is down. Next.js logs the rewrite target on startup.
- **MuseTalk first request is slow (~4 min on a 4K image)** — expected. The
  blend loop scales with input resolution. 720p face videos run in ~40 s.
- **Import error around `flash_attn` on musetalk-api startup** — the shim
  at the top of `musetalk-api/server.py` handles this. If it resurfaces,
  check that nothing imported `transformers` before the shim ran.

---

## 6. Pointers

- API contract (what each endpoint expects/returns): `docs/API_CONTRACT.md`
- Execution log and phase breakdown: `docs/PLAN_AND_EXECUTION.md`
- Swapping in a different TTS or lip-sync model: `docs/PLUGGING_NEW_MODELS.md`
- Per-service READMEs for deeper details:
  `orchestrator/README.md`, `musetalk-api/README.md`, `frontend/README.md`,
  `svara-tts-inference/README.md`.
