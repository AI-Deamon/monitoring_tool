"""
Buffer Module
SQLite-based buffering for offline resilience
"""
import sqlite3
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class BufferDB:
    """SQLite buffer for telemetry data with thread-safety"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()  # Thread-local connections
        self._init_lock = threading.Lock()
        
        # Initialize database - CREATE TABLE IF NOT EXISTS handles everything safely
        with self._init_lock:
            # If database doesn't exist, create it
            if not self.db_path.exists():
                logger.info("Database not found, creating new database")
                self._init_db()
            else:
                # Database exists - validate schema
                if not self.validate_schema():
                    logger.warning("Schema invalid or missing, recreating database")
                    self._recreate_db()
                    self._init_db()
                else:
                    logger.info("Database schema validated successfully")
    
    @contextmanager
    def _get_connection(self):
        """Thread-safe connection context manager with transactions"""
        import time
        
        # Track connection age for periodic refresh (Bug #2 fix - connection leak)
        if not hasattr(self._local, 'conn_created'):
            self._local.conn_created = 0
        
        # Refresh connections older than 1 hour to prevent memory leaks
        current_time = time.time()
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            if current_time - self._local.conn_created > 3600:  # 1 hour
                try:
                    self._local.conn.close()
                    logger.debug("Refreshed stale database connection (age > 1 hour)")
                except Exception as e:
                    logger.debug(f"Error closing stale connection: {e}")
                self._local.conn = None
        
        # Get or create thread-local connection
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,
                isolation_level='DEFERRED',  # Explicit transactions
                check_same_thread=False
            )
            # Performance PRAGMAs - optimized for low memory
            self._local.conn.execute("PRAGMA journal_mode=WAL")        # Write-ahead logging
            self._local.conn.execute("PRAGMA busy_timeout=5000")       # 5s busy timeout
            self._local.conn.execute("PRAGMA synchronous=NORMAL")      # Balanced durability
            self._local.conn.execute("PRAGMA cache_size=-2000")        # 2MB cache (reduced from 8MB)
            self._local.conn.execute("PRAGMA temp_store=MEMORY")       # Temp tables in memory
            self._local.conn.execute("PRAGMA mmap_size=16777216")      # 16MB memory-mapped I/O (reduced from 64MB)
            self._local.conn.execute("PRAGMA page_size=4096")          # 4KB pages (optimal)
            self._local.conn_created = current_time
        
        conn = self._local.conn
        
        try:
            yield conn
            conn.commit()  # Commit on success
        except Exception as e:
            conn.rollback()  # Rollback on error
            logger.error(f"Database error, rolled back: {e}")
            raise
    
    def close(self):
        """Close all thread-local connections"""
        if hasattr(self._local, 'conn') and self._local.conn:
            try:
                self._local.conn.close()
                self._local.conn = None
            except:
                pass
    
    def emergency_cleanup(self) -> int:
        """
        FIX #7: Emergency cleanup when disk is full.
        Deletes old processed data to free space.
        Returns: Number of rows deleted
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                total_deleted = 0

                # Delete old processed heartbeats (older than 7 days)
                cursor.execute('''
                    DELETE FROM heartbeats 
                    WHERE processed = 1 
                    AND timestamp < datetime('now', '-7 days')
                ''')
                deleted_hb = cursor.rowcount
                total_deleted += deleted_hb

                # Delete old uploaded events (older than 7 days)
                cursor.execute('''
                    DELETE FROM merged_events 
                    WHERE uploaded = 1 
                    AND timestamp < datetime('now', '-7 days')
                ''')
                deleted_events = cursor.rowcount
                total_deleted += deleted_events

                # Delete old domain sessions (older than 7 days)
                cursor.execute('''
                    DELETE FROM domain_active_sessions 
                    WHERE uploaded = 1 
                    AND start_time < datetime('now', '-7 days')
                ''')
                deleted_domains = cursor.rowcount
                total_deleted += deleted_domains

                # Delete old state spans (older than 7 days)
                cursor.execute('''
                    DELETE FROM state_spans 
                    WHERE uploaded = 1 
                    AND start_time < datetime('now', '-7 days')
                ''')
                deleted_spans = cursor.rowcount
                total_deleted += deleted_spans

            logger.warning(
                f"[BUFFER] Emergency cleanup: "
                f"Deleted {deleted_hb} heartbeats, {deleted_events} events, "
                f"{deleted_domains} domain sessions, {deleted_spans} spans "
                f"(total: {total_deleted} rows)"
            )

            # Run VACUUM to reclaim disk space
            try:
                with self._get_connection() as conn:
                    conn.execute('VACUUM')
                logger.info("[BUFFER] VACUUM completed - disk space reclaimed")
            except Exception as ve:
                logger.warning(f"[BUFFER] VACUUM failed: {ve}")

            return total_deleted

        except Exception as e:
            logger.error(f"[BUFFER] Emergency cleanup failed: {e}")
            return 0
    
    def validate_schema(self) -> bool:
        """Validate that all required tables exist and have required columns"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Required tables
            required_tables = {
                'heartbeats',
                'merged_events', 
                'domain_visits',
                'domain_active_sessions',
                'state_spans',
                'inventory_snapshots',
                'upload_batches',
                'state'
            }
            
            # Get existing tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = {row[0] for row in cursor.fetchall()}
            
            # Check if all required tables exist
            missing_tables = required_tables - existing_tables
            if missing_tables:
                logger.error(f"Missing database tables: {missing_tables}")
                conn.close()
                return False
            
            # Bug #7 fix: Validate required columns exist in critical tables
            required_columns = {
                'heartbeats': ['agent_id', 'sequence', 'timestamp', 'payload', 'received_at', 'processed'],
                'merged_events': ['agent_id', 'username', 'event_type', 'start_time', 'end_time', 'duration_seconds', 'state_data', 'heartbeat_count', 'uploaded'],
                'domain_active_sessions': ['agent_id', 'domain', 'browser', 'url', 'title', 'start_time', 'end_time', 'duration_seconds', 'uploaded'],
                'state_spans': ['span_id', 'state', 'start_time', 'end_time', 'duration_seconds', 'uploaded'],
            }
            
            for table, columns in required_columns.items():
                if table not in existing_tables:
                    continue  # Table missing already reported above
                
                # Get actual columns for this table
                cursor.execute(f"PRAGMA table_info({table})")
                actual_columns = {row[1] for row in cursor.fetchall()}
                
                missing_cols = set(columns) - actual_columns
                if missing_cols:
                    logger.error(f"Table '{table}' missing required columns: {missing_cols}")
                    conn.close()
                    return False
            
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Schema validation error: {e}")
            return False
    
    def _recreate_db(self):
        """Delete and recreate the database"""
        try:
            if self.db_path.exists():
                self.db_path.unlink()
                logger.info(f"Deleted corrupted database: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to delete database: {e}")
    
    def _init_db(self):
        """Initialize database schema with integrity check"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Check integrity
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            if result and result[0] != 'ok':
                logger.error(f"Database integrity check failed: {result[0]}")
                conn.close()
                self._recreate_db()
                conn = sqlite3.connect(self.db_path)
            
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
        except Exception as e:
            logger.error(f"Error checking database integrity: {e}")
            # Try to proceed or recreate? Recreate is safer for an autonomous agent
            try:
                if conn: conn.close()
            except: pass
            self._recreate_db()
            conn = sqlite3.connect(self.db_path)
            conn.execute('PRAGMA journal_mode=WAL')
        
        # Raw heartbeats table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                sequence INTEGER,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL,
                processed INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_processed ON heartbeats (processed)
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_timestamp ON heartbeats (timestamp)
        ''')
        
        # Merged events (aggregated from heartbeats)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS merged_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                username TEXT DEFAULT 'unknown',
                event_type TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds REAL,
                state_data TEXT NOT NULL,
                heartbeat_count INTEGER DEFAULT 1,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        # Add username column if missing (migration)
        try:
            conn.execute('ALTER TABLE merged_events ADD COLUMN username TEXT DEFAULT "unknown"')
        except:
            pass  # Column already exists
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded ON merged_events (uploaded)
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_type_time ON merged_events (event_type, start_time)
        ''')
        
        # Domain visits (LEGACY - history-based)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS domain_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                domain TEXT NOT NULL,
                url TEXT,
                title TEXT,
                browser TEXT,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_domains ON domain_visits (uploaded)
        ''')
        
        # Domain active sessions (NEW - session-based tracking)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS domain_active_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                browser TEXT,
                url TEXT,
                title TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_domain_sessions_uploaded ON domain_active_sessions (uploaded)
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_domain_sessions_domain ON domain_active_sessions (domain, start_time)
        ''')
        
        # State spans (NEW - Idempotent screen time tracking)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS state_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                span_id TEXT UNIQUE NOT NULL,
                agent_id TEXT NOT NULL,
                state TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_state_spans_uploaded ON state_spans (uploaded)
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_state_spans_time ON state_spans (start_time)
        ''')
        
        # Inventory snapshots
        conn.execute('''
            CREATE TABLE IF NOT EXISTS inventory_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                apps_json TEXT NOT NULL,
                changes_json TEXT,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_inventory ON inventory_snapshots (uploaded)
        ''')
        
        # Upload batches (for idempotency tracking)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS upload_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT UNIQUE NOT NULL,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0,
                last_attempt TEXT,
                response TEXT
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_status ON upload_batches (status)
        ''')
        
        # State table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info(f"Buffer database initialized: {self.db_path}")
    
    def store_heartbeat(self, heartbeat: Dict) -> int:
        """Store raw heartbeat with optimized write and disk full handling"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Use faster JSON serialization
                payload = json.dumps(heartbeat, separators=(',', ':'))
                
                cursor.execute('''
                    INSERT INTO heartbeats (agent_id, sequence, timestamp, payload, received_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    heartbeat.get('agent_id'),
                    heartbeat.get('sequence'),
                    heartbeat.get('timestamp'),
                    payload,
                    datetime.now(timezone.utc).isoformat()
                ))
                
                row_id = cursor.lastrowid or 0
                
                return row_id
                
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            
            # FIX #7: Check if it's a disk full error
            if 'disk' in error_msg or 'full' in error_msg or 'space' in error_msg:
                logger.critical(
                    "[BUFFER] DISK FULL - Cannot store heartbeat! "
                    "Attempting emergency cleanup..."
                )
                
                # Try emergency cleanup
                deleted = self.emergency_cleanup()
                
                if deleted > 0:
                    # Retry once after cleanup
                    logger.info("[BUFFER] Retrying heartbeat store after cleanup")
                    try:
                        with self._get_connection() as conn:
                            cursor = conn.cursor()
                            payload = json.dumps(heartbeat, separators=(',', ':'))
                            cursor.execute('''
                                INSERT INTO heartbeats (agent_id, sequence, timestamp, payload, received_at)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (
                                heartbeat.get('agent_id'),
                                heartbeat.get('sequence'),
                                heartbeat.get('timestamp'),
                                payload,
                                datetime.now(timezone.utc).isoformat()
                            ))
                            return cursor.lastrowid or 0
                    except Exception as retry_error:
                        logger.error(f"[BUFFER] Retry failed: {retry_error}")
                        return 0
                else:
                    logger.critical("[BUFFER] Emergency cleanup found nothing to delete!")
                    return 0
            else:
                # Other SQLite error
                logger.error(f"[BUFFER] SQLite error storing heartbeat: {e}")
                return 0
                
        except Exception as e:
            logger.error(f"Error storing heartbeat: {e}")
            return 0
    
    def get_unprocessed_heartbeats(self, limit: int = 1000) -> List[Dict]:
        """Get unprocessed heartbeats"""
        # Read-only operation doesn't need strict transaction management like writes,
        # but using context manager ensures clean connection handling
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, payload FROM heartbeats
                WHERE processed = 0
                ORDER BY id ASC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row['id'],
                    'data': json.loads(row['payload'])
                })
            
            return results
    
    def mark_heartbeats_processed(self, ids: List[int]):
        """Mark heartbeats as processed"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE heartbeats SET processed = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    def store_merged_event(self, event: Dict) -> int:
        """Store merged event (handles both session and delta events)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Screentime events don't have start/end, use timestamp instead
            if event.get('type') == 'screentime':
                start_time = event.get('timestamp')
                end_time = event.get('timestamp')
                duration = 0
                state_data = {
                    'delta_active_seconds': event.get('delta_active_seconds', 0),
                    'delta_idle_seconds': event.get('delta_idle_seconds', 0),
                    'delta_locked_seconds': event.get('delta_locked_seconds', 0),
                    'current_state': event.get('current_state', 'active')
                }
            else:
                # Regular session-based events (app, idle, etc.)
                start_time = event['start']
                end_time = event['end']
                duration = event.get('duration_seconds', 0)
                state_data = event.get('state', {})
            
            cursor.execute('''
                INSERT INTO merged_events (
                    agent_id, username, event_type, start_time, end_time,
                    duration_seconds, state_data, heartbeat_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event['agent_id'],
                event.get('username', 'unknown'),
                event['type'],
                start_time,
                end_time,
                duration,
                json.dumps(state_data),
                event.get('heartbeat_count', 1)
            ))
            
            return cursor.lastrowid
    
    def get_unuploaded_merged_events(self, limit: int = 1000) -> List[Dict]:
        """Get merged events that haven't been uploaded"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM merged_events
                WHERE uploaded = 0
                ORDER BY id ASC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row['id'],
                    'agent_id': row['agent_id'],
                    'username': row['username'] if 'username' in row.keys() else 'unknown',
                    'type': row['event_type'],
                    'start': row['start_time'],
                    'end': row['end_time'],
                    'duration_seconds': row['duration_seconds'],
                    'state': json.loads(row['state_data']),
                    'heartbeat_count': row['heartbeat_count']
                })
            
            return results
    
    def mark_events_uploaded(self, ids: List[int]):
        """Mark merged events as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE merged_events SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    def store_domain_visits(self, visits: List[Dict]) -> int:
        """Store domain visits"""
        if not visits:
            return 0
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            for visit in visits:
                cursor.execute('''
                    INSERT INTO domain_visits (
                        agent_id, timestamp, domain, url, title, browser
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    visit.get('agent_id'),
                    visit.get('timestamp'),
                    visit.get('domain'),
                    visit.get('url'),
                    visit.get('title'),
                    visit.get('browser')
                ))
            
            return cursor.rowcount
    
    def get_unuploaded_domains(self, limit: int = 1000) -> List[Dict]:
        """Get unuploaded domain visits"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM domain_visits
                WHERE uploaded = 0
                ORDER BY id ASC
                LIMIT ?
            ''', (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def mark_domains_uploaded(self, ids: List[int]):
        """Mark domains as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE domain_visits SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    # ========================================================================
    #   DOMAIN ACTIVE SESSIONS (NEW - Session-based tracking)
    # ========================================================================
    
    def store_domain_sessions(self, sessions: List[Dict]) -> int:
        """Store domain active sessions"""
        if not sessions:
            return 0
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            for session in sessions:
                cursor.execute('''
                    INSERT INTO domain_active_sessions (
                        agent_id, domain, browser, url, title,
                        start_time, end_time, duration_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session.get('agent_id'),
                    session.get('domain'),
                    session.get('browser'),
                    session.get('url'),
                    session.get('title'),
                    session.get('start'),
                    session.get('end'),
                    session.get('duration_seconds', 0)
                ))
            
            return len(sessions)
    
    def get_unuploaded_domain_sessions(self, limit: int = 500) -> List[Dict]:
        """Get unuploaded domain active sessions"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM domain_active_sessions
                WHERE uploaded = 0
                ORDER BY id ASC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row['id'],
                    'agent_id': row['agent_id'],
                    'domain': row['domain'],
                    'browser': row['browser'],
                    'url': row['url'],
                    'title': row['title'],
                    'start': row['start_time'],
                    'end': row['end_time'],
                    'duration_seconds': row['duration_seconds']
                })
            
            return results
    
    def mark_domain_sessions_uploaded(self, ids: List[int]):
        """Mark domain sessions as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE domain_active_sessions SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)

    # ========================================================================
    #   STATE SPANS (NEW - Idempotent screen time tracking)
    # ========================================================================

    def store_state_span(self, span: Dict) -> bool:
        """Store state span with idempotency check"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Use INSERT OR IGNORE for span_id idempotency
                cursor.execute('''
                    INSERT OR IGNORE INTO state_spans (
                        span_id, agent_id, state, start_time, end_time,
                        duration_seconds, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    span.get('span_id'),
                    span.get('agent_id'),
                    span.get('state'),
                    span.get('start_time'),
                    span.get('end_time'),
                    span.get('duration_seconds'),
                    span.get('created_at')
                ))
                return True
        except Exception as e:
            logger.error(f"[BUFFER] Error storing state span: {e}")
            return False

    def get_unuploaded_state_spans(self, limit: int = 500) -> List[Dict]:
        """Get unuploaded state spans"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM state_spans
                WHERE uploaded = 0
                ORDER BY id ASC
                LIMIT ?
            ''', (limit,))
            
            return [dict(row) for row in cursor.fetchall()]

    def mark_state_spans_uploaded(self, ids: List[int]):
        """Mark state spans as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE state_spans SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    def store_inventory(self, inventory: Dict) -> int:
        """Store inventory snapshot"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO inventory_snapshots (
                    agent_id, timestamp, apps_json, changes_json
                ) VALUES (?, ?, ?, ?)
            ''', (
                inventory.get('agent_id'),
                inventory.get('timestamp'),
                json.dumps(inventory.get('apps', [])),
                json.dumps(inventory.get('changes', {}))
            ))
            
            return cursor.lastrowid
    
    def get_unuploaded_inventory(self, limit: int = 10) -> List[Dict]:
        """Get unuploaded inventory snapshots"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM inventory_snapshots
                WHERE uploaded = 0
                ORDER BY id ASC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row['id'],
                    'agent_id': row['agent_id'],
                    'timestamp': row['timestamp'],
                    'apps': json.loads(row['apps_json']),
                    'changes': json.loads(row['changes_json']) if row['changes_json'] else {}
                })
            
            return results
    
    def mark_inventory_uploaded(self, ids: List[int]):
        """Mark inventory snapshots as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE inventory_snapshots SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    def store_state_change(self, event_data: Dict) -> int:
        """
        Store state-change event for upload.
        Uses merged_events table with event_type='state-change'
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Store as a merged event with type 'state-change'
            state_data = {
                'previous_state': event_data.get('previous_state'),
                'current_state': event_data.get('current_state'),
                'username': event_data.get('username', '')
            }
            
            cursor.execute('''
                INSERT INTO merged_events (
                    agent_id, username, event_type, start_time, end_time,
                    duration_seconds, state_data, heartbeat_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_data.get('agent_id'),
                event_data.get('username', 'unknown'),
                'state-change',
                event_data.get('timestamp'),
                event_data.get('timestamp'),  # end_time = start_time for instant events
                event_data.get('duration_seconds', 0),
                json.dumps(state_data),
                1
            ))
            
            row_id = cursor.lastrowid or 0
            logger.debug(f"Stored state-change event id={row_id}")
            return row_id
    
    def get_state(self, key: str) -> Optional[str]:
        """Get state value"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM state WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row[0] if row else None
    
    def set_state(self, key: str, value: str):
        """Set state value"""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO state (key, value)
                VALUES (?, ?)
            ''', (key, value))

    def get_counts(self) -> Dict[str, int]:
        """Get counts of buffered items"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            return {
                'heartbeats': cursor.execute("SELECT COUNT(*) FROM heartbeats").fetchone()[0],
                'events': cursor.execute("SELECT COUNT(*) FROM merged_events").fetchone()[0],
                'domains': cursor.execute("SELECT COUNT(*) FROM domain_visits").fetchone()[0]
            }

    def get_latest_heartbeat(self) -> Optional[Dict]:
        """Get the most recent heartbeat"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT payload FROM heartbeats
                ORDER BY id DESC
                LIMIT 1
            ''')
            
            row = cursor.fetchone()
            if row:
                return json.loads(row['payload'])
            return None

    def get_recent_activity(self, limit: int = 50) -> List[Dict]:
        """Get recent merged events (activity)"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM merged_events
                ORDER BY start_time DESC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'type': row['event_type'],
                    'start': row['start_time'],
                    'end': row['end_time'],
                    'duration': row['duration_seconds'],
                    'state': json.loads(row['state_data'])
                })
            return results

    def get_recent_apps(self, limit: int = 50) -> List[Dict]:
        """Get recent app sessions from merged events"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM merged_events
                WHERE event_type = 'app'
                ORDER BY start_time DESC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                state = json.loads(row['state_data'])
                results.append({
                    'app': state.get('app_name'),
                    'title': state.get('window_title'),
                    'start': row['start_time'],
                    'duration': row['duration_seconds']
                })
            return results

    def get_recent_domains(self, limit: int = 50) -> List[Dict]:
        """Get recent domain sessions"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM domain_active_sessions
                ORDER BY start_time DESC
                LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'domain': row['domain'],
                    'browser': row['browser'],
                    'url': row['url'],
                    'start': row['start_time'],
                    'duration': row['duration_seconds']
                })
            return results

    def get_latest_inventory(self) -> List[Dict]:
        """Get latest inventory snapshot"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT apps_json FROM inventory_snapshots
                ORDER BY timestamp DESC
                LIMIT 1
            ''')
            
            row = cursor.fetchone()
            if row:
                return json.loads(row['apps_json'])
            return []

    def cleanup_uploaded_data(self, retention_days: int = 7) -> Dict[str, int]:
        """
        Delete uploaded data older than retention period to prevent infinite growth.
        
        Args:
            retention_days: Keep last N days of uploaded data for debugging (default: 7)
            
        Returns:
            Dict with counts of deleted records by table
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        heartbeat_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        
        deleted_counts = {
            'merged_events': 0,
            'domain_sessions': 0,
            'domain_visits': 0,
            'heartbeats': 0,
            'inventory': 0
        }
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Clean uploaded merged events older than retention period
                cursor.execute('''
                    DELETE FROM merged_events 
                    WHERE uploaded = 1 AND end_time < ?
                ''', (cutoff,))
                deleted_counts['merged_events'] = cursor.rowcount
                
                # Clean uploaded domain active sessions
                cursor.execute('''
                    DELETE FROM domain_active_sessions 
                    WHERE uploaded = 1 AND end_time < ?
                ''', (cutoff,))
                deleted_counts['domain_sessions'] = cursor.rowcount
                
                # Clean uploaded domain visits
                cursor.execute('''
                    DELETE FROM domain_visits 
                    WHERE uploaded = 1 AND timestamp < ?
                ''', (cutoff,))
                deleted_counts['domain_visits'] = cursor.rowcount
                
                # Clean processed heartbeats older than 24 hours
                # (heartbeats are intermediate, don't need long retention)
                cursor.execute('''
                    DELETE FROM heartbeats 
                    WHERE processed = 1 AND timestamp < ?
                ''', (heartbeat_cutoff,))
                deleted_counts['heartbeats'] = cursor.rowcount
                
                # Clean uploaded inventory (keep last 2 snapshots only)
                cursor.execute('''
                    DELETE FROM inventory_snapshots 
                    WHERE uploaded = 1 
                    AND id NOT IN (
                        SELECT id FROM inventory_snapshots 
                        ORDER BY timestamp DESC LIMIT 2
                    )
                ''')
                deleted_counts['inventory'] = cursor.rowcount
            
            total_deleted = sum(deleted_counts.values())
            
            if total_deleted > 0:
                logger.info(
                    f"[CLEANUP] Deleted {total_deleted} old records "
                    f"(retention: {retention_days} days) - "
                    f"Events: {deleted_counts['merged_events']}, "
                    f"Domains: {deleted_counts['domain_sessions']}, "
                    f"Visits: {deleted_counts['domain_visits']}, "
                    f"Heartbeats: {deleted_counts['heartbeats']}, "
                    f"Inventory: {deleted_counts['inventory']}"
                )
                
                # Run VACUUM to reclaim disk space (only if significant deletions)
                if total_deleted > 100:
                    try:
                        with self._get_connection() as conn:
                            conn.execute('VACUUM')
                        logger.info("[CLEANUP] Database vacuumed to reclaim space")
                    except Exception as e:
                        logger.warning(f"[CLEANUP] VACUUM failed (non-critical): {e}")
            else:
                logger.debug("[CLEANUP] No old records to clean up")
            
            return deleted_counts
            
        except Exception as e:
            logger.error(f"[CLEANUP] Error during cleanup: {e}")
            return deleted_counts
