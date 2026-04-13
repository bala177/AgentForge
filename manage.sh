#!/usr/bin/env bash
# ============================================================
#  manage.sh — Manage the AI Agent Platform (FastAPI + Uvicorn)
#
#  Usage:  ./manage.sh {start|stop|restart|status|log|clean|install|help}
# ============================================================

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_CMD="python main.py"           # FastAPI entry-point
PID_FILE="$APP_DIR/.app.pid"
LOG_FILE="$APP_DIR/app.log"
VENV_DIR="$APP_DIR/.venv"
PORT=5000

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'  # No Colour

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Activate venv if present ────────────────────────────────
activate_venv() {
    if [[ -d "$VENV_DIR" ]]; then
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate" 2>/dev/null \
            || source "$VENV_DIR/Scripts/activate" 2>/dev/null \
            || true
    fi
}

# ── Install ──────────────────────────────────────────────────
do_install() {
    info "Creating virtual environment in $VENV_DIR …"
    python -m venv "$VENV_DIR"
    activate_venv
    info "Installing dependencies …"
    pip install --upgrade pip -q
    pip install -r "$APP_DIR/requirements.txt" -q
    info "Done. Run  ./manage.sh start  to launch the app."
}

# ── Start ────────────────────────────────────────────────────
do_start() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        warn "App is already running (PID $(cat "$PID_FILE"))."
        return
    fi

    activate_venv
    info "Starting app on port $PORT …"
    cd "$APP_DIR"
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 nohup $APP_CMD --port $PORT >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    info "App started (PID $(cat "$PID_FILE")).  Log → $LOG_FILE"
    info "Dashboard:  http://localhost:$PORT"
    info "API Docs:   http://localhost:$PORT/docs"
    info "WebSocket:  ws://localhost:$PORT/ws/chat/{session_id}"
}

# ── Stop ─────────────────────────────────────────────────────
do_stop() {
    if [[ ! -f "$PID_FILE" ]]; then
        warn "PID file not found — app may not be running."
        return
    fi

    local pid
    pid=$(cat "$PID_FILE")

    if kill -0 "$pid" 2>/dev/null; then
        info "Stopping app (PID $pid) …"
        kill "$pid"
        # Wait up to 5 s for graceful shutdown
        for _ in $(seq 1 10); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        # Force kill if still alive
        if kill -0 "$pid" 2>/dev/null; then
            warn "Graceful stop failed — sending SIGKILL …"
            kill -9 "$pid" 2>/dev/null || true
        fi
        info "App stopped."
    else
        warn "Process $pid is not running."
    fi

    rm -f "$PID_FILE"
}

# ── Restart ──────────────────────────────────────────────────
do_restart() {
    do_stop
    sleep 1
    do_start
}

# ── Status ───────────────────────────────────────────────────
do_status() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        info "App is ${GREEN}running${NC} (PID $(cat "$PID_FILE"), port $PORT)."
    else
        warn "App is ${RED}not running${NC}."
        [[ -f "$PID_FILE" ]] && rm -f "$PID_FILE"
    fi
}

# ── Log ──────────────────────────────────────────────────────
do_log() {
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "No log file found at $LOG_FILE"
        return
    fi
    local lines="${1:-50}"
    info "Last $lines lines of $LOG_FILE :"
    echo "────────────────────────────────────────"
    tail -n "$lines" "$LOG_FILE"
}

do_log_follow() {
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "No log file found at $LOG_FILE"
        return
    fi
    info "Tailing $LOG_FILE  (Ctrl+C to stop) ..."
    # Use --retry for files that may be rotated, and poll for Windows compat
    tail -f --retry "$LOG_FILE" 2>/dev/null || tail -f "$LOG_FILE"
}

# ── Clean ────────────────────────────────────────────────────
do_clean() {
    info "Cleaning up …"
    rm -f "$LOG_FILE"
    rm -f "$PID_FILE"
    rm -f "$APP_DIR/nul"
    rm -rf "$APP_DIR/__pycache__"
    find "$APP_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$APP_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    info "Cleaned: logs, pid file, __pycache__, *.pyc"
}

do_purge() {
    do_stop 2>/dev/null || true
    do_clean
    if [[ -d "$VENV_DIR" ]]; then
        info "Removing virtual environment …"
        rm -rf "$VENV_DIR"
    fi
    info "Purge complete."
}

# ── Run CLI (main.py interactive mode) ───────────────────────
do_cli() {
    activate_venv
    cd "$APP_DIR"
    python main.py --cli
}

# ── Help ─────────────────────────────────────────────────────
do_help() {
    echo ""
    echo -e "${CYAN}AI Agent Platform — Management Script${NC}"
    echo ""
    echo "Usage:  ./manage.sh <command> [args]"
    echo ""
    echo "Commands:"
    echo "  install       Create venv and install dependencies"
    echo "  start         Start the FastAPI server in background"
    echo "  stop          Stop the running server"
    echo "  restart       Stop + start"
    echo "  status        Check if the server is running"
    echo "  log [N]       Show last N lines of log  (default: 50)"
    echo "  logf          Tail -f the log (live follow)"
    echo "  clean         Remove logs, pid file, __pycache__"
    echo "  purge         clean + remove venv"
    echo "  cli           Run the interactive CLI  (main.py --cli)"
    echo "  help          Show this help message"
    echo ""
}

# ── Dispatch ─────────────────────────────────────────────────
case "${1:-help}" in
    install)    do_install  ;;
    start)      do_start    ;;
    stop)       do_stop     ;;
    restart)    do_restart  ;;
    status)     do_status   ;;
    log)        do_log "${2:-50}" ;;
    logf)       do_log_follow ;;
    clean)      do_clean    ;;
    purge)      do_purge    ;;
    cli)        do_cli      ;;
    help|*)     do_help     ;;
esac
