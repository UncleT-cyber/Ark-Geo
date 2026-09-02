#!/usr/bin/env bash
# ============================================================================
# THE ARK (ArkGeo) — single-command local launch
#
#   ./launch.sh            start everything (backend + web + Ollama) and open
#                          the browser
#   ./launch.sh backend    start ONLY the FastAPI backend  (127.0.0.1:12000)
#   ./launch.sh frontend   start ONLY the web portal       (127.0.0.1:12001)
#   ./launch.sh stop       stop everything started by this script
#   ./launch.sh status     show what is currently running
#
# Ports (do NOT run backend and frontend as separate steps — this does it):
#   backend  → http://127.0.0.1:12000  (uvicorn, no --reload)
#   frontend → http://127.0.0.1:12001  (vite dev, proxies /api → :12000)
# ============================================================================
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${TMPDIR:-/tmp}/arkgeo-logs"
mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/arkgeo.pids"

BACKEND_PORT=12000
FRONTEND_PORT=12001
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}/api/v1/health"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"

port_listening() { lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1; }

log()  { printf '\033[36m[ark]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[ark]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[ark]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[ark]\033[0m %s\n' "$*"; }

save_pid() { echo "$1" >> "$PID_FILE"; }
kill_pids() {
  if [ -f "$PID_FILE" ]; then
    while read -r pid; do
      kill "$pid" >/dev/null 2>&1 || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
}

ensure_ollama() {
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama already running (qwen2.5-coder:3b for the AI agent)."
    return 0
  fi
  warn "Ollama is not running — starting it now (needed for the ARK agent)."
  if command -v ollama >/dev/null 2>&1; then
    (nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &) || true
  elif [ -d "/Applications/Ollama.app" ]; then
    open -a Ollama 2>/dev/null || true
  else
    err "Ollama not found. Install it (brew install ollama) or the ARK agent"
    err "will fall back to deterministic replies (no tool planning)."
    return 1
  fi
  for _ in $(seq 1 20); do
    curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && { ok "Ollama up."; return 0; }
    sleep 1
  done
  err "Ollama did not come up — ARK agent will run deterministic only."
  return 1
}

start_backend() {
  if port_listening "$BACKEND_PORT"; then
    ok "Backend already running on :${BACKEND_PORT}."
    return 0
  fi
  log "Starting backend (uvicorn) on :${BACKEND_PORT} …"
  ( cd "$ROOT/arkgeo-backend" && exec nohup .venv/bin/python -m uvicorn main:app \
      --host 127.0.0.1 --port "$BACKEND_PORT" \
      >"$LOG_DIR/backend.log" 2>&1 </dev/null ) &
  save_pid "$!"
  for _ in $(seq 1 30); do
    curl -s "$BACKEND_URL" >/dev/null 2>&1 && { ok "Backend healthy."; return 0; }
    sleep 1
  done
  err "Backend failed to start — see $LOG_DIR/backend.log"
  return 1
}

start_frontend() {
  if port_listening "$FRONTEND_PORT"; then
    ok "Frontend already running on :${FRONTEND_PORT}."
    return 0
  fi
  log "Starting web portal (vite) on :${FRONTEND_PORT} …"
  ( cd "$ROOT/arkgeo-investigator-web" && exec nohup npm run dev \
      >"$LOG_DIR/frontend.log" 2>&1 </dev/null ) &
  save_pid "$!"
  for _ in $(seq 1 45); do
    curl -s "$FRONTEND_URL" -o /dev/null >/dev/null 2>&1 && { ok "Web portal up."; return 0; }
    sleep 1
  done
  err "Frontend failed to start — see $LOG_DIR/frontend.log"
  return 1
}

case "${1:-all}" in
  stop)
    kill_pids
    # Kill stray uvicorn/vite only if launched from this repo tree.
    pkill -f "$ROOT/arkgeo-backend.*uvicorn" >/dev/null 2>&1 || true
    pkill -f "vite.*arkgeo-investigator-web" >/dev/null 2>&1 || true
    ok "Stopped. (Ollama left running.)"
    ;;
  status)
    port_listening "$BACKEND_PORT" && ok "Backend   UP  http://127.0.0.1:${BACKEND_PORT}" || warn "Backend   down (:${BACKEND_PORT})"
    port_listening "$FRONTEND_PORT" && ok "Frontend  UP  http://127.0.0.1:${FRONTEND_PORT}" || warn "Frontend  down (:${FRONTEND_PORT})"
    curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && ok "Ollama    UP" || warn "Ollama    down"
    ;;
  backend)
    ensure_ollama
    start_backend
    ;;
  frontend)
    start_frontend
    ;;
  all)
    ensure_ollama
    start_backend
    start_frontend
    ok "THE ARK is live:"
    ok "  Web portal  → http://127.0.0.1:${FRONTEND_PORT}   (Admin: /#/admin)"
    ok "  API docs    → http://127.0.0.1:${BACKEND_PORT}/docs"
    ok "  API health  → $BACKEND_URL"
    open "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null || true
    ;;
  *)
    err "Usage: ./launch.sh [backend|frontend|stop|status]"
    exit 1
    ;;
esac
