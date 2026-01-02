# SentinelEdge Server Deployment Guide
# =====================================
# Complete setup for a fresh system

## Prerequisites

### 1. System Requirements
- Python 3.10 or higher
- PostgreSQL 14 or higher
- 2GB RAM minimum
- 10GB disk space

### 2. Required Software

**Windows:**
```powershell
# Install Python from python.org
# Install PostgreSQL from postgresql.org
# Or use chocolatey:
choco install python postgresql
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3.10 python3-pip postgresql postgresql-contrib
```

---

## STEP 1: Database Setup (5 minutes)

### 1.1 Create PostgreSQL Database

**Windows (pgAdmin or psql):**
```sql
-- Connect as postgres superuser, then run:
CREATE USER sentinelserver WITH PASSWORD 'sentinel_edge_secure';
CREATE DATABASE sentinel_edge_v1 OWNER sentinelserver;
GRANT ALL PRIVILEGES ON DATABASE sentinel_edge_v1 TO sentinelserver;
```

**Linux:**
```bash
sudo -u postgres psql
CREATE USER sentinelserver WITH PASSWORD 'sentinel_edge_secure';
CREATE DATABASE sentinel_edge_v1 OWNER sentinelserver;
GRANT ALL PRIVILEGES ON DATABASE sentinel_edge_v1 TO sentinelserver;
\q
```

### 1.2 Test Connection
```bash
psql -h localhost -U sentinelserver -d sentinel_edge_v1
# Enter password: sentinel_edge_secure
# Should connect successfully
```

---

## STEP 2: Server Setup (10 minutes)

### 2.1 Copy Server Files
```bash
# Copy the entire server folder to new system
# Location: /opt/sentineledge/server (Linux) or C:\SentinelEdge\server (Windows)
```

### 2.2 Create Virtual Environment
```bash
cd server
python -m venv venv

# Activate:
# Windows:
venv\Scripts\activate
# Linux:
source venv/bin/activate
```

### 2.3 Install Dependencies
```bash
pip install -r server_requirements.txt
```

### 2.4 Configure Environment
Create `.env` file in server folder:
```bash
# .env file
DATABASE_URL=postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1
SECRET_KEY=your-secret-key-here-change-this
HOST=0.0.0.0
PORT=5050
LOG_LEVEL=INFO

# Optional: For production
REGISTRATION_SECRET=your-registration-secret
```

---

## STEP 3: Database Migration (2 minutes)

### 3.1 Create Tables
```bash
# Method 1: Using Flask (recommended)
python -c "
from server_app import create_app
from extensions import db
app = create_app()
with app.app_context():
    db.create_all()
    print('Tables created!')
"

# Method 2: Using Alembic migrations
alembic upgrade head
```

### 3.2 Setup Classification Tables
```bash
# Run the classification setup SQL
psql -h localhost -U sentinelserver -d sentinel_edge_v1 -f scripts/setup_classification.sql
```

---

## STEP 4: Start Server (1 minute)

### 4.1 Development Mode
```bash
python server_main.py
```

### 4.2 Production Mode (with Gunicorn)
```bash
# Linux/Mac:
gunicorn -c gunicorn_config.py server_main:application

# Windows (use waitress instead):
pip install waitress
python -c "from waitress import serve; from server_main import application; serve(application, host='0.0.0.0', port=5050)"
```

---

## STEP 5: Verify Installation (1 minute)

### 5.1 Check Endpoints
```bash
# Health check
curl http://localhost:5050/
# Expected: {"status": "ok", "service": "SentinelEdge Server"}

# Dashboard
# Open browser: http://localhost:5050/dashboard/

# Classification Admin
# Open browser: http://localhost:5050/admin/classification
```

### 5.2 Check Logs
```bash
# Windows:
type logs\server.log

# Linux:
tail -f logs/server.log
```

---

## STEP 6: Agent Configuration

After server is running, configure agents to connect:

Edit agent config file (`agent/config/config.yaml` or `.env`):
```yaml
server_url: http://YOUR_SERVER_IP:5050
```

---

## Quick Start Commands (Copy-Paste)

### Fresh Install - All Commands:
```bash
# 1. Clone/copy server files
cd /path/to/server

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r server_requirements.txt

# 4. Create .env file (edit with your values)
cat > .env << 'EOF'
DATABASE_URL=postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1
SECRET_KEY=change-this-to-random-string
HOST=0.0.0.0
PORT=5050
LOG_LEVEL=INFO
EOF

# 5. Create database tables
python -c "from server_app import create_app; from extensions import db; app = create_app(); app.app_context().push(); db.create_all(); print('Done!')"

# 6. Start server
python server_main.py
```

---

## Troubleshooting

### Database Connection Error
```
Check:
1. PostgreSQL is running: sudo systemctl status postgresql
2. DATABASE_URL in .env is correct
3. User has permissions: GRANT ALL ON DATABASE sentinel_edge_v1 TO sentinelserver;
```

### Port Already in Use
```bash
# Find process using port 5050
netstat -ano | findstr :5050  # Windows
lsof -i :5050                 # Linux

# Kill it or change PORT in .env
```

### Module Not Found
```bash
# Ensure virtual environment is activated
# Reinstall dependencies:
pip install -r server_requirements.txt
```

---

## Production Checklist

- [ ] Change SECRET_KEY to random string
- [ ] Set REGISTRATION_SECRET for agent registration security
- [ ] Configure firewall to allow port 5050
- [ ] Set up SSL/HTTPS (recommended: nginx reverse proxy)
- [ ] Configure log rotation
- [ ] Set up systemd service (Linux) or Windows Service
- [ ] Regular database backups

---

## Systemd Service (Linux Production)

Create `/etc/systemd/system/sentineledge.service`:
```ini
[Unit]
Description=SentinelEdge Server
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/opt/sentineledge/server
Environment="PATH=/opt/sentineledge/server/venv/bin"
ExecStart=/opt/sentineledge/server/venv/bin/gunicorn -c gunicorn_config.py server_main:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sentineledge
sudo systemctl start sentineledge
sudo systemctl status sentineledge
```
