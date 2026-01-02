"""
Performance Optimization Migration - PERF-001
==============================================
Adds database indexes, query optimizations, and performance improvements.

Run with: python migrations/performance_optimization.py
"""
import os
import sys
import psycopg2
from datetime import datetime

# Get database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL', 
    'postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1')

def parse_db_url(url):
    """Parse database URL into connection parameters"""
    url = url.replace('postgresql://', '')
    auth, rest = url.split('@')
    user, password = auth.split(':')
    host_port, db = rest.split('/')
    if ':' in host_port:
        host, port = host_port.split(':')
    else:
        host, port = host_port, '5432'
    return {
        'host': host,
        'port': port,
        'user': user,
        'password': password,
        'dbname': db
    }

def run_migration():
    """Run all performance optimizations"""
    print("=" * 70)
    print("PERFORMANCE OPTIMIZATION - Database & Server")
    print("=" * 70)
    
    conn_params = parse_db_url(DATABASE_URL)
    conn = psycopg2.connect(**conn_params)
    conn.autocommit = True
    cur = conn.cursor()
    
    optimizations = []
    
    # =========================================================================
    # 1. CRITICAL INDEXES (Most frequently queried columns)
    # =========================================================================
    print("\n📊 Adding Critical Indexes...")
    
    critical_indexes = [
        # Agent lookups
        ("idx_agents_last_seen", "agents", "last_seen DESC"),
        ("idx_agents_status", "agents", "status"),
        
        # Screen time queries (most frequent dashboard query)
        ("idx_screen_time_date_agent", "screen_time", "date DESC, agent_id"),
        
        # App usage queries
        ("idx_app_usage_date_duration", "app_usage", "date DESC, duration_seconds DESC"),
        ("idx_app_usage_agent_date_app", "app_usage", "agent_id, date, app"),
        
        # Domain usage queries
        ("idx_domain_usage_date_duration", "domain_usage", "date DESC, duration_seconds DESC"),
        ("idx_domain_usage_agent_date_domain", "domain_usage", "agent_id, date, domain"),
        
        # App sessions (timeline queries)
        ("idx_app_sessions_start_time", "app_sessions", "start_time DESC"),
        ("idx_app_sessions_agent_start", "app_sessions", "agent_id, start_time DESC"),
        
        # Agent current status (real-time queries)
        ("idx_agent_status_username", "agent_current_status", "username"),
        ("idx_agent_status_state", "agent_current_status", "current_state"),
        
        # State changes (timeline)
        ("idx_state_changes_timestamp", "state_changes", "timestamp DESC"),
        ("idx_state_changes_agent_ts", "state_changes", "agent_id, timestamp DESC"),
    ]
    
    for idx_name, table, columns in critical_indexes:
        try:
            # Check if index exists
            cur.execute(f"""
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = '{idx_name}'
            """)
            if cur.fetchone():
                print(f"  ⏭️  Index {idx_name} already exists")
            else:
                cur.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} ON {table} ({columns})")
                print(f"  ✅ Created index: {idx_name}")
                optimizations.append(f"Created index {idx_name}")
        except Exception as e:
            print(f"  ⚠️  Index {idx_name}: {e}")
    
    # =========================================================================
    # 2. PARTIAL INDEXES (For specific query patterns)
    # =========================================================================
    print("\n📊 Adding Partial Indexes...")
    
    partial_indexes = [
        # Active agents only
        ("idx_agents_active", "agents", "id, last_seen", 
         "WHERE status = 'active'"),
        
        # Recent screen time only (last 30 days)
        ("idx_screen_time_recent", "screen_time", "agent_id, date, active_seconds",
         "WHERE date >= CURRENT_DATE - INTERVAL '30 days'"),
        
        # Unprocessed raw events (for background processing)
        ("idx_raw_events_unprocessed", "raw_events", "id, received_at",
         "WHERE processed = false"),
    ]
    
    for idx_name, table, columns, condition in partial_indexes:
        try:
            cur.execute(f"""
                SELECT 1 FROM pg_indexes 
                WHERE schemaname = 'public' AND indexname = '{idx_name}'
            """)
            if cur.fetchone():
                print(f"  ⏭️  Partial index {idx_name} already exists")
            else:
                cur.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} ON {table} ({columns}) {condition}")
                print(f"  ✅ Created partial index: {idx_name}")
                optimizations.append(f"Created partial index {idx_name}")
        except Exception as e:
            print(f"  ⚠️  Partial index {idx_name}: {e}")
    
    # =========================================================================
    # 3. DATABASE STATISTICS CONFIGURATION
    # =========================================================================
    print("\n📊 Updating Statistics Configuration...")
    
    try:
        # Increase statistics target for frequently filtered columns
        stat_columns = [
            ("screen_time", "agent_id"),
            ("screen_time", "date"),
            ("app_usage", "agent_id"),
            ("app_usage", "date"),
            ("app_usage", "app"),
            ("domain_usage", "agent_id"),
            ("domain_usage", "date"),
        ]
        
        for table, column in stat_columns:
            cur.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET STATISTICS 500")
        
        print("  ✅ Increased statistics target for key columns")
        optimizations.append("Increased statistics target")
    except Exception as e:
        print(f"  ⚠️  Statistics config: {e}")
    
    # =========================================================================
    # 4. ANALYZE TABLES (Update query planner statistics)
    # =========================================================================
    print("\n📊 Analyzing Tables...")
    
    tables = [
        'agents', 'screen_time', 'app_usage', 'domain_usage',
        'app_sessions', 'agent_current_status', 'state_changes'
    ]
    
    for table in tables:
        try:
            cur.execute(f"ANALYZE {table}")
            print(f"  ✅ Analyzed: {table}")
        except Exception as e:
            print(f"  ⚠️  Analyze {table}: {e}")
    
    optimizations.append(f"Analyzed {len(tables)} tables")
    
    # =========================================================================
    # 5. VACUUM ANALYZE (Clean up and update stats)
    # =========================================================================
    print("\n🧹 Running VACUUM ANALYZE...")
    
    try:
        cur.execute("VACUUM ANALYZE")
        print("  ✅ VACUUM ANALYZE complete")
        optimizations.append("VACUUM ANALYZE")
    except Exception as e:
        print(f"  ⚠️  VACUUM: {e}")
    
    # =========================================================================
    # 6. CHECK TABLE SIZES
    # =========================================================================
    print("\n📊 Table Sizes:")
    
    cur.execute("""
        SELECT 
            relname as table,
            pg_size_pretty(pg_total_relation_size(relid)) as total_size,
            n_live_tup as row_count
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 10
    """)
    
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} ({row[2]:,} rows)")
    
    # Cleanup
    cur.close()
    conn.close()
    
    print("\n" + "=" * 70)
    print(f"✅ Optimization complete! {len(optimizations)} changes made")
    print("=" * 70)
    
    return optimizations

if __name__ == '__main__':
    run_migration()
