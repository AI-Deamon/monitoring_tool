#!/usr/bin/env python3
"""
Script to extract all unique domains from the database.
"""

import os
import sys
from sqlalchemy import distinct

# Add the server directory to Python path
sys.path.insert(0, '/home/kali_linux/Desktop/cmon/Stable Set 1/server')

from extensions import db
from server_models import DomainUsage, DomainVisit, DomainSession
from server_app import create_app

def get_unique_domains():
    """Get all unique domains from database."""
    app = create_app()
    
    with app.app_context():
        try:
            # Get unique domains from all domain-related tables
            domains_usage = [row[0] for row in db.session.query(distinct(DomainUsage.domain)).all() if row[0]]
            domains_visit = [row[0] for row in db.session.query(distinct(DomainVisit.domain)).all() if row[0]]
            domains_session = [row[0] for row in db.session.query(distinct(DomainSession.domain)).all() if row[0]]
            
            # Combine and deduplicate
            all_domains = set(domains_usage + domains_visit + domains_session)
            
            # Sort alphabetically
            sorted_domains = sorted(list(all_domains))
            
            return sorted_domains
            
        except Exception as e:
            print(f"Error extracting domains: {e}")
            return []

def main():
    print("SentinelEdge - Domain Extractor")
    print("=" * 40)
    
    # Set database URL from environment
    os.environ['DATABASE_URL'] = 'postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1'
    
    domains = get_unique_domains()
    
    if domains:
        print(f"Found {len(domains)} unique domains")
        
        # Create file with domains
        output_file = "/home/kali_linux/Desktop/cmon/Stable Set 1/unique_domains.txt"
        with open(output_file, 'w') as f:
            f.write("SentinelEdge - Unique Domains List\n")
            f.write(f"Total Count: {len(domains)}\n")
            f.write("=" * 50 + "\n\n")
            
            for domain in domains:
                f.write(f"{domain}\n")
        
        print(f"Domains saved to: {output_file}")
        
        # Show first 20 domains as preview
        print("\nFirst 20 domains:")
        for i, domain in enumerate(domains[:20]):
            print(f"{i+1:2d}. {domain}")
        
        if len(domains) > 20:
            print(f"... and {len(domains) - 20} more")
    else:
        print("No domains found in database")

if __name__ == "__main__":
    main()