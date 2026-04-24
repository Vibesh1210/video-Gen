#!/usr/bin/env bash
# Start every service for the lip-sync stack.
#
#   ./start.sh              -> full stack (svara + musetalk + orchestrator + frontend)
#   ./start.sh stop         -> kill everything
#   ./start.sh status       -> show current state
#   ./start.sh logs <name>  -> tail a service log
#
# Each service runs in the background with its log at /tmp/lipsync-<name>.log.
# Conda env for MuseTalk is /home/vibesh/miniconda3/envs/MuseTalk. Svara,
# orchestrator and frontend all run from the base env.
#
# Safe to re-run: kills existing PIDs on the four ports before starting.

set -euo pipefail

ROOT="/home/vibesh/museTalk"
CONDA_SH="/home/vibesh/miniconda3/etc/profile.d/conda.sh"

SVARA_PORT=8090
MUSETALK_PORT=8081
ORCHESTRATOR_PORT=8000
FRONTEND_PORT=3000

LOG_DIR=/tmp
PID_DIR=/tmp
SERVICES=(svara musetalk orchestrator frontend)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

c_red()   { printf '\033[31m%s\033[0m' "$*"; }
c_grn()   { printf '\033[32m%s\033[0m' "$*"; }
c_ylw()   { printf '\033[33m%s\033[0m' "$*"; }
c_dim()   { printf '\033[2m%s\033[0m' "$*"; }

log_path() { echo "$LOG_DIR/lipsync-$1.log"; }
pid_path() { echo "$PID_DIR/lipsync-$1.pid"; }

port_of() {
  case "$1" in
    svara)        echo $SVARA_PORT ;;
    musetalk)     echo $MUSETALK_PORT ;;
    orchestrator) echo $ORCHESTRATOR_PORT ;;
    frontend)     echo $FRONTEND_PORT ;;
  esac
}

kill_port() {
  local port=$1
  local pids
  pids=$(ss -tlnp 2>/dev/null | awk -v p=":$port " '$0~p { match($0,/pid=[0-9]+/); if (RLENGTH>0) print substr($0,RSTART+4,RLENGTH-4) }' | sort -u)
  [ -z "$pids" ] && return 0
  echo "  killing pid(s) on :$port → $pids"
  for p in $pids; do kill "$p" 2>/dev/null || true; done
  sleep 1
  for p in $pids; do kill -9 "$p" 2>/dev/null || true; done
}

wait_http() {
  local url=$1 label=$2 max=${3:-180}
  local t=0
  printf "  waiting for %s " "$label"
  while ! curl -sf -m 2 "$url" >/dev/null 2>&1; do
    t=$((t+2)); sleep 2
    if [ "$t" -ge "$max" ]; then
      printf " %s (timeout after %ds — see %s)\n" "$(c_red "FAIL")" "$max" "$(log_path "$label")"
      return 1
    fi
    printf "."
  done
  printf " %s (in %ds)\n" "$(c_grn "UP")" "$t"
}

start_svara() {
  local log; log=$(log_path svara)
  echo "$(c_ylw "[svara]") starting on :$SVARA_PORT"
  kill_port $SVARA_PORT
  (
    cd "$ROOT/svara-tts-inference/api"
    nohup env \
      API_HOST=0.0.0.0 API_PORT=$SVARA_PORT \
      VLLM_MODEL="${VLLM_MODEL:-kenpath/svara-tts-v1}" \
      VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.5}" \
      VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-4096}" \
      SNAC_DEVICE="${SNAC_DEVICE:-cpu}" \
      LOG_LEVEL="${LOG_LEVEL:-INFO}" \
      CUDA_VISIBLE_DEVICES="${SVARA_GPU:-0}" \
      python -m uvicorn server:app --host 0.0.0.0 --port $SVARA_PORT \
      > "$log" 2>&1 &
    echo $! > "$(pid_path svara)"
  )
  # Svara loads vLLM — can take minutes on first launch.
  wait_http "http://127.0.0.1:$SVARA_PORT/v1/voices" svara 600
}

