# orchestrator

Public-facing API + job queue. Glues TTS and lip-sync services together via
an adapter layer so either can be swapped without changing business logic.

Contract: see `../docs/API_CONTRACT.md` §1.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# from orchestrator/
python server.py
# or
uvicorn server:app --host 0.0.0.0 --port 8000
```

## Environment

| Var                     | Default                   | Notes                                        |
|-------------------------|---------------------------|----------------------------------------------|
| `ORCHESTRATOR_HOST`     | `0.0.0.0`                 |                                              |
| `ORCHESTRATOR_PORT`     | `8000`                    |                                              |
| `TTS_URL`               | `http://localhost:8080`   | Svara TTS base URL                           |
| `MUSETALK_URL`          | `http://localhost:8081`   | MuseTalk API base URL                        |
| `TTS_ADAPTER`           | `svara`                   | `svara` or `mock`                            |
| `LIPSYNC_ADAPTER`       | `musetalk`                | `musetalk` or `mock`                         |
| `JOB_STORE_PATH`        | `./data/jobs.db`          | SQLite path                                  |
| `STORAGE_ROOT`          | `./data/storage`          | inputs / tts / outputs live here             |
| `MAX_CONCURRENT_JOBS`   | `1`                       | asyncio.Semaphore                            |
| `TTS_TIMEOUT`           | `120`                     | seconds                                      |
| `LIPSYNC_TIMEOUT`       | `900`                     | seconds (long videos)                        |
| `LOG_LEVEL`             | `INFO`                    |                                              |

## Smoke test (with mocks — no GPU services needed)

```bash
TTS_ADAPTER=mock LIPSYNC_ADAPTER=mock python server.py &
curl -sf http://localhost:8000/healthz | jq

JOB=$(curl -sS -X POST http://localhost:8000/api/v1/jobs \
  -F text="Hello world" \
  -F voice=mock_en \
  -F face=@../MuseTalk/data/video/soub.jpg | jq -r .job_id)
echo "job=$JOB"

# poll until done
until [ "$(curl -sf http://localhost:8000/api/v1/jobs/$JOB | jq -r .status)" = "done" ]; do
  sleep 1
done

curl -sS http://localhost:8000/api/v1/jobs/$JOB/download -o out.mp4
ffprobe out.mp4
```

## Plugging a new model

See `../docs/PLUGGING_NEW_MODELS.md`. Summary: implement `TTSAdapter` or
`LipSyncAdapter` (`adapters/base.py`), register in `adapters/__init__.py`,
flip `TTS_ADAPTER=<name>` / `LIPSYNC_ADAPTER=<name>`.
