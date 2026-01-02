# 📋 SentinelEdge Implementation Task Sheet

This sheet tracks the alignment of all server endpoints and dashboard logic with the **Approved Data Architecture Plan**.

## 🧠 Core Logic (The "Golden Rules")
1. **Screen Time**: `active_seconds` comes from **Incremental Telemetry** (+30s). Atomic UPSERT.
2. **Active Duration**: Calculated from **App Sessions** (History) for maximum accuracy.
3. **Live Status**: Comes from **App Active** (Heartbeat). One row per agent.
4. **History**: App/Domain Switches are **Append-Only** (Source of Truth).

---

## 🚀 1. Telemetry Endpoints (Data Ingestion)

### ✅ A. Screen Time (`/telemetry/screentime`)
- [x] **Logic**: Atomic Increment (`active_seconds += 30`) using raw SQL Upsert.
- [x] **Safety**: Prevents race conditions.
- [x] **Status**: **DONE** (Implemented & Verified).

### ⏳ B. App Active (`/telemetry/app-active`)
- [ ] **Logic**: Live Status Upsert (One row per agent).
- [ ] **Target Table**: `agent_current_status`.
- [ ] **Action**: Check `server_telemetry.py` to ensure it replaces/updates correctly.

### ⏳ C. App Switch (`/telemetry/app-switch`)
- [ ] **Logic**: 
    1. **History**: Append to `app_sessions` (Source of Truth).
    2. **Aggregation**: Upsert to `app_usage` (Daily Totals for speed).
- [ ] **Action**: Verify both tables are updated in `server_telemetry.py`.

### ⏳ D. Domain Active (`/telemetry/domain-active`)
- [ ] **Logic**: Update open session end_time/duration.
- [ ] **Target Table**: `domain_sessions`.
- [ ] **Action**: Verify session extension logic.

### ⏳ E. Domain Switch (`/telemetry/domain-switch`)
- [ ] **Logic**: 
    1. **History**: Append to `domain_sessions`.
    2. **Aggregation**: Upsert to `domain_usage` (Daily Totals).
- [ ] **Action**: Verify `domain_usage` aggregation exists (might be missing).

---

## 📊 2. Dashboard Logic (Data Display)

### ✅ A. Overview API
- [x] **Active Time**: Uses `app_sessions` (SUM duration).
- [x] **Idle/Locked**: Uses `screen_time` table.
- [x] **Status**: Uses `app_sessions` for reliable active time calculation.

### ⏳ B. Agent Detail API
- [ ] **Active Time**: Ensure it uses `app_sessions` sum.
- [ ] **Timeline**: Fetch from `app_sessions`.
- [ ] **Status**: Fetch from `agent_current_status`.

---

## 🛠️ 3. Verification Steps
1. **Simulate 30s passing**: Send manual `app-active` and `screentime` payloads.
2. **Simulate App Switch**: Send `app-switch` payload.
3. **Check DB**: Confirm `screen_time` incremented, `app_sessions` appended, `agent_current_status` updated.
