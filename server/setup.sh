#!/bin/bash

# SentinelEdge Server - Automated Setup Script
# This script automates all steps from QUICKSTART.md

set -e  # Exit on any error

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     SentinelEdge Server - Automated Setup Script            ║"
echo "║     This will set up everything automatically                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration (override by exporting before running, e.g. DB_NAME=foo ./setup.sh)
DB_NAME="${DB_NAME:-sentineledge}"
DB_USER="${DB_USER:-sentinel_user}"
SERVER_PORT="${SERVER_PORT:-5050}"

# Postgres folds unquoted identifiers to lowercase (CREATE DATABASE Foo really
# creates "foo"), but `psql -d`'s dbname is a literal connection parameter
# with no folding — a mixed-case DB_NAME/DB_USER override created the DB fine
# but then failed to connect to it later ("database Foo does not exist").
# Lowercase both up front so every reference in this script stays consistent.
DB_NAME="$(echo "$DB_NAME" | tr '[:upper:]' '[:lower:]')"
DB_USER="$(echo "$DB_USER" | tr '[:upper:]' '[:lower:]')"

if [ ! -f "server_requirements.txt" ]; then
    echo -e "${RED}✗ server_requirements.txt not found in the current directory.${NC}"
    echo "Run this script from inside the server/ directory."
    exit 1
fi

# ============================================================================
# STEP 1: Check Prerequisites
# ============================================================================
echo -e "${YELLOW}[1/8] Checking prerequisites...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 is not installed!${NC}"
    echo "Please install Python 3.8 or higher and try again."
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✓ Python ${PYTHON_VERSION} found${NC}"

# Check PostgreSQL
if ! command -v psql &> /dev/null; then
    echo -e "${RED}✗ PostgreSQL is not installed!${NC}"
    echo "Please install PostgreSQL 12 or higher and try again."
    exit 1
fi
PSQL_VERSION=$(psql --version | cut -d' ' -f3)
echo -e "${GREEN}✓ PostgreSQL ${PSQL_VERSION} found${NC}"

# Check if PostgreSQL service is running
if ! sudo systemctl is-active --quiet postgresql; then
    echo -e "${YELLOW}PostgreSQL service is not running. Starting it...${NC}"
    sudo systemctl start postgresql
    echo -e "${GREEN}✓ PostgreSQL service started${NC}"
else
    echo -e "${GREEN}✓ PostgreSQL service is running${NC}"
fi

# Generate fresh secrets now that python3 is confirmed present. Each
# deployment gets its own DB password / keys instead of sharing one
# hardcoded value across every install.
DB_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
UPDATE_SIGNING_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
REGISTRATION_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
ADMIN_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')

echo ""

# ============================================================================
# STEP 2: Create Virtual Environment
# ============================================================================
echo -e "${YELLOW}[2/8] Setting up Python virtual environment...${NC}"

