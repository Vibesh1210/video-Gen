# musetalk-api

Thin FastAPI wrapper around MuseTalk. Loads the VAE / UNet / Whisper / face
parser once at startup and reuses them across requests.

Contract: see `../docs/API_CONTRACT.md` §2.

## Install

Requires the MuseTalk conda env (see `../inference-guide.md`). On top of it:

```bash
conda activate MuseTalk
cd musetalk-api
pip install -r requirements.txt
```

## Run

```bash
# from musetalk-api/
uvicorn server:app --host 0.0.0.0 --port 8081
```

Environment variables (all optional):

| Var                      | Default                                  |
|--------------------------|------------------------------------------|
| `MUSETALK_HOST`          | `0.0.0.0`                                |
| `MUSETALK_PORT`          | `8081`                                   |
| `MUSETALK_GPU_ID`        | `0`                                      |
| `MUSETALK_USE_FLOAT16`   | `1`                                      |
| `MUSETALK_VERSION`       | `v15`                                    |
| `MUSETALK_UNET_MODEL`    | `models/musetalkV15/unet.pth`            |
| `MUSETALK_UNET_CONFIG`   | `models/musetalkV15/musetalk.json`       |
| `MUSETALK_WHISPER_DIR`   | `models/whisper`                         |
| `LOG_LEVEL`              | `INFO`                                   |

Relative paths resolve inside `../MuseTalk/`.

## Smoke test

```bash
curl -sf http://localhost:8081/healthz | jq

curl -sS -X POST http://localhost:8081/lipsync \
  -F face=@../MuseTalk/data/video/soub.jpg \
  -F audio=@../MuseTalk/data/audio/highlish.wav \
  -F 'params={"bbox_shift":5}' \
  -o out.mp4

ffprobe out.mp4   # must show both video and audio streams
```

## Notes

- GPU access is serialised by a process-wide `threading.Lock` — concurrent
  `POST /lipsync` requests queue. Scale by running multiple processes on
  separate GPUs and load-balancing upstream.
- The first request after startup is warmer than subsequent ones (CUDA graph
  capture, autotune).
