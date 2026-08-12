"""
Migration: Add Dashboard-Driven Update Control columns to agents table.

Adds:
  - target_version   (VARCHAR 50)  — Set by dashboard admin
  - update_status    (VARCHAR 50)  — Lifecycle state
  - last_update_check (TIMESTAMP)  — Last poll time
  - update_attempts  (INTEGER)     — Retry counter
  - last_update_error (TEXT)       — Last failure reason

Run: python migrations/add_update_control.py
"""

import os
import sys
import psycopg2

def get_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise SystemExit("DATABASE_URL environment variable must be set")
    # Parse: postgresql://user:pass@host:port/dbname
    url = db_url.replace('postgresql://', '')
    userpass, hostdb = url.split('@')
    user, password = userpass.split(':')
    hostport, dbname = hostdb.split('/')
    if ':' in hostport:
        host, port = hostport.split(':')
    else:
        host, port = hostport, '5432'
    
    return psycopg2.connect(
        host=host, port=port, dbname=dbname,
        user=user, password=password
    )


COLUMNS = [
    ("target_version",    "VARCHAR(50)",  "NULL"),
    ("update_status",     "VARCHAR(50)",  "DEFAULT 'up_to_date'"),
    ("last_update_check", "TIMESTAMP",    "NULL"),
    ("update_attempts",   "INTEGER",      "DEFAULT 0"),
    ("last_update_error", "TEXT",         "NULL"),
]


def migrate():
    conn = get_connection()
    cur = conn.cursor()
    
    added = 0
    skipped = 0
    
    for col_name, col_type, col_default in COLUMNS:
        # Check if column already exists
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'agents' AND column_name = %s
        """, (col_name,))
        
        if cur.fetchone():
            print(f"  [SKIP] {col_name} already exists")
            skipped += 1
            continue
        
        sql = f"ALTER TABLE agents ADD COLUMN {col_name} {col_type} {col_default}"
        print(f"  [ADD]  {col_name} ({col_type} {col_default})")
        cur.execute(sql)
        added += 1
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"\nDone: {added} added, {skipped} skipped")


def rollback():
    """Remove update control columns (for rollback)."""
    conn = get_connection()
    cur = conn.cursor()
    
    for col_name, _, _ in COLUMNS:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'agents' AND column_name = %s
        """, (col_name,))
        
        if cur.fetchone():
            print(f"  [DROP] {col_name}")
            cur.execute(f"ALTER TABLE agents DROP COLUMN {col_name}")
    
    conn.commit()
    cur.close()
    conn.close()
    print("Rollback complete")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--rollback':
        print("Rolling back update control columns...")
        rollback()
    else:
        print("Adding update control columns to agents table...")
        migrate()
