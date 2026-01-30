# CURRENT_STATE.md - Dashboard Codebase Analysis

## Dependencies (base.html)
| Dependency | Version | CDN |
|------------|---------|-----|
| Chart.js | 4.4.0 | `chart.js@4.4.0/dist/chart.umd.min.js` |
| Inter Font | - | Google Fonts |
| JetBrains Mono | - | Google Fonts |

**Missing (Required for new charts):**
- `chartjs-chart-treemap` - for domain treemap
- `chartjs-plugin-annotation` - for anomaly markers

---

## CSS Variables (:root in dashboard.css)
```css
--brand-primary: #6366f1
--surface: #ffffff
--border: #e2e8f0
--text-primary: #0f172a
--success: #10b981
--warning: #f59e0b
--danger: #ef4444
--info: #06b6d4
--heatmap-low: #e0e7ff    /* NEW */
--heatmap-high: #4f46e5   /* NEW */
--gauge-bg: #f3f4f6       /* NEW */
```

---

## JavaScript Functions

### timezone_utils.js
| Function | Purpose |
|----------|---------|
| `formatDateTimeIST(dateStr)` | Full datetime with IST |
| `formatTimeIST(dateStr)` | Time only with IST |
| `formatTime(seconds)` | Duration (Xh Xm Xs) |
| `getCurrentTimeIST()` | Current IST time |

### utils.js
| Function | Purpose |
|----------|---------|
| `fetchJSON(url)` | Fetch with error handling |
| `fetchJSONCached(url)` | Cached fetch (30s TTL) |
| `showToast(msg, status)` | Toast notifications |
| `debounce(fn, wait)` | Input debounce |
| `getStatusBadge(lastSeen)` | Active/Idle/Offline badge |

---

## API Endpoints (server_dashboard.py)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/overview` | GET | Fleet metrics, screen time totals |
| `/api/agents` | GET | All agents with stats |
| `/api/agent/{id}/screentime` | GET | 7-day history |
| `/api/agent/{id}/apps` | GET | Top 20 apps |
| `/api/agent/{id}/domains` | GET | Top 20 domains |
| `/api/agent/{id}/full-report` | GET | Complete agent data |
| `/api/agent/{id}/activity-timeline` | GET | Hourly breakdown |
| `/api/agent/{id}/app-sessions` | GET | Individual sessions |

### New Endpoints Needed
| Endpoint | Data Source |
|----------|-------------|
| `/api/overview/productivity-score` | screen_time table |
| `/api/overview/category-breakdown` | app_usage + classification |
| `/api/overview/idle-analysis` | screen_time hourly |
| `/api/overview/activity-heatmap` | app_sessions aggregated |

---

## Overview Page Structure (overview.html)
- **Metrics Grid**: 3 cards (Total Agents, Online, Offline)
- **Charts Grid 1**: Top 5 Active/Idle/Locked (3 bar charts)
- **Charts Grid 2**: Agent Status + Screen Time (2 doughnut)
- **Metrics Row**: Top App + Top Domain cards
- **Inline CSS**: Lines 100-171
- **Inline JS**: Lines 175-422

---

## Authentication Pattern
```python
@bp.route('/api/...')
@login_required
@api_rate_limit
def api_function():
    user_filter = get_user_filter()  # None for admin
```

---

## Timezone Handling
- All DB timestamps: **Naive UTC**
- Frontend conversion: **Asia/Kolkata (IST)**
- Footer displays: **"IST (UTC+5:30)"**
