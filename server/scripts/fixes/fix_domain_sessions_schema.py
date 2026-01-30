#!/usr/bin/env python3
"""
Fix domain_sessions schema - Add missing idempotency_key column
"""
import sys
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from server_app import create_app
from extensions import db
from sqlalchemy import text

def fix_domain_sessions_schema():
    """Add missing idempotency_key column to domain_sessions table"""
    app = create_app()
    
    with app.app_context():
        try:
            print("🔧 Fixing domain_sessions schema...")
            
            # Add the missing column
            db.session.execute(text("""
                ALTER TABLE domain_sessions 
                ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);
            """))
            
            # Add index for performance
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_domain_sessions_idempotency_key 
                ON domain_sessions(idempotency_key);
            """))
            
            db.session.commit()
            
            # Verify the column exists
            result = db.session.execute(text("""
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_name = 'domain_sessions'
                AND column_name = 'idempotency_key';
            """))
            
            row = result.fetchone()
            if row:
                print(f"✅ Column added successfully: {row[0]} ({row[1]}({row[2]}))")
                print("✅ Index created: idx_domain_sessions_idempotency_key")
                print("\n🎉 Schema fix complete! Domain switch events should now work.")
                return True
            else:
                print("❌ Column verification failed")
                return False
                
        except Exception as e:
            print(f"❌ Error: {e}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    success = fix_domain_sessions_schema()
    sys.exit(0 if success else 1)
