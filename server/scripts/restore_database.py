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
import os
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from server_config import get_config


def find_psql() -> str:
    """Locate psql.exe across common PostgreSQL installation paths."""
    # 1. Check PATH first
    found = shutil.which("psql")
    if found:
        return found

    # 2. Check common PostgreSQL installation directories
    common_paths = [
        r"C:\Program Files\PostgreSQL\18\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\17\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\15\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\14\bin\psql.exe",
        r"C:\Program Files (x86)\PostgreSQL\18\bin\psql.exe",
        r"C:\Program Files (x86)\PostgreSQL\17\bin\psql.exe",
        r"C:\Program Files (x86)\PostgreSQL\16\bin\psql.exe",
    ]
    for path in common_paths:
        if Path(path).exists():
            return path

    # 3. Search Program Files for any psql.exe
    for prog_dir in [r"C:\Program Files\PostgreSQL", r"C:\Program Files (x86)\PostgreSQL"]:
        base = Path(prog_dir)
        if base.exists():
            for ver_dir in sorted(base.iterdir(), reverse=True):
                candidate = ver_dir / "bin" / "psql.exe"
                if candidate.exists():
                    return str(candidate)

    raise FileNotFoundError(
        "psql.exe not found. Please install PostgreSQL client tools or add the "
        "PostgreSQL bin directory to your system PATH."
    )


def resolve_host(host: str) -> str:
    """Resolve hostname, falling back to 127.0.0.1 if localhost fails DNS."""
    if host.lower() in ("localhost", "127.0.0.1", "::1"):
        # On some Windows machines, localhost doesn't resolve.
        # Force 127.0.0.1 which works without DNS.
        return "127.0.0.1"
    return host


def restore_database(input_file: str, db_url_override: str = None):
    """Restore database from SQL file"""
    config = get_config()
    
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Backup file not found: {input_path}")
        return False
    
    # Parse DATABASE_URL
    db_url = db_url_override if db_url_override else config.DATABASE_URL
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
    
    # Resolve host (localhost -> 127.0.0.1 to avoid DNS issues on Windows)
    host = resolve_host(host)
    
    print(f"🔄 Restoring database '{database}' from {input_path}...")
    print(f"⚠️  WARNING: This will DROP and recreate all tables!")
    
    response = input("Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Restore canceled")
        return False
    
    # Locate psql executable
    try:
        psql_path = find_psql()
        print(f"✓ Found psql at: {psql_path}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return False
    
    env = {'PGPASSWORD': password}
    
    # Step 1: Drop schema with CASCADE to remove all objects (tables, functions, indices, etc.)
    print("   Step 1/2: Dropping existing schema with CASCADE...")
    try:
        drop_cmd = [
            psql_path,
            '-h', host,
            '-p', port,
            '-U', username,
            '-d', database,
            '-c', 'DROP SCHEMA public CASCADE;'
        ]
        result_drop = subprocess.run(drop_cmd, env=env, capture_output=True, text=True)
        if result_drop.returncode == 0:
            print("   ✓ Schema dropped")
        else:
            print(f"   ⚠️ Drop schema note: {result_drop.stderr.strip()}")
    except Exception as e:
        print(f"   ⚠️ Drop schema warning (non-fatal): {e}")
    
    # Step 2: Recreate schema
    try:
        create_cmd = [
            psql_path,
            '-h', host,
            '-p', port,
            '-U', username,
            '-d', database,
            '-c', 'CREATE SCHEMA public;'
        ]
        result_create = subprocess.run(create_cmd, env=env, capture_output=True, text=True)
        if result_create.returncode == 0:
            print("   ✓ Schema recreated")
    except Exception as e:
        print(f"   ⚠️ Create schema warning (non-fatal): {e}")
    
    # Step 3: Restore from backup
    print(f"   Step 2/2: Restoring from {input_path.name}...")
    try:
        cmd = [
            psql_path,
            '-h', host,
            '-p', port,
            '-U', username,
            '-d', database,
            '-f', str(input_path)
        ]
        
        print(f"   Running: {psql_path} -h {host} -p {port} -U {username} -d {database} -f {input_path.name}")
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ Restore successful!")
            print(f"\n🎉 Database is ready. You can now start the server:")
            print(f"   python server_main.py")
            return True
        else:
            # psql may return non-zero for non-fatal errors during restore
            # Check if tables were actually created
            check_cmd = [
                psql_path,
                '-h', host,
                '-p', port,
                '-U', username,
                '-d', database,
                '-t',
                '-c', "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
            ]
            check_result = subprocess.run(check_cmd, env=env, capture_output=True, text=True)
            table_count = check_result.stdout.strip()
            try:
                table_count_int = int(table_count)
                if table_count_int > 0:
                    print(f"✅ Restore completed with {table_count_int} tables (some non-fatal warnings above).")
                    print(f"\n🎉 Database is ready. You can now start the server:")
                    print(f"   python server_main.py")
                    return True
            except ValueError:
                pass
            
            # Print both stdout and stderr for diagnostics
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            if stdout:
                print(f"   stdout: {stdout[:2000]}")
            if stderr:
                print(f"❌ Restore failed: {stderr[:2000]}")
            return False
            
    except FileNotFoundError:
        print(f"❌ psql not found at: {psql_path}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Restore SentinelEdge database')
    parser.add_argument('--input', '-i', required=True, help='Input SQL file path')
    parser.add_argument('--db-url', help='Override DATABASE_URL connection string')
    args = parser.parse_args()
    
    success = restore_database(args.input, args.db_url)
    sys.exit(0 if success else 1)