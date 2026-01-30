#!/usr/bin/env python3
"""
Fix Database Collation Version Mismatch
Run this to resolve warnings about OS collation version changes.
"""
import sys
import logging
from pathlib import Path
from sqlalchemy import text

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from server_app import create_app
from extensions import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_collation():
    app = create_app()
    with app.app_context():
        # Get database name
        db_name = db.engine.url.database
        
        logger.info(f"Attempting to refresh collation version for {db_name}...")
        
        try:
            # Requires strict isolation handling. 
            # ALTER DATABASE cannot run inside a transaction block.
            # We need to use valid SQLALCHEMY execution options if possible, 
            # or typically this must be run from psql CLI.
            
            # Since we can't easily break out of transaction in Flask-SQLAlchemy default setup
            # We will try, but expect it might fail if inside transaction.
            # Actually, using connection.execution_options(isolation_level="AUTOCOMMIT") might work.
            
            with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text(f"ALTER DATABASE {db_name} REFRESH COLLATION VERSION"))
                
            logger.info("✓ Collation version refreshed successfully")
        except Exception as e:
            logger.warning(f"Could not automatically refresh collation: {e}")
            logger.info("Try running manually:")
            logger.info(f"  psql -c 'ALTER DATABASE {db_name} REFRESH COLLATION VERSION'")

if __name__ == "__main__":
    fix_collation()
