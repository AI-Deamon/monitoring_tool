"""
Add Performance Indexes
========================
Run this once to optimize query performance.
"""

import sys
import logging
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_indexes():
    app = create_app()
    
    with app.app_context():
        logger.info("=" * 60)
        logger.info("Adding performance indexes...")
        logger.info("=" * 60)
        
        try:
            # Index for app_sessions queries (most common)
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_app_sessions_agent_date 
                ON app_sessions(agent_id, start_time);
            """))
            logger.info("[OK] Created index: idx_app_sessions_agent_date")
            
            # Index for domain_sessions queries
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_domain_sessions_agent_date 
                ON domain_sessions(agent_id, start_time);
            """))
            logger.info("[OK] Created index: idx_domain_sessions_agent_date")
            
            # Index for app_usage queries
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_app_usage_agent_date 
                ON app_usage(agent_id, date);
            """))
            logger.info("[OK] Created index: idx_app_usage_agent_date")
            
            # Index for domain_usage queries
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_domain_usage_agent_date 
                ON domain_usage(agent_id, date);
            """))
            logger.info("[OK] Created index: idx_domain_usage_agent_date")
            
            # Index for screen_time queries
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_screen_time_agent_date 
                ON screen_time(agent_id, date);
            """))
            logger.info("[OK] Created index: idx_screen_time_agent_date")
            
            # Index for raw_events queries (for audit/replay)
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_raw_events_received 
                ON raw_events(agent_id, received_at, processed);
            """))
            logger.info("[OK] Created index: idx_raw_events_received")
            
            # Index for agent_current_status queries
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_agent_current_status_last_seen 
                ON agent_current_status(last_seen);
            """))
            logger.info("[OK] Created index: idx_agent_current_status_last_seen")
            
            db.session.commit()
            logger.info("=" * 60)
            logger.info("[SUCCESS] All indexes created!")
            logger.info("=" * 60)
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"[ERROR] Failed to add indexes: {e}")
            raise

if __name__ == "__main__":
    add_indexes()
