# End-to-End Voice Agent with LLaMA-Omni2 + MuseTalk

A plan for building a real-time, lip-synced voice agent by combining a speech-to-speech LLM (LLaMA-Omni2) with a lip-sync video generator (MuseTalk).

---

## 1. Goal

Build a conversational agent where:

- A user speaks into a microphone.
- The agent replies with both natural speech **and** a lip-synced video of a pre-recorded avatar appearing to say the reply.
- The whole loop runs with sub-second perceived latency (target: first video frame within ~1 s of the user finishing speaking).

---

## 2. High-Level Architecture

```
mic ─▶ [LLaMA-Omni2] ─▶ response audio ─▶ [MuseTalk + cached avatar] ─▶ lip-synced video ─▶ client
                     (speech-in, speech-out)          (avatar prepared once, offline)
```

Three decoupled services:

1. **LLaMA-Omni2** — handles ASR + LLM reasoning + TTS internally as a single speech-to-speech model. Speech goes in, speech comes out.
2. **MuseTalk (realtime)** — consumes the audio stream and emits lip-synced video frames using a pre-prepared avatar.
3. **Gateway / transport** — WebRTC or WebSocket layer that carries mic audio up and video+audio back down.

Keep these as separate services talking over gRPC or a message bus so any one of them can be swapped out.

---

## 3. Detailed Data Flow

```
┌─────────┐  mic audio ┌──────────────┐  PCM chunks  ┌─────────────────┐
│ Client  │───────────▶│ Gateway (WS/ │─────────────▶│  LLaMA-Omni2    │
│ (WebRTC)│            │  WebRTC SFU) │              │  (S2S)          │
└────┬────┘            └──────┬───────┘              └────────┬────────┘
     │                        │                               │ audio chunks
     │                        │                               ▼
     │                        │                      ┌─────────────────┐
     │                        │                      │ Audio buffer +  │
     │                        │                      │ VAD / barge-in  │
     │                        │                      └────────┬────────┘
     │                        │                               │
     │                        │                               ▼
     │                        │                      ┌─────────────────┐
     │                        │                      │ MuseTalk real-  │
     │                        │                      │ time (cached    │
     │                        │                      │ avatar latents) │
     │                        │                      └────────┬────────┘
     │                        │                               │ frames + audio
     │                        │     video + audio             ▼
     │                        │◀───────────────────── ffmpeg / WebRTC encoder
     │◀───────────────────────┘
```

---

## 4. Component Responsibilities

### 4.1 LLaMA-Omni2 (brain + voice)

- Input: raw 16 kHz PCM from the mic, streamed in 20–80 ms frames.
- Output: synthesized response audio, also streamed in chunks (token-by-token at the speech decoder level).
- Why speech-to-speech (not ASR → LLM → TTS): saves 300–600 ms of pipeline latency, and emits audio progressively so MuseTalk can start generating video before the full reply is done.
- Language note: the open Omni2 checkpoints are English-first. For Hindi / Indic languages, validate quality first; if insufficient, fall back to a pipelined **Indic ASR → LLM → IndicTTS** stack or use a model with broader coverage (Qwen2.5-Omni, Moshi).

### 4.2 MuseTalk (lip-sync)

- Runs the realtime inference path from `scripts/realtime_inference.py`.
- **Avatar prep (offline, once per voice agent):**
  - Record 20–30 seconds of the avatar on camera — frontal, good lighting, natural idle motion (small sway, occasional blinks). Loopable.
  - Run the `Avatar` prep step to cache: `latents.pt`, `coords.pkl`, `mask/*.png`, `full_imgs/*.png`.
  - Longer than 10 seconds is important — short clips cause visible ping-pong when the reply is longer than the source.
- **Per-request cost (online):** Whisper encode → UNet forward (single step) → VAE decode → parsing-mask blend. ~20–40 ms per frame on a decent GPU.
- Produces one 256×256 face per audio window, blended back into the original frame.

### 4.3 Audio buffer / VAD / barge-in

A thin service between Omni2 and MuseTalk that:

- Buffers Omni2's audio output into a rolling window.
- Releases audio to MuseTalk only once enough "future" audio is present to fill MuseTalk's right-padding window (~200–300 ms). This is the minimum latency floor.
- Runs voice activity detection on the **mic input** to detect user interruptions, and on trigger: cancels Omni2 generation, flushes the audio queue, stops MuseTalk frame generation, and returns the avatar to the idle loop.

### 4.4 Gateway / encoder

- Accepts the mic stream from the client (WebRTC preferred for lowest latency).
- Pipes generated frames + synthesized audio into a live encoder (ffmpeg `rawvideo` → `libx264` / `h264_nvenc`, or directly into a WebRTC track).
- Sends the muxed stream back to the client.

