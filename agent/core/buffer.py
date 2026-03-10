"""
Buffer Module
SQLite-based buffering for offline resilience
"""
import sqlite3
import json
import uuid
import hashlib
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
        self._stats = {
            "duplicate_drops": 0,
            "upload_ack_failures": 0
        }
        
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
        self._ensure_optional_columns()
    
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
            with self._init_lock:
                # Re-check inside lock to prevent double initialization
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

    def _make_idempotency_key(self, prefix: str, payload: Dict) -> str:
        """Create deterministic idempotency key for retry-safe inserts."""
        normalized = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
        return f"{prefix}_{digest}"

    def _mark_duplicate_drop(self):
        self._stats["duplicate_drops"] += 1

    def record_upload_ack_failure(self):
        """Track upload responses that were non-ack and retained in buffer."""
        self._stats["upload_ack_failures"] += 1
    
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
                'hardware_snapshots',
                'extended_inventory',
                'security_indicators',
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

    def _ensure_optional_columns(self):
        """Best-effort schema evolution for non-critical optional columns/indexes."""
        try:
            conn = sqlite3.connect(self.db_path)
            migrations = {
                'merged_events': 'idempotency_key',
                'domain_visits': 'idempotency_key',
                'domain_active_sessions': 'idempotency_key',
                'inventory_snapshots': 'idempotency_key',
                'hardware_snapshots': 'idempotency_key',
                'extended_inventory': 'idempotency_key',
                'security_indicators': 'idempotency_key',
                'eol_data': 'idempotency_key',
            }
            for table, column in migrations.items():
                try:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')
                except Exception:
                    pass

            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_merged_events_idem ON merged_events(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_visits_idem ON domain_visits(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_sessions_idem ON domain_active_sessions(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_idem ON inventory_snapshots(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_hardware_idem ON hardware_snapshots(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_inv_idem ON extended_inventory(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_security_idem ON security_indicators(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_eol_idem ON eol_data(idempotency_key) WHERE idempotency_key IS NOT NULL')
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[BUFFER] Optional schema migration skipped: {e}")
    
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
                idempotency_key TEXT UNIQUE,
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
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_merged_events_idem
            ON merged_events(idempotency_key)
            WHERE idempotency_key IS NOT NULL
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
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_domains ON domain_visits (uploaded)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_visits_idem
            ON domain_visits(idempotency_key)
            WHERE idempotency_key IS NOT NULL
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
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_domain_sessions_uploaded ON domain_active_sessions (uploaded)
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_domain_sessions_domain ON domain_active_sessions (domain, start_time)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_sessions_idem
            ON domain_active_sessions(idempotency_key)
            WHERE idempotency_key IS NOT NULL
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
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_inventory ON inventory_snapshots (uploaded)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_idem
            ON inventory_snapshots(idempotency_key)
            WHERE idempotency_key IS NOT NULL
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
        
        # EOL data
        conn.execute('''
            CREATE TABLE IF NOT EXISTS eol_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_eol_data_uploaded ON eol_data (uploaded)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_eol_idem
            ON eol_data(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        ''')
        
        # State table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        # Hardware snapshots (for asset hardware collection)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS hardware_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_hardware ON hardware_snapshots (uploaded)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hardware_idem
            ON hardware_snapshots(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        ''')
        
        # Extended inventory snapshots (CLI tools, drivers, extensions, plugins, etc.)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS extended_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_ext_inv ON extended_inventory (uploaded)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_inv_idem
            ON extended_inventory(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        ''')
        
        # Security indicators (risk assessments from SecurityCollector)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS security_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_security ON security_indicators (uploaded)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_security_idem
            ON security_indicators(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        ''')

        # Raw system visibility snapshots (ports/connections/startup/tasks/disk)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS system_visibility (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                uploaded INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_uploaded_system_visibility ON system_visibility (uploaded)
        ''')
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_system_visibility_idem
            ON system_visibility(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        ''')

        # Migration safety: add idempotency columns for existing databases.
        for table in [
            'merged_events',
            'domain_visits',
            'domain_active_sessions',
            'inventory_snapshots',
            'hardware_snapshots',
            'extended_inventory',
            'security_indicators',
            'system_visibility',
            'eol_data'
        ]:
            try:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN idempotency_key TEXT')
            except Exception:
                pass
        
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
                    'active_seconds': event.get('active_seconds', 0),
                    'idle_seconds': event.get('idle_seconds', 0),
                    'locked_seconds': event.get('locked_seconds', 0),
                    'away_seconds': event.get('away_seconds', 0),
                    'current_state': event.get('current_state', 'active')
                }
            else:
                # Regular session-based events (app, idle, etc.)
                start_time = event['start']
                end_time = event['end']
                duration = event.get('duration_seconds', 0)
                state_data = event.get('state', {})

            idempotency_key = self._make_idempotency_key("merged", {
                'agent_id': event['agent_id'],
                'type': event['type'],
                'start': start_time,
                'end': end_time,
                'duration': duration,
                'state': state_data
            })
            
            cursor.execute('''
                INSERT OR IGNORE INTO merged_events (
                    agent_id, username, event_type, start_time, end_time,
                    duration_seconds, state_data, heartbeat_count, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event['agent_id'],
                event.get('username', 'unknown'),
                event['type'],
                start_time,
                end_time,
                duration,
                json.dumps(state_data),
                event.get('heartbeat_count', 1),
                idempotency_key
            ))

            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
            return cursor.lastrowid or 0
    
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
                event = {
                    'id': row['id'],
                    'agent_id': row['agent_id'],
                    'username': row['username'] if 'username' in row.keys() else 'unknown',
                    'type': row['event_type'],
                    'start': row['start_time'],
                    'end': row['end_time'],
                    'duration_seconds': row['duration_seconds'],
                    'state': json.loads(row['state_data']),
                    'heartbeat_count': row['heartbeat_count']
                }
                
                # For screentime events, extract cumulative values from state_data
                if event['type'] == 'screentime':
                    state_data = json.loads(row['state_data'])
                    event['active_seconds'] = state_data.get('active_seconds', 0)
                    event['idle_seconds'] = state_data.get('idle_seconds', 0)
                    event['locked_seconds'] = state_data.get('locked_seconds', 0)
                    event['away_seconds'] = state_data.get('away_seconds', 0)
                    event['current_state'] = state_data.get('current_state', 'active')
                    event['timestamp'] = row['start_time']  # Use start_time as timestamp
                
                results.append(event)
            
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
            inserted = 0
            
            for visit in visits:
                idempotency_key = self._make_idempotency_key("domain_visit", {
                    'agent_id': visit.get('agent_id'),
                    'timestamp': visit.get('timestamp'),
                    'domain': visit.get('domain'),
                    'url': visit.get('url'),
                    'title': visit.get('title'),
                    'browser': visit.get('browser'),
                })
                cursor.execute('''
                    INSERT OR IGNORE INTO domain_visits (
                        agent_id, timestamp, domain, url, title, browser, idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    visit.get('agent_id'),
                    visit.get('timestamp'),
                    visit.get('domain'),
                    visit.get('url'),
                    visit.get('title'),
                    visit.get('browser'),
                    idempotency_key
                ))
                if cursor.rowcount == 0:
                    self._mark_duplicate_drop()
                else:
                    inserted += 1
            
            return inserted
    
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
            inserted = 0
            
            for session in sessions:
                idempotency_key = self._make_idempotency_key("domain_session", {
                    'agent_id': session.get('agent_id'),
                    'domain': session.get('domain'),
                    'browser': session.get('browser'),
                    'url': session.get('url'),
                    'title': session.get('title'),
                    'start': session.get('start'),
                    'end': session.get('end'),
                    'duration_seconds': session.get('duration_seconds', 0),
                })
                cursor.execute('''
                    INSERT OR IGNORE INTO domain_active_sessions (
                        agent_id, domain, browser, url, title,
                        start_time, end_time, duration_seconds, idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session.get('agent_id'),
                    session.get('domain'),
                    session.get('browser'),
                    session.get('url'),
                    session.get('title'),
                    session.get('start'),
                    session.get('end'),
                    session.get('duration_seconds', 0),
                    idempotency_key
                ))
                if cursor.rowcount == 0:
                    self._mark_duplicate_drop()
                else:
                    inserted += 1
            
            return inserted
    
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
            apps_json = json.dumps(inventory.get('apps', []))
            changes_json = json.dumps(inventory.get('changes', {}))
            idempotency_key = self._make_idempotency_key("inventory", {
                'agent_id': inventory.get('agent_id'),
                'timestamp': inventory.get('timestamp'),
                'apps': inventory.get('apps', []),
                'changes': inventory.get('changes', {})
            })
            
            cursor.execute('''
                INSERT OR IGNORE INTO inventory_snapshots (
                    agent_id, timestamp, apps_json, changes_json, idempotency_key
                ) VALUES (?, ?, ?, ?, ?)
            ''', (
                inventory.get('agent_id'),
                inventory.get('timestamp'),
                apps_json,
                changes_json,
                idempotency_key
            ))
            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
            return cursor.lastrowid or 0
    
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
    
    # ========================================================================
    #   HARDWARE SNAPSHOTS (Asset hardware collection)
    # ========================================================================
    
    def store_hardware(self, data: Dict) -> int:
        """Store hardware snapshot"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            payload_json = json.dumps(data)
            ts = data.get('collected_at', datetime.now(timezone.utc).isoformat())
            idempotency_key = self._make_idempotency_key("hardware", {
                'agent_id': data.get('agent_id'),
                'timestamp': ts,
                'payload': data
            })
            
            cursor.execute('''
                INSERT OR IGNORE INTO hardware_snapshots (
                    agent_id, timestamp, payload_json, idempotency_key
                ) VALUES (?, ?, ?, ?)
            ''', (
                data.get('agent_id'),
                ts,
                payload_json,
                idempotency_key
            ))
            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
            return cursor.lastrowid or 0
    
    def get_unuploaded_hardware(self, limit: int = 10) -> List[Dict]:
        """Get unuploaded hardware snapshots"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM hardware_snapshots
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
                    'data': json.loads(row['payload_json'])
                })
            
            return results
    
    def mark_hardware_uploaded(self, ids: List[int]):
        """Mark hardware snapshots as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE hardware_snapshots SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    # ========================================================================
    #   EXTENDED INVENTORY
    # ========================================================================
    
    def store_extended_inventory(self, data: Dict) -> int:
        """Store extended inventory snapshot"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            ts = data.get('timestamp', datetime.now(timezone.utc).isoformat())
            payload_json = json.dumps(data)
            idempotency_key = self._make_idempotency_key("ext_inventory", {
                'agent_id': data.get('agent_id'),
                'timestamp': ts,
                'payload': data
            })
            
            cursor.execute('''
                INSERT OR IGNORE INTO extended_inventory (
                    agent_id, timestamp, payload_json, idempotency_key
                ) VALUES (?, ?, ?, ?)
            ''', (
                data.get('agent_id'),
                ts,
                payload_json,
                idempotency_key
            ))
            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
            return cursor.lastrowid or 0
    
    def get_unuploaded_extended_inventory(self, limit: int = 10) -> List[Dict]:
        """Get unuploaded extended inventory snapshots"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM extended_inventory
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
                    'data': json.loads(row['payload_json'])
                })
            
            return results
    
    def mark_extended_inventory_uploaded(self, ids: List[int]):
        """Mark extended inventory snapshots as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE extended_inventory SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    # ========================================================================
    #   SECURITY INDICATORS
    # ========================================================================
    
    def store_security_indicators(self, data: Dict) -> int:
        """Store security indicators snapshot"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            ts = data.get('timestamp', datetime.now(timezone.utc).isoformat())
            payload_json = json.dumps(data)
            idempotency_key = self._make_idempotency_key("security", {
                'agent_id': data.get('agent_id'),
                'timestamp': ts,
                'payload': data
            })
            
            cursor.execute('''
                INSERT OR IGNORE INTO security_indicators (
                    agent_id, timestamp, payload_json, idempotency_key
                ) VALUES (?, ?, ?, ?)
            ''', (
                data.get('agent_id'),
                ts,
                payload_json,
                idempotency_key
            ))
            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
            return cursor.lastrowid or 0
    
    def get_unuploaded_security_indicators(self, limit: int = 10) -> List[Dict]:
        """Get unuploaded security indicator snapshots"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM security_indicators
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
                    'data': json.loads(row['payload_json'])
                })
            
            return results
    
    def mark_security_indicators_uploaded(self, ids: List[int]):
        """Mark security indicator snapshots as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE security_indicators SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)

    # ========================================================================
    #   SYSTEM VISIBILITY SNAPSHOTS
    # ========================================================================

    def store_system_visibility(self, data: Dict) -> int:
        """Store raw system visibility snapshot."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            ts = data.get('timestamp', datetime.now(timezone.utc).isoformat())
            payload_json = json.dumps(data)
            idempotency_key = self._make_idempotency_key("system_visibility", {
                'agent_id': data.get('agent_id'),
                'timestamp': ts,
                'payload': data
            })

            cursor.execute('''
                INSERT OR IGNORE INTO system_visibility (
                    agent_id, timestamp, payload_json, idempotency_key
                ) VALUES (?, ?, ?, ?)
            ''', (
                data.get('agent_id'),
                ts,
                payload_json,
                idempotency_key
            ))
            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
            return cursor.lastrowid or 0

    def get_unuploaded_system_visibility(self, limit: int = 10) -> List[Dict]:
        """Get unuploaded raw system visibility snapshots."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT * FROM system_visibility
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
                    'data': json.loads(row['payload_json'])
                })

            return results

    def mark_system_visibility_uploaded(self, ids: List[int]):
        """Mark system visibility snapshots as uploaded."""
        if not ids:
            return

        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE system_visibility SET uploaded = 1
                WHERE id IN ({placeholders})
            ''', ids)
    
    # ========================================================================
    #   EOL DATA
    # ========================================================================
    
    def store_eol_data(self, data: Dict) -> int:
        """Store EOL data snapshot"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            ts = data.get('timestamp', datetime.now(timezone.utc).isoformat())
            payload_json = json.dumps(data)
            idempotency_key = self._make_idempotency_key("eol", {
                'agent_id': data.get('agent_id'),
                'timestamp': ts,
                'payload': data
            })
            
            cursor.execute('''
                INSERT OR IGNORE INTO eol_data (
                    agent_id, timestamp, data_json, idempotency_key
                ) VALUES (?, ?, ?, ?)
            ''', (
                data.get('agent_id'),
                ts,
                payload_json,
                idempotency_key
            ))
            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
            return cursor.lastrowid or 0
    
    def get_unuploaded_eol_data(self, limit: int = 10) -> List[Dict]:
        """Get unuploaded EOL data snapshots"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM eol_data
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
                    'data': json.loads(row['data_json'])
                })
            
            return results
    
    def mark_eol_data_uploaded(self, ids: List[int]):
        """Mark EOL data snapshots as uploaded"""
        if not ids:
            return
        
        with self._get_connection() as conn:
            placeholders = ','.join('?' * len(ids))
            conn.execute(f'''
                UPDATE eol_data SET uploaded = 1
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
            idempotency_key = self._make_idempotency_key("state_change", {
                'agent_id': event_data.get('agent_id'),
                'previous_state': event_data.get('previous_state'),
                'current_state': event_data.get('current_state'),
                'timestamp': event_data.get('timestamp'),
                'duration_seconds': event_data.get('duration_seconds', 0)
            })
            
            cursor.execute('''
                INSERT OR IGNORE INTO merged_events (
                    agent_id, username, event_type, start_time, end_time,
                    duration_seconds, state_data, heartbeat_count, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_data.get('agent_id'),
                event_data.get('username', 'unknown'),
                'state-change',
                event_data.get('timestamp'),
                event_data.get('timestamp'),  # end_time = start_time for instant events
                event_data.get('duration_seconds', 0),
                json.dumps(state_data),
                1,
                idempotency_key
            ))
            
            row_id = cursor.lastrowid or 0
            if cursor.rowcount == 0:
                self._mark_duplicate_drop()
                return 0
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

    def get_pending_counts(self) -> Dict[str, int]:
        """Per-table pending row counts for observability."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            return {
                'heartbeats_unprocessed': cursor.execute("SELECT COUNT(*) FROM heartbeats WHERE processed = 0").fetchone()[0],
                'events_unuploaded': cursor.execute("SELECT COUNT(*) FROM merged_events WHERE uploaded = 0").fetchone()[0],
                'domains_unuploaded': cursor.execute("SELECT COUNT(*) FROM domain_visits WHERE uploaded = 0").fetchone()[0],
                'domain_sessions_unuploaded': cursor.execute("SELECT COUNT(*) FROM domain_active_sessions WHERE uploaded = 0").fetchone()[0],
                'state_spans_unuploaded': cursor.execute("SELECT COUNT(*) FROM state_spans WHERE uploaded = 0").fetchone()[0],
                'inventory_unuploaded': cursor.execute("SELECT COUNT(*) FROM inventory_snapshots WHERE uploaded = 0").fetchone()[0],
                'hardware_unuploaded': cursor.execute("SELECT COUNT(*) FROM hardware_snapshots WHERE uploaded = 0").fetchone()[0],
                'extended_inventory_unuploaded': cursor.execute("SELECT COUNT(*) FROM extended_inventory WHERE uploaded = 0").fetchone()[0],
                'security_unuploaded': cursor.execute("SELECT COUNT(*) FROM security_indicators WHERE uploaded = 0").fetchone()[0],
                'system_visibility_unuploaded': cursor.execute("SELECT COUNT(*) FROM system_visibility WHERE uploaded = 0").fetchone()[0],
                'eol_unuploaded': cursor.execute("SELECT COUNT(*) FROM eol_data WHERE uploaded = 0").fetchone()[0],
            }

    def get_buffer_diagnostics(self) -> Dict:
        """Structured diagnostics for offline durability and duplicate handling."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            oldest_rows = {
                'heartbeats': cursor.execute("SELECT MIN(timestamp) FROM heartbeats WHERE processed = 0").fetchone()[0],
                'events': cursor.execute("SELECT MIN(start_time) FROM merged_events WHERE uploaded = 0").fetchone()[0],
                'domains': cursor.execute("SELECT MIN(timestamp) FROM domain_visits WHERE uploaded = 0").fetchone()[0],
                'domain_sessions': cursor.execute("SELECT MIN(start_time) FROM domain_active_sessions WHERE uploaded = 0").fetchone()[0],
            }

            oldest_pending_age_seconds = None
            now = datetime.now(timezone.utc)
            parsed = []
            for value in oldest_rows.values():
                if not value:
                    continue
                try:
                    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    parsed.append((now - dt).total_seconds())
                except Exception:
                    continue
            if parsed:
                oldest_pending_age_seconds = int(max(parsed))

            integrity_ok = True
            try:
                row = cursor.execute("PRAGMA integrity_check").fetchone()
                integrity_ok = bool(row and row[0] == 'ok')
            except Exception:
                integrity_ok = False

            pending_counts = {
                'heartbeats_unprocessed': cursor.execute("SELECT COUNT(*) FROM heartbeats WHERE processed = 0").fetchone()[0],
                'events_unuploaded': cursor.execute("SELECT COUNT(*) FROM merged_events WHERE uploaded = 0").fetchone()[0],
                'domains_unuploaded': cursor.execute("SELECT COUNT(*) FROM domain_visits WHERE uploaded = 0").fetchone()[0],
                'domain_sessions_unuploaded': cursor.execute("SELECT COUNT(*) FROM domain_active_sessions WHERE uploaded = 0").fetchone()[0],
                'state_spans_unuploaded': cursor.execute("SELECT COUNT(*) FROM state_spans WHERE uploaded = 0").fetchone()[0],
                'inventory_unuploaded': cursor.execute("SELECT COUNT(*) FROM inventory_snapshots WHERE uploaded = 0").fetchone()[0],
                'hardware_unuploaded': cursor.execute("SELECT COUNT(*) FROM hardware_snapshots WHERE uploaded = 0").fetchone()[0],
                'extended_inventory_unuploaded': cursor.execute("SELECT COUNT(*) FROM extended_inventory WHERE uploaded = 0").fetchone()[0],
                'security_unuploaded': cursor.execute("SELECT COUNT(*) FROM security_indicators WHERE uploaded = 0").fetchone()[0],
                'system_visibility_unuploaded': cursor.execute("SELECT COUNT(*) FROM system_visibility WHERE uploaded = 0").fetchone()[0],
                'eol_unuploaded': cursor.execute("SELECT COUNT(*) FROM eol_data WHERE uploaded = 0").fetchone()[0],
            }

            return {
                'pending_counts': pending_counts,
                'oldest_pending_age_seconds': oldest_pending_age_seconds,
                'duplicate_drops': self._stats.get('duplicate_drops', 0),
                'upload_ack_failures': self._stats.get('upload_ack_failures', 0),
                'integrity_ok': integrity_ok
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
            'inventory': 0,
            'state_spans': 0,
            'hardware': 0,
            'extended_inventory': 0,
            'security': 0,
            'system_visibility': 0,
            'eol': 0
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

                # Clean uploaded state spans
                cursor.execute('''
                    DELETE FROM state_spans
                    WHERE uploaded = 1 AND end_time < ?
                ''', (cutoff,))
                deleted_counts['state_spans'] = cursor.rowcount

                # Clean uploaded hardware snapshots
                cursor.execute('''
                    DELETE FROM hardware_snapshots
                    WHERE uploaded = 1 AND timestamp < ?
                ''', (cutoff,))
                deleted_counts['hardware'] = cursor.rowcount

                # Clean uploaded extended inventory
                cursor.execute('''
                    DELETE FROM extended_inventory
                    WHERE uploaded = 1 AND timestamp < ?
                ''', (cutoff,))
                deleted_counts['extended_inventory'] = cursor.rowcount

                # Clean uploaded security indicators
                cursor.execute('''
                    DELETE FROM security_indicators
                    WHERE uploaded = 1 AND timestamp < ?
                ''', (cutoff,))
                deleted_counts['security'] = cursor.rowcount

                # Clean uploaded system visibility snapshots
                cursor.execute('''
                    DELETE FROM system_visibility
                    WHERE uploaded = 1 AND timestamp < ?
                ''', (cutoff,))
                deleted_counts['system_visibility'] = cursor.rowcount

                # Clean uploaded EOL snapshots
                cursor.execute('''
                    DELETE FROM eol_data
                    WHERE uploaded = 1 AND timestamp < ?
                ''', (cutoff,))
                deleted_counts['eol'] = cursor.rowcount
            
            total_deleted = sum(deleted_counts.values())
            
            if total_deleted > 0:
                logger.info(
                    f"[CLEANUP] Deleted {total_deleted} old records "
                    f"(retention: {retention_days} days) - "
                    f"Events: {deleted_counts['merged_events']}, "
                    f"Domains: {deleted_counts['domain_sessions']}, "
                    f"Visits: {deleted_counts['domain_visits']}, "
                    f"Heartbeats: {deleted_counts['heartbeats']}, "
                    f"Inventory: {deleted_counts['inventory']}, "
                    f"Spans: {deleted_counts['state_spans']}, "
                    f"Hardware: {deleted_counts['hardware']}, "
                    f"ExtInv: {deleted_counts['extended_inventory']}, "
                    f"Security: {deleted_counts['security']}, "
                    f"Visibility: {deleted_counts['system_visibility']}, "
                    f"EOL: {deleted_counts['eol']}"
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