if [ -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment already exists. Removing old one...${NC}"
    rm -rf venv
fi

python3 -m venv venv
source venv/bin/activate
echo -e "${GREEN}✓ Virtual environment created and activated${NC}"
echo ""

# ============================================================================
# STEP 3: Install Python Dependencies
# ============================================================================
echo -e "${YELLOW}[3/8] Installing Python dependencies...${NC}"

pip install --upgrade pip > /dev/null
pip install -r server_requirements.txt > /dev/null
echo -e "${GREEN}✓ All Python dependencies installed${NC}"
echo ""

# ============================================================================
# STEP 4: Create PostgreSQL Database and User
# ============================================================================
echo -e "${YELLOW}[4/8] Setting up PostgreSQL database...${NC}"

# Check if database already exists
DROP_AND_RECREATE="n"
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
    echo -e "${YELLOW}Database '${DB_NAME}' already exists.${NC}"
    # Read from the controlling terminal and default to "no" on EOF/no-tty
    # (e.g. piped into bash) instead of letting `set -e` kill the script.
    read -p "Do you want to drop and recreate it? (y/N): " -n 1 -r REPLY < /dev/tty || REPLY="n"
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        DROP_AND_RECREATE="y"
    fi
fi

if [ "$DROP_AND_RECREATE" = "y" ]; then
    # Kick existing connections first — DROP DATABASE fails while any
    # session (e.g. a running gunicorn worker) still holds it open.
    sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" > /dev/null || true
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${DB_NAME};" > /dev/null
    sudo -u postgres psql -c "DROP USER IF EXISTS ${DB_USER};" > /dev/null
    echo -e "${GREEN}✓ Old database dropped${NC}"
elif sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
    echo -e "${YELLOW}Keeping existing database${NC}"
fi

# Create user if not exists
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
    sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" > /dev/null
    echo -e "${GREEN}✓ Database user '${DB_USER}' created${NC}"
else
    # User already existed (kept from a previous run) — align its password
    # with the freshly generated one so it matches the .env we're about to write.
    sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" > /dev/null
    echo -e "${GREEN}✓ Database user '${DB_USER}' already exists (password refreshed)${NC}"
fi

# Create database if not exists
if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
    sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" > /dev/null
    echo -e "${GREEN}✓ Database '${DB_NAME}' created${NC}"
fi

# Grant all privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" > /dev/null
sudo -u postgres psql -d ${DB_NAME} -c "GRANT ALL ON SCHEMA public TO ${DB_USER};" > /dev/null
sudo -u postgres psql -d ${DB_NAME} -c "ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};" > /dev/null
echo -e "${GREEN}✓ Database permissions configured${NC}"
echo ""

# ============================================================================
# STEP 5: Create .env File
# ============================================================================
echo -e "${YELLOW}[5/8] Creating environment configuration...${NC}"

if [ -f ".env" ]; then
    echo -e "${YELLOW}.env file already exists. Backing up to .env.backup${NC}"
    cp .env .env.backup
fi

cat > .env << EOF
# Database Configuration
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}

# Server Configuration
PORT=${SERVER_PORT}
SECRET_KEY=${SECRET_KEY}

# Update Signing Key (HMAC-SHA256 for agent update package signing).
# If this server is replacing an existing one for the SAME agent fleet,
# overwrite this with the OLD server's UPDATE_SIGNING_KEY instead of the
# freshly generated value below — agents verify updates against whatever
# key signed them, and a mismatch makes every agent reject updates silently.
UPDATE_SIGNING_KEY=${UPDATE_SIGNING_KEY}

# Required in production — without it, anyone who can reach this server
# can register a fake agent (see server_api.py REGISTER endpoint).
REGISTRATION_SECRET=${REGISTRATION_SECRET}

# Password for the auto-created "admin" dashboard user (first server start
# only — has no effect once that account already exists). Change it via the
# dashboard after logging in, then feel free to remove this line.
DEFAULT_ADMIN_PASSWORD=${ADMIN_PASSWORD}

# Environment
FLASK_ENV=production
EOF

echo -e "${GREEN}✓ .env file created with secure credentials${NC}"
echo ""

# ============================================================================
# STEP 6: Run Alembic Migrations
# ============================================================================
echo -e "${YELLOW}[6/8] Running database migrations...${NC}"

# Run migrations
alembic upgrade head

echo -e "${GREEN}✓ Database schema initialized${NC}"
echo ""

# ============================================================================
# STEP 7: Verify Setup
# ============================================================================
echo -e "${YELLOW}[7/8] Verifying setup...${NC}"

# Check database connection
if python3 -c "
import os
from sqlalchemy import create_engine
from dotenv import load_dotenv
load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
conn = engine.connect()
conn.close()
" 2>/dev/null; then
    echo -e "${GREEN}✓ Database connection successful${NC}"
else
    echo -e "${RED}✗ Database connection failed${NC}"
    exit 1
fi

# Check if alembic_version table exists
if sudo -u postgres psql -d ${DB_NAME} -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version'" | grep -q 1; then
    MIGRATION_VERSION=$(sudo -u postgres psql -d ${DB_NAME} -tAc "SELECT version_num FROM alembic_version")
    echo -e "${GREEN}✓ Migrations applied (version: ${MIGRATION_VERSION})${NC}"
else
    echo -e "${RED}✗ Alembic migrations not applied${NC}"
    exit 1
fi
echo ""

# ============================================================================
# STEP 8: Install as a systemd service (auto-detected, skipped if unavailable
# or if a service by this name already exists — never overwrites a service
# you've customized).
# ============================================================================
echo -e "${YELLOW}[8/8] Installing systemd service...${NC}"

