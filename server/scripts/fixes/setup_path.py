#!/usr/bin/env python3
"""
Script Runner Helper
====================
Adds the server directory to Python path before importing.
Use this as a template for all scripts in subdirectories.
"""
import sys
from pathlib import Path

# Add server directory to path
SERVER_DIR = Path(__file__).parent.parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# Now you can do: from setup_path import SERVER_DIR
