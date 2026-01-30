#!/usr/bin/env python3
"""
Utility script to remove an agent by hostname or ID to allow clean re-registration.
"""
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db
import server_models
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def remove_agent(identifier):
    app = create_app()
    with app.app_context():
        # Try finding by ID first
        agent = server_models.Agent.query.filter_by(agent_id=identifier).first()
        
        # If not found, try finding by hostname
        if not agent:
            agent = server_models.Agent.query.filter_by(hostname=identifier).first()
            
        if not agent:
            logger.error(f"Agent '{identifier}' not found.")
            return False
            
        agent_id = agent.id
        hostname = agent.hostname
        
        logger.info(f"Deleting agent: {hostname} ({agent_id})")
        
        try:
            # Delete references in other tables if cascade doesn't handle it
            # (Though in our models it should handle most)
            
            # 1. ScreenTime
            server_models.ScreenTime.query.filter_by(agent_id=agent_id).delete()
            # 2. AppUsage
            server_models.AppUsage.query.filter_by(agent_id=agent_id).delete()
            # 3. AppSession
            server_models.AppSession.query.filter_by(agent_id=agent_id).delete()
            # 4. DomainUsage
            server_models.DomainUsage.query.filter_by(agent_id=agent_id).delete()
            # 5. DomainVisit
            server_models.DomainVisit.query.filter_by(agent_id=agent_id).delete()
            # 6. DomainSession
            server_models.DomainSession.query.filter_by(agent_id=agent_id).delete()
            # 7. AppInventory
            server_models.AppInventory.query.filter_by(agent_id=agent_id).delete()
            # 8. AppInventoryChange
            server_models.AppInventoryChange.query.filter_by(agent_id=agent_id).delete()
            # 9. StateChange
            server_models.StateChange.query.filter_by(agent_id=agent_id).delete()
            # 10. RawEvent
            server_models.RawEvent.query.filter_by(agent_id=agent_id).delete()
            
            # 11. AgentCurrentStatus (Live activity)
            server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).delete()
            
            # Finally delete the agent
            db.session.delete(agent)
            db.session.commit()
            logger.info(f"✅ Successfully removed agent '{hostname}' and all its data.")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete agent: {e}")
            return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 remove_agent.py <hostname_or_id>")
        sys.exit(1)
        
    remove_agent(sys.argv[1])
