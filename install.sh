#!/usr/bin/env bash
set -e

# Install & Run helper for sellable products
# - Detects OS basics
# - Creates virtualenv
# - Installs requirements
# - Prints next steps

VENV_DIR=".venv"
PYTHON_BIN="python3"
PIP_BIN="pip"

command -v ${PYTHON_BIN} >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }

if [ ! -d "$VENV_DIR" ]; then
  echo "[+] Creating virtual environment..."
  ${PYTHON_BIN} -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if [ -f requirements.txt ]; then
  echo "[+] Installing requirements..."
  ${PIP_BIN} install --upgrade pip >/dev/null
  ${PIP_BIN} install -r requirements.txt
fi

echo "\n[✔] Installation complete. Next steps:\n"
cat << 'EOF'
1) Quick Deploy options:
   - ./quick_deploy.sh setup
   - ./quick_deploy.sh monitoring
   - ./quick_deploy.sh bot
   - ./quick_deploy.sh all

2) Telegram Bot:
   - Put your token to .env or export TELEGRAM_BOT_TOKEN
   - Run: python3 commercial_bot_template.py

3) Monitoring Service:
   - export MONITORING_API_KEY=demo PORT=8088
   - Run: python3 monitoring_service.py
   - Open: http://localhost:8088/dashboard

4) Landing Page:
   - Open landing_page.html in your browser
   - Or push to GitHub main/master to auto-deploy with GitHub Actions

5) Sales:
   - Bot pricing: $299 / $599 / $999
   - Monitoring subscription: $29 / $59 / $99 per month
EOF
