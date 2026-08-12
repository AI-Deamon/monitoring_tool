"""
Migration: Create asset_info table for IT asset hardware tracking.

Creates the asset_info table with columns for:
  - System identity (hostname, serial, manufacturer, model, BIOS UUID)
  - Hardware specs (CPU, RAM, GPU, disks, motherboard)
  - Network config (MAC, IP, DNS, domain)
  - Security posture (OS, antivirus, firewall, BitLocker)

Run: python migrations/add_asset_info_table.py
Rollback: python migrations/add_asset_info_table.py --rollback
"""

import os
import sys
import psycopg2


def get_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise SystemExit("DATABASE_URL environment variable must be set")
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


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS asset_info (
    id SERIAL PRIMARY KEY,
    agent_id UUID NOT NULL UNIQUE REFERENCES agents(agent_id) ON DELETE CASCADE,
    
    -- Identity
    hostname VARCHAR(255),
    serial_number VARCHAR(255),
    manufacturer VARCHAR(255),
    model VARCHAR(255),
    bios_uuid VARCHAR(255),
    system_uuid VARCHAR(255),
    asset_tag VARCHAR(255),
    domain VARCHAR(255),
    workgroup VARCHAR(255),
    
    -- Hardware Specs
    cpu_name TEXT,
    cpu_cores INTEGER,
    cpu_threads INTEGER,
    cpu_speed_mhz INTEGER,
    ram_total_gb REAL,
    ram_slots_used INTEGER,
    ram_slots_total INTEGER,
    gpu_name TEXT,
    gpu_memory_gb REAL,
    disks_json TEXT,
    motherboard TEXT,
    
    -- Network
    primary_mac VARCHAR(255),
    primary_ip VARCHAR(255),
    all_macs_json TEXT,
    all_ips_json TEXT,
    dns_servers_json TEXT,
    domain_joined BOOLEAN DEFAULT FALSE,
    domain_name VARCHAR(255),
    
    -- Security Posture
    os_name VARCHAR(255),
    os_version VARCHAR(255),
    os_build VARCHAR(255),
    os_architecture VARCHAR(255),
    antivirus_json TEXT,
    firewall_enabled BOOLEAN DEFAULT FALSE,
    last_boot_time VARCHAR(255),
    windows_update_enabled BOOLEAN DEFAULT FALSE,
    bitlocker_status VARCHAR(255),
    
    -- Meta
    collected_at TIMESTAMP DEFAULT NOW(),
    collection_hash VARCHAR(64),
    agent_version VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_asset_info_agent_id ON asset_info(agent_id);
"""


def migrate():
    conn = get_connection()
    cur = conn.cursor()
    
    # Check if table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'asset_info'
        )
    """)
    exists = cur.fetchone()[0]
    
    if exists:
        print("  [SKIP] asset_info table already exists")
    else:
        print("  [CREATE] asset_info table")
        cur.execute(CREATE_TABLE_SQL)
        print("  [CREATE] index on agent_id")
    
    conn.commit()
    cur.close()
    conn.close()
    print("\nMigration complete")


def rollback():
    """Drop asset_info table (for rollback)."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'asset_info'
        )
    """)
    
    if cur.fetchone()[0]:
        print("  [DROP] asset_info table")
        cur.execute("DROP TABLE asset_info CASCADE")
    else:
        print("  [SKIP] asset_info table does not exist")
    
    conn.commit()
    cur.close()
    conn.close()
    print("Rollback complete")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--rollback':
        print("Rolling back asset_info table...")
        rollback()
    else:
        print("Creating asset_info table...")
        migrate()
