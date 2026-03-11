import os
import sys
from pathlib import Path
from sqlalchemy import text
import logging

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db
import server_models
from auth import DashboardUser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def initialize_data():
    app = create_app()
    with app.app_context():
        try:
            logger.info("Initializing Enterprise Data...")
            
            # 1. Ensure default organization exists
            default_org = server_models.Organization.query.filter_by(slug='default').first()
            if not default_org:
                default_org = server_models.Organization(
                    name='Default Organization',
                    slug='default'
                )
                db.session.add(default_org)
                db.session.commit()
                logger.info("  ✅ Default organization created")
            else:
                logger.info("  ℹ️ Default organization already exists")
            
            # 2. Link all existing users to default org
            users_updated = DashboardUser.query.filter(DashboardUser.org_id == None).update({DashboardUser.org_id: default_org.id})
            logger.info(f"  ✅ Linked {users_updated} users to default organization")
            
            # 3. Link all existing agents to default org
            agents_updated = server_models.Agent.query.filter(server_models.Agent.org_id == None).update({server_models.Agent.org_id: default_org.id})
            logger.info(f"  ✅ Linked {agents_updated} agents to default organization")
            
            # 4. Link all existing asset_info to default org
            assets_updated = server_models.AssetInfo.query.filter(server_models.AssetInfo.org_id == None).update({server_models.AssetInfo.org_id: default_org.id})
            logger.info(f"  ✅ Linked {assets_updated} asset_info records to default organization")
            
            db.session.commit()
            logger.info("Data Initialization Complete!")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"  ❌ Data initialization failed: {e}")
            return False

if __name__ == "__main__":
    initialize_data()
