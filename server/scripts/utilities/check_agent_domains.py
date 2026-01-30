#!/usr/bin/env python3
"""
Script to check all domain-related data for a specific agent.
"""

import os
import sys

# Add the server directory to Python path
sys.path.insert(0, '/home/kali_linux/Desktop/cmon/Stable Set 1/server')

from extensions import db
from server_models import Agent, DomainUsage, DomainVisit, DomainSession, AgentCurrentStatus
from server_app import create_app

def check_agent_domain_data(agent_id):
    """Check all domain data for a specific agent."""
    app = create_app()
    
    with app.app_context():
        try:
            # Get agent info
            agent = Agent.query.filter_by(agent_id=agent_id).first()
            if not agent:
                print(f"Agent {agent_id} not found")
                return
            
            print(f"Agent: {agent.hostname} ({agent.id})")
            print(f"Status: {agent.status}, Last seen: {agent.last_seen}")
            print()
            
            # Check current status
            current_status = AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
            if current_status:
                print(f"Current username: {current_status.username}")
                print(f"Current domain: {current_status.current_domain}")
                print(f"Current browser: {current_status.current_browser}")
                print()
            
            # Check domain usage
            domain_usage = DomainUsage.query.filter_by(agent_id=agent_id).all()
            print(f"Domain Usage records: {len(domain_usage)}")
            for record in domain_usage[:5]:  # Show first 5
                print(f"  {record.date}: {record.domain} ({record.browser}) - {record.duration_seconds}s")
            
            # Check domain visits
            domain_visits = DomainVisit.query.filter_by(agent_id=agent_id).all()
            print(f"\nDomain Visit records: {len(domain_visits)}")
            for record in domain_visits[:5]:  # Show first 5
                print(f"  {record.visited_at}: {record.domain} ({record.browser})")
            
            # Check domain sessions
            domain_sessions = DomainSession.query.filter_by(agent_id=agent_id).all()
            print(f"\nDomain Session records: {len(domain_sessions)}")
            for record in domain_sessions[:5]:  # Show first 5
                print(f"  {record.start_time}: {record.domain} ({record.browser}) - {record.duration_seconds}s")
                
            # Check all domains with this username
            if current_status and current_status.username:
                usage_by_username = DomainUsage.query.filter_by(username=current_status.username).all()
                visits_by_username = DomainVisit.query.filter_by(username=current_status.username).all()
                sessions_by_username = DomainSession.query.filter_by(username=current_status.username).all()
                
                print(f"\nRecords by username '{current_status.username}':")
                print(f"  Domain Usage: {len(usage_by_username)}")
                print(f"  Domain Visits: {len(visits_by_username)}")
                print(f"  Domain Sessions: {len(sessions_by_username)}")
                
                if usage_by_username:
                    print("\nFirst few usage records by username:")
                    for record in usage_by_username[:3]:
                        print(f"  {record.date}: {record.domain} - Agent: {record.agent_id}")
                
        except Exception as e:
            print(f"Error checking agent data: {e}")

def main():
    agent_id = "6ebbe65b-9f49-480c-860e-371973c6bdcf"  # Harish's current agent
    
    print("SentinelEdge - Agent Domain Data Checker")
    print("=" * 50)
    
    # Set database URL from environment
    os.environ['DATABASE_URL'] = 'postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1'
    
    check_agent_domain_data(agent_id)

if __name__ == "__main__":
    main()