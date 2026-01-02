# SentinelEdge Server - Release v2.0.0

Production-ready server for SentinelEdge agent telemetry collection.
Features robust data ingestion, atomic processing, and comprehensive analytics.

## 🌟 Key Features

### 1. Robust Data Ingestion
- **Raw Event Storage**: All incoming telemetry is immediately stored in a `raw_events` table before processing. This provides an immutable audit trail and allows for data replay if needed.
- **Batch & Single Support**: Telemetry endpoints handle both single items (live streaming) and batch arrays (buffered uploads) seamlessy.

### 2. Atomic Data Processing
- **Stored Procedures**: Critical logic (Screen Time, App Switching) is handled via PostgreSQL stored procedures (`process_screentime_event`, `process_app_switch_event`).
- **Transaction Safety**: Data processing is wrapped in transactions to ensure zero partial writes.
- **Daily Totals**: Screen time tracking uses a "Replace/Greatest" logic to handle daily cumulative totals from agents, preventing data drift.

### 3. Analytics Dashboard
- **Rich Visualization**: View detailed screen time, app usage, and domain tracking.
- **User Attribution**: Displays `DOMAIN\User` for all agents.
- **Friendly Names**: Automatically maps `chrome.exe` to "Google Chrome", etc.
- **Time-Travel**: View historical data for any date.

## Quick Deploy

### Docker (Recommended)

```bash
# 1. Set up environment
cp .env.production.template .env
# Edit .env with your secure values

# 2. Deploy
docker-compose up -d

# 3. Verify
curl http://localhost:5050/
```

### Manual

```bash
# 1. Install dependencies
pip install -r server_requirements.txt

# 2. Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/sentinel_edge"
export SECRET_KEY="your-secure-key"

# 3. Initialize Database
# Only needed for first run if migrations aren't automatic
# python apply_sync_functions.py

# 4. Run with Gunicorn
gunicorn --bind 0.0.0.0:5050 --workers 4 wsgi:app
```

## Maintenance & Troubleshooting

### fixing "Function does not exist" errors
If you see errors about missing functions (`sync_screen_time_from_sessions`, etc.) in the logs, run the patch script:

```bash
python apply_sync_functions.py
```

This applies the necessary Stored Procedures to the running database.

### Endpoints

- **Health**: `GET /`
- **Dashboard**: `GET /dashboard/`
- **API Base**: `/api/v1/`
    - `/register`: Agent registration
    - `/telemetry/*`: Live telemetry ingestion
    - `/merged-events`: Batch historical data

## Requirements

- Python 3.11+
- PostgreSQL 14+
- 512MB RAM minimum
