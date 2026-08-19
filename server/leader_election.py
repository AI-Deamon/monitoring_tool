"""
Scheduler leader election via PostgreSQL advisory lock.

Problem: gunicorn runs `workers = cpu*2+1` processes and each one calls
create_application(), which historically started the BackgroundScheduler plus
the sync/cleanup threads — so every scheduled job ran once *per worker*,
racing the same tables.

This module elects exactly one process as the scheduler leader. The leader
holds a session-level advisory lock on a dedicated connection; if that process
dies, PostgreSQL releases the lock and another worker takes over on its next
poll. Background loops call `get_leader(app).check()` each tick and skip work
while not leader.

Override with the RUN_BACKGROUND_TASKS env var:
    unset / "auto"  -> advisory-lock election (default, safe under gunicorn)
    "1"/"true"      -> always run jobs in this process (dedicated worker)
    "0"/"false"     -> never run jobs in this process (web-only worker)
"""

import os
import logging
import threading

logger = logging.getLogger(__name__)

# Arbitrary fixed bigint identifying "SentinelEdge scheduler" cluster-wide.
SCHEDULER_LOCK_KEY = 861003741

_leader = None
_leader_init_lock = threading.Lock()


class SchedulerLeader:
    def __init__(self, app):
        self.app = app
        self._conn = None
        self._engine = None
        self._is_leader = False
        self._lock = threading.Lock()
        self._last_logged_state = None

    def check(self) -> bool:
        """Return True if this process should run background jobs right now.

        Safe to call from multiple threads; cheap when already leader
        (a SELECT 1 liveness probe on the dedicated connection).
        """
        mode = os.getenv('RUN_BACKGROUND_TASKS', 'auto').strip().lower()
        if mode in ('0', 'false', 'no', 'off'):
            return False
        if mode in ('1', 'true', 'yes', 'on'):
            return True

        with self._lock:
            result = self._check_advisory_lock()
        if result != self._last_logged_state:
            if result:
                logger.info(
                    "[SCHEDULER-LEADER] This process (pid=%s) is now the "
                    "background-job leader", os.getpid()
                )
            else:
                logger.info(
                    "[SCHEDULER-LEADER] Another process holds the scheduler "
                    "lock - background jobs idle in pid=%s", os.getpid()
                )
            self._last_logged_state = result
        return result

    def _check_advisory_lock(self) -> bool:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        try:
            if self._engine is None:
                uri = self.app.config.get('SQLALCHEMY_DATABASE_URI', '')
                self._engine = create_engine(uri, poolclass=NullPool)

            # Non-Postgres (e.g. SQLite in tests): no advisory locks and no
            # multi-worker deployment either - single process runs the jobs.
            if self._engine.dialect.name != 'postgresql':
                return True

            if self._conn is None or self._conn.closed:
                self._conn = self._engine.connect().execution_options(
                    isolation_level='AUTOCOMMIT'
                )
                self._is_leader = False

            if self._is_leader:
                # Advisory locks are session-scoped: leadership lives exactly
                # as long as this connection. Probe it.
                self._conn.execute(text('SELECT 1'))
                return True

            got = self._conn.execute(
                text('SELECT pg_try_advisory_lock(:key)'),
                {'key': SCHEDULER_LOCK_KEY},
            ).scalar()
            self._is_leader = bool(got)
            return self._is_leader

        except Exception as e:
            logger.warning(
                "[SCHEDULER-LEADER] Lock check failed (%s) - treating as "
                "not-leader until the database is reachable", e
            )
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._is_leader = False
            return False


def get_leader(app) -> SchedulerLeader:
    """Process-wide singleton so all background loops share one election."""
    global _leader
    with _leader_init_lock:
        if _leader is None:
            _leader = SchedulerLeader(app)
        return _leader
