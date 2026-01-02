"""
Add enhanced OS detection fields to agents table.
Date: December 16, 2025

Adds:
- agent_name: Custom display name for agent
- os_build: Integer build number (e.g., 22631)
- windows_edition: Edition string (Pro, Home, Enterprise)
- architecture: System architecture (AMD64, x86, ARM64)
"""

from extensions import db
from sqlalchemy import text


def upgrade():
    """Add new OS detection columns to agents table."""
    
    print("Adding enhanced OS detection fields to agents table...")
    
    # Add new columns (all nullable for backwards compatibility)
    with db.engine.connect() as conn:
        # Add agent_name column
        try:
            conn.execute(text(
                """
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS agent_name VARCHAR(255)
                """
            ))
            print("  ✅ Added agent_name column")
        except Exception as e:
            print(f"  ⚠️ agent_name column may already exist: {e}")
        
        # Add os_build column
        try:
            conn.execute(text(
                """
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS os_build INTEGER
                """
            ))
            print("  ✅ Added os_build column")
        except Exception as e:
            print(f"  ⚠️ os_build column may already exist: {e}")
        
        # Add windows_edition column
        try:
            conn.execute(text(
                """
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS windows_edition VARCHAR(50)
                """
            ))
            print("  ✅ Added windows_edition column")
        except Exception as e:
            print(f"  ⚠️ windows_edition column may already exist: {e}")
        
        # Add architecture column
        try:
            conn.execute(text(
                """
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS architecture VARCHAR(50)
                """
            ))
            print("  ✅ Added architecture column")
        except Exception as e:
            print(f"  ⚠️ architecture column may already exist: {e}")
        
        conn.commit()
    
    print("✅ Enhanced OS detection fields migration complete!")
    
    # Optional: Backfill data for existing agents
    backfill_existing_data()


def backfill_existing_data():
    """
    Attempt to populate new fields from existing data.
    This is optional but helps with existing agents.
    """
    from server_models import Agent
    
    print("\nBackfilling data for existing agents...")
    
    try:
        agents = Agent.query.filter(Agent.os_build.is_(None)).all()
        updated = 0
        
        for agent in agents:
            if agent.os and 'Windows' in (agent.os or ''):
                # Try to extract edition
                if 'Pro' in agent.os:
                    agent.windows_edition = 'Pro'
                    updated += 1
                elif 'Home' in agent.os:
                    agent.windows_edition = 'Home'
                    updated += 1
                elif 'Enterprise' in agent.os:
                    agent.windows_edition = 'Enterprise'
                    updated += 1
                elif 'Education' in agent.os:
                    agent.windows_edition = 'Education'
                    updated += 1
        
        db.session.commit()
        print(f"  ✅ Backfilled {updated} agents with edition info")
    except Exception as e:
        print(f"  ⚠️ Backfill error (non-fatal): {e}")
        db.session.rollback()


def downgrade():
    """Remove the new columns if needed (rollback)."""
    
    print("Rolling back OS detection fields...")
    
    with db.engine.connect() as conn:
        conn.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS agent_name"))
        conn.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS os_build"))
        conn.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS windows_edition"))
        conn.execute(text("ALTER TABLE agents DROP COLUMN IF EXISTS architecture"))
        conn.commit()
    
    print("✅ Rollback complete")


if __name__ == '__main__':
    import sys
    import os
    
    # Add parent directory to path for imports
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    from flask import Flask
    from extensions import db
    
    # Create minimal Flask app for database connection
    app = Flask(__name__)
    
    # Load config from environment or use defaults
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 
        'postgresql://sentineledge:sentineledge@localhost:5432/sentineledge'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        if len(sys.argv) > 1 and sys.argv[1] == '--downgrade':
            downgrade()
        else:
            upgrade()
