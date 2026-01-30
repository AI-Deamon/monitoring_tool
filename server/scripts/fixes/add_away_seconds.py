"""
Migration Script: Add away_seconds Column to screen_time Table
=============================================================
This script adds the away_seconds column to the screen_time table
using the application context and database configuration.
"""

import sys
import logging
from pathlib import Path
from sqlalchemy import text

# Add the server root to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from server_app import create_app
from extensions import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_away_seconds_column():
    """Add away_seconds column to screen_time table if it doesn't exist."""
    app = create_app()
    
    with app.app_context():
        logger.info("Checking for 'away_seconds' column in 'screen_time' table...")
        
        try:
            # Check if column already exists
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'screen_time' 
                AND column_name = 'away_seconds'
            """))
            
            if result.fetchone():
                logger.info("✓ Column 'away_seconds' already exists in screen_time table")
                return True
            
            # Add the column
            logger.info("Adding 'away_seconds' column to screen_time table...")
            db.session.execute(text("""
                ALTER TABLE screen_time 
                ADD COLUMN away_seconds INTEGER DEFAULT 0
            """))
            
            # Update existing records
            db.session.execute(text("""
                UPDATE screen_time 
                SET away_seconds = 0 
                WHERE away_seconds IS NULL
            """))
            
            db.session.commit()
            logger.info("✓ Column 'away_seconds' added successfully!")
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"✗ Error adding column: {e}")
            return False

if __name__ == '__main__':
    print("=" * 60)
    print("Migration: Add away_seconds to screen_time")
    print("=" * 60)
    add_away_seconds_column()
    print("=" * 60)
