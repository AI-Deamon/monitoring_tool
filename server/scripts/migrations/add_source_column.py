"""
Add 'source' column to app_inventory table.
Run ONCE after updating server_models.py

Usage:
    python add_source_column.py
"""

from server_app import create_app
from extensions import db
from sqlalchemy import text

def add_source_column():
    """Add source column to app_inventory table"""
    app = create_app()
    with app.app_context():
        try:
            # Check if column already exists
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='app_inventory' AND column_name='source'
            """))
            
            if result.fetchone():
                print("[OK] Column 'source' already exists in app_inventory table.")
                return True
            
            # Add the column
            print("[*] Adding 'source' column to app_inventory table...")
            db.session.execute(text("""
                ALTER TABLE app_inventory 
                ADD COLUMN source VARCHAR(50)
            """))
            db.session.commit()
            print("[OK] Successfully added 'source' column to app_inventory!")
            
            # Verify the column was added
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='app_inventory' AND column_name='source'
            """))
            
            if result.fetchone():
                print("[OK] Verification passed - column exists!")
                return True
            else:
                print("[ERROR] Column was not added properly")
                return False
            
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Failed to add column: {e}")
            raise

if __name__ == '__main__':
    print("=" * 60)
    print("Adding 'source' column to app_inventory table")
    print("=" * 60)
    add_source_column()
    print("=" * 60)
    print("Migration complete!")
    print("=" * 60)

