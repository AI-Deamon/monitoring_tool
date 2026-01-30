# 🖥️ SentinelEdge Server v2.1.0

**Enterprise-grade telemetry collection and analytics server**

SentinelEdge Server is a robust, production-ready backend for collecting, processing, and visualizing endpoint monitoring data from SentinelEdge Agents. Built with Flask and PostgreSQL, it provides real-time dashboards, detailed analytics, and comprehensive reporting.

---

## 📋 Table of Contents

- [Features](#-features)
- [System Requirements](#-system-requirements)
- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [API Reference](#-api-reference)
- [Dashboard](#-dashboard)
- [Database Architecture](#-database-architecture)
- [Security](#-security)
- [Deployment](#-deployment)
- [Maintenance](#-maintenance)
- [Troubleshooting](#-troubleshooting)
- [Version History](#-version-history)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📊 **Real-time Dashboard** | Live monitoring of all endpoints |
| 📈 **Analytics** | Screen time, app usage, domain tracking |
| 🔐 **Authentication** | Multi-user role-based access control |
| 📦 **Batch Processing** | Efficient handling of buffered agent data |
| 🗄️ **PostgreSQL Backend** | Robust, scalable data storage |
| 📄 **Reports** | PDF/CSV export with date filtering |
| 🏷️ **Domain Classification** | Categorize domains (productive, unproductive, etc.) |
| 🔒 **HMAC Verification** | Secure agent communication |

---

## 💻 System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| **OS** | Ubuntu 20.04+ / Debian 11+ | Ubuntu 22.04 LTS |
| **Python** | 3.11+ | 3.13 |
| **PostgreSQL** | 14+ | 16 |
| **RAM** | 512 MB | 2 GB |
| **CPU** | 1 core | 2+ cores |
| **Disk** | 10 GB | 50 GB |

---

## 🚀 Quick Start

### Using Docker (Recommended)

```bash
# 1. Clone and configure
cp .env.example .env
nano .env  # Edit with your values

# 2. Start services
docker-compose up -d

# 3. Verify
curl http://localhost:5050/
```

### Manual Installation

```bash
# 1. Install dependencies
pip install -r server_requirements.txt

# 2. Set environment
export DATABASE_URL="postgresql://user:pass@localhost:5432/sentinel_edge"
export SECRET_KEY="your-secure-secret-key"

# 3. Initialize database
python -c "from server_app import app, db; app.app_context().push(); db.create_all()"
python apply_sync_functions.py

# 4. Run server
gunicorn --bind 0.0.0.0:5050 --workers 4 wsgi:app
```

---

## 📥 Installation

### Step 1: Database Setup

```bash
# Create PostgreSQL database
sudo -u postgres psql << EOF
CREATE USER sentinel_user WITH PASSWORD 'your_secure_password';
CREATE DATABASE sentinel_edge OWNER sentinel_user;
GRANT ALL PRIVILEGES ON DATABASE sentinel_edge TO sentinel_user;
EOF
```

### Step 2: Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r server_requirements.txt
```

### Step 3: Configure Environment

Create `.env` file:

```bash
# Database
DATABASE_URL=postgresql://sentinel_user:your_password@localhost:5432/sentinel_edge

# Security
SECRET_KEY=your-very-secure-random-string-here
REGISTRATION_SECRET=agent-registration-secret

# Server
FLASK_ENV=production
SERVER_HOST=0.0.0.0
SERVER_PORT=5050

# Features
ENABLE_RATE_LIMITING=true
RATE_LIMIT_PER_MINUTE=60
```

### Step 4: Initialize Database

```bash
# Apply migrations
flask db upgrade

# Apply stored procedures
python apply_sync_functions.py
```

### Step 5: Start Server

```bash
# Development
python server_main.py

# Production
gunicorn --bind 0.0.0.0:5050 --workers 4 --timeout 120 wsgi:app
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | - | PostgreSQL connection string |
| `SECRET_KEY` | ✅ | - | Flask secret key for sessions |
| `REGISTRATION_SECRET` | ✅ | - | Agent registration password |
| `SERVER_HOST` | ❌ | `0.0.0.0` | Bind address |
| `SERVER_PORT` | ❌ | `5050` | Listen port |
| `FLASK_ENV` | ❌ | `production` | Environment mode |
| `ENABLE_RATE_LIMITING` | ❌ | `true` | API rate limiting |
| `RATE_LIMIT_PER_MINUTE` | ❌ | `60` | Requests per minute per IP |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity |

### Sample `.env.example`

```env
# Database Connection
DATABASE_URL=postgresql://sentinel_user:password@localhost:5432/sentinel_edge

# Security Keys (CHANGE THESE!)
SECRET_KEY=change-this-to-random-64-char-string
REGISTRATION_SECRET=change-this-agent-registration-secret

# Server Configuration
FLASK_ENV=production
SERVER_HOST=0.0.0.0
SERVER_PORT=5050

# Rate Limiting
ENABLE_RATE_LIMITING=true
RATE_LIMIT_PER_MINUTE=60

# Logging
LOG_LEVEL=INFO
```

---

## 🔌 API Reference

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/login` | User login |
| `POST` | `/auth/logout` | User logout |
| `GET` | `/auth/users` | List users (admin) |
| `POST` | `/auth/users/add` | Add user (admin) |

### Agent Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/register` | Agent registration |
| `POST` | `/api/v1/heartbeat` | Agent heartbeat |
| `GET` | `/api/v1/agent/{id}/config` | Get agent config |

### Telemetry Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/telemetry/screentime` | Screen time data |
| `POST` | `/api/v1/telemetry/app-switch` | App switch events |
| `POST` | `/api/v1/telemetry/domain` | Domain visit data |
| `POST` | `/api/v1/telemetry/inventory` | App inventory |
| `POST` | `/api/v1/merged-events` | Batch upload |

### Dashboard API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/agents` | List all agents |
| `GET` | `/api/v1/agents/{id}` | Agent details |
| `GET` | `/api/v1/screentime` | Screen time data |
| `GET` | `/api/v1/app-usage` | App usage data |
| `GET` | `/api/v1/domain-usage` | Domain usage data |

### Example: Agent Registration

```bash
curl -X POST http://server:5050/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "WORKSTATION-01",
    "username": "DOMAIN\\User",
    "os_version": "Windows 10 Pro",
    "registration_secret": "your-secret"
  }'
```

---

## 📊 Dashboard

### Access Dashboard

Navigate to: `http://your-server:5050/dashboard/`

### Dashboard Features

| Page | Description |
|------|-------------|
| **Overview** | Summary cards, charts, recent activity |
| **Agents** | List of all registered agents with status |
| **Agent Detail** | Individual agent metrics and history |
| **Reports** | Generate PDF/CSV reports |
| **Admin** | User management, domain classification |

### Default Login

```
Username: admin
Password: (set during first run)
```

---

## 🗄️ Database Architecture

### Core Tables

| Table | Description |
|-------|-------------|
| `agents` | Registered endpoint agents |
| `users` | Dashboard users |
| `raw_events` | Immutable event log |
| `sessions` | User sessions with state |
| `screentime` | Daily screen time totals |
| `app_usage` | Application usage records |
| `domain_visits` | Domain visit records |
| `app_inventory` | Installed applications |

### Key Stored Procedures

| Procedure | Purpose |
|-----------|---------|
| `process_screentime_event()` | Process incoming screen time data |
| `process_app_switch_event()` | Handle app switch events |
| `sync_screen_time_from_sessions()` | Aggregate session data |
| `cleanup_old_data()` | Data retention cleanup |

### Entity Relationship

```
┌─────────────┐       ┌─────────────┐
│   agents    │───┬───│  sessions   │
└─────────────┘   │   └─────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌─────────┐ ┌───────────┐ ┌─────────────┐
│screentime│ │ app_usage │ │domain_visits│
└─────────┘ └───────────┘ └─────────────┘
```

---

## 🔒 Security

### Security Features

| Feature | Description |
|---------|-------------|
| 🔐 **HMAC Verification** | All agent requests signed |
| 🔒 **HTTPS Support** | TLS encryption |
| 👥 **Role-Based Access** | Admin/User roles |
| 🚦 **Rate Limiting** | Prevent API abuse |
| 🔑 **Session Security** | Secure cookie handling |
| 📝 **Audit Logging** | All actions logged |

### Setting Up HTTPS

```nginx
# Nginx reverse proxy example
server {
    listen 443 ssl;
    server_name sentinel.example.com;
    
    ssl_certificate /etc/ssl/certs/sentinel.crt;
    ssl_certificate_key /etc/ssl/private/sentinel.key;
    
    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 🚀 Deployment

### Docker Deployment

```yaml
# docker-compose.yml
version: '3.8'
services:
  server:
    build: .
    ports:
      - "5050:5050"
    environment:
      - DATABASE_URL=postgresql://sentinel:password@db:5432/sentinel_edge
      - SECRET_KEY=${SECRET_KEY}
    depends_on:
      - db
      
  db:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=sentinel
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=sentinel_edge

volumes:
  postgres_data:
```

### Systemd Service

```ini
# /etc/systemd/system/sentineledge.service
[Unit]
Description=SentinelEdge Server
After=network.target postgresql.service

[Service]
Type=simple
User=sentineledge
WorkingDirectory=/opt/sentineledge/server
Environment="PATH=/opt/sentineledge/venv/bin"
ExecStart=/opt/sentineledge/venv/bin/gunicorn --bind 0.0.0.0:5050 --workers 4 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

### Production Checklist

- [ ] Set strong `SECRET_KEY` and `REGISTRATION_SECRET`
- [ ] Configure HTTPS (reverse proxy or direct)
- [ ] Set up database backups
- [ ] Configure log rotation
- [ ] Set up monitoring/alerting
- [ ] Review firewall rules (port 5050)
- [ ] Test rate limiting
- [ ] Create admin user

---

## 🔧 Maintenance

### Log Files

| Log | Location | Contents |
|-----|----------|----------|
| **Server Log** | `logs/server.log` | Main application log |
| **API Log** | `logs/api.log` | API request/response |
| **Dashboard Log** | `logs/dashboard.log` | Dashboard access |

### Database Maintenance

```bash
# Vacuum database
psql -U sentinel_user -d sentinel_edge -c "VACUUM ANALYZE;"

# Check table sizes
psql -U sentinel_user -d sentinel_edge -c "
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;"

# Backup database
pg_dump -U sentinel_user sentinel_edge > backup_$(date +%Y%m%d).sql
```

### Cleanup Old Data

```bash
# Run cleanup script (keeps last 90 days by default)
python scripts/utilities/cleanup_data.py --days 90
```

---

## 🐛 Troubleshooting

### Common Issues

#### "Function does not exist" Errors

```bash
# Apply stored procedures
python apply_sync_functions.py
```

#### Database Connection Failed

1. Check PostgreSQL is running:
   ```bash
   sudo systemctl status postgresql
   ```

2. Verify connection string in `.env`

3. Test connection:
   ```bash
   psql $DATABASE_URL -c "SELECT 1;"
   ```

#### Agent Not Registering

1. Check registration secret matches
2. Verify network connectivity
3. Check server logs: `logs/api.log`

#### Dashboard Not Loading

1. Check server is running:
   ```bash
   curl http://localhost:5050/
   ```

2. Check browser console for JavaScript errors

3. Clear browser cache

#### High Memory Usage

1. Reduce Gunicorn workers
2. Check for query issues in logs
3. Vacuum PostgreSQL database

---

## 📜 Version History

### v2.1.0 (2026-01-01)
- ⚡ Performance optimizations (connection pooling, query optimization)
- 🔒 Enhanced authentication with password policies
- 📊 Improved dashboard visualizations
- 🏷️ Domain classification system
- 📄 Report generation (PDF/CSV)
- 🐛 Bug fixes and stability improvements

### v2.0.0 (2025-12-01)
- 🔐 Multi-user authentication
- 📊 Complete dashboard redesign
- 🗄️ PostgreSQL stored procedures
- 📈 Real-time telemetry streaming
- 🔒 HMAC request verification

### v1.0.0 (2025-10-01)
- 🎉 Initial release
- 📊 Basic dashboard
- 📦 Agent registration and telemetry

---

## 📁 Project Structure

```
server/
├── server_main.py          # Entry point
├── server_app.py           # Flask application factory
├── server_api.py           # REST API endpoints
├── server_telemetry.py     # Telemetry processing
├── server_dashboard.py     # Dashboard routes
├── server_auth.py          # Authentication
├── server_models.py        # SQLAlchemy models
├── server_config.py        # Configuration
├── auth.py                 # Auth helpers
├── rate_limiter.py         # Rate limiting
├── domain_classifier.py    # Domain categorization
├── gunicorn_config.py      # Gunicorn settings
├── wsgi.py                 # WSGI entry point
├── migrations/             # Database migrations
├── scripts/                # Utility scripts
├── static/                 # CSS, JS assets
│   ├── css/
│   └── js/
├── templates/              # Jinja2 templates
│   ├── auth/
│   ├── admin/
│   └── dashboard/
├── logs/                   # Log files
├── .env.example            # Environment template
└── server_requirements.txt # Python dependencies
```

---

## 📞 Support

For issues:

1. **Check Logs**: `logs/server.log`, `logs/api.log`
2. **Database**: Verify PostgreSQL connectivity
3. **Network**: Check firewall and port availability
4. **Documentation**: Review this README

---

## 📄 License

Proprietary - Internal Use Only

© 2026 SentinelEdge. All Rights Reserved.
