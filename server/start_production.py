#!/usr/bin/env python3
"""
SentinelEdge Server - Production Startup
========================================
Detects OS and starts the server with a production WSGI server.
- Windows: Uses 'waitress'
- Linux/Unix: Uses 'gunicorn'
"""
import sys
import os
import platform
import subprocess
from pathlib import Path
import logging

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def check_package(package_name):
    """Check if a package is installed, install if missing"""
    try:
        __import__(package_name)
        return True
    except ImportError:
        logger.info(f"📦 Package '{package_name}' missing. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            return True
        except Exception as e:
            logger.error(f"❌ Failed to install {package_name}: {e}")
            return False

def run_setup():
    """Run the auto-setup script"""
    logger.info("Step 1: Running database setup and procedures...")
    try:
        # Import the main from start_server and run it with --no-start
        from start_server import main
        # Mock sys.argv
        old_argv = sys.argv
        sys.argv = ['start_server.py', '--no-start']
        main()
        sys.argv = old_argv
        return True
    except Exception as e:
        logger.error(f"❌ Setup failed: {e}")
        return False

def start_waitress(host, port):
    """Start the server using Waitress (Windows)"""
    if check_package("waitress"):
        from waitress import serve
        from server_app import create_app
        
        app = create_app()
        logger.info(f"\n🚀 Starting Production Server (Waitress) on http://{host}:{port}")
        logger.info("   Dashboard: http://localhost:5000/dashboard")
        logger.info("="*60)
        
        serve(app, host=host, port=port, threads=8)
    else:
        logger.error("❌ Waitress installation failed. Cannot start production server on Windows.")

def start_gunicorn():
    """Start the server using Gunicorn (Linux)"""
    logger.info("\n🚀 Starting Production Server (Gunicorn)...")
    logger.info("   Gunicorn config: gunicorn_config.py")
    logger.info("="*60)
    
    try:
        subprocess.run(["gunicorn", "-c", "gunicorn_config.py", "server_main:application"])
    except FileNotFoundError:
        logger.error("❌ Gunicorn command not found. Please install it: pip install gunicorn")
    except Exception as e:
        logger.error(f"❌ Gunicorn failed: {e}")

def main():
    """Main production startup workflow"""
    # 1. Run Setup
    if not run_setup():
        sys.exit(1)
        
    # 2. Detect OS and start
    is_windows = platform.system() == "Windows"
    
    host = "0.0.0.0"
    port = 5000 # Standard port
    
    if is_windows:
        logger.info("✅ OS: Windows detected. Using Waitress for production.")
        start_waitress(host, port)
    else:
        logger.info("✅ OS: Linux/Unix detected. Using Gunicorn for production.")
        start_gunicorn()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n👋 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"\n❌ Fatal error: {e}")
        sys.exit(1)
