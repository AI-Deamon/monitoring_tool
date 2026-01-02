# SentinelEdge Server - Deployment Guide

## Overview

SentinelEdge Server is a Flask-based telemetry ingestion and dashboard server that collects and visualizes agent data including:

- **Screen Time**: Active, idle, and locked time tracking
- **App Usage**: Application usage duration and sessions
- **Domain Usage**: Website/domain tracking with duration
- **App Inventory**: Installed applications tracking
- **Real-time Telemetry**: Live data ingestion every 30 seconds

## Quick Start

### Development (Local)

```powershell
# 1. Install dependencies
pip install -r server_requirements.txt

# 2. Set up environment
copy .env.production.template .env
# Edit .env with your database credentials

# 3. Start PostgreSQL (WSL example)
wsl sudo service postgresql start

# 4. Run the server
python server_main.py
```

Server will be available at:
- **API**: http://localhost:5050/api/v1/
- **Dashboard**: http://localhost:5050/dashboard/
- **Health Check**: http://localhost:5050/

### Production (Docker)

```bash
# 1. Set up environment variables
cp .env.production.template .env
# Edit .env with secure values

# 2. Generate a secret key
python -c "import secrets; print(secrets.token_hex(32))"
# Add to .env as SECRET_KEY

# 3. Start services
docker-compose up -d

# 4. Check logs
docker-compose logs -f server

# 5. View status
docker-compose ps
```

### Production (Manual)

```bash
# 1. Install dependencies
pip install -r server_requirements.txt

# 2. Set environment variables
export DATABASE_URL="postgresql://sentinel:password@localhost:5432/sentinel_edge"
export SECRET_KEY="your-secure-key"
export LOG_LEVEL="INFO"

# 3. Run with Gunicorn
gunicorn --bind 0.0.0.0:5050 --workers 4 --threads 2 wsgi:app
```

## API Endpoints

### Authentication

All endpoints (except `/register`) require authentication:

```
X-API-Key: sk_live_xxxxx
X-Agent-ID: HOSTNAME-UUID
```

### Core Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | Health check |
| `/register` | POST | No | Agent registration |
| `/heartbeat` | POST | Yes | Agent heartbeat |
| `/inventory` | POST | Yes | App inventory upload |

### Telemetry Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/telemetry/screentime` | POST | Screen time data |
| `/telemetry/app-active` | POST | Active app tracking |
| `/telemetry/domain-active` | POST | Active domain tracking |
| `/telemetry/app-switch` | POST | App switch events |
| `/telemetry/domain-switch` | POST | Domain switch events |
| `/telemetry/state-change` | POST | State change events |

### Batch Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/screentime` | POST | Batch screen time |
| `/app-usage` | POST | Batch app usage |
| `/domain-usage` | POST | Batch domain usage |

### Dashboard API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/dashboard/` | GET | Dashboard UI |
| `/dashboard/api/overview` | GET | Overview metrics |
| `/dashboard/api/agents` | GET | All agents list |
| `/dashboard/api/agents/{id}/today` | GET | Agent today data |

## Database Setup

### PostgreSQL (Recommended)

```sql
-- Create user and database
CREATE USER sentinel WITH PASSWORD 'your_secure_password';
CREATE DATABASE sentinel_edge OWNER sentinel;
GRANT ALL PRIVILEGES ON DATABASE sentinel_edge TO sentinel;
```

### Migrations

```bash
# Initialize migrations (if not done)
alembic init migrations

# Run migrations
alembic upgrade head

# Create new migration after model changes
alembic revision --autogenerate -m "description"
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string |
| `SERVER_HOST` | 0.0.0.0 | Bind address |
| `SERVER_PORT` | 5050 | Listen port |
| `SECRET_KEY` | dev-secret | JWT signing key |
| `LOG_LEVEL` | INFO | Logging level |
| `RATE_LIMIT_ENABLED` | true | Enable rate limiting |
| `RATE_LIMIT_REQUESTS` | 100 | Requests per period |
| `RATE_LIMIT_PERIOD` | 60 | Period in seconds |
| `RETENTION_DAYS` | 90 | Data retention days |

## Security

### Production Checklist

- [ ] Change `SECRET_KEY` to a secure random value
- [ ] Use strong database password
- [ ] Enable HTTPS (use Nginx reverse proxy)
- [ ] Configure firewall rules
- [ ] Enable rate limiting
- [ ] Set up log rotation
- [ ] Configure backup strategy

### Nginx SSL Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    location / {
        proxy_pass http://localhost:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Monitoring

### Health Checks

```bash
# Simple health check
curl http://localhost:5050/

# Expected response
{"service": "SentinelEdge Server", "status": "ok", "version": "2.0.0"}
```

### Logs

```bash
# Docker logs
docker-compose logs -f server

# Local logs
tail -f logs/server.log
```

## Troubleshooting

### Common Issues

1. **Database Connection Error**
   - Verify PostgreSQL is running
   - Check DATABASE_URL format
   - Ensure database and user exist

2. **401 Unauthorized**
   - Verify X-API-Key header
   - Check agent registration status
   - Ensure correct X-Agent-ID

3. **DateTime Mismatch Error**
   - Ensure server uses timezone-aware datetimes
   - Check agent timestamp format (should include Z or +00:00)

4. **Permission Denied (Docker)**
   - Check volume ownership
   - Verify user exists in container

## Version History

- **v2.0.0** - Complete server rewrite with improved telemetry
- **v1.x** - Legacy agent support

## License

Proprietary - SentinelEdge
