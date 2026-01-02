"""
Enhanced logging configuration for SentinelEdge Server.
Provides structured logging with proper formatting and rotation.
"""
import logging
import logging.handlers
import os
from pathlib import Path
from datetime import datetime


def setup_logging(log_level='INFO', log_dir='logs'):
    """
    Configure logging with file rotation and console output.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files
    """
    # Create log directory
    Path(log_dir).mkdir(exist_ok=True)
    
    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Format string with agent context
    log_format = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler with rotation
    log_file = os.path.join(log_dir, 'server.log')
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,  # Keep 5 backup files
        encoding='utf-8'  # Fix Windows encoding issues with special characters
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.addHandler(file_handler)
    
    # API-specific log file
    api_log_file = os.path.join(log_dir, 'api.log')
    api_handler = logging.handlers.RotatingFileHandler(
        api_log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    api_handler.setFormatter(log_format)
    api_handler.setLevel(logging.INFO)
    api_logger = logging.getLogger('server_api')
    api_logger.addHandler(api_handler)
    
    # Dashboard log file
    dash_log_file = os.path.join(log_dir, 'dashboard.log')
    dash_handler = logging.handlers.RotatingFileHandler(
        dash_log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    dash_handler.setFormatter(log_format)
    dash_handler.setLevel(logging.INFO)
    dash_logger = logging.getLogger('server_dashboard')
    dash_logger.addHandler(dash_handler)
    
    # Console handler (for development) - use UTF-8 for Windows compatibility
    import sys
    import io
    # Wrap stdout with UTF-8 encoding to fix Windows console issues
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    # Suppress overly verbose libraries
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    root_logger.info(f"Logging initialized - Level: {log_level}, Log dir: {log_dir}")
    
    return root_logger


def get_logger(name):
    """Get a logger instance for a specific module."""
    return logging.getLogger(name)


class RequestLogger:
    """Middleware-like logger for HTTP requests."""
    
    @staticmethod
    def log_request(request, agent_id=None):
        """Log incoming request."""
        logger = logging.getLogger('server_api.requests')
        logger.info(
            f"[{request.remote_addr}] {request.method} {request.path} "
            f"from {agent_id or 'unknown'}"
        )
    
    @staticmethod
    def log_response(request, response_code, agent_id=None, duration_ms=None):
        """Log response."""
        logger = logging.getLogger('server_api.requests')
        duration_str = f"{duration_ms}ms" if duration_ms else "?"
        logger.info(
            f"[{request.remote_addr}] {request.method} {request.path} "
            f"→ {response_code} ({duration_str}) agent={agent_id or 'unknown'}"
        )


class PerformanceLogger:
    """Logger for performance metrics and bottlenecks."""
    
    THRESHOLDS = {
        'slow_query': 1000,  # 1 second
        'slow_request': 2000,  # 2 seconds
        'large_payload': 1024 * 1024,  # 1MB
    }
    
    @staticmethod
    def log_slow_query(query, duration_ms):
        """Log slow database query."""
        logger = logging.getLogger('server_api.performance')
        if duration_ms > PerformanceLogger.THRESHOLDS['slow_query']:
            logger.warning(
                f"SLOW_QUERY ({duration_ms}ms): {str(query)[:200]}..."
            )
    
    @staticmethod
    def log_slow_request(endpoint, duration_ms, agent_id=None):
        """Log slow HTTP request."""
        logger = logging.getLogger('server_api.performance')
        if duration_ms > PerformanceLogger.THRESHOLDS['slow_request']:
            logger.warning(
                f"SLOW_REQUEST ({duration_ms}ms): {endpoint} agent={agent_id}"
            )
    
    @staticmethod
    def log_large_payload(endpoint, size_bytes, agent_id=None):
        """Log large request/response payload."""
        logger = logging.getLogger('server_api.performance')
        if size_bytes > PerformanceLogger.THRESHOLDS['large_payload']:
            size_mb = size_bytes / (1024 * 1024)
            logger.warning(
                f"LARGE_PAYLOAD ({size_mb:.2f}MB): {endpoint} agent={agent_id}"
            )


class AgentLogger:
    """Structured logging for agent activity."""
    
    @staticmethod
    def log_agent_registration(agent_id, hostname, os_info):
        """Log agent registration."""
        logger = logging.getLogger('server_api.agents')
        logger.info(
            f"[AGENT {agent_id}] Registration: hostname={hostname}, os={os_info}"
        )
    
    @staticmethod
    def log_agent_data_upload(agent_id, endpoint, record_count, size_bytes):
        """Log agent data upload."""
        logger = logging.getLogger('server_api.agents')
        logger.info(
            f"[AGENT {agent_id}] {endpoint}: {record_count} records ({size_bytes} bytes)"
        )
    
    @staticmethod
    def log_agent_error(agent_id, endpoint, error):
        """Log agent-related error."""
        logger = logging.getLogger('server_api.agents')
        logger.error(
            f"[AGENT {agent_id}] {endpoint} ERROR: {error}"
        )
    
    @staticmethod
    def log_agent_status(agent_id, status):
        """Log agent status change."""
        logger = logging.getLogger('server_api.agents')
        logger.info(
            f"[AGENT {agent_id}] Status changed to: {status}"
        )


class SecurityLogger:
    """Logging for security-related events."""
    
    @staticmethod
    def log_auth_failure(identifier, reason):
        """Log authentication failure."""
        logger = logging.getLogger('server_api.security')
        logger.warning(
            f"AUTH_FAILURE: {identifier} - {reason}"
        )
    
    @staticmethod
    def log_rate_limit_exceeded(key, endpoint):
        """Log rate limit exceeded."""
        logger = logging.getLogger('server_api.security')
        logger.warning(
            f"RATE_LIMIT_EXCEEDED: {key} on {endpoint}"
        )
    
    @staticmethod
    def log_suspicious_activity(agent_id, activity):
        """Log suspicious activity."""
        logger = logging.getLogger('server_api.security')
        logger.warning(
            f"SUSPICIOUS_ACTIVITY [AGENT {agent_id}]: {activity}"
        )
    
    @staticmethod
    def log_validation_error(agent_id, endpoint, error):
        """Log validation error."""
        logger = logging.getLogger('server_api.security')
        logger.warning(
            f"VALIDATION_ERROR [AGENT {agent_id}] {endpoint}: {error}"
        )


# Export convenience functions
logger = logging.getLogger(__name__)
info = logger.info
debug = logger.debug
warning = logger.warning
error = logger.error
critical = logger.critical
