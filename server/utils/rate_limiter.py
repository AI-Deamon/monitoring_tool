"""
Rate limiting for API endpoints to prevent abuse and ensure fair resource usage.
"""
from functools import wraps
from flask import request, jsonify, g
from datetime import datetime, timedelta
import logging
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter for API endpoints."""
    
    def __init__(self, requests_per_period=100, period_seconds=60):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_period: Max requests allowed
            period_seconds: Time period in seconds
        """
        self.requests_per_period = requests_per_period
        self.period_seconds = period_seconds
        self.request_history = defaultdict(list)  # {key: [timestamp, timestamp, ...]}
        self.lock = threading.Lock()
        
        # Bug #3 Fix: Auto-cleanup thread to prevent unbounded memory growth
        self._cleanup_running = True
        self._cleanup_thread = threading.Thread(
            target=self._auto_cleanup_loop, 
            daemon=True,
            name="RateLimiterCleanup"
        )
        self._cleanup_thread.start()
    
    def _auto_cleanup_loop(self):
        """Background cleanup thread that runs periodically."""
        import time
        while self._cleanup_running:
            try:
                time.sleep(3600)  # Run every hour
                if self._cleanup_running:  # Check again after sleep
                    self.cleanup_old_entries()
            except Exception as e:
                logger.error(f"Rate limiter cleanup error: {e}")
    
    def is_allowed(self, key):
        """
        Check if request is allowed for the given key.
        
        Args:
            key: Unique identifier (agent_id, IP, etc.)
        
        Returns:
            (allowed: bool, remaining_requests: int, reset_time: datetime)
        """
        with self.lock:
            now = datetime.utcnow()
            cutoff_time = now - timedelta(seconds=self.period_seconds)
            
            # Clean old requests
            if key in self.request_history:
                self.request_history[key] = [
                    ts for ts in self.request_history[key]
                    if ts > cutoff_time
                ]
            
            current_count = len(self.request_history[key])
            
            if current_count < self.requests_per_period:
                # Request allowed
                self.request_history[key].append(now)
                remaining = self.requests_per_period - current_count - 1
                reset_time = cutoff_time + timedelta(seconds=self.period_seconds)
                return True, remaining, reset_time
            else:
                # Request denied
                oldest_request = min(self.request_history[key])
                reset_time = oldest_request + timedelta(seconds=self.period_seconds)
                return False, 0, reset_time
    
    def cleanup_old_entries(self, max_keys=10000):
        """Remove old entries to prevent unbounded memory growth."""
        with self.lock:
            if len(self.request_history) > max_keys:
                now = datetime.utcnow()
                cutoff_time = now - timedelta(seconds=self.period_seconds * 2)
                
                keys_to_delete = []
                for key, timestamps in self.request_history.items():
                    active_timestamps = [ts for ts in timestamps if ts > cutoff_time]
                    if not active_timestamps:
                        keys_to_delete.append(key)
                
                for key in keys_to_delete:
                    del self.request_history[key]
                
                if keys_to_delete:
                    logger.debug(f"Cleaned up {len(keys_to_delete)} rate limit entries")


# Global rate limiter instances
api_limiter = RateLimiter(requests_per_period=100, period_seconds=60)
agent_limiter = RateLimiter(requests_per_period=500, period_seconds=60)  # Higher for agents


def rate_limit(limiter=None, key_func=None):
    """
    Rate limiting decorator for Flask routes.
    
    Args:
        limiter: RateLimiter instance (defaults to api_limiter)
        key_func: Function to extract rate limit key from request
    
    Usage:
        @app.route('/endpoint')
        @rate_limit(key_func=lambda: request.remote_addr)
        def endpoint():
            return jsonify({'status': 'ok'})
    """
    if limiter is None:
        limiter = api_limiter
    
    if key_func is None:
        key_func = lambda: request.remote_addr
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                key = key_func()
                allowed, remaining, reset_time = limiter.is_allowed(key)
                
                if not allowed:
                    logger.warning(f"Rate limit exceeded for {key}")
                    return jsonify({
                        'status': 'error',
                        'message': 'Rate limit exceeded',
                        'retry_after': int((reset_time - datetime.utcnow()).total_seconds())
                    }), 429
                
                # Store rate limit info in g for logging
                g.rate_limit_remaining = remaining
                
            except Exception as e:
                logger.error(f"Rate limiter error: {e}")
                # Continue anyway - don't block on rate limit errors
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


def rate_limit_by_agent(limiter=None):
    """
    Rate limiting decorator that uses agent_id as the key.
    
    Usage:
        @app.route('/api/endpoint')
        @require_auth
        @rate_limit_by_agent()
        def endpoint():
            return jsonify({'status': 'ok'})
    """
    if limiter is None:
        limiter = agent_limiter
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                from flask import g
                agent_id = getattr(g, 'current_agent_id', 'unknown')
                
                allowed, remaining, reset_time = limiter.is_allowed(agent_id)
                
                if not allowed:
                    logger.warning(f"Agent rate limit exceeded: {agent_id}")
                    return jsonify({
                        'status': 'error',
                        'message': 'Agent rate limit exceeded',
                        'retry_after': int((reset_time - datetime.utcnow()).total_seconds())
                    }), 429
                
                g.rate_limit_remaining = remaining
                
            except Exception as e:
                logger.error(f"Agent rate limiter error: {e}")
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


def cleanup_rate_limiters():
    """Clean up rate limiter memory periodically."""
    try:
        api_limiter.cleanup_old_entries()
        agent_limiter.cleanup_old_entries()
    except Exception as e:
        logger.error(f"Rate limiter cleanup error: {e}")
