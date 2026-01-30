"""
Quick fix: Add missing domain_session_start and domain_duration_seconds columns
Run this script on your server to add the missing columns.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from extensions import db
from server_app import create_app

def add_missing_columns():
    """Add the missing columns to agent_current_status table"""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if columns exist first
            result = db.session.execute(db.text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'agent_current_status' 
                AND column_name IN ('domain_session_start', 'domain_duration_seconds')
            """))
            existing_cols = [row[0] for row in result]
            
            # Add domain_session_start if missing
            if 'domain_session_start' not in existing_cols:
                print("[+] Adding domain_session_start column...")
                db.session.execute(db.text("""
                    ALTER TABLE agent_current_status 
                    ADD COLUMN domain_session_start TIMESTAMP NULL
                """))
                print("[OK] Added domain_session_start")
            else:
                print("[OK] domain_session_start already exists")
            
            # Add domain_duration_seconds if missing
            if 'domain_duration_seconds' not in existing_cols:
                print("[+] Adding domain_duration_seconds column...")
                db.session.execute(db.text("""
                    ALTER TABLE agent_current_status 
                    ADD COLUMN domain_duration_seconds INTEGER DEFAULT 0
                """))
                print("[OK] Added domain_duration_seconds")
            else:
                print("[OK] domain_duration_seconds already exists")
            
            db.session.commit()
            print("\n✅ Database schema updated successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Error: {e}")
            raise

if __name__ == '__main__':
    add_missing_columns()
