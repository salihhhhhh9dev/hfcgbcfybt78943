#!/usr/bin/env bash
# =========================================================================
# KALIX Lyceum SaaS — Linux / macOS Quick Deployment & Runner Script
# =========================================================================
set -e

echo "=============================================="
echo "  KALIX Lyceum SaaS — Deploy & Start Script"
echo "=============================================="

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is required but not found in PATH. Please install Python 3.10+."
    exit 1
fi

# 2. Setup Virtual Environment
if [ ! -d "venv" ]; then
    echo "[1/4] Creating virtual environment in ./venv..."
    python3 -m venv venv
fi

echo "[2/4] Activating virtual environment and updating dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Seed Database
echo "[3/4] Ensuring database schema and initial data..."
python seed_db.py

# 4. Start Server
PORT="${PORT:-5000}"
HOST="${HOST:-0.0.0.0}"
echo "[4/4] Starting KALIX Lyceum SaaS on http://${HOST}:${PORT}..."
if command -v gunicorn &> /dev/null; then
    exec gunicorn --bind "${HOST}:${PORT}" --workers 3 --timeout 120 wsgi:app
else
    exec python app.py
fi
