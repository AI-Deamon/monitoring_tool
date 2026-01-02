# SentinelEdge Data Architecture Plan
## Comprehensive Analysis & Optimization Strategy

---

## 1. Telemetry Endpoints - Data Analysis

### 1.1 `/telemetry/screentime` (Every 30 seconds)
```json
{
  "agent_id": "bee1d4c6-...",
  "username": "Pittala Bhaskar",
  "timestamp": "2025-12-10T06:26:25+00:00",
  "period_start": "2025-12-10T06:25:55+00:00",
  "period_end": "2025-12-10T06:26:25+00:00",
  "active_seconds": 30,        ← INCREMENTAL (for this 30s period)
  "idle_seconds": 0,           ← INCREMENTAL
  "locked_seconds": 0,         ← INCREMENTAL
  "current_state": "active"    ← Current state
}
```

**Key Insight:** Agent sends **incremental values** (30s chunks), not totals.

---

### 1.2 `/telemetry/app-active` (Every 30 seconds)
```json
{
  "agent_id": "bee1d4c6-...",
  "username": "Pittala Bhaskar",
  "timestamp": "2025-12-10T06:26:55+00:00",
  "app": "mstsc.exe",
  "friendly_name": "Mstsc",
  "category": "other",
  "window_title": "192.168.1.101 - Remote Desktop Connection",
  "session_start": "2025-12-10T06:06:14+00:00",  ← When this app session started
  "duration_seconds": 1230,                       ← CUMULATIVE session duration
  "is_active": true
}
```

**Key Insight:** `duration_seconds` is **CUMULATIVE** (how long since `session_start`).

---

### 1.3 `/telemetry/app-switch` (On app change)
```json
{
  "agent_id": "2540eb54-...",
  "username": "surya",
  "timestamp": "2025-12-10T06:26:53+00:00",
  "app": "outlook.exe",
  "window_title": "Inbox - surya.k@bsolsystems.com - Outlook",
  "session_start": "2025-12-10T06:24:52+00:00",
  "session_end": "2025-12-10T06:26:53+00:00",
  "total_seconds": 121.485189,    ← FINAL duration of completed session
  "is_active": false              ← Session ended
}
```

**Key Insight:** This is a **COMPLETED session** - perfect for historical records.

---

### 1.4 `/telemetry/domain-active` (Every 30 seconds)
```json
{
  "agent_id": "fb172ea2-...",
  "username": "Venkatesan",
  "timestamp": "2025-12-10T06:27:17+00:00",
  "domain": "chatgpt.com",
  "browser": "Google Chrome",
  "url": null,
  "session_start": "2025-12-10T06:20:41+00:00",
  "duration_seconds": 395.74,     ← CUMULATIVE session duration
  "is_active": true
}
```

---

### 1.5 `/telemetry/domain-switch` (On domain change)
```json
{
  "agent_id": "...",
  "username": "...",
  "domain": "example.com",
  "session_start": "...",
  "session_end": "...",
  "total_seconds": 120.5,         ← FINAL duration
  "is_active": false
}
```

---

## 2. Data Architecture - Optimized Design

### Layer 1: LIVE STATUS (Real-time Dashboard)
**Table: `agent_current_status`**
- One row per agent (UPSERT)
- Updated every 30 seconds
- Shows: Who is using what RIGHT NOW

| Column | Source | Update Logic |
|--------|--------|--------------|
| current_app | app-active | REPLACE with latest |
| window_title | app-active | REPLACE with latest |
| current_state | screentime | REPLACE with latest |
| duration_seconds | app-active | REPLACE (cumulative from agent) |
| current_domain | domain-active | REPLACE with latest |
| current_browser | domain-active | REPLACE with latest |
| last_seen | all endpoints | REPLACE with timestamp |

---

### Layer 2: DAILY AGGREGATIONS (Dashboard Metrics)

#### Table: `screen_time`
| Column | Source | Update Logic |
|--------|--------|--------------|
| active_seconds | screentime telemetry | `+= 30` (INCREMENT) |
| idle_seconds | screentime telemetry | `+= 30` (INCREMENT) |
| locked_seconds | screentime telemetry | `+= 30` (INCREMENT) |

**PostgreSQL UPSERT:**
```sql
ON CONFLICT (agent_id, date) DO UPDATE SET
    active_seconds = screen_time.active_seconds + 30,
    idle_seconds = screen_time.idle_seconds + :idle,
    locked_seconds = screen_time.locked_seconds + :locked
```

#### Table: `app_usage`
| Column | Source | Update Logic |
|--------|--------|--------------|
| app | app-switch | App name |
| duration_seconds | app-switch | `+= total_seconds` (INCREMENT) |
| session_count | app-switch | `+= 1` (INCREMENT) |

---

### Layer 3: DETAILED HISTORY (Reports & Timeline)

#### Table: `app_sessions`
| Column | Source |
|--------|--------|
| app | app-switch |
| window_title | app-switch |
| start_time | session_start |
| end_time | session_end |
| duration_seconds | total_seconds |

**Logic:** APPEND-ONLY - Insert on each app-switch event.

#### Table: `domain_sessions`
| Column | Source |
|--------|--------|
| domain | domain-switch |
| browser | domain-switch |
| start_time | session_start |
| end_time | session_end |
| duration_seconds | total_seconds |

---

