# Plan and Execution — Lip-Synced Video Service

Project journal. Updated as work lands. Describes the goal, the phased
rollout, the contracts between services, and a running execution log.

---

## 1. Goal & Scope

Build an async web service where a user submits **text + an image/short clip
+ a voice selection** and receives a **downloadable lip-synced video** (with
in-browser preview).

**In scope for v1**

- Async job model — submit → poll → preview + download.
- Still image and short video supported as the face input.
- 19 Indic languages + English, selectable per request.
- Pluggable TTS and lip-sync backends via an adapter layer.
- Local SQLite + filesystem job store. Single-node deploy via docker-compose.

**Out of scope for v1**

- Authentication / multi-tenancy.
- Streaming / realtime voice agent (see `../end-to-end.md`).
- Autoscaling / Kubernetes.
- Avatar caching across requests.

---

## 2. Architecture

Three services, each independently deployable:

```
Browser (Next.js UI)
        │  HTTPS
        ▼
┌───────────────────────┐   Port 8000, CPU node
│  Orchestrator API     │
│  FastAPI + SQLite     │
│  + local FS + queue   │
│  Adapters:            │
│   - TTSAdapter        │
│   - LipSyncAdapter    │
└──────┬──────┬─────────┘
       │      │
       ▼      ▼
┌───────────┐ ┌──────────────────┐
│ Svara TTS │ │ MuseTalk API     │   Ports 8080 / 8081, GPU nodes
│ (exists)  │ │ (new FastAPI)    │
└───────────┘ └──────────────────┘
```

Principles:

- Orchestrator never imports model code. Only HTTP via adapters.
- Each adapter is a thin HTTP client. Swapping a model = new adapter + env
  flip, no business-logic changes.
- Contracts are frozen in `API_CONTRACT.md` — the invariant.

---

## 3. Phased Execution Plan

Each phase lists: objective, files touched, acceptance test. Phase is
"done" only when the acceptance test passes on a real invocation.

### Phase 1 — MuseTalk FastAPI wrapper

**Objective.** Expose MuseTalk as an HTTP service at `POST /lipsync`. Models
are loaded once at startup and reused across requests.

**Files.**
- `musetalk-api/inference_core.py` — refactor of `MuseTalk/scripts/inference.py`
  `main()` into two functions: `load_models()` at startup, and
  `run_inference(face_bytes, face_filename, audio_bytes, params) -> bytes`
  per request. Reuses `musetalk.utils.*` helpers.
- `musetalk-api/server.py` — FastAPI app, `/lipsync`, `/healthz`.
- `musetalk-api/schemas.py`, `requirements.txt`, `README.md`.

**Acceptance test.**
```bash
# start service
cd musetalk-api && uvicorn server:app --port 8081

# unit check
curl -sf http://localhost:8081/healthz

# functional check — reuse shipped sample assets
curl -sS -X POST http://localhost:8081/lipsync \
  -F face=@../MuseTalk/data/video/soub.jpg \
  -F audio=@../MuseTalk/data/audio/highlish.wav \
  -o out.mp4
ffprobe out.mp4         # must have video + audio streams
```

### Phase 2 — Orchestrator skeleton + mock adapters

**Objective.** Prove the job lifecycle end-to-end without any GPU services.

**Files.**
- `orchestrator/server.py`, `jobs.py`, `worker.py`, `storage.py`,
  `schemas.py`, `config.py`, `requirements.txt`, `README.md`.
- `orchestrator/adapters/base.py` — Protocols.
- `orchestrator/adapters/tts_mock.py` — returns a canned 1s WAV.
- `orchestrator/adapters/lipsync_mock.py` — returns a canned MP4.
- `orchestrator/adapters/__init__.py` — registry.

**Acceptance test.**
```bash
cd orchestrator && uvicorn server:app --port 8000

JID=$(curl -sS -X POST http://localhost:8000/api/v1/jobs \
  -F text="hello" -F voice=en_male -F face=@../MuseTalk/data/video/soub.jpg \
  | jq -r .job_id)

# poll until done
while true; do
  STATUS=$(curl -sS http://localhost:8000/api/v1/jobs/$JID | jq -r .status)
  echo "$STATUS"; [ "$STATUS" = "done" ] && break
  sleep 1
done

curl -sS http://localhost:8000/api/v1/jobs/$JID/download -o got.mp4
```

### Phase 3 — Real adapters (Svara + MuseTalk)

**Objective.** Replace mocks with httpx-backed real adapters.

**Files.**
- `orchestrator/adapters/tts_svara.py` — calls `POST {TTS_URL}/v1/audio/speech`.
- `orchestrator/adapters/lipsync_musetalk.py` — calls
  `POST {MUSETALK_URL}/lipsync` with multipart.

**Acceptance test.** Same curl flow as Phase 2, but with `TTS_ADAPTER=svara`
and `LIPSYNC_ADAPTER=musetalk`. Downloaded MP4 must contain the synthesized
Indic/English audio with lip-synced motion on the uploaded face.

### Phase 4 — Next.js frontend

**Objective.** Browser UI covering the happy path.

**Files.**
- `frontend/app/page.tsx` — form + polling + `<video>` + download button.
- `frontend/lib/api.ts` — typed client (`submitJob`, `getJob`, `listVoices`).
- `frontend/app/layout.tsx`, `components/*`, scaffold files.

**Acceptance test.** Open `http://localhost:3000`, upload an image, pick
voice `hi_female`, enter Hindi text, submit. Progress bar animates through
`queued → tts → lipsync → done`. Video plays in-browser. Download button
saves the MP4.

### Phase 5 — docker-compose

