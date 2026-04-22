# API Contract — Text + Face → Lip-Synced Video

This document is the **source of truth** for every request/response exchanged
between the services in this project. It is the invariant: when we swap a
model (TTS or lip-sync), the new implementation must match these contracts.
Orchestrator business logic depends only on these shapes — not on the
underlying model.

Three services:

| Service       | Default URL               | Role                                    |
|---------------|---------------------------|-----------------------------------------|
| Orchestrator  | `http://localhost:8000`   | Public API + job queue + UI host        |
| Svara TTS     | `http://localhost:8080`   | Text → audio (existing, unchanged)      |
| MuseTalk API  | `http://localhost:8081`   | (Face + audio) → lip-synced MP4 (new)   |

The orchestrator is the **only** service that the frontend/UI and external
clients talk to. The other two are internal.

---

## 1. Orchestrator API (public)

Base: `http://<orchestrator-host>:8000`
Versioned under `/api/v1`.

All requests/responses use JSON unless stated otherwise.
Errors use the shape:
```json
{ "error": "short_code", "detail": "human readable reason" }
```
with appropriate HTTP status codes (400/404/422/500).

### 1.1 `POST /api/v1/jobs`

Submit a new lip-sync job.

**Request** — `multipart/form-data`

| Field            | Type         | Required | Description                                                          |
|------------------|--------------|----------|----------------------------------------------------------------------|
| `text`           | string       | yes      | Text to speak. No hard length limit in v1.                           |
| `face`           | file         | yes      | `image/jpeg`, `image/png`, or `video/mp4`.                           |
| `voice`          | string       | no       | Voice ID accepted by the active TTS adapter (e.g. `hi_female`). If omitted, the orchestrator uses `DEFAULT_VOICE` env var; if that is unset, it falls back to the first voice returned by the TTS adapter. |
| `tts_model`      | string       | no       | Override the active TTS adapter by name. Falls back to server env.   |
| `lipsync_model`  | string       | no       | Override the active lip-sync adapter by name.                        |
| `params`         | string(JSON) | no       | Pass-through knobs, e.g. `{"bbox_shift":5,"temperature":0.7}`.       |

**Response** — `201 Created`
```json
{ "job_id": "b9d31e4c-...", "status": "queued" }
```

**Errors**
- `400 bad_request` — missing field or unsupported file type.
- `400 no_voice_available` — `voice` omitted, no `DEFAULT_VOICE` configured, and the TTS adapter returned no voices.
- `404 unknown_voice` — voice not offered by the active TTS adapter.
- `404 unknown_model` — `tts_model` / `lipsync_model` not registered.
- `502 tts_unreachable` — `voice` omitted and the orchestrator could not reach the TTS adapter to pick a default.

**curl**
```bash
curl -sS -X POST http://localhost:8000/api/v1/jobs \
  -F text="नमस्ते, मैं स्वरा हूं।" \
  -F voice=hi_female \
  -F face=@/path/to/face.jpg \
  -F 'params={"bbox_shift":5}'
```

---

### 1.2 `GET /api/v1/jobs/{job_id}`

Poll job status.

**Response** — `200 OK`
```json
{
  "job_id": "b9d31e4c-...",
  "status": "queued | running | done | failed",
  "stage":  "tts | lipsync | done | null",
  "progress": 0,
  "created_at": "2026-04-19T10:20:30Z",
  "updated_at": "2026-04-19T10:20:45Z",
  "preview_url":  "/api/v1/jobs/b9d31e4c-.../preview",
  "download_url": "/api/v1/jobs/b9d31e4c-.../download",
  "error": null
}
```

- `preview_url` and `download_url` are only valid when `status == "done"`.
- `error` is `null` until `status == "failed"`, then a short human message.
- `progress` is best-effort (0-100); may stay at 0 if the backend does not
  report progress.

**Errors**
- `404 not_found` — no such job.

---

### 1.3 `GET /api/v1/jobs/{job_id}/preview`

Inline MP4 suitable for a browser `<video>` tag.

- `200 OK`, `Content-Type: video/mp4`, no `Content-Disposition`.
- `404 not_found` or `409 not_ready` if job not done.

---

### 1.4 `GET /api/v1/jobs/{job_id}/download`

Same bytes as preview, but forces a download.

- `200 OK`, `Content-Type: video/mp4`,
  `Content-Disposition: attachment; filename="lipsync_{job_id}.mp4"`.

---

### 1.5 `DELETE /api/v1/jobs/{job_id}`

Remove job and all associated files.

- `204 No Content`
- `404 not_found`

---

### 1.6 `GET /api/v1/voices`

List voices supported by the currently selected TTS adapter. Proxies the
underlying TTS service.

**Response** — `200 OK`
```json
{
  "voices": [
    {
      "voice_id": "hi_female",
      "name": "Hindi (Female)",
      "model_id": "svara-tts-v1",
      "gender": "female",
      "language_code": "hi"
    }
  ]
}
```

Every voice object MUST have `voice_id`, `name`, and `language_code`.
`gender` and `description` are optional.

---

### 1.7 `GET /api/v1/models`

**Response** — `200 OK`
```json
{
  "tts":     { "active": "svara-tts-v1",  "available": ["svara-tts-v1"] },
  "lipsync": { "active": "musetalk-v1.5", "available": ["musetalk-v1.5"] }
}
```

