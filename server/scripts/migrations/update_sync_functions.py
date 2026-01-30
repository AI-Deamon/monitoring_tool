#!/usr/bin/env python3
"""
Quick script to apply the updated sync functions with GREATEST() fix.
Run this after updating apply_sync_functions.py to update the database.

Usage: python3 update_sync_functions.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from apply_sync_functions import apply_patch

if __name__ == "__main__":
    print("Applying updated sync functions with GREATEST() fix...")
    apply_patch()
    print("Done!")
