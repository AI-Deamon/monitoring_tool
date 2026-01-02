"""
Database Migration: Add operational status columns to agents table
This migration adds columns needed for Helper monitoring and degraded mode detection.

Run this script from the server directory:
    python migrations/add_agent_operational_status.py
"""
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

def upgrade(db):
    """Add operational status columns to agents table"""
    print("=" * 70)
    print("Adding operational status columns to agents table...")
    print("=" * 70)
    
    migrations = [
        (
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS operational_status VARCHAR(50) DEFAULT 'NORMAL' NOT NULL",
            "operational_status"
        ),
        (
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS status_reason TEXT",
            "status_reason"
        ),
        (
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_status_change TIMESTAMP WITH TIME ZONE",
            "last_status_change"
        ),
        (
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS diagnostics_json TEXT",
            "diagnostics_json"
        ),
    ]
    
    with db.engine.connect() as conn:
        for sql, column_name in migrations:
            try:
                conn.execute(text(sql))
                print(f"  ✓ Added column: {column_name}")
            except Exception as e:
                if 'already exists' in str(e).lower() or 'duplicate column' in str(e).lower():
                    print(f"  - Column already exists: {column_name}")
                else:
                    print(f"  ✗ Error adding {column_name}: {e}")
        
        conn.commit()
    
    print("")
    print("=" * 70)
    print("Migration complete!")
    print("=" * 70)


def run_standalone():
    """Run migration independently (not from Flask app)"""
    from dotenv import load_dotenv
    load_dotenv()
    
    from flask import Flask
    from extensions import db
    
    app = Flask(__name__)
    
    # Configure database from environment
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        upgrade(db)


if __name__ == '__main__':
    run_standalone()
