#!/bin/bash
# ============================================================
# SentinelEdge Server Startup Script
# ============================================================

# Change to server directory
cd "$(dirname "$0")"

# Load .env file if it exists
if [ -f .env ]; then
    echo "📁 Loading configuration from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# Generate a secure JWT secret if not already set
if [ -z "$JWT_SECRET" ] || [ "$JWT_SECRET" = "dev-secret" ] || [ ${#JWT_SECRET} -lt 32 ]; then
    export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "✅ Generated secure JWT_SECRET (64 characters)"
fi

# Check DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL not set! Please configure .env file."
    exit 1
fi

# Display configuration
echo ""
echo "============================================================"
echo "  SentinelEdge Server Configuration"
echo "============================================================"
echo "  DATABASE_URL: ${DATABASE_URL:0:50}..."
echo "  JWT_SECRET: ${JWT_SECRET:0:16}... (${#JWT_SECRET} chars)"
echo "  REGISTRATION_SECRET: ${REGISTRATION_SECRET:-'(not set - open registration)'}"
echo "============================================================"
echo ""

# Start the server
echo "Starting SentinelEdge Server..."
python3 server_main.py
