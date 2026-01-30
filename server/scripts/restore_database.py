#!/usr/bin/env python3
"""
Database Restore Script
=======================
Restores SentinelEdge database from a backup SQL file.
"""
import sys
import subprocess
from pathlib import Path
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from server_config import get_config

def restore_database(input_file: str):
    """Restore database from SQL file"""
    config = get_config()
    
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Backup file not found: {input_path}")
        return False
    
    # Parse DATABASE_URL
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
    
    print(f"🔄 Restoring database '{database}' from {input_path}...")
    print(f"⚠️  WARNING: This will DROP and recreate all tables!")
    
    response = input("Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Restore canceled")
        return False
    
    # Use psql to restore backup
    try:
        env = {'PGPASSWORD': password}
        cmd = [
            'psql',
            '-h', host,
            '-p', port,
            '-U', username,
            '-d', database,
            '-f', str(input_path)
        ]
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ Restore successful!")
            print(f"\n🎉 Database is ready. You can now start the server:")
            print(f"   python server_main.py")
            return True
        else:
            print(f"❌ Restore failed: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("❌ psql not found. Please install PostgreSQL client tools.")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Restore SentinelEdge database')
    parser.add_argument('--input', '-i', required=True, help='Input SQL file path')
    args = parser.parse_args()
    
    success = restore_database(args.input)
    sys.exit(0 if success else 1)
