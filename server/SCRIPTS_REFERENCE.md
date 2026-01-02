# SentinelEdge Server - Scripts & Procedures Reference
# =====================================================

## 📁 Directory Structure

```
server/
├── scripts/
│   ├── fixes/           # Data repair scripts
│   ├── utilities/       # Admin utilities
│   └── migrations/      # Database migrations
├── migrations/          # Alembic migrations
└── *.py                 # Main server files
```

---

## 🔧 FIX SCRIPTS (scripts/fixes/)

### 1. fix_locked_state.py
**Purpose:** Fix incorrect locked state calculations
**When to use:** Screen time showing too much locked time
```bash
python scripts/fixes/fix_locked_state.py
```

### 2. fix_screentime_logic.py
**Purpose:** Recalculate screen time from raw sessions
**When to use:** Screen time totals are wrong
```bash
python scripts/fixes/fix_screentime_logic.py
```

### 3. fix_domain_columns.py
**Purpose:** Add missing domain classification columns
**When to use:** After upgrade, classification not working
```bash
python scripts/fixes/fix_domain_columns.py
```

### 4. fix_duplicate_events.py
**Purpose:** Remove duplicate events from database
**When to use:** Same events appearing multiple times
```bash
python scripts/fixes/fix_duplicate_events.py
```

### 5. cleanup_screentime.py
**Purpose:** Clean up old/invalid screen time records
**When to use:** Dashboard showing incorrect data
```bash
python scripts/fixes/cleanup_screentime.py
```

### 6. add_away_seconds.py
**Purpose:** Add away_seconds column to screen_time table
**When to use:** Upgrading from older version
```bash
python scripts/fixes/add_away_seconds.py
```

### 7. add_indexes.py
**Purpose:** Add performance indexes to database
**When to use:** Dashboard loading slowly
```bash
python scripts/fixes/add_indexes.py
```

### 8. apply_sync_functions.py
**Purpose:** Create/update database sync functions
**When to use:** After fresh install or upgrade
```bash
python scripts/fixes/apply_sync_functions.py
```

---

## 🛠️ UTILITY SCRIPTS (scripts/utilities/)

### 1. list_users.py
**Purpose:** List all registered agents
```bash
python scripts/utilities/list_users.py
```
**Output:**
```
Agent ID                    | Hostname    | Last Seen
------------------------------------------------------------
LAPTOP-ABC-xyz123           | john-laptop | 2025-12-21 10:30
```

### 2. delete_agent.py
**Purpose:** Delete an agent and all its data
```bash
python scripts/utilities/delete_agent.py AGENT_ID
```

### 3. check_db_data.py
**Purpose:** Check database health and data integrity
```bash
python scripts/utilities/check_db_data.py
```

### 4. get_agent_domains.py
**Purpose:** Get domain usage for specific agent
```bash
python scripts/utilities/get_agent_domains.py AGENT_ID
```

### 5. get_user_domains.py
**Purpose:** Get domain usage summary for all users
```bash
python scripts/utilities/get_user_domains.py
```

### 6. check_agent_domains.py
**Purpose:** Check domain classification status for agent
```bash
python scripts/utilities/check_agent_domains.py AGENT_ID
```

### 7. extract_domains.py
**Purpose:** Export domains to CSV for analysis
```bash
python scripts/utilities/extract_domains.py > domains.csv
```

---

## 📊 SQL SCRIPTS (scripts/)

### setup_classification.sql
**Purpose:** Create domain classification tables and rules
**When to use:** New installation
```bash
psql -U sentinelserver -d sentinel_edge_v1 -f scripts/setup_classification.sql
```

---

## 🔄 DATABASE SYNC FUNCTIONS

These SQL functions are created by `apply_sync_functions.py`:

| Function | Purpose | Runs |
|----------|---------|------|
| `sync_screen_time_from_sessions()` | Sync daily screen time | Every 5 min |
| `sync_app_usage_from_sessions()` | Sync app usage | Every 5 min |
| `sync_domain_usage_from_sessions()` | Sync domain usage | Every 5 min |

---

## 📋 MAIN SERVER SCRIPTS

| Script | Purpose | Usage |
|--------|---------|-------|
| `server_main.py` | Main server entry point | `python server_main.py` |
| `server_cleanup.py` | Data cleanup & classification | `python server_cleanup.py --classify` |
| `classify_domains.py` | Manual domain classification | `python classify_domains.py` |

---

## 🚨 COMMON FIXES

### Dashboard shows 0 screen time
```bash
python scripts/fixes/apply_sync_functions.py
python scripts/fixes/fix_screentime_logic.py
```

### Domain classification not working
```bash
psql -f scripts/setup_classification.sql
python classify_domains.py
```

### Too much "locked" time showing
```bash
python scripts/fixes/fix_locked_state.py
```

### Database slow
```bash
python scripts/fixes/add_indexes.py
```

### Agent not appearing
```bash
python scripts/utilities/list_users.py
# Check if agent is registered
```

---

## 📝 Running Fix Scripts

All fix scripts follow this pattern:

```bash
# 1. Navigate to server directory
cd server

# 2. Activate virtual environment (if using)
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux

# 3. Run the script
python scripts/fixes/SCRIPT_NAME.py

# 4. Restart server after fixes
python server_main.py
```

---

## ⚠️ Important Notes

1. **Always backup database** before running fix scripts
2. **Stop server** before running major fixes
3. **Check logs** after running: `logs/server.log`
4. Fix scripts are **idempotent** - safe to run multiple times
