"""
Gunicorn configuration for SentinelEdge Server
Usage: gunicorn -c gunicorn_config.py server_main:application
"""
import os
import multiprocessing
import sys
from pathlib import Path
from dotenv import load_dotenv

# gunicorn reads this config file directly, before importing the app module —
# server_config.py's load_dotenv() (which the app relies on) hasn't run yet
# at that point. Without this, GUNICORN_BIND/USE_TLS below would only ever
# see .env's values if something had already exported them into the shell/
# systemd environment, silently ignoring .env otherwise.
load_dotenv()

# Server socket — defaults to the app's own PORT so changing .env's PORT
# doesn't leave gunicorn still bound to the old one. GUNICORN_BIND is an
# explicit override for binding to a different host/port than PORT.
bind = os.getenv("GUNICORN_BIND") or f"0.0.0.0:{os.getenv('PORT', '5050')}"
backlog = 2048

# NEW: Ensure logs directory exists
Path("logs").mkdir(exist_ok=True)

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"  # Use 'gevent' for async if needed
worker_connections = 1000
timeout = 120  # 2 minutes for slow database queries
keepalive = 60

# Logging
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "sentineledge_server"

# Server mechanics
daemon = False  # Set to True for background process
pidfile = "logs/gunicorn.pid"
user = None  # Set to specific user if needed
group = None
umask = 0
tmp_upload_dir = None

# Restart workers after this many requests (prevent memory leaks)
max_requests = 1000
max_requests_jitter = 50

# FIX 6: SECURITY - Request Limits
limit_request_line = 4096        # Max URL length
limit_request_fields = 100       # Max number of headers
limit_request_field_size = 8192  # Max header size

# Graceful timeout (seconds to wait for requests to finish)
graceful_timeout = 30

# SSL/TLS — off by default, matching the app's own USE_TLS flag
# (server_config.py / server_app.py). Agents authenticate with X-API-Key,
# not client certificates, so mTLS (cert_reqs=CERT_REQUIRED) was never
# actually satisfiable by anything in this codebase — it just made gunicorn
# refuse to start unless someone manually dropped cert files in place.
# Set USE_TLS=true and provide SSL_CERT_PATH/SSL_KEY_PATH to terminate TLS
# here directly; otherwise leave a reverse proxy (nginx, etc.) to handle it,
# or run plain HTTP behind a trusted network boundary.
if os.getenv("USE_TLS", "false").lower() == "true":
    certfile = os.getenv("SSL_CERT_PATH", "certs/server.crt")
    keyfile = os.getenv("SSL_KEY_PATH", "certs/server.key")
    ca_certs = os.getenv("SSL_CA_PATH") or None
    cert_reqs = 2 if ca_certs else 0  # CERT_REQUIRED only if a CA is actually configured (mTLS); else server-only TLS
    ssl_version = 'TLSv1_2'

# Pre-fork callback - runs before workers are created
def on_starting(server):
    """Called just before the master process is initialized."""
    print("=" * 70)
    print(" SentinelEdge Server Starting")
    print("=" * 70)
    
    # NEW: Run automatic database setup and procedure installation
    print("[INIT] Running database and procedure setup...")
    try:
        # Add current directory to path so start_server can be imported
        server_dir = str(Path(__file__).parent.absolute())
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
            
        from start_server import main as run_setup
        # Mock sys.argv to pass --no-start
        old_argv = sys.argv
        sys.argv = ['start_server.py', '--no-start']
        run_setup()
        sys.argv = old_argv
        print("[INIT] Database setup complete.")
    except Exception as e:
        print(f"[ERROR] Database setup failed: {e}")
        # In a real production environment, we might want to exit here
        # sys.exit(1)
    
    print("-" * 70)

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    print("Reloading workers...")

def when_ready(server):
    """Called just after the server is started."""
    print(f"Server ready. Listening on {bind}")
    print(f"Workers: {workers}")
    print("=" * 70)

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    # Each worker gets its own database connection pool
    pass

def worker_int(worker):
    """Called when a worker receives INT or QUIT signal."""
    print(f"Worker {worker.pid} received signal, shutting down gracefully...")

def worker_abort(worker):
    """Called when a worker receives SIGABRT signal."""
    print(f"Worker {worker.pid} aborted!")

def pre_exec(server):
    """Called just before a new master process is forked."""
    print("Forking new master process...")

def child_exit(server, worker):
    """Called in the master process after a worker exits."""
    print(f"Worker {worker.pid} exited")