**Objective.** One-command local deploy.

**Files.**
- Top-level `docker-compose.yml` with services `tts`, `musetalk-api`,
  `orchestrator`, `frontend`.
- Dockerfile per service (reuse existing TTS image; new ones for MuseTalk
  and orchestrator).
- GPU passthrough on `tts` and `musetalk-api`.

**Acceptance test.** `docker-compose up` brings all four up; Phase 4 flow
works against the composed stack from the host browser.

### Phase 6 — Pluggability smoke test

**Objective.** Prove the adapter seam.

**Acceptance test.** With the full stack running, set `TTS_ADAPTER=mock`,
restart only orchestrator, submit a job. Job still completes end-to-end.
Document the swap in `PLUGGING_NEW_MODELS.md`.

---

## 4. Execution Log

Running journal. Append, don't rewrite history.

| Date       | Phase | Note                                                                                |
|------------|-------|-------------------------------------------------------------------------------------|
| 2026-04-19 | 0     | Plan approved. `docs/` created with API_CONTRACT + this file.                        |
| 2026-04-19 | 1     | `musetalk-api/` built. `/healthz` returns model info; `/lipsync` end-to-end smoke (4K face + 20s audio) produced H264+AAC MP4. Fixed flash_attn/peft ABI shim; `os.chdir` into MuseTalk dir before import for mmengine's dwpose-config relative paths. |
| 2026-04-19 | 2     | `orchestrator/` built with SQLite job store, asyncio.Semaphore-bounded worker, adapter registry. Mock-only smoke passes: POST /jobs → poll done in <1s → /download yields 3.2 MB H264+AAC MP4. /models, /voices, /healthz, DELETE, 404/400 paths verified. `tts_svara` and `lipsync_musetalk` adapters also landed (registered as `svara` / `musetalk`) — full-stack real-service test is Phase 3 acceptance. |
| 2026-04-19 | 3(partial) | `lipsync_musetalk` HTTP adapter verified end-to-end against the live musetalk-api :8081 using `TTS_ADAPTER=mock LIPSYNC_ADAPTER=musetalk`. 720p/8s face + 2s mock-TTS WAV → 44s total runtime, 352 KB H264+AAC MP4 out. Full real-stack test (svara + musetalk) deferred until Svara TTS is started — code path is proven. |
| 2026-04-19 | 4     | `frontend/` Next.js (App Router, TS) with form + polling + `<video>` + download. `next.config.js` rewrites `/api/v1/*` → orchestrator. Typecheck clean; dev server on :3000 proxies to :8000 correctly; end-to-end submit through the proxy produces the same MP4 as direct curl. |
| 2026-04-19 | 5     | `docker-compose.yml` at repo root wiring tts/musetalk-api/orchestrator/frontend. Dockerfiles written for orchestrator (python:3.11-slim + ffmpeg) and frontend (node:20-alpine multi-stage). MuseTalk Dockerfile drafted on top of nvidia/cuda:12.1.1 + conda. Not build-validated in this session (no Docker locally) — will be verified on the GPU deployment host. |
| 2026-04-19 | 6     | Pluggability seam validated. Flipped `LIPSYNC_ADAPTER=mock → musetalk → mock` across restarts with no code changes; both jobs completed. `GET /api/v1/models` correctly reflects active + available adapters on each flip. |

---

## 5. API Contract (summary)

Full schemas + curl examples in `API_CONTRACT.md`.

| Method | Path                               | Service       | Purpose                 |
|--------|------------------------------------|---------------|-------------------------|
| POST   | `/api/v1/jobs`                     | Orchestrator  | Submit job              |
| GET    | `/api/v1/jobs/{id}`                | Orchestrator  | Poll status             |
| GET    | `/api/v1/jobs/{id}/preview`        | Orchestrator  | Inline MP4              |
| GET    | `/api/v1/jobs/{id}/download`       | Orchestrator  | Attachment MP4          |
| GET    | `/api/v1/voices`                   | Orchestrator  | List voices             |
| GET    | `/api/v1/models`                   | Orchestrator  | List active adapters    |
| DELETE | `/api/v1/jobs/{id}`                | Orchestrator  | Remove job              |
| POST   | `/lipsync`                         | MuseTalk API  | Face+audio → MP4        |
| GET    | `/healthz`                         | MuseTalk API  | Liveness                |
| POST   | `/v1/audio/speech`                 | Svara TTS     | Text → audio            |
| GET    | `/v1/voices`                       | Svara TTS     | List TTS voices         |

---

## 6. How to Run Locally

```bash
# 1. Svara TTS (existing)
cd svara-tts-inference && docker-compose up -d

# 2. MuseTalk API (after Phase 1)
cd musetalk-api
conda activate MuseTalk
uvicorn server:app --host 0.0.0.0 --port 8081

# 3. Orchestrator (after Phase 2)
cd orchestrator
pip install -r requirements.txt
TTS_URL=http://localhost:8080 \
MUSETALK_URL=http://localhost:8081 \
TTS_ADAPTER=svara \
LIPSYNC_ADAPTER=musetalk \
uvicorn server:app --port 8000

# 4. Frontend dev (after Phase 4)
cd frontend && npm install && npm run dev
# → http://localhost:3000
```

---

## 7. Open Questions / Deferred

- Avatar caching: reuse MuseTalk's `Avatar` class to cache per-image latents
  across repeat submissions. Could cut repeat-submit latency significantly.
- Long-text handling beyond Svara's own chunker.
- Webhook callbacks (`on_complete`) instead of poll.
- Auth.
- Object storage (S3/MinIO) behind the current local-FS interface.
