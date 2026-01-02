#!/usr/bin/env python3
"""
WSGI Entry Point for SentinelEdge Server

For production deployment with Gunicorn, uWSGI, or other WSGI servers.

Usage:
    gunicorn --bind 0.0.0.0:5050 --workers 4 --threads 2 wsgi:app
    uwsgi --http :5050 --wsgi-file wsgi.py --callable app --processes 4
"""

import os
import sys
from pathlib import Path

# Ensure the server directory is in the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Set production defaults if not set
os.environ.setdefault('LOG_LEVEL', 'INFO')

from server_app import create_app
from extensions import db

# Create the Flask application
app = create_app()

# Initialize database tables (on first request)
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"Warning: Could not create database tables: {e}")


def main():
    """Development server runner (not for production)."""
    from server_config import get_config
    config = get_config()
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=False,
        threaded=True
    )


if __name__ == '__main__':
    main()
