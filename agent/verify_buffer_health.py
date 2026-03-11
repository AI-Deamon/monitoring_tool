#!/usr/bin/env python3
"""
Offline buffer diagnostics helper.

Usage:
  python verify_buffer_health.py --db "C:\\ProgramData\\WinDiagSvc\\state\\buffer.db"
"""
import argparse
import json
from pathlib import Path

from core.buffer import BufferDB


def main():
    parser = argparse.ArgumentParser(description="Inspect Core offline buffer health")
    parser.add_argument("--db", required=True, help="Path to buffer SQLite DB")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Buffer DB not found: {db_path}")

    buffer_db = BufferDB(db_path)
    diagnostics = buffer_db.get_buffer_diagnostics()
    print(json.dumps(diagnostics, indent=2))


if __name__ == "__main__":
    main()