start_musetalk() {
  local log; log=$(log_path musetalk)
  echo "$(c_ylw "[musetalk]") starting on :$MUSETALK_PORT"
  kill_port $MUSETALK_PORT
  (
    # Conda activate in a subshell. `conda run` is flakier than sourcing.
    # shellcheck disable=SC1090
    source "$CONDA_SH"
    conda activate MuseTalk
    cd "$ROOT/musetalk-api"
    nohup env \
      MUSETALK_HOST=0.0.0.0 MUSETALK_PORT=$MUSETALK_PORT \
      MUSETALK_GPU_ID="${MUSETALK_GPU:-0}" \
      MUSETALK_USE_FLOAT16="${MUSETALK_USE_FLOAT16:-1}" \
      MUSETALK_VERSION="${MUSETALK_VERSION:-v15}" \
      LOG_LEVEL="${LOG_LEVEL:-INFO}" \
      python server.py \
      > "$log" 2>&1 &
    echo $! > "$(pid_path musetalk)"
  )
  wait_http "http://127.0.0.1:$MUSETALK_PORT/healthz" musetalk 300
}

start_orchestrator() {
  local log; log=$(log_path orchestrator)
  echo "$(c_ylw "[orchestrator]") starting on :$ORCHESTRATOR_PORT"
  kill_port $ORCHESTRATOR_PORT
  (
    cd "$ROOT/orchestrator"
    nohup env \
      ORCHESTRATOR_HOST=0.0.0.0 ORCHESTRATOR_PORT=$ORCHESTRATOR_PORT \
      TTS_URL="http://localhost:$SVARA_PORT" \
      MUSETALK_URL="http://localhost:$MUSETALK_PORT" \
      TTS_ADAPTER="${TTS_ADAPTER:-svara}" \
      LIPSYNC_ADAPTER="${LIPSYNC_ADAPTER:-musetalk}" \
      MAX_CONCURRENT_JOBS="${MAX_CONCURRENT_JOBS:-1}" \
      LOG_LEVEL="${LOG_LEVEL:-INFO}" \
      ${DEFAULT_VOICE:+DEFAULT_VOICE="$DEFAULT_VOICE"} \
      python server.py \
      > "$log" 2>&1 &
    echo $! > "$(pid_path orchestrator)"
  )
  wait_http "http://127.0.0.1:$ORCHESTRATOR_PORT/healthz" orchestrator 60
}

start_frontend() {
  local log; log=$(log_path frontend)
  echo "$(c_ylw "[frontend]") starting on :$FRONTEND_PORT"
  kill_port $FRONTEND_PORT
  (
    cd "$ROOT/frontend"
    [ -d node_modules ] || npm install >> "$log" 2>&1
    nohup env \
      ORCHESTRATOR_URL="http://localhost:$ORCHESTRATOR_PORT" \
      PORT=$FRONTEND_PORT \
      npm run dev \
      > "$log" 2>&1 &
    echo $! > "$(pid_path frontend)"
  )
  wait_http "http://127.0.0.1:$FRONTEND_PORT/" frontend 60
}

cmd_start() {
  mkdir -p "$LOG_DIR" "$PID_DIR"
  # Order matters: orchestrator needs TTS + MuseTalk reachable to list voices
  # on first request; starting them first also fails fast if something is
  # misconfigured.
  start_svara
  start_musetalk
  start_orchestrator
  start_frontend
  echo
  cmd_status
  echo
  echo "$(c_grn "All up.") Open:  $(c_grn "http://localhost:$FRONTEND_PORT/")"
  echo "Logs:  tail -f /tmp/lipsync-<name>.log     (name: svara / musetalk / orchestrator / frontend)"
}

cmd_stop() {
  for svc in "${SERVICES[@]}"; do
    local port; port=$(port_of "$svc")
    echo "[$svc] stopping (:$port)…"
    kill_port "$port"
    rm -f "$(pid_path "$svc")"
  done
  echo "$(c_grn "stopped.")"
}

cmd_status() {
  printf "%-14s %-6s %-6s %s\n" SERVICE PORT STATE PID
  for svc in "${SERVICES[@]}"; do
    local port; port=$(port_of "$svc")
    local pid="-"
    if [ -f "$(pid_path "$svc")" ]; then pid=$(cat "$(pid_path "$svc")"); fi
    local state
    if ss -tln 2>/dev/null | grep -q ":$port "; then
      state=$(c_grn "UP")
    else
      state=$(c_red "DOWN")
    fi
    printf "%-14s %-6s %-15b %s\n" "$svc" "$port" "$state" "$pid"
  done
}

cmd_logs() {
  local svc=${1:-}
  if [ -z "$svc" ]; then
    echo "usage: $0 logs <svara|musetalk|orchestrator|frontend>"
    exit 1
  fi
  tail -f "$(log_path "$svc")"
}

# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  logs)    cmd_logs "${2:-}" ;;
  *)
    echo "usage: $0 {start|stop|restart|status|logs <name>}"
    exit 2
    ;;
esac
