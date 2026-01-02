#!/usr/bin/env python3
"""
Script to extract domain history for a specific user (Harish).
"""

import os
import sys
from datetime import datetime

# Add the server directory to Python path
sys.path.insert(0, '/home/kali_linux/Desktop/cmon/Stable Set 1/server')

from extensions import db
from server_models import DomainUsage, DomainVisit, DomainSession
from server_app import create_app

def get_domain_history_for_user(username):
    """Get domain history for a specific user."""
    app = create_app()
    
    with app.app_context():
        try:
            results = {}
            
            # Get domain usage records
            domain_usage = DomainUsage.query.filter_by(username=username).order_by(DomainUsage.date.desc()).all()
            if domain_usage:
                results['domain_usage'] = []
                for record in domain_usage:
                    results['domain_usage'].append({
                        'date': record.date.isoformat(),
                        'domain': record.domain,
                        'browser': record.browser,
                        'duration_seconds': record.duration_seconds,
                        'session_count': record.session_count
                    })
            
            # Get domain visit records
            domain_visits = DomainVisit.query.filter_by(username=username).order_by(DomainVisit.visited_at.desc()).all()
            if domain_visits:
                results['domain_visits'] = []
                for record in domain_visits:
                    results['domain_visits'].append({
                        'visited_at': record.visited_at.isoformat(),
                        'domain': record.domain,
                        'url': record.url,
                        'browser': record.browser
                    })
            
            # Get domain session records
            domain_sessions = DomainSession.query.filter_by(username=username).order_by(DomainSession.start_time.desc()).all()
            if domain_sessions:
                results['domain_sessions'] = []
                for record in domain_sessions:
                    results['domain_sessions'].append({
                        'start_time': record.start_time.isoformat(),
                        'end_time': record.end_time.isoformat() if record.end_time else None,
                        'domain': record.domain,
                        'url': record.url,
                        'browser': record.browser,
                        'duration_seconds': record.duration_seconds
                    })
            
            return results
            
        except Exception as e:
            print(f"Error extracting domain history for {username}: {e}")
            return {}

def main():
    username = "BSOLAD\\Harish"
    
    print("SentinelEdge - Domain History Extractor")
    print("=" * 50)
    print(f"User: {username}")
    print()
    
    # Set database URL from environment
    os.environ['DATABASE_URL'] = 'postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1'
    
    domain_history = get_domain_history_for_user(username)
    
    if not domain_history:
        print(f"No domain history found for user: {username}")
        print("This may be because:")
        print("1. The user's agent was deleted")
        print("2. No domain data was collected for this user")
        print("3. The username case or spelling is different")
        return
    
    # Create output file
    output_file = f"/home/kali_linux/Desktop/cmon/Stable Set 1/domain_history_{username.lower()}.txt"
    with open(output_file, 'w') as f:
        f.write(f"SentinelEdge - Domain History for {username}\n")
        f.write("=" * 50 + "\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        
        # Write domain usage (aggregated daily data)
        if 'domain_usage' in domain_history:
            f.write("DOMAIN USAGE (Daily Aggregated Data)\n")
            f.write("-" * 40 + "\n")
            f.write("Date        | Domain                     | Browser    | Duration | Sessions\n")
            f.write("-" * 85 + "\n")
            
            for record in domain_history['domain_usage']:
                date = record['date']
                domain = record['domain'][:25] + "..." if len(record['domain']) > 25 else record['domain']
                browser = record['browser'][:10] if record['browser'] else "Unknown"
                duration = f"{record['duration_seconds']}s"
                sessions = str(record['session_count'])
                
                f.write(f"{date} | {domain:25s} | {browser:10s} | {duration:8s} | {sessions}\n")
            
            f.write(f"\nTotal daily usage records: {len(domain_history['domain_usage'])}\n\n")
        
        # Write domain visits (individual visits)
        if 'domain_visits' in domain_history:
            f.write("DOMAIN VISITS (Individual Visits)\n")
            f.write("-" * 40 + "\n")
            f.write("Visited At               | Domain                     | Browser\n")
            f.write("-" * 85 + "\n")
            
            for record in domain_history['domain_visits']:
                visited_at = record['visited_at'][:19]
                domain = record['domain'][:25] + "..." if len(record['domain']) > 25 else record['domain']
                browser = record['browser'][:10] if record['browser'] else "Unknown"
                
                f.write(f"{visited_at} | {domain:25s} | {browser:10s}\n")
            
            f.write(f"\nTotal visit records: {len(domain_history['domain_visits'])}\n\n")
        
        # Write domain sessions (detailed session data)
        if 'domain_sessions' in domain_history:
            f.write("DOMAIN SESSIONS (Detailed Sessions)\n")
            f.write("-" * 40 + "\n")
            f.write("Start Time               | Duration | Domain                     | Browser\n")
            f.write("-" * 85 + "\n")
            
            for record in domain_history['domain_sessions']:
                start_time = record['start_time'][:19]
                duration = f"{record['duration_seconds']}s"
                domain = record['domain'][:25] + "..." if len(record['domain']) > 25 else record['domain']
                browser = record['browser'][:10] if record['browser'] else "Unknown"
                
                f.write(f"{start_time} | {duration:8s} | {domain:25s} | {browser:10s}\n")
            
            f.write(f"\nTotal session records: {len(domain_history['domain_sessions'])}\n")
    
    print(f"Domain history for {username} saved to: {output_file}")
    
    # Show summary
    total_records = sum(len(domain_history[key]) for key in domain_history.keys())
    print(f"Total records found: {total_records}")
    
    for key, records in domain_history.items():
        print(f"  {key}: {len(records)} records")

if __name__ == "__main__":
    main()