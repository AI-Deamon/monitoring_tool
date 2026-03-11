import os
import sys
from pathlib import Path
from sqlalchemy import text
import logging

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def apply_schema_changes():
    app = create_app()
    with app.app_context():
        try:
            logger.info("Starting Enterprise Schema Migration...")
            
            # 1. Create Organizations table
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS organizations (
                    id SERIAL PRIMARY KEY,
                    org_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(100) UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """))
            logger.info("  ✅ Organizations table created/verified")
            
            # 2. Add org_id to existing tables
            tables_to_update = ['dashboard_users', 'agents', 'asset_info']
            for table in tables_to_update:
                try:
                    # Check if column exists
                    result = db.session.execute(text(f"""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name='{table}' AND column_name='org_id';
                    """)).fetchone()
                    
                    if not result:
                        logger.info(f"  Adding org_id to {table}...")
                        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN org_id INTEGER REFERENCES organizations(id);"))
                        # Create index
                        db.session.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table}_org_id ON {table}(org_id);"))
                        logger.info(f"  ✅ Added org_id to {table}")
                    else:
                        logger.info(f"  ℹ️ org_id already exists in {table}")
                except Exception as e:
                    logger.error(f"  ❌ Failed to update {table}: {e}")
            
            db.session.commit()
            logger.info("Schema Migration Complete!")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"  ❌ Migration failed: {e}")
            return False

if __name__ == "__main__":
    apply_schema_changes()
