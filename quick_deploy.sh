#!/usr/bin/env bash
set -e

# Quick Deploy Script
# - Creates virtualenv
# - Installs minimal dependencies
# - Prepares .env
# - Runs monitoring service and/or bot
#
# Usage:
#   chmod +x quick_deploy.sh
#   ./quick_deploy.sh all        # setup + run monitoring (port 8088) and bot
#   ./quick_deploy.sh monitoring # setup + run monitoring only
#   ./quick_deploy.sh bot        # setup + run bot only
#   ./quick_deploy.sh setup      # just create venv and install deps
#
# Env vars you can set:
#   MONITORING_API_KEY   (default: demo)
#   PORT                 (default: 8088)
#   TELEGRAM_BOT_TOKEN   (recommended to put into .env)

VENV_DIR=".venv"
PYTHON_BIN="python3"
PIP_BIN="pip"

command -v ${PYTHON_BIN} >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }

setup() {
  if [ ! -d "$VENV_DIR" ]; then
    echo "[+] Creating virtual environment..."
    ${PYTHON_BIN} -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  echo "[+] Installing dependencies (Flask only)..."
  ${PIP_BIN} install --upgrade pip >/dev/null
  ${PIP_BIN} install Flask >/dev/null
  echo "[+] Done."
}

ensure_env() {
  if [ ! -f .env ]; then
    echo "[+] Creating .env sample..."
    cat > .env << EOF
# Fill your secrets below
TELEGRAM_BOT_TOKEN=
MONITORING_API_KEY=${MONITORING_API_KEY:-demo}
PORT=${PORT:-8088}
EOF
    echo "[i] Update .env with your TELEGRAM_BOT_TOKEN"
  fi
}

run_monitoring() {
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  export MONITORING_API_KEY=${MONITORING_API_KEY:-demo}
  export PORT=${PORT:-8088}
  echo "[+] Starting monitoring_service.py on port ${PORT} (API key: ${MONITORING_API_KEY})"
  nohup ${PYTHON_BIN} monitoring_service.py > monitoring.out 2>&1 &
  echo $! > monitoring.pid
  echo "[i] Dashboard: http://localhost:${PORT}/dashboard"
  echo "[i] Health:    http://localhost:${PORT}/health"
  echo "[i] API:       POST /api/metrics with header X-API-Key: ${MONITORING_API_KEY}"
}

run_bot() {
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  echo "[+] Starting commercial_bot_template.py (Ctrl+C to stop)"
  ${PYTHON_BIN} commercial_bot_template.py
}

case "$1" in
  setup)
    setup
    ensure_env
    ;;
  monitoring)
    setup
    ensure_env
    run_monitoring
    ;;
  bot)
    setup
    ensure_env
    run_bot
    ;;
  all|"")
    setup
    ensure_env
    run_monitoring
    run_bot
    ;;
  *)
    echo "Usage: $0 [setup|monitoring|bot|all]"
    exit 1
    ;;

esac