---

## 5. Streaming Contract Between Services

The one thing people get wrong: **do not wait for Omni2 to finish before starting MuseTalk.**

- Omni2 emits audio chunks (20–80 ms PCM frames).
- Buffer until ~200–300 ms is available (MuseTalk needs some future audio for right-padding).
- Feed the rolling buffer into MuseTalk frame-by-frame. It emits one face every 40 ms at 25 fps (or 33 ms at 30 fps).
- Mux frames + audio into the outbound stream as they arrive.

---

## 6. Latency Budget

| Stage                                   | Realistic |
| --------------------------------------- | --------- |
| Mic → Omni2 first audio token           | 200–400 ms |
| Omni2 audio chunk → MuseTalk buffer     | 200–300 ms (right padding) |
| MuseTalk frame generation               | 20–40 ms / frame |
| Encode + transport (WebRTC)             | 100–200 ms |
| **Total first-frame latency**           | **~700 ms – 1.2 s** |

- Under ~1 s → feels conversational.
- Over ~1.5 s → feels laggy.
- Biggest knobs: Omni2 time-to-first-audio, and MuseTalk `audio_padding_length_right`.

---

## 7. Things That Will Bite You (Plan For These)

- **GPU contention.** Omni2 and MuseTalk both want a GPU. Prefer separate GPUs; if sharing one card, expect jittery latency. MuseTalk is light and runs happily on a T4 / L4.
- **Barge-in / interruption.** Essential. Without VAD-driven cancellation the agent feels deaf. Must cleanly: stop Omni2, flush audio, stop MuseTalk, return to idle loop.
- **Idle animation.** While listening, do **not** freeze the video. Loop the raw source clip (or run MuseTalk with silence) so the avatar keeps blinking and swaying.
- **Audio-video drift.** Over a long reply, tiny timing errors accumulate. Timestamp every audio chunk and every frame against a shared monotonic clock; drop/duplicate frames to re-sync.
- **First-response warmup.** Cold start is always 2–3× slower. Keep both models hot with a keepalive ping.
- **End-to-end language validation.** MuseTalk itself handles Hindi/Indic fine via Whisper features, but only if Omni2 (or your fallback TTS) produces natural-sounding Hindi/Indic audio. Test the full loop in the target language before committing.

---

## 8. Build Order

Resist the urge to build it streaming on day one. Stage it:

1. **Offline end-to-end prototype.**
   - Record a wav, send it to Omni2 offline, take the response wav, run MuseTalk's file-based `inference.py` on it with a prepared avatar.
   - Goal: verify output quality, identity preservation, lip-sync accuracy, language quality. No streaming.
2. **Avatar prep pipeline.**
   - Script the `realtime_inference.py` `Avatar` prep step as a one-shot CLI that takes a source video and produces the cached artifacts.
3. **Single-request real-time pipeline.**
   - Wire Omni2 → audio buffer → MuseTalk realtime → ffmpeg encoder → MP4 file. Still request/response, but now using the streaming MuseTalk path.
4. **Persistent streaming loop.**
   - Add WebRTC / WebSocket gateway, client UI, continuous mic capture, and bidirectional streaming.
5. **Barge-in, idle loop, drift correction.**
   - Add VAD on the mic, interruption handling, idle animation, monotonic-clock re-sync.
6. **Warm pools and autoscaling.**
   - Keep models hot, measure p50/p95 latency, add GPU autoscaling per concurrent session.

---

## 9. Tech Choices Summary

| Concern              | Choice |
| -------------------- | ------ |
| Speech-to-speech LLM | LLaMA-Omni2 (fallback: Qwen2.5-Omni, Moshi; or ASR+LLM+IndicTTS for Indic) |
| Lip-sync             | MuseTalk 1.5 realtime path (`scripts/realtime_inference.py`) |
| Avatar               | 20–30 s frontal clip, prepped once into cached latents + masks |
| Transport            | WebRTC (preferred) or WebSocket for audio-in + muxed AV-out |
| Encoder              | ffmpeg `libx264` / `h264_nvenc`, or direct WebRTC track |
| VAD                  | Silero VAD or WebRTC VAD on the mic stream |
| GPU layout           | Omni2 on one GPU, MuseTalk on a separate (cheaper) GPU |

---

## 10. Out of Scope (for now)

- Training a custom MuseTalk or SyncNet on Indic talking-head data (possible later fine-tune).
- Multi-speaker avatars / dynamic avatar switching mid-conversation.
- Emotion / expression control beyond what Omni2's prosody and the source video already provide.
- Full-body / gesture generation — MuseTalk only regenerates the lower face.
