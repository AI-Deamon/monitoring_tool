# SentinelEdge Server - Quick Start Guide

Get the server running on a new machine in 5 minutes.

---

## Prerequisites

- **Python 3.9+** installed
- **PostgreSQL 12+** installed and running
- **Git** (optional, for cloning)

---

## Step 1: Install PostgreSQL

### Windows
```bash
# Download from: https://www.postgresql.org/download/windows/
# During installation, remember your postgres password
```

### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

### macOS
```bash
brew install postgresql@14
brew services start postgresql@14
```

---

## Step 2: Create Database

```bash
# Login to PostgreSQL
sudo -u postgres psql

# Create database and assign owner immediately
# (This prevents permission denied errors later)
CREATE USER sentinel_user WITH PASSWORD 'your_password';
CREATE DATABASE sentineledge OWNER sentinel_user;

# Exit
\q
```

---

## Step 3: Setup Server Files

```bash
# Copy server directory to your machine
cd /path/to/server
```

### Option A: Using Virtual Environment (Recommended for Linux)

**Required for:** Kali Linux, Debian 12+, Ubuntu 23.04+, and other modern Linux distributions

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r server_requirements.txt
```

**Note:** Keep the virtual environment activated for all subsequent commands. To deactivate later, run `deactivate`.

### Option B: System-Wide Installation (Windows/macOS)

```bash
# Install Python dependencies directly
pip install -r server_requirements.txt
```

**Linux users:** If you get an "externally-managed-environment" error, use Option A instead.

---

## Step 4: Configure Environment

Create and configure your environment file.

### 1. Create .env file
```bash
# Copy template or create new file
cp .env.template .env
```

### 2. Generate Secret Key
Run this command to generate a secure secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Edit .env Configuration
Open `.env` in your preferred editor (Notepad, nano, vim) and set these values:

```env
# Database Configuration (Format: postgresql://user:password@host:port/dbname)
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/sentineledge

# Security (Paste the key generated above)
SECRET_KEY=paste_the_generated_key_here

# Server Configuration
FLASK_ENV=production
HOST=0.0.0.0
PORT=5050
```

**Key Requirements:**
- **DATABASE_URL**: Must be a valid PostgreSQL connection string.
- **SECRET_KEY**: Essential for session encryption. **Never** share this key.
- **PORT**: Ensure this port is open in your firewall.

---

## Step 5: Initialize Database Schema

Run Alembic migrations to create all tables:

```bash
# This single command creates everything:
# - All tables (agents, screen_time, app_usage, domain_sessions, etc.)
# - All indexes and constraints
# - All stored procedures
# - Default classification rules

alembic upgrade head
```

**Verify migration:**
```bash
alembic current
# Should show: 668a1f8f863e (head)
```

---

## Step 6: Start the Server

**If using virtual environment (Linux):**
```bash
# Make sure venv is activated first
source venv/bin/activate
```

### Development Mode
```bash
python start_server.py
```

### Production Mode (with Gunicorn)
```bash
gunicorn -c gunicorn_config.py server_app:app
```

---

## Step 7: Verify Deployment

1. **Health Check:**
   ```bash
   curl http://localhost:5050/health
   # Should return: {"status": "healthy"}
   ```

2. **Dashboard:**
   - Open browser: `http://localhost:5050/dashboard`
   - Should load the monitoring dashboard

3. **Database Check:**
   ```bash
   psql -U postgres -d sentineledge -c "\dt"
   # Should list 15+ tables
   ```

---

## Troubleshooting

### Database Connection Error
```
Error: could not connect to server
```
**Fix:** Ensure PostgreSQL is running.

### FATAL: password authentication failed
```
psycopg2.OperationalError: FATAL: password authentication failed for user "sentinel_user"
```
**Fix:** 
1. **Check .env**: Open your `.env` file and verify the password in `DATABASE_URL`.
2. **Reset Password**: If you forgot the password, reset it in PostgreSQL:
   ```bash
   psql -U postgres
   ALTER USER sentinel_user WITH PASSWORD 'your_new_password';
   \q
   ```
3. **Check User**: Ensure the user exists:
   ```bash
   psql -U postgres -c "\du"
   ```
   If `sentinel_user` is missing, create it:
   ```bash
   psql -U postgres -c "CREATE USER sentinel_user WITH PASSWORD 'your_password';"
   ```

### permission denied for schema public
```
psycopg2.errors.InsufficientPrivilege: permission denied for schema public
```
**Fix:** In PostgreSQL 15+, the `public` schema no longer allows non-owners to create objects by default. Grant permission to your user:
```bash
# Connect to the database as superuser (postgres)
psql -U postgres -d sentineledge

# Grant full rights on the public schema to your user
GRANT ALL ON SCHEMA public TO sentinel_user;

# Exit
\q
```

### Alembic Migration Error
```
Error: Can't locate revision identified by '...'
```
**Fix:** Reset Alembic and re-run:
```bash
alembic downgrade base
alembic upgrade head
```

### Port Already in Use
```
Error: Address already in use
```
**Fix:** Change port in `.env`:
```env
PORT=5051
```

---

## Next Steps

1. **Register an Agent:**
   - Install agent on a machine
   - Configure agent to point to server: `http://your-server-ip:5050`

2. **Configure Domain Classification:**
   - Go to: `http://localhost:5050/admin/classification`
   - Add custom domain rules

3. **Monitor Activity:**
   - Dashboard: `http://localhost:5050/dashboard`
   - View agents, screen time, app usage, and domain activity

---

## Production Deployment Checklist

- [ ] Use strong `SECRET_KEY`
- [ ] Set `FLASK_ENV=production`
- [ ] Use Gunicorn instead of development server
- [ ] Configure firewall (allow port 5050)
- [ ] Setup SSL/TLS (recommended)
- [ ] Configure PostgreSQL backups
- [ ] Setup log rotation
- [ ] Monitor server resources

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `alembic upgrade head` | Apply all migrations |
| `alembic current` | Show current migration |
| `alembic history` | Show migration history |
| `python start_server.py` | Start development server |
| `gunicorn -c gunicorn_config.py server_app:app` | Start production server |

---

## Support

For issues or questions:
- Check logs: `server/logs/`
- Review migration files: `server/migrations/versions/`
- Verify database schema: `psql -d sentineledge -c "\d+ table_name"`
