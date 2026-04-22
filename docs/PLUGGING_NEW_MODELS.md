# Plugging In a New Model

How to swap Svara TTS or MuseTalk for a different model. The orchestrator
is designed so this never requires touching business logic — only a new
adapter file + a registry entry + an env flip.

---

## 1. Pick the right interface

Open `orchestrator/adapters/base.py`:

```python
class TTSAdapter(Protocol):
    name: str
    async def synthesize(self, text: str, voice: str, fmt: str = "wav",
                         **kwargs) -> tuple[bytes, str]: ...
    async def list_voices(self) -> list[dict]: ...

class LipSyncAdapter(Protocol):
    name: str
    async def generate(self, face: bytes, face_filename: str,
                       audio_wav: bytes,
                       params: dict | None = None) -> bytes: ...
```

Pick `TTSAdapter` or `LipSyncAdapter`.

## 2. Implement the adapter

Create `orchestrator/adapters/tts_<name>.py` or
`orchestrator/adapters/lipsync_<name>.py`. Typical pattern — a thin httpx
client around the new model's HTTP API:

```python
# orchestrator/adapters/tts_elevenlabs.py
import httpx
from .base import TTSAdapter

class ElevenLabsTTS:
    name = "elevenlabs"

    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.AsyncClient(base_url=base_url,
                                         headers={"xi-api-key": api_key})

    async def synthesize(self, text, voice, fmt="wav", **kwargs):
        r = await self._client.post(f"/v1/text-to-speech/{voice}",
                                    json={"text": text,
                                          "output_format": fmt})
        r.raise_for_status()
        return r.content, r.headers["content-type"]

    async def list_voices(self):
        r = await self._client.get("/v1/voices")
        r.raise_for_status()
        return [
            {"voice_id": v["voice_id"],
             "name": v["name"],
             "language_code": v.get("labels", {}).get("language", "en")}
            for v in r.json()["voices"]
        ]
```

**Contract requirements — not optional.**
- `synthesize` MUST return raw audio bytes plus a mime type like
  `"audio/wav"`. Lip-sync expects WAV; if your TTS can't emit WAV, have the
  adapter transcode via ffmpeg before returning.
- `list_voices` MUST return `voice_id`, `name`, `language_code` per voice.
- `generate` MUST return MP4 bytes with audio already muxed.

## 3. Register it

Edit `orchestrator/adapters/__init__.py`. The registry maps adapter names to
**factories** `(Config) -> Adapter` so each can read its own env vars:

```python
import os
from .tts_elevenlabs import ElevenLabsTTS    # add this

TTS_ADAPTERS = {
    "svara":      lambda cfg: SvaraTTSAdapter(cfg.tts_url, timeout=cfg.tts_timeout),
    "mock":       lambda cfg: MockTTSAdapter(),
    "elevenlabs": lambda cfg: ElevenLabsTTS(       # add this
        base_url=os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io"),
        api_key=os.environ["ELEVENLABS_API_KEY"],
    ),
}
```

## 4. (Optional) Extend the shared Config

If several adapters share the same knobs, add them to `orchestrator/config.py`'s
`Config` dataclass. For one-off settings, reading `os.getenv` in the factory
(as above) is fine.

## 5. Flip the switch

```bash
# ~/.env for orchestrator
TTS_ADAPTER=elevenlabs
ELEVENLABS_BASE_URL=https://api.elevenlabs.io
ELEVENLABS_API_KEY=sk-...
```

Restart the orchestrator. No other code changes needed.

## 6. Update the contract docs

`docs/API_CONTRACT.md` §1.6 (voices) is implementation-neutral, but any new
optional `params` keys the adapter understands should be documented there so
UI and API clients know what to send.

Add an entry to `docs/PLAN_AND_EXECUTION.md` §4 (Execution Log) noting the
swap.

## 7. Verify

```bash
curl http://localhost:8000/api/v1/models   # "active" reflects new name
curl http://localhost:8000/api/v1/voices   # voices from new provider

# end-to-end smoke
JID=$(curl -sS -X POST http://localhost:8000/api/v1/jobs \
  -F text="smoke test" -F voice=<one of the new voice ids> \
  -F face=@sample.jpg | jq -r .job_id)
# poll and download as usual
```

If anything in that flow breaks, the adapter contract is not being
honored — fix the adapter, not the orchestrator.