---

## 2. MuseTalk API (internal)

Base: `http://<musetalk-host>:8081`

### 2.1 `POST /lipsync`

Generate a lip-synced MP4 from a face (image or short video) and an audio
track.

**Request** — `multipart/form-data`

| Field    | Type         | Required | Description                                                                     |
|----------|--------------|----------|---------------------------------------------------------------------------------|
| `face`   | file         | yes      | `image/jpeg`, `image/png`, or `video/mp4`.                                      |
| `audio`  | file         | yes      | `audio/wav` (16-bit PCM preferred; other sample rates accepted).                |
| `params` | string(JSON) | no       | See below.                                                                      |

`params` schema (all keys optional):
```json
{
  "bbox_shift": 0,
  "extra_margin": 10,
  "parsing_mode": "jaw",
  "fps": 25,
  "version": "v15",
  "left_cheek_width": 90,
  "right_cheek_width": 90,
  "batch_size": 8,
  "use_float16": true
}
```

**Response** — `200 OK`, `Content-Type: video/mp4`
The MP4 body is streamed. Audio is already muxed into the file.

**Errors** — `422`
```json
{ "error": "no_face_detected", "detail": "Could not locate a face in the input image" }
```
Other error codes: `bad_input`, `audio_decode_failed`, `inference_failed`.

### 2.2 `GET /healthz`

```json
{ "status": "ok", "model": "musetalk-v1.5", "device": "cuda:0" }
```

---

## 3. Svara TTS (internal, existing — unchanged)

Base: `http://<tts-host>:8080`

Full schema lives in `svara-tts-inference/api/models.py`. This section
documents only what the orchestrator depends on.

### 3.1 `POST /v1/audio/speech`

**Request** — `application/json`
```json
{
  "model": "svara-tts-v1",
  "input": "text to synthesize",
  "voice": "hi_female",
  "response_format": "wav",
  "stream": false
}
```

Full optional fields (see `OpenAISpeechRequest`): `speed`, `reference_audio`,
`reference_transcript`, `temperature`, `top_p`, `top_k`, `repetition_penalty`,
`max_tokens`, `chunk_size`, `buffer_ms`.

**Response**
- `stream=false` → `200 OK`, `Content-Type: audio/wav` (or mp3/opus/aac/pcm).
- `stream=true`  → streamed chunks of the same media type, plus headers
  `X-Sample-Rate: 24000`, `X-Channels: 1`.

### 3.2 `GET /v1/voices`

```json
{ "voices": [ { "voice_id": "hi_female", "name": "Hindi (Female)", "model_id": "svara-tts-v1", "gender": "female", "language_code": "hi" } ] }
```

---

## 4. Adapter Contract (Python)

The orchestrator talks to TTS / lip-sync only through these Protocols.
Implementations live in `orchestrator/adapters/`.

```python
from typing import Protocol

class TTSAdapter(Protocol):
    name: str

    async def synthesize(
        self,
        text: str,
        voice: str,
        fmt: str = "wav",
        **kwargs,
    ) -> tuple[bytes, str]:
        """Return (audio_bytes, mime_type)."""
        ...

    async def list_voices(self) -> list[dict]:
        """Return voices in the shape documented in §1.6."""
        ...

class LipSyncAdapter(Protocol):
    name: str

    async def generate(
        self,
        face: bytes,
        face_filename: str,         # e.g. "face.jpg" / "clip.mp4"
        audio_wav: bytes,
        params: dict | None = None,
    ) -> bytes:
        """Return the MP4 bytes."""
        ...
```

Adding a new model = new file `adapters/tts_<name>.py` or
`adapters/lipsync_<name>.py` implementing the Protocol, a registry entry in
`adapters/__init__.py`, and flipping `TTS_ADAPTER=<name>` /
`LIPSYNC_ADAPTER=<name>` in env. No orchestrator business logic changes.

See `PLUGGING_NEW_MODELS.md` for the step-by-step.

---

## 5. Request Flow

```
UI ──POST /api/v1/jobs──▶ Orchestrator
                            │
                            ├─ persist Job(row, status=queued)
                            ├─ save face upload to storage/inputs/
                            └─ asyncio.create_task(run_job)
UI ◀──201 {job_id}─────────┘

[worker]  status=running, stage=tts
          └─ TTSAdapter.synthesize(text, voice) ──HTTP──▶ Svara /v1/audio/speech
             └─ save to storage/tts/{job}.wav

          stage=lipsync
          └─ LipSyncAdapter.generate(face, wav) ──HTTP──▶ MuseTalk /lipsync
             └─ save to storage/outputs/{job}.mp4

          status=done

UI ──GET /api/v1/jobs/{id}──▶ Orchestrator  (poll every ~1s)
UI ──GET /api/v1/jobs/{id}/download──▶ Orchestrator  (once status=done)
```

---

## 6. Versioning

- Orchestrator endpoints are versioned via the `/api/v1/` prefix. Any
  breaking change → bump to `/api/v2/`, keep `/api/v1/` until clients migrate.
- Internal contracts (MuseTalk API, adapter Protocol) are not versioned; they
  are allowed to change in lockstep with the orchestrator.
- This document is versioned via git. Every PR that changes a contract MUST
  edit this file first.
