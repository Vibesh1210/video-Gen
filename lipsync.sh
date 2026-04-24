#!/usr/bin/env bash
set -euo pipefail

SVARA_PID=/tmp/lipsync-svara.pid
ORCH_PID=/tmp/lipsync-orchestrator.pid
FRONTEND_PID=/tmp/lipsync-frontend.pid

usage() {
  echo "Usage: $0 {start|stop|status|restart}"
  exit 1
}

# ── helpers ──────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }

wait_for_port() {
  local name=$1 port=$2 max=${3:-60}
  log "Waiting for $name on :$port ..."
  for i in $(seq 1 $max); do
    if curl -sf "http://localhost:$port" -o /dev/null 2>/dev/null ||
       curl -sf "http://localhost:${port}/healthz" -o /dev/null 2>/dev/null ||
       curl -sf "http://localhost:${port}/v1/voices" -o /dev/null 2>/dev/null; then
      log "$name is up."
      return 0
    fi
    sleep 2
  done
  log "WARNING: $name did not respond after $((max * 2))s — check logs."
}

kill_by_pid() {
  local pidfile=$1 name=$2
  if [[ -f $pidfile ]]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && log "Stopped $name (pid $pid)"
    else
      log "$name pid $pid already gone"
    fi
    rm -f "$pidfile"
  else
    log "$name pid file not found — trying port kill"
  fi
}

kill_by_port() {
  local port=$1 name=$2
  local pid
  pid=$(ss -tlnp 2>/dev/null | awk -F'pid=' "/:${port} /{print \$2+0}" | head -1)
  if [[ -n $pid && $pid -gt 0 ]]; then
    kill "$pid" 2>/dev/null && log "Stopped $name via port :$port (pid $pid)"
  fi
}

# ── start ─────────────────────────────────────────────────────────────────────

start() {
  log "=== Starting lip-sync stack ==="

  # 1. Svara TTS
  log "Starting Svara TTS on :8081 ..."
  cd /home/ravindra/Desktop/vibesh/video-Gen/svara-tts-inference/api
  API_PORT=8081 \
  VLLM_MODEL=kenpath/svara-tts-v1 \
  VLLM_GPU_MEMORY_UTILIZATION=0.5 \
  VLLM_MAX_MODEL_LEN=4096 \
  SNAC_DEVICE=cuda \
  SNAC_COMPILE=false \
  PYTORCH_JIT=0 \
  CUDA_VISIBLE_DEVICES=0 \
  LOG_LEVEL=INFO \
  /home/ravindra/miniconda3/envs/svara/bin/python -m uvicorn server:app \
      --host 0.0.0.0 --port 8081 \
      > /tmp/lipsync-svara.log 2>&1 &
  echo $! > "$SVARA_PID"
  log "Svara pid $(cat $SVARA_PID) — logs: /tmp/lipsync-svara.log"

  # 2. MuseTalk (Docker)
  log "Starting MuseTalk container on :8082 ..."
  docker start musetalk-dev
  docker exec -d musetalk-dev bash -c "
    cd /workspace/MuseTalk
    MUSETALK_HOST=0.0.0.0 MUSETALK_PORT=8082 \
    MUSETALK_GPU_ID=0 MUSETALK_USE_FLOAT16=1 MUSETALK_VERSION=v15 \
    LOG_LEVEL=INFO \
    PYTHONPATH=/workspace/musetalk-api:/workspace/MuseTalk \
    python /workspace/musetalk-api/server.py > /tmp/musetalk.log 2>&1
  "
  log "MuseTalk server started inside container — logs: docker exec musetalk-dev tail -f /tmp/musetalk.log"

  # 3. Orchestrator
  log "Starting Orchestrator on :8000 ..."
  cd /home/ravindra/Desktop/vibesh/video-Gen/orchestrator
  ORCHESTRATOR_HOST=0.0.0.0 \
  ORCHESTRATOR_PORT=8000 \
  TTS_URL=http://localhost:8081 \
  MUSETALK_URL=http://localhost:8082 \
  TTS_ADAPTER=svara \
  LIPSYNC_ADAPTER=musetalk \
  MAX_CONCURRENT_JOBS=1 \
  LOG_LEVEL=INFO \
  /home/ravindra/miniconda3/bin/python server.py \
      > /tmp/lipsync-orchestrator.log 2>&1 &
  echo $! > "$ORCH_PID"
  log "Orchestrator pid $(cat $ORCH_PID) — logs: /tmp/lipsync-orchestrator.log"

  # 4. Frontend
  log "Starting Frontend on :3000 ..."
  cd /home/ravindra/Desktop/vibesh/video-Gen/frontend
  ORCHESTRATOR_URL=http://localhost:8000 npm run dev \
      > /tmp/lipsync-frontend.log 2>&1 &
  echo $! > "$FRONTEND_PID"
  log "Frontend pid $(cat $FRONTEND_PID) — logs: /tmp/lipsync-frontend.log"

  log ""
  log "All services launched. Waiting for them to be ready..."
  log "(Svara + MuseTalk take 30–60s to load weights)"
  wait_for_port "Svara"       8081 90
  wait_for_port "MuseTalk"    8082 90
  wait_for_port "Orchestrator" 8000 30
  wait_for_port "Frontend"    3000 30

  log ""
  log "=== Stack ready ==="
  status
}

# ── stop ──────────────────────────────────────────────────────────────────────

stop() {
  log "=== Stopping lip-sync stack ==="

  kill_by_pid "$FRONTEND_PID" "Frontend"
  kill_by_port 3000 "Frontend"

  kill_by_pid "$ORCH_PID" "Orchestrator"
  kill_by_port 8000 "Orchestrator"

  kill_by_pid "$SVARA_PID" "Svara"
  kill_by_port 8081 "Svara"

  # Stop the server process inside the container, then stop the container
  docker exec musetalk-dev bash -c "pkill -f 'server.py' 2>/dev/null || true"
  docker stop musetalk-dev 2>/dev/null && log "Stopped musetalk-dev container" || true

  log "=== All services stopped ==="
}

# ── status ────────────────────────────────────────────────────────────────────

status() {
  echo ""
  echo "  Service        Port   Status"
  echo "  ─────────────────────────────────────────────────────"

  check() {
    local name=$1 port=$2 url=$3
    local result
    result=$(curl -sf "$url" -o /dev/null -w "%{http_code}" 2>/dev/null || echo "000")
    if [[ $result == "200" ]]; then
      printf "  %-14s %-6s ✓ up\n" "$name" ":$port"
    else
      printf "  %-14s %-6s ✗ down (HTTP $result)\n" "$name" ":$port"
    fi
  }

  check "Svara TTS"     8081 "http://localhost:8081/v1/voices"
  check "MuseTalk"      8082 "http://localhost:8082/healthz"
  check "Orchestrator"  8000 "http://localhost:8000/api/v1/voices"
  check "Frontend"      3000 "http://localhost:3000/"
  echo ""
}

# ── main ──────────────────────────────────────────────────────────────────────

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 2; start ;;
  status)  status ;;
  *)       usage ;;
esac
