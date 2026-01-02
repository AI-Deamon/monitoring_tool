#!/usr/bin/env python3
"""
Migration Script: Add away_seconds Column to screen_time Table

This migration adds the away_seconds column to support the new "away" classification
for prolonged locked periods (> 2 hours).

Usage:
    python add_away_seconds.py

What it does:
- Adds 'away_seconds' column to screen_time table (default: 0)
- Safe to run multiple times (idempotent)
"""

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

def get_connection():
    """Get PostgreSQL connection from environment."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'sentineledge'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', '')
    )

def add_away_seconds_column():
    """Add away_seconds column to screen_time table if it doesn't exist."""
    conn = get_connection()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'screen_time' 
            AND column_name = 'away_seconds'
        """)
        
        if cursor.fetchone():
            print("✓ Column 'away_seconds' already exists in screen_time table")
            return True
        
        # Add the column
        print("Adding 'away_seconds' column to screen_time table...")
        cursor.execute("""
            ALTER TABLE screen_time 
            ADD COLUMN away_seconds INTEGER DEFAULT 0
        """)
        
        print("✓ Column 'away_seconds' added successfully!")
        
        # Update existing records to have 0 (already handled by DEFAULT, but just in case)
        cursor.execute("""
            UPDATE screen_time 
            SET away_seconds = 0 
            WHERE away_seconds IS NULL
        """)
        print("✓ Existing records updated with default value")
        
        return True
        
    except Exception as e:
        print(f"✗ Error adding column: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def main():
    print("=" * 60)
    print("Migration: Add away_seconds to screen_time")
    print("=" * 60)
    print()
    
    success = add_away_seconds_column()
    
    print()
    print("=" * 60)
    if success:
        print("Migration completed successfully!")
        print()
        print("The 'away_seconds' column is now available for tracking")
        print("prolonged locked periods (> 2 hours) as 'away' time.")
    else:
        print("Migration failed - please check errors above")
    print("=" * 60)

if __name__ == '__main__':
    main()
