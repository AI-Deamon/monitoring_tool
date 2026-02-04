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

# Configuration
DB_NAME="sentineledge"
DB_USER="sentinel_user"
DB_PASSWORD="sentinel_secure_password_2024"
SERVER_PORT="5050"

# ============================================================================
# STEP 1: Check Prerequisites
# ============================================================================
echo -e "${YELLOW}[1/7] Checking prerequisites...${NC}"

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

echo ""

# ============================================================================
# STEP 2: Create Virtual Environment
# ============================================================================
echo -e "${YELLOW}[2/7] Setting up Python virtual environment...${NC}"

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
echo -e "${YELLOW}[3/7] Installing Python dependencies...${NC}"

pip install --upgrade pip > /dev/null 2>&1
pip install -r server_requirements.txt > /dev/null 2>&1
echo -e "${GREEN}✓ All Python dependencies installed${NC}"
echo ""

# ============================================================================
# STEP 4: Create PostgreSQL Database and User
# ============================================================================
echo -e "${YELLOW}[4/7] Setting up PostgreSQL database...${NC}"

# Check if database already exists
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw ${DB_NAME}; then
    echo -e "${YELLOW}Database '${DB_NAME}' already exists.${NC}"
    read -p "Do you want to drop and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${DB_NAME};" > /dev/null 2>&1
        sudo -u postgres psql -c "DROP USER IF EXISTS ${DB_USER};" > /dev/null 2>&1
        echo -e "${GREEN}✓ Old database dropped${NC}"
    else
        echo -e "${YELLOW}Keeping existing database${NC}"
    fi
fi

# Create user if not exists
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
    sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" > /dev/null 2>&1
    echo -e "${GREEN}✓ Database user '${DB_USER}' created${NC}"
else
    echo -e "${GREEN}✓ Database user '${DB_USER}' already exists${NC}"
fi

# Create database if not exists
if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw ${DB_NAME}; then
    sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" > /dev/null 2>&1
    echo -e "${GREEN}✓ Database '${DB_NAME}' created${NC}"
fi

# Grant all privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" > /dev/null 2>&1
sudo -u postgres psql -d ${DB_NAME} -c "GRANT ALL ON SCHEMA public TO ${DB_USER};" > /dev/null 2>&1
sudo -u postgres psql -d ${DB_NAME} -c "ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};" > /dev/null 2>&1
echo -e "${GREEN}✓ Database permissions configured${NC}"
echo ""

# ============================================================================
# STEP 5: Create .env File
# ============================================================================
echo -e "${YELLOW}[5/7] Creating environment configuration...${NC}"

if [ -f ".env" ]; then
    echo -e "${YELLOW}.env file already exists. Backing up to .env.backup${NC}"
    cp .env .env.backup
fi

# Generate a secure secret key
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

cat > .env << EOF
# Database Configuration
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}

# Server Configuration
PORT=${SERVER_PORT}
SECRET_KEY=${SECRET_KEY}

# Optional: Set this in production to prevent unauthorized agent registration
# REGISTRATION_SECRET=your-secret-key-here

# Environment
FLASK_ENV=development
EOF

echo -e "${GREEN}✓ .env file created with secure credentials${NC}"
echo ""

# ============================================================================
# STEP 6: Run Alembic Migrations
# ============================================================================
echo -e "${YELLOW}[6/7] Running database migrations...${NC}"

# Run migrations
alembic upgrade head

echo -e "${GREEN}✓ Database schema initialized${NC}"
echo ""

# ============================================================================
# STEP 7: Verify Setup
# ============================================================================
echo -e "${YELLOW}[7/7] Verifying setup...${NC}"

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
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  ✅ SETUP COMPLETE!                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}Your SentinelEdge server is ready to start!${NC}"
echo ""
echo "Database Details:"
echo "  - Database: ${DB_NAME}"
echo "  - User: ${DB_USER}"
echo "  - Password: ${DB_PASSWORD}"
echo ""
echo "Next Steps:"
echo "  1. Start the server:"
echo "     ${YELLOW}python start_server.py${NC}"
echo ""
echo "  2. Access the dashboard:"
echo "     ${YELLOW}http://localhost:${SERVER_PORT}/dashboard${NC}"
echo "     Login: admin / changeme123"
echo ""
echo "  3. (Optional) Set REGISTRATION_SECRET in .env for production"
echo ""
echo "For production deployment, use:"
echo "  ${YELLOW}gunicorn -c gunicorn_config.py server_main:application${NC}"
echo ""
