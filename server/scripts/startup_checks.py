#!/usr/bin/env python3
"""
Master Startup Check Script
Runs all critical fix/migration scripts to ensure server health.
"""
import sys
import logging
import subprocess
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [STARTUP] %(message)s'
)
logger = logging.getLogger(__name__)

# Base directory
BASE_DIR = Path(__file__).parent.parent.parent
SCRIPTS_DIR = BASE_DIR / 'scripts'
FIXES_DIR = SCRIPTS_DIR / 'fixes'

def run_script(script_path, desc):
    """Run a python script and log output."""
    logger.info(f"Running: {desc}...")
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info(f"✓ {desc} - OK")
            return True
        else:
            logger.error(f"✗ {desc} - FAILED")
            logger.error(f"  Output: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"✗ {desc} - ERROR: {e}")
        return False

def main():
    logger.info("=" * 60)
    logger.info(" SENTINELEDGE SERVER - STARTUP CHECKS")
    logger.info("=" * 60)

    # 1. CRITICAL: Fix Stored Procedures (Round error fix)
    run_script(
        FIXES_DIR / 'ensure_procedures_correct.py',
        "Stored Procedure Fixes (Round Function Patch)"
    )

    # 2. CRITICAL: Apply Sync Functions (Dashboard Sync)
    run_script(
        FIXES_DIR / 'apply_sync_functions.py',
        "Sync Functions Update"
    )

    # 3. HIGH: Add Indexes (Performance)
    run_script(
        FIXES_DIR / 'add_indexes.py',
        "Database Index Verification"
    )
    
    # 4. MEDIUM: Fix Schema/Columns (OS Build, etc)
    # Using fix_db_schema.py which covers multiple fixes
    run_script(
        FIXES_DIR / 'fix_db_schema.py',
        "Schema Verification (Missing Columns)"
    )

    # 5. LOW: Fix Collation Warning
    run_script(
        FIXES_DIR / 'fix_collation.py',
        "Database Collation Refresh"
    )

    logger.info("=" * 60)
    logger.info(" Startup checks complete.")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
