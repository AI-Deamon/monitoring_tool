#!/usr/bin/env python3
"""
Script to list all users and their agent information currently in the database.
"""

import os
import sys

# Add the server directory to Python path
sys.path.insert(0, '/home/kali_linux/Desktop/cmon/Stable Set 1/server')

from extensions import db
from server_models import Agent, AgentCurrentStatus, DomainUsage
from server_app import create_app

def list_all_users():
    """List all users and agents currently in database."""
    app = create_app()
    
    with app.app_context():
        try:
            # Get all agents
            agents = Agent.query.all()
            
            print(f"Total agents in database: {len(agents)}")
            print()
            
            if not agents:
                print("No agents found in database.")
                return
            
            for agent in agents:
                print(f"Agent ID: {agent.id}")
                print(f"Hostname: {agent.hostname}")
                print(f"OS: {agent.os}")
                print(f"Status: {agent.status}")
                print(f"Last Seen: {agent.last_seen}")
                print(f"Created: {agent.created_at}")
                
                # Get current status
                current_status = AgentCurrentStatus.query.filter_by(agent_id=agent.id).first()
                if current_status:
                    print(f"Current User: {current_status.username}")
                    print(f"Current App: {current_status.current_app}")
                    print(f"Current State: {current_status.current_state}")
                
                # Get domain usage count
                domain_count = DomainUsage.query.filter_by(agent_id=agent.id).count()
                print(f"Domain Usage Records: {domain_count}")
                
                print("-" * 50)
            
            # Get unique usernames from domain usage table
            unique_users = db.session.query(AgentCurrentStatus.username).filter(AgentCurrentStatus.username.isnot(None)).distinct().all()
            usernames = [user[0] for user in unique_users]
            
            print(f"\nUnique usernames found: {len(usernames)}")
            for username in sorted(usernames):
                print(f"  - {username}")
                
        except Exception as e:
            print(f"Error listing users: {e}")

def main():
    print("SentinelEdge - User/Agent Listing")
    print("=" * 40)
    
    # Set database URL from environment
    os.environ['DATABASE_URL'] = 'postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1'
    
    list_all_users()

if __name__ == "__main__":
    main()