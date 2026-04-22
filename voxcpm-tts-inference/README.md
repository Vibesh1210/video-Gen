# VoxCPM TTS Service

Drop-in replacement for `svara-tts-inference/`. Exposes the same HTTP
contract (`POST /v1/audio/speech`, `GET /v1/voices`) backed by
[VoxCPM2](https://huggingface.co/openbmb/VoxCPM2). The orchestrator
switches providers by flipping `TTS_URL`; no adapter code changes.

See `docs/VOXCPM_TTS_SPEC.md` for the full design doc.

## Run locally

Weights are expected at `/DATA/USERS/vibesh/models/VoxCPM2` (the download
step covers this).

```bash
cd voxcpm-tts-inference
pip install torch==2.5.1 voxcpm
pip install -r requirements.txt

VOXCPM_MODEL_PATH=/DATA/USERS/vibesh/models/VoxCPM2 \
  uvicorn api.server:app --host 0.0.0.0 --port 8080
```

## Smoke test

```bash
# Health
curl -s localhost:8080/healthz

# Catalog
curl -s localhost:8080/v1/voices | jq

# Synth
curl -s -X POST localhost:8080/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello from VoxCPM.","voice":"default","response_format":"wav"}' \
  --output out.wav
```

## Swapping in for Svara

`docker-compose.yml` declares both services. To switch:

```bash
# use VoxCPM (default)
docker compose up voxcpm-tts musetalk-api orchestrator frontend

# use Svara instead
docker compose up tts musetalk-api orchestrator frontend
# and point the orchestrator: TTS_URL=http://tts:8080
```

Locally, just set `TTS_URL` on the orchestrator to whichever host:port is
running. No orchestrator code change required.

## Voice catalog

Edit `voices.yaml`. Two modes per entry:

- `clone` — uses `reference_wav` (a clip in `voices/`). Optional
  `prompt_text` (transcript of the clip) unlocks *ultimate cloning*
  quality.
- `design` — no reference audio; instead a natural-language description
  in `design_prompt` (e.g. `"A warm middle-aged male narrator"`).

Restart the service after editing `voices.yaml`.
