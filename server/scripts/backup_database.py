#!/usr/bin/env python3
"""
Database Backup Script
======================
Exports the entire SentinelEdge database to a portable SQL file.
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from server_config import get_config

def backup_database(output_file: str = None):
    """Backup database to SQL file"""
    config = get_config()
    
    # Parse DATABASE_URL
    # Format: postgresql://user:password@host:port/database
    db_url = config.DATABASE_URL
    if not db_url.startswith('postgresql://'):
        print("❌ Only PostgreSQL databases are supported")
        return False
    
    # Extract connection details
    db_url = db_url.replace('postgresql://', '')
    if '@' in db_url:
        auth, location = db_url.split('@')
        username, password = auth.split(':')
        host_port, database = location.split('/')
        host = host_port.split(':')[0]
        port = host_port.split(':')[1] if ':' in host_port else '5432'
    else:
        print("❌ Invalid DATABASE_URL format")
        return False
    
    # Generate output filename if not provided
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"sentineledge_backup_{timestamp}.sql"
    
    output_path = Path(output_file).absolute()
    
    print(f"🔄 Backing up database '{database}' to {output_path}...")
    
    # Use pg_dump to create backup
    try:
        env = {'PGPASSWORD': password}
        cmd = [
            'pg_dump',
            '-h', host,
            '-p', port,
            '-U', username,
            '-d', database,
            '-F', 'p',  # Plain text format
            '--clean',  # Include DROP statements
            '--if-exists',  # Use IF EXISTS
            '-f', str(output_path)
        ]
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode == 0:
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"✅ Backup successful!")
            print(f"   File: {output_path}")
            print(f"   Size: {size_mb:.2f} MB")
            print(f"\n📦 To restore on another machine:")
            print(f"   python scripts/restore_database.py --input {output_path.name}")
            return True
        else:
            print(f"❌ Backup failed: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("❌ pg_dump not found. Please install PostgreSQL client tools.")
        print("   Windows: Install PostgreSQL from https://www.postgresql.org/download/windows/")
        print("   Linux: sudo apt-get install postgresql-client")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Backup SentinelEdge database')
    parser.add_argument('--output', '-o', help='Output SQL file path')
    args = parser.parse_args()
    
    success = backup_database(args.output)
    sys.exit(0 if success else 1)