SERVICE_NAME="sentineledge"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_INSTALLED="n"

if ! command -v systemctl >/dev/null 2>&1 || [ "$(ps -p 1 -o comm= 2>/dev/null)" != "systemd" ]; then
    echo -e "${YELLOW}systemd not detected — skipping. Start manually (see Next Steps below).${NC}"
elif [ -f "$SERVICE_FILE" ]; then
    echo -e "${YELLOW}${SERVICE_FILE} already exists — restarting it to pick up this run's changes.${NC}"
    sudo systemctl daemon-reload
    sudo systemctl restart "${SERVICE_NAME}.service"
    sleep 3

    if sudo systemctl is-active --quiet "${SERVICE_NAME}.service"; then
        echo -e "${GREEN}✓ ${SERVICE_NAME}.service restarted and running${NC}"
        SERVICE_INSTALLED="y"
    else
        echo -e "${RED}✗ Service exists but failed to (re)start.${NC}"
        echo "  Check: sudo journalctl -u ${SERVICE_NAME}.service --no-pager -n 40"
    fi
else
    INSTALL_DIR="$(pwd)"
    RUN_USER="$(whoami)"

    sudo tee "$SERVICE_FILE" > /dev/null << SVCEOF
[Unit]
Description=SentinelEdge Server (gunicorn)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart="${INSTALL_DIR}/venv/bin/gunicorn" -c gunicorn_config.py server_main:application
Restart=always
RestartSec=5
StartLimitIntervalSec=0
Environment=GUNICORN_WORKERS=4
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SVCEOF

    sudo systemctl daemon-reload
    sudo systemctl enable --now "${SERVICE_NAME}.service"
    sleep 3

    if sudo systemctl is-active --quiet "${SERVICE_NAME}.service"; then
        echo -e "${GREEN}✓ ${SERVICE_NAME}.service installed, enabled, and running${NC}"
        echo "  Survives crashes (Restart=always) and reboots (enabled)."
        SERVICE_INSTALLED="y"
    else
        echo -e "${RED}✗ Service installed but failed to start.${NC}"
        echo "  Check: sudo journalctl -u ${SERVICE_NAME}.service --no-pager -n 40"
    fi
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  ✅ SETUP COMPLETE!                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Database Details:"
echo "  - Database: ${DB_NAME}"
echo "  - User: ${DB_USER}"
echo "  - Password: saved in .env (DATABASE_URL) — not printed here"
echo ""
echo -e "${YELLOW}All generated secrets (DB password, SECRET_KEY, UPDATE_SIGNING_KEY,${NC}"
echo -e "${YELLOW}REGISTRATION_SECRET) live only in .env. Keep it out of version control${NC}"
echo -e "${YELLOW}and copy it somewhere safe before wiping this machine.${NC}"
echo ""

if [ "$SERVICE_INSTALLED" = "y" ]; then
    echo -e "${GREEN}Your SentinelEdge server is running as a service.${NC}"
    echo ""
    echo "Useful commands:"
    echo "  sudo systemctl status ${SERVICE_NAME}    # check it's up"
    echo "  sudo systemctl restart ${SERVICE_NAME}   # after changing .env or code"
    echo "  sudo journalctl -u ${SERVICE_NAME} -f    # follow logs"
else
    echo -e "${GREEN}Your SentinelEdge server is ready to start!${NC}"
    echo ""
    echo "Next Steps:"
    echo "  1. Start the server:"
    echo -e "     ${YELLOW}python start_server.py${NC}                                 # dev"
    echo -e "     ${YELLOW}gunicorn -c gunicorn_config.py server_main:application${NC} # production"
fi

echo ""
echo "Access the dashboard:"
echo -e "  ${YELLOW}http://localhost:${SERVER_PORT}/dashboard${NC}"
echo -e "  Login: admin / ${GREEN}${ADMIN_PASSWORD}${NC}"
echo -e "  ${YELLOW}This is generated fresh for this install, not the old 'changeme123'${NC}"
echo -e "  ${YELLOW}default — but still change it via the dashboard after first login.${NC}"
echo ""
