"""
Add raw_title, raw_url, domain_source columns to domain_sessions table.
Run: python add_domain_raw_fields.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from server_app import create_app
from extensions import db
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    app = create_app()
    with app.app_context():
        try:
            logger.info("Adding raw data columns to domain_sessions table...")

            # Add columns to domain_sessions table
            # Using IF NOT EXISTS equivalent for PostgreSQL
            columns_to_add = [
                ("raw_title", "TEXT"),
                ("raw_url", "TEXT"),
                ("domain_source", "VARCHAR(20) DEFAULT 'agent'"),
                ("needs_review", "BOOLEAN DEFAULT FALSE")
            ]
            
            for col_name, col_type in columns_to_add:
                try:
                    db.session.execute(text(f'''
                        ALTER TABLE domain_sessions 
                        ADD COLUMN {col_name} {col_type}
                    '''))
                    logger.info(f"  Added column: {col_name}")
                except Exception as e:
                    if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                        logger.info(f"  Column {col_name} already exists, skipping")
                    else:
                        raise

            db.session.commit()
            logger.info("✅ Migration completed successfully!")

        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Migration failed: {e}")
            raise

if __name__ == '__main__':
    run_migration()
