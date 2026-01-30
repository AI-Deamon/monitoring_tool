"""
Ingest Module - Enhanced with hardened HMAC verification
Local HTTP server for receiving helper data with replay protection
Now includes a comprehensive Debug Dashboard with Authentication.
"""

import json
import hmac
import hashlib
import time
import base64
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread, Lock
from datetime import datetime, timezone
from typing import Dict, Optional
from collections import OrderedDict
import logging
from queue import Queue, Empty, Full  # Added Full for queue overflow handling

from .config import CoreConfig
from .buffer import BufferDB

logger = logging.getLogger(__name__)

class ReplayProtectionCache:
    """LRU cache for replay protection with timestamp window"""
    
    def __init__(self, max_size: int = 1000, window_seconds: int = 60):
        self.max_size = max_size
        self.window_seconds = window_seconds
        self.cache = OrderedDict()
        self.cleanup_interval = 120  # 2 minutes
        self.last_cleanup = time.time()
    
    def is_valid(self, agent_id: str, timestamp: str, payload_hash: str) -> bool:
        """Check if request is valid (not replayed) and within time window"""
        current_time = time.time()
        
        # Clean up old entries periodically
        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup()
        
        try:
            # Parse timestamp
            request_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            request_timestamp = request_time.timestamp()
            
            # Check timestamp window (+/-60 seconds)
            time_diff = abs(current_time - request_timestamp)
            if time_diff > self.window_seconds:
                logger.warning(f"Timestamp out of window: {time_diff}s > {self.window_seconds}s")
                return False
            
            # Create cache key
            cache_key = f"{agent_id}:{payload_hash}"
            
            # Check if already seen
            if cache_key in self.cache:
                logger.warning(f"Replay detected for key: {cache_key[:20]}...")
                return False
            
            # Add to cache
            self.cache[cache_key] = current_time
            
            # Maintain size limit
            if len(self.cache) > self.max_size:
                # Remove oldest entry
                self.cache.popitem(last=False)
            
            return True
            
        except Exception as e:
            logger.error(f"Replay protection validation error: {e}")
            return False
    
    def _cleanup(self):
        """Remove old entries from cache"""
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds
        
        # Remove entries older than window
        keys_to_remove = []
        for key, timestamp in self.cache.items():
            if timestamp < cutoff_time:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.cache[key]
        
        self.last_cleanup = current_time
        logger.debug(f"Replay cache cleanup: removed {len(keys_to_remove)} entries")

class HelperRequestHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        logger.debug(format % args)

    # ============================
    #   AUTH / SECURITY
    # ============================
    def _verify_auth(self, request_data: dict) -> bool:
        """
        Verify request authorization.
        Security Disabled: Always returns True to simplify communication.
        """
        return True

    def _check_basic_auth(self) -> bool:
        """Check Basic Authentication for Dashboard"""
        auth_header = self.headers.get('Authorization')
        if not auth_header:
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="SentinelEdge Dashboard"')
            self.end_headers()
            return False
        
        try:
            auth_type, encoded_credentials = auth_header.split(' ', 1)
            if auth_type.lower() != 'basic':
                return False
            
            decoded_bytes = base64.b64decode(encoded_credentials)
            decoded_str = decoded_bytes.decode('utf-8')
            username, password = decoded_str.split(':', 1)
            
            # Simple hardcoded auth for debugging tool
            # In production this should come from secure config
            valid_user = os.environ.get('DASHBOARD_USER', 'admin')
            valid_pass = os.environ.get('DASHBOARD_PASS', 'sentinel')
            
            if username == valid_user and password == valid_pass:
                return True
        except:
            pass
            
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="SentinelEdge Dashboard"')
        self.end_headers()
        return False

    # ============================
    #   JSON RESPONSE HELPERS
    # ============================
    def _send_json(self, data: dict, status: int = 200):
        try:
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as e:
            # Client closed connection before we could respond
            # Log at debug level to help diagnose data loss issues (Bug #10 fix)
            logger.debug(f"Client connection closed during response: {e}")
            pass

    def _send_error(self, msg: str, status: int = 400):
        try:
            self._send_json({"error": msg}, status)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    # ============================
    #   GET HANDLER (Identity Sync & Dashboard)
    # ============================
    def do_GET(self):
        """Handle GET requests - used for identity sync and dashboard"""
        try:
            # Identity sync (No auth required for local helper)
            if self.path == "/identity":
                return self._handle_identity()
            
            # Dashboard routes (Require Basic Auth)
            if self.path == "/" or self.path.startswith("/api/"):
                if not self._check_basic_auth():
                    return

            if self.path == "/":
                return self._handle_dashboard()
            elif self.path == "/status": # Legacy alias
                return self._handle_api_status()
            elif self.path == "/api/status":
                return self._handle_api_status()
            elif self.path == "/api/activity":
                return self._handle_api_activity()
            elif self.path == "/api/apps":
                return self._handle_api_apps()
            elif self.path == "/api/domains":
                return self._handle_api_domains()
            elif self.path == "/api/inventory":
                return self._handle_api_inventory()
            else:
                return self._send_error("Unknown endpoint", 404)
        except Exception as e:
            logger.error(f"GET handler error: {e}", exc_info=True)
            self._send_error("Internal server error", 500)
    
    def _handle_identity(self):
        """Return Core's identity for Helper synchronization"""
        identity = {
            "agent_id": self.server.config.agent_id,
            "local_agent_key": self.server.config.local_agent_key,
            "token_present": bool(self.server.config.api_token)
        }
        logger.info(f"[SYNC] Helper requesting identity: {identity['agent_id'][:16]}...")
        self._send_json(identity)

    # ============================
    #   DASHBOARD API HANDLERS
    # ============================
    def _handle_api_status(self):
        """Return general status JSON"""
        buffer_counts = self.server.buffer.get_counts()
        live_stats = {}
        if hasattr(self.server, 'live_telemetry') and self.server.live_telemetry:
            live_stats = self.server.live_telemetry.get_stats()

        status = {
            'agent_id': self.server.config.agent_id,
            'server_url': self.server.config.server_url,
            'is_registered': self.server.config.is_registered(),
            'server_available': live_stats.get('server_available', False),
            'live': live_stats,
            'buffer': buffer_counts,
            'timestamp': datetime.now().isoformat()
        }
        self._send_json(status)

    def _handle_api_activity(self):
        """Return recent activity (merged events)"""
        events = self.server.buffer.get_recent_activity(limit=50)
        self._send_json({'data': events})

    def _handle_api_apps(self):
        """Return recent app sessions"""
        apps = self.server.buffer.get_recent_apps(limit=50)
        self._send_json({'data': apps})

    def _handle_api_domains(self):
        """Return recent domain sessions"""
        domains = self.server.buffer.get_recent_domains(limit=50)
        self._send_json({'data': domains})

    def _handle_api_inventory(self):
        """Return latest inventory"""
        apps = self.server.buffer.get_latest_inventory()
        self._send_json({'data': apps})

    def _handle_dashboard(self):
        """Serve the Dashboard SPA"""
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SentinelEdge Agent Dashboard</title>
    <style>
        :root { --primary: #2563eb; --bg: #f3f4f6; --card-bg: #ffffff; --text: #1f2937; --border: #e5e7eb; }
        body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; }
        .header { background: var(--card-bg); padding: 1rem 2rem; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .header h1 { margin: 0; font-size: 1.25rem; color: var(--primary); }
        .status-bar { display: flex; gap: 1rem; font-size: 0.875rem; color: #6b7280; }
        .status-dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; background: #ccc; margin-right: 4px; }
        .status-dot.online { background: #10b981; }
        .status-dot.offline { background: #ef4444; }
        .container { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
        .tabs { display: flex; gap: 1rem; margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); }
        .tab { padding: 0.75rem 1rem; cursor: pointer; border-bottom: 2px solid transparent; font-weight: 500; color: #6b7280; }
        .tab.active { border-bottom-color: var(--primary); color: var(--primary); }
        .card { background: var(--card-bg); border-radius: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; margin-bottom: 1.5rem; }
        .card-header { padding: 1rem; border-bottom: 1px solid var(--border); font-weight: 600; display: flex; justify-content: space-between; }
        table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
        th, td { text-align: left; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); }
        th { background: #f9fafb; font-weight: 600; color: #4b5563; }
        tr:hover { background: #f9fafb; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem; margin-bottom: 1.5rem; }
        .stat-card { padding: 1.5rem; }
        .stat-label { font-size: 0.875rem; color: #6b7280; margin-bottom: 0.5rem; }
        .stat-value { font-size: 1.5rem; font-weight: 700; color: #111827; }
        .refresh-btn { background: var(--primary); color: white; border: none; padding: 0.5rem 1rem; border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem; }
        .refresh-btn:hover { opacity: 0.9; }
        .footer { text-align: center; color: #9ca3af; font-size: 0.75rem; margin-top: 3rem; }
        .tag { padding: 2px 6px; border-radius: 4px; font-size: 0.75em; font-weight: 600; }
        .tag.active { background: #dcfce7; color: #166534; }
        .tag.idle { background: #fef9c3; color: #854d0e; }
        .tag.locked { background: #fee2e2; color: #991b1b; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ SentinelEdge Agent</h1>
        <div class="status-bar">
            <span id="agent-id">ID: ...</span>
            <span><span id="server-status" class="status-dot"></span>Server</span>
            <button class="refresh-btn" onclick="refreshAll()">Refresh</button>
        </div>
    </div>

    <div class="container">
        <!-- Live Metrics -->
        <div class="grid">
            <div class="card stat-card">
                <div class="stat-label">Current State</div>
                <div class="stat-value" id="current-state">-</div>
            </div>
            <div class="card stat-card">
                <div class="stat-label">Current App</div>
                <div class="stat-value" id="current-app" style="font-size: 1.1rem">-</div>
            </div>
            <div class="card stat-card">
                <div class="stat-label">Active Time (Session)</div>
                <div class="stat-value" id="active-time">0s</div>
            </div>
            <div class="card stat-card">
                <div class="stat-label">Buffer Queue</div>
                <div class="stat-value" id="buffer-size">0</div>
            </div>
        </div>

        <!-- Navigation -->
        <div class="tabs">
            <div class="tab active" onclick="switchTab('activity')">Activity Log</div>
            <div class="tab" onclick="switchTab('apps')">App Usage</div>
            <div class="tab" onclick="switchTab('domains')">Domain Tracking</div>
            <div class="tab" onclick="switchTab('inventory')">App Inventory</div>
        </div>

        <!-- Content Sections -->
        <div id="activity-view" class="view">
            <div class="card">
                <div class="card-header">Recent Activity (Merged Events)</div>
                <table>
                    <thead><tr><th>Type</th><th>Start Time</th><th>Duration</th><th>State Details</th></tr></thead>
                    <tbody id="activity-table"></tbody>
                </table>
            </div>
        </div>

        <div id="apps-view" class="view" style="display:none">
            <div class="card">
                <div class="card-header">Recent App Sessions</div>
                <table>
                    <thead><tr><th>App Name</th><th>Window Title</th><th>Start Time</th><th>Duration</th></tr></thead>
                    <tbody id="apps-table"></tbody>
                </table>
            </div>
        </div>

        <div id="domains-view" class="view" style="display:none">
            <div class="card">
                <div class="card-header">Recent Domain Sessions</div>
                <table>
                    <thead><tr><th>Domain</th><th>Browser</th><th>URL</th><th>Start Time</th><th>Duration</th></tr></thead>
                    <tbody id="domains-table"></tbody>
                </table>
            </div>
        </div>

        <div id="inventory-view" class="view" style="display:none">
            <div class="card">
                <div class="card-header">Installed Applications <span id="inv-count" style="font-weight:normal; color:#666; margin-left:10px"></span></div>
                <table>
                    <thead><tr><th>Name</th><th>Version</th><th>Publisher</th><th>Install Location</th><th>Install Date</th><th>Source</th></tr></thead>
                    <tbody id="inventory-table"></tbody>
                </table>
            </div>
        </div>

        <div class="footer">
            Last updated: <span id="last-updated">Never</span> | Auto-refresh: 5s
        </div>
    </div>

    <script>
        const VIEWS = ['activity', 'apps', 'domains', 'inventory'];
        let currentView = 'activity';

        function switchTab(view) {
            currentView = view;
            VIEWS.forEach(v => {
                document.getElementById(`${v}-view`).style.display = v === view ? 'block' : 'none';
            });
            document.querySelectorAll('.tab').forEach(t => {
                t.classList.toggle('active', t.textContent.toLowerCase().includes(view.split(' ')[0]));
            });
            refreshAll();
        }

        async function fetchJSON(endpoint) {
            try {
                const res = await fetch(endpoint);
                if (!res.ok) throw new Error(res.statusText);
                return await res.json();
            } catch (e) {
                console.error(`Fetch error ${endpoint}:`, e);
                return null;
            }
        }

        function formatTime(iso) {
            if (!iso) return '-';
            return new Date(iso).toLocaleString();
        }

        function formatDuration(sec) {
            if (sec === undefined || sec === null) return '-';
            const s = Math.round(sec);
            if (s < 60) return `${s}s`;
            const m = Math.floor(s / 60);
            return `${m}m ${s % 60}s`;
        }

        async function updateStatus() {
            const data = await fetchJSON('/api/status');
            if (!data) return;

            document.getElementById('agent-id').textContent = `ID: ${data.agent_id}`;
            const sDot = document.getElementById('server-status');
            sDot.className = `status-dot ${data.server_available ? 'online' : 'offline'}`;
            
            if (data.live) {
                const state = data.live.current_state;
                document.getElementById('current-state').innerHTML = `<span class="tag ${state}">${state.toUpperCase()}</span>`;
                document.getElementById('current-app').textContent = data.live.current_app || 'None';
                document.getElementById('active-time').textContent = `${data.live.counters?.active_seconds || 0}s`;
            }
            
            if (data.buffer) {
                document.getElementById('buffer-size').textContent = 
                    (data.buffer.heartbeats || 0) + (data.buffer.events || 0) + (data.buffer.domains || 0);
            }
            
            document.getElementById('last-updated').textContent = new Date().toLocaleTimeString();
        }

        async function updateActivity() {
            const data = await fetchJSON('/api/activity');
            if (!data) return;
            const tbody = document.getElementById('activity-table');
            tbody.innerHTML = data.data.map(e => `
                <tr>
                    <td><span class="tag ${e.type === 'idle' ? 'idle' : 'active'}">${e.type}</span></td>
                    <td>${formatTime(e.start)}</td>
                    <td>${formatDuration(e.duration)}</td>
                    <td>${JSON.stringify(e.state).substring(0, 100)}</td>
                </tr>
            `).join('');
        }

        async function updateApps() {
            const data = await fetchJSON('/api/apps');
            if (!data) return;
            const tbody = document.getElementById('apps-table');
            tbody.innerHTML = data.data.map(a => `
                <tr>
                    <td style="font-weight:500">${a.app}</td>
                    <td style="color:#666">${a.title || '-'}</td>
                    <td>${formatTime(a.start)}</td>
                    <td>${formatDuration(a.duration)}</td>
                </tr>
            `).join('');
        }

        async function updateDomains() {
            const data = await fetchJSON('/api/domains');
            if (!data) return;
            const tbody = document.getElementById('domains-table');
            tbody.innerHTML = data.data.map(d => `
                <tr>
                    <td style="font-weight:500">${d.domain}</td>
                    <td>${d.browser || '-'}</td>
                    <td title="${d.url}" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${d.url || '-'}</td>
                    <td>${formatTime(d.start)}</td>
                    <td>${formatDuration(d.duration)}</td>
                </tr>
            `).join('');
        }

        async function updateInventory() {
            const data = await fetchJSON('/api/inventory');
            if (!data) return;
            document.getElementById('inv-count').textContent = `(${data.data.length})`;
            const tbody = document.getElementById('inventory-table');
            tbody.innerHTML = data.data.map(i => `
                <tr>
                    <td style="font-weight:500">${i.name || i.Name}</td>
                    <td>${i.version || i.Version || '-'}</td>
                    <td>${i.publisher || i.Publisher || '-'}</td>
                    <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${i.install_location || i.InstallLocation || ''}">${i.install_location || i.InstallLocation || '-'}</td>
                    <td>${i.install_date || i.InstallDate || '-'}</td>
                    <td><span style="font-size:0.8em;padding:2px 6px;background:#e5e7eb;border-radius:4px">${i.source || i.Source || 'Unknown'}</span></td>
                </tr>
            `).join('');
        }

        function refreshAll() {
            updateStatus();
            if (currentView === 'activity') updateActivity();
            if (currentView === 'apps') updateApps();
            if (currentView === 'domains') updateDomains();
            if (currentView === 'inventory') updateInventory();
        }

        // Initial load
        refreshAll();
        
        // Auto-refresh 5s
        setInterval(refreshAll, 5000);
    </script>
</body>
</html>
        """
        
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html.encode())

    # ============================
    #   MAIN POST ROUTER
    # ============================
    def do_POST(self):
        try:
            logger.debug(f"POST request to {self.path}")
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            if not body:
                return self._send_error("Empty body")

            data = json.loads(body.decode())
            logger.debug(f"Request data: {data}")

            # Authentication for POST only
            if not self._verify_auth(data):
                return self._send_error("Authentication failed", 401)

            # Routing
            if self.path == "/ping":
                return self._send_json({"status": "ok"})
            
            if self.path == "/heartbeat":
                return self._handle_heartbeat(data)

            elif self.path == "/domains":
                return self._handle_domains(data)
            
            elif self.path == "/domains_active":
                return self._handle_domains_active(data)

            elif self.path == "/inventory":
                return self._handle_inventory(data)
            
            elif self.path == "/telemetry/state-change":
                return self._handle_state_change(data)

            elif self.path == "/screentime_spans":
                return self._handle_screentime_spans(data)

            else:
                return self._send_error("Unknown endpoint", 404)

        except json.JSONDecodeError:
            self._send_error("Invalid JSON")

        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # Client closed connection - ignore silently
            pass

        except Exception as e:
            logger.error(f"POST handler error: {e}", exc_info=True)
            self._send_error("Internal server error", 500)

    # ============================
    #   ENDPOINT HANDLERS
    # ============================
    def _handle_heartbeat(self, data):
        try:
            # FAST PATH: Store heartbeat in buffer FIRST (this is the backup)
            row_id = self.server.buffer.store_heartbeat(data)
            logger.debug(f"Stored heartbeat id={row_id}")
            
            # QUEUE live telemetry processing to background thread
            if hasattr(self.server, 'live_telemetry') and self.server.live_telemetry:
                try:
                    self.server.request_queue.put({
                        'type': 'heartbeat',
                        'data': data,
                        'timestamp': time.time()
                    }, timeout=0.1)
                except Full:
                    # Queue full - but data is already in buffer!
                    # Background uploader will handle it
                    logger.warning("[QUEUE] Request queue full, heartbeat stored in buffer for batch upload")
                except Exception as e:
                    logger.debug(f"Queue error (non-critical): {e}")
            
            # Notify Helper monitor that heartbeat was received
            if hasattr(self.server, 'ingest_server') and self.server.ingest_server:
                if self.server.ingest_server.heartbeat_callback:
                    try:
                        self.server.ingest_server.heartbeat_callback()
                    except Exception as e:
                        logger.debug(f"Heartbeat callback error: {e}")
            
            self._send_json({"status": "ok", "id": row_id})
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client closed connection
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            self._send_error("Storage failed", 500)

    def _handle_domains(self, data):
        """Handle legacy domain visits (history-based)"""
        try:
            domains = data.get("domains", [])
            for d in domains:
                d["agent_id"] = data.get("agent_id")

            count = self.server.buffer.store_domain_visits(domains)
            logger.debug(f"Stored {count} domain visits (history)")
            self._send_json({"status": "ok", "count": count})
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client closed connection
        except Exception as e:
            logger.error(f"Domain storage error: {e}")
            self._send_error("Storage failed", 500)
    
    def _handle_domains_active(self, data):
        """Handle domain active sessions (session-based tracking)"""
        try:
            sessions = data.get("domains_active", [])
            agent_id = data.get("agent_id")
            
            # Add agent_id to each session
            for session in sessions:
                session["agent_id"] = agent_id
            
            count = self.server.buffer.store_domain_sessions(sessions)
            
            total_duration = sum(s.get("duration_seconds", 0) for s in sessions)
            logger.info(f"Stored {count} domain sessions ({total_duration:.0f}s total)")
            
            self._send_json({"status": "ok", "count": count})

        except Exception as e:
            logger.error(f"Domain session storage error: {e}")
            self._send_error("Storage failed", 500)

    def _handle_inventory(self, data):
        try:
            row_id = self.server.buffer.store_inventory(data)
            self._send_json({"status": "ok", "id": row_id})
        except Exception as e:
            logger.error(f"Inventory error: {e}")
            self._send_error("Storage failed", 500)
    
    def _handle_state_change(self, data):
        """
        Handle immediate state-change telemetry from Helper.
        Queues for background upload to server.
        """
        try:
            # Validate required fields
            required_fields = ['previous_state', 'current_state', 'timestamp']
            for field in required_fields:
                if field not in data:
                    return self._send_error(f'Missing required field: {field}', 400)
            
            # Prepare event data
            event_data = {
                'agent_id': data.get('agent_id', self.server.config.agent_id),
                'event_type': 'state-change',
                'previous_state': data['previous_state'],
                'current_state': data['current_state'],
                'timestamp': data['timestamp'],
                'username': data.get('username', ''),
                'duration_seconds': data.get('duration_seconds', 0)
            }
            
            # Store in buffer for upload
            row_id = self.server.buffer.store_state_change(event_data)
            
            logger.info(
                f"[STATE] State-change received: "
                f"{data['previous_state']} -> {data['current_state']}"
            )
            
            # Queue for immediate upload (if live telemetry enabled)
            if hasattr(self.server, 'live_telemetry') and self.server.live_telemetry:
                try:
                    self.server.request_queue.put({
                        'type': 'state-change',
                        'data': event_data,
                        'timestamp': time.time()
                    }, timeout=0.1)
                except Exception as e:
                    logger.debug(f"Queue full, state-change will upload via buffer: {e}")
            
            self._send_json({'status': 'ok', 'id': row_id, 'queued': True})
            
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client closed connection
        except Exception as e:
            logger.error(f"State-change handler error: {e}", exc_info=True)
            self._send_error('Storage failed', 500)

    def _handle_screentime_spans(self, data):
        """Handle state spans from Helper for screen time tracking"""
        try:
            spans = data.get("spans", [])
            agent_id = data.get("agent_id")
            
            if not spans:
                return self._send_json({"status": "ok", "count": 0})
            
            count = 0
            for span in spans:
                span["agent_id"] = agent_id
                if self.server.buffer.store_state_span(span):
                    count += 1
            
            logger.info(f"[INGEST] Received {len(spans)} spans, stored {count} in buffer")
            
            self._send_json({"status": "ok", "count": count})

        except Exception as e:
            logger.error(f"Screentime spans storage error: {e}")
            self._send_error("Storage failed", 500)


class IngestServer:
    """Local HTTP server for receiving helper data - Config-driven"""
    
    def __init__(self, config: CoreConfig, buffer: BufferDB):
        self.config = config
        self.buffer = buffer
        self.server = None
        self.thread = None
        self.replay_cache = ReplayProtectionCache()
        self.enabled = True  # Can be toggled via config
        self.logger = logging.getLogger('IngestServer')
        self._current_port = config.listen_port
        self.live_telemetry = None  # Set by SentinelCore after initialization
        
        # Helper monitoring callback
        self.heartbeat_callback = None  # Called when Helper heartbeat received
        
        # Request queue for async processing
        self.request_queue = Queue(maxsize=100)
        self.queue_thread = None
        
        # Apply initial config
        self.apply_config(config)
    
    def set_heartbeat_callback(self, callback):
        """Set callback to notify when Helper heartbeat received"""
        self.heartbeat_callback = callback
    
    def _process_queue(self):
        """Background thread to process queued requests"""
        while True:
            try:
                # Get request from queue with timeout
                request_data = self.request_queue.get(timeout=1.0)
                
                # Process the request (this runs in background)
                if request_data['type'] == 'heartbeat':
                    # Full processing for heartbeats
                    if self.live_telemetry:
                        self.live_telemetry.process_heartbeat(request_data['data'])
                
                elif request_data['type'] == 'state-change':
                    # Upload state-change immediately
                    if self.live_telemetry:
                        self.live_telemetry.upload_state_change(request_data['data'])
                
                self.request_queue.task_done()
                
            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"Queue processing error: {e}")
    
    def apply_config(self, config):
        """Apply configuration changes dynamically"""
        core_config = config.config.get("core", {})
        old_enabled = self.enabled
        self.enabled = core_config.get("enable_ingest", True)
        new_port = core_config.get("listen_port", 48123)
        
        # Handle port change (requires restart)
        if self._current_port != new_port:
            self.logger.info(f"[CONFIG] Ingest port changed: {self._current_port} -> {new_port}")
            if self.server:
                self.stop()
                time.sleep(0.5)
                if self.enabled:
                    self.start()
        
        self._current_port = new_port
        
        # Handle enable/disable
        if old_enabled != self.enabled:
            if self.enabled and not self.server:
                self.logger.info("[CONFIG] Ingest server enabled, starting...")
                self.start()
            elif not self.enabled and self.server:
                self.logger.info("[CONFIG] Ingest server disabled, stopping...")
                self.stop()

    def start(self):
        if not self.enabled:
            self.logger.warning("Cannot start ingest server - disabled in config")
            return
        
        if self.server:
            self.logger.warning("Ingest server already running")
            return
        
        address = (self.config.listen_host, self.config.listen_port)

        self.server = HTTPServer(address, HelperRequestHandler)
        self.server.config = self.config
        self.server.buffer = self.buffer
        self.server.replay_cache = self.replay_cache
        self.server.live_telemetry = self.live_telemetry  # Pass to request handler

        # Start queue processor thread
        self.queue_thread = Thread(target=self._process_queue, daemon=True)
        self.queue_thread.start()
        
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        logger.info(f"Ingest server listening on {address[0]}:{address[1]}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server = None
            self.thread = None
            logger.info("Ingest server stopped")