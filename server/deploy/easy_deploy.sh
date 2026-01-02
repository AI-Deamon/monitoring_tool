#!/bin/bash
set -e

echo "=============================================="
echo "   SentinelEdge Server - Easy Deployment"
echo "=============================================="

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Please install Python 3.11+"
    exit 1
fi

# 2. Virtual Environment
if [ ! -d "venv" ]; then
    echo "[SETUP] Creating virtual environment..."
    python3 -m venv venv
fi

echo "[SETUP] Activating virtual environment..."
source venv/bin/activate

# 3. Install Dependencies
echo "[SETUP] Installing dependencies..."
pip install --upgrade pip -q
pip install -r server_requirements.txt -q

# 4. Database Setup
echo "[DB] Applying database patches and functions..."
# This script applies all Stored Procedures and Sync Functions needed for v2.0
python3 apply_sync_functions.py

# 5. Start Server
# Read port from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    SERVER_PORT=5051
    SERVER_HOST=0.0.0.0
fi

echo "=============================================="
echo "   Server Starting on Port $SERVER_PORT"
echo "=============================================="

if command -v gunicorn &> /dev/null; then
    # Production mode
    echo "[RUN] Starting Gunicorn (Production)..."
    gunicorn --bind $SERVER_HOST:$SERVER_PORT --workers 4 --access-logfile - --error-logfile - wsgi:app
else
    # Dev mode fallback
    echo "[RUN] Starting Python (Development)..."
    python3 server_main.py
fi
