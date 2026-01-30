#!/usr/bin/env python3
"""
Script to delete an agent and all its related data from the database.
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the server directory to Python path
sys.path.insert(0, '/home/kali_linux/Desktop/cmon/Stable Set 1/server')

from extensions import db
from server_models import Agent, AgentCurrentStatus
from server_app import create_app

def delete_agent(agent_id):
    """Delete agent and all related data from database."""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if agent exists
            agent = Agent.query.filter_by(agent_id=agent_id).first()
            if not agent:
                print(f"Agent {agent_id} not found in database")
                return False
            
            print(f"Found agent: {agent.hostname} ({agent.id})")
            print(f"Status: {agent.status}, Last seen: {agent.last_seen}")
            
            # Auto-confirm deletion for this specific agent
            print(f"\nDeleting agent {agent_id} and ALL related data...")
            print("This includes:")
            print("- Agent record")
            print("- Current status")
            print("- Screen time records")
            print("- App usage and sessions")
            print("- Domain usage and visits")
            print("- App inventory")
            print("- State changes")
            print("- Raw events")
            print()
            
            # Delete current status first due to foreign key constraint
            current_status = AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
            if current_status:
                db.session.delete(current_status)
                db.session.commit()
            
            # Delete agent (cascade will handle related records)
            db.session.delete(agent)
            db.session.commit()
            
            print(f"✓ Successfully deleted agent {agent_id} and all related data")
            return True
            
        except Exception as e:
            print(f"Error deleting agent: {e}")
            db.session.rollback()
            return False

def delete_agent_with_context(app, agent_id):
    """Helper function to delete agent within app context."""
    with app.app_context():
        return delete_agent(agent_id)

def main():
    # List of agents to delete
    agent_ids = [
        "eb0761d9-77e5-444c-8dfd-12997c784d91",
        "9f51c12d-af94-423c-9dc6-cfb8d177da75", 
        "c53f0bbf-fe60-4e27-9556-bb43e1a80d17"
    ]
    
    print("SentinelEdge - Agent Deletion Tool")
    print("=" * 50)
    print(f"Target Agents: {len(agent_ids)} agents")
    for agent_id in agent_ids:
        print(f"  - {agent_id}")
    print()
    
    # Set database URL from environment
    os.environ['DATABASE_URL'] = 'postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1'
    
    # Create app once
    app = create_app()
    
    # Delete each agent
    success_count = 0
    for agent_id in agent_ids:
        print(f"\n{'='*20} Processing Agent {agent_id} {'='*20}")
        success = delete_agent_with_context(app, agent_id)
        if success:
            success_count += 1
        print()
    
    print("=" * 50)
    print(f"Deletion Summary: {success_count}/{len(agent_ids)} agents deleted successfully")
    
    if success_count == len(agent_ids):
        print("\nAll deletions completed successfully")
        sys.exit(0)
    else:
        print("\nSome deletions failed")
        sys.exit(1)

if __name__ == "__main__":
    main()