## 3. Dashboard Data Sources - Optimal Strategy

### 3.1 Overview Dashboard

| Metric | Source | Logic |
|--------|--------|-------|
| **Total Agents** | `agents` table | `COUNT(*)` |
| **Online Agents** | `agents.last_seen` | `WHERE last_seen > NOW() - 5min` |
| **Fleet Active Time** | `app_sessions` | `SUM(duration_seconds) WHERE date = today` |
| **Fleet Idle Time** | `screen_time` | `SUM(idle_seconds) WHERE date = today` |
| **Fleet Locked Time** | `screen_time` | `SUM(locked_seconds) WHERE date = today` |
| **Top App (Fleet)** | `app_usage` | `GROUP BY app ORDER BY SUM(duration) DESC LIMIT 1` |
| **Top Domain (Fleet)** | `domain_usage` | Same pattern |

### 3.2 Per-Agent Summary (Multi-Agent Table)

| Column | Source | Logic |
|--------|--------|-------|
| Hostname | `agents.hostname` | Direct |
| Status | `agents.last_seen` | Online if < 5 min ago |
| Current App | `agent_current_status.current_app` | Direct |
| Active Time | `app_sessions` | `SUM(duration) WHERE agent_id = X AND date = today` |
| Idle Time | `screen_time` | `idle_seconds WHERE agent_id = X AND date = today` |
| Top App | `app_usage` | `MAX(duration) WHERE agent_id = X AND date = today` |
| Apps Used | `app_usage` | `COUNT(DISTINCT app) WHERE agent_id = X` |
| Domains | `domain_usage` | `COUNT(DISTINCT domain) WHERE agent_id = X` |
| Installed Apps | `app_inventory` | `COUNT(*)` |

### 3.3 Agent Detail Page

| Section | Source |
|---------|--------|
| Live Status | `agent_current_status` |
| Screen Time Chart (7 days) | `screen_time WHERE date >= today - 7` |
| App Timeline | `app_sessions ORDER BY start_time` |
| Top Apps | `app_usage ORDER BY duration DESC` |
| Domain Timeline | `domain_sessions` |
| Top Domains | `domain_usage ORDER BY duration DESC` |
| Installed Apps | `app_inventory` |

---

## 4. Data Source Decision Matrix

| Metric | Use This Table | Why |
|--------|----------------|-----|
| **Active Time** | `app_sessions` | Append-only, never corrupted |
| **Idle Time** | `screen_time` | Only source of idle data |
| **Locked Time** | `screen_time` | Only source of locked data |
| **Current App** | `agent_current_status` | Real-time, one row per agent |
| **App History** | `app_sessions` | Complete session records |
| **Domain History** | `domain_sessions` | Complete session records |
| **Daily App Summary** | `app_usage` | Pre-aggregated for speed |

---

## 5. Endpoint Processing Logic

### screentime (Every 30s)
```
1. Parse: active_seconds, idle_seconds, locked_seconds (INCREMENTAL)
2. ATOMIC UPSERT into screen_time:
   active_seconds += incoming.active_seconds
   idle_seconds += incoming.idle_seconds
   locked_seconds += incoming.locked_seconds
```

### app-active (Every 30s)
```
1. UPSERT into agent_current_status:
   current_app = incoming.app
   window_title = incoming.window_title
   duration_seconds = incoming.duration_seconds (REPLACE, not add)
   last_seen = NOW()
```

### app-switch (On app change)
```
1. INSERT into app_sessions (APPEND-ONLY):
   Complete session record with start/end times
   
2. UPSERT into app_usage (daily aggregation):
   duration_seconds += incoming.total_seconds
   session_count += 1
```

### domain-active (Every 30s)
```
1. UPSERT into domain_sessions:
   Update end_time and duration for active session
   
2. UPSERT into agent_current_status:
   Update current_domain, current_browser, current_url
```

### domain-switch (On domain change)
```
1. INSERT into domain_sessions (APPEND-ONLY)
2. UPSERT into domain_usage (daily aggregation)
3. UPSERT into agent_current_status (Live View)
```

---

## 6. Performance Optimizations

### Indexes Required
```sql
CREATE INDEX idx_app_sessions_agent_date ON app_sessions(agent_id, start_time);
CREATE INDEX idx_screen_time_agent_date ON screen_time(agent_id, date);
CREATE INDEX idx_app_usage_agent_date ON app_usage(agent_id, date);
CREATE INDEX idx_domain_usage_agent_date ON domain_usage(agent_id, date);
```

### Query Optimization
1. Always filter by date FIRST
2. Use pre-aggregated tables for dashboard (app_usage, domain_usage)
3. Only query app_sessions for detailed timeline views
4. Cache fleet totals in memory (refresh every 30s)

---

## 7. Summary

| Data Need | Best Source | Why |
|-----------|-------------|-----|
| Real-time status | `agent_current_status` | One row per agent, always current |
| Active time (accurate) | `app_sessions` | Append-only, never corrupted |
| Idle/Locked time | `screen_time` | Only source |
| Daily metrics | `app_usage`, `domain_usage` | Pre-aggregated |
| Detailed history | `app_sessions`, `domain_sessions` | Complete records |

**Golden Rule:** 
- Active time → Calculate from `app_sessions`
- Idle/Locked → Use `screen_time` table
- Real-time → Use `agent_current_status`
