#!/usr/bin/env python3
"""
Domain Classification Script - One-time execution
Run this to classify existing unreviewed domain sessions.

Usage:
    python classify_domains.py
    
Or set up as hourly cron job:
    0 * * * * cd /path/to/server && python classify_domains.py
"""
import sys
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent))

from server_cleanup import classify_unreviewed_domains

if __name__ == "__main__":
    print("=" * 60)
    print(" SentinelEdge Domain Classification")
    print("=" * 60)
    classify_unreviewed_domains()
    print("=" * 60)
