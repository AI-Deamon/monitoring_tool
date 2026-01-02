# SentinelEdge Server v2.0

Enterprise endpoint monitoring server with dashboard.

## 📁 Directory Structure

```
server/
├── deploy/                    # Deployment files
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── easy_deploy.bat/sh
│   └── wsgi.py
│
├── docs/                      # Documentation
│   ├── README.md              # Original readme
│   ├── DEPLOYMENT.md          # Deployment guide
│   ├── DATA_ARCHITECTURE_PLAN.md
│   ├── AGENTS.md
│   └── TASK_SHEET.md
│
├── logs/                      # Server logs (auto-generated)
│   ├── server.log
│   ├── api.log
│   └── dashboard.log
│
├── migrations/                # Alembic database migrations
│   ├── versions/
│   ├── add_os_details.py      # OS detection fields migration
│   └── env.py
│
├── scripts/                   # Utility scripts
│   ├── fixes/                 # One-time database fixes
│   │   ├── fix_db_schema.py
│   │   ├── fix_locked_state.py
│   │   └── ...
│   └── utilities/             # Data extraction tools
│       ├── check_db_data.py
│       ├── delete_agent.py
│       ├── list_users.py
│       └── ...
│
├── static/                    # Static assets (CSS/JS)
│   ├── css/
│   └── js/
│
├── templates/                 # Jinja2 HTML templates
│   └── dashboard/
│       ├── overview.html
│       ├── agent_detail.html
│       └── ...
│
├── ─────────────────────────  # CORE SERVER FILES
├── server_main.py             # Entry point - run this
├── server_app.py              # Flask app factory
├── server_config.py           # Configuration loader
├── server_models.py           # SQLAlchemy models
├── server_api.py              # REST API endpoints
├── server_telemetry.py        # Telemetry processing
├── server_dashboard.py        # Dashboard routes & APIs
├── server_auth.py             # Authentication/JWT
├── server_cleanup.py          # Background cleanup tasks
├── server_analytics.py        # Analytics functions
│
├── ─────────────────────────  # SUPPORTING FILES
├── extensions.py              # Flask extensions (db, etc)
├── schemas.py                 # Pydantic validation schemas
├── rate_limiter.py            # API rate limiting
├── logging_config.py          # Logging configuration
├── background_tasks.py        # Background task scheduler
│
├── ─────────────────────────  # CONFIG FILES
├── .env                       # Environment variables
├── alembic.ini                # Alembic config
└── server_requirements.txt    # Python dependencies
```

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r server_requirements.txt

# 2. Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/sentinel_edge"
export JWT_SECRET_KEY="your-secret-key"

# 3. Run server
python server_main.py
```

## 🔧 Core Files Description

| File | Purpose |
|------|---------|
| `server_main.py` | **Entry point** - starts Flask server |
| `server_app.py` | Flask app factory |
| `server_config.py` | Loads config from environment |
| `server_models.py` | All SQLAlchemy database models |
| `server_api.py` | REST API endpoints (/register, /telemetry/*) |
| `server_telemetry.py` | Processes agent telemetry data |
| `server_dashboard.py` | Dashboard pages & APIs |
| `server_auth.py` | JWT authentication decorators |
| `schemas.py` | Pydantic request validation |

## 📊 Database Tables

| Table | Description |
|-------|-------------|
| `agents` | Registered agents |
| `screen_time` | Daily screen time per agent |
| `state_changes` | Active/idle/locked transitions |
| `app_sessions` | Application usage sessions |
| `app_usage` | Aggregated app usage per day |
| `domain_usage` | Aggregated domain usage per day |
| `domain_visits` | Individual domain visits |
| `app_inventory` | Installed applications |

## 🔐 Authentication

Agents authenticate using:
1. JWT Bearer token (Authorization header)
2. API Key (X-API-Key header)

## 📝 Recent Changes (Dec 17, 2025)

- Added startup state event handling
- Added duration sanity checks (4-hour cap, same-day only)
- Added `away_seconds` to screen_time
- Added OS detection fields to agents table
