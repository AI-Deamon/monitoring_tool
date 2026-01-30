"""
Gunicorn configuration for SentinelEdge Server
Usage: gunicorn -c gunicorn_config.py server_main:application
"""
import os
import multiprocessing

# Server socket
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5050")
backlog = 2048

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

# SSL/TLS (uncomment for HTTPS - recommended for production)
# certfile = '/path/to/cert.pem'
# keyfile = '/path/to/key.pem'
# ssl_version = 'TLSv1_2'

# Pre-fork callback - runs before workers are created
def on_starting(server):
    """Called just before the master process is initialized."""
    print("=" * 70)
    print(" SentinelEdge Server Starting")
    print("=" * 70)

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
