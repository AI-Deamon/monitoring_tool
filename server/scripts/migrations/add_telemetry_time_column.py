#!/usr/bin/env python3
"""
Migration: Add last_telemetry_time column to agents table

This column tracks when actual telemetry data was last received,
helping to detect "silent failures" - agents that are online but
not sending data.

Run: python3 add_telemetry_time_column.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from server_app import create_app
from extensions import db
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    app = create_app()
    
    with app.app_context():
        logger.info("Adding last_telemetry_time column to agents table...")
        
        try:
            # Check if column already exists
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='agents' AND column_name='last_telemetry_time'
            """))
            
            if result.fetchone():
                logger.info("Column 'last_telemetry_time' already exists")
            else:
                # Add the column
                db.session.execute(text("""
                    ALTER TABLE agents 
                    ADD COLUMN last_telemetry_time TIMESTAMP
                """))
                
                # Initialize with last_seen for existing agents
                db.session.execute(text("""
                    UPDATE agents 
                    SET last_telemetry_time = last_seen 
                    WHERE last_telemetry_time IS NULL AND last_seen IS NOT NULL
                """))
                
                db.session.commit()
                logger.info("✅ Column 'last_telemetry_time' added successfully")
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"Migration failed: {e}")
            raise


if __name__ == "__main__":
    run_migration()
