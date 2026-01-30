"""
Server Performance Middleware - PERF-002
=========================================
Provides response compression, caching headers, and query caching.
"""
import time
import hashlib
import logging
from functools import wraps
from flask import request, g
import gzip

logger = logging.getLogger(__name__)

# =============================================================================
# SIMPLE IN-MEMORY CACHE
# =============================================================================

class QueryCache:
    """
    Simple in-memory cache for expensive database queries.
    Caches results for a configurable TTL (time-to-live).
    """
    
    def __init__(self, default_ttl: int = 30):
        self._cache = {}  # key -> (value, expiry_time)
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0
        self._max_size = 1000  # Maximum cache entries
    
    def get(self, key: str):
        """Get cached value if exists and not expired"""
        if key in self._cache:
            value, expiry = self._cache[key]
            if time.time() < expiry:
                self._hits += 1
                return value
            else:
                # Expired - delete
                del self._cache[key]
        
        self._misses += 1
        return None
    
    def set(self, key: str, value, ttl: int = None):
        """Set cache value with TTL in seconds"""
        if ttl is None:
            ttl = self._default_ttl
        
        # Evict old entries if cache is full
        if len(self._cache) >= self._max_size:
            self._evict_oldest()
        
        self._cache[key] = (value, time.time() + ttl)
    
    def invalidate(self, pattern: str = None):
        """Invalidate cache entries matching pattern (or all if None)"""
        if pattern is None:
            self._cache.clear()
        else:
            keys_to_delete = [k for k in self._cache if pattern in k]
            for k in keys_to_delete:
                del self._cache[k]
    
    def _evict_oldest(self):
        """Remove 10% oldest entries"""
        entries = sorted(self._cache.items(), key=lambda x: x[1][1])
        evict_count = max(1, len(entries) // 10)
        for key, _ in entries[:evict_count]:
            del self._cache[key]
    
    def get_stats(self):
        """Get cache statistics"""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            'entries': len(self._cache),
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': f'{hit_rate:.1f}%'
        }


# Global cache instance
query_cache = QueryCache(default_ttl=30)


def cached(ttl: int = 30, key_prefix: str = ''):
    """
    Decorator to cache function results.
    
    Usage:
        @cached(ttl=60, key_prefix='overview')
        def get_overview():
            return expensive_query()
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Build cache key from function name + args
            key_data = f"{key_prefix}:{f.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            cache_key = hashlib.md5(key_data.encode()).hexdigest()
            
            # Check cache
            cached_value = query_cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute and cache
            result = f(*args, **kwargs)
            query_cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


# =============================================================================
# RESPONSE COMPRESSION
# =============================================================================

def compress_response(response):
    """Compress response if client accepts gzip and response is large enough"""
    # Check if client accepts gzip
    accept_encoding = request.headers.get('Accept-Encoding', '')
    if 'gzip' not in accept_encoding:
        return response
    
    # Skip responses in direct passthrough mode (streaming, etc.)
    if response.direct_passthrough:
        return response
    
    # Don't compress small responses (< 500 bytes)
    if response.content_length and response.content_length < 500:
        return response
    
    # Don't compress already compressed content
    if response.headers.get('Content-Encoding'):
        return response
    
    # Only compress text-based content types
    content_type = response.content_type or ''
    if not any(ct in content_type for ct in ['json', 'html', 'text', 'javascript', 'css']):
        return response
    
    try:
        # Get response data
        data = response.get_data()
        if len(data) < 500:
            return response
        
        # Compress
        compressed = gzip.compress(data, compresslevel=6)
        
        # Only use compressed version if it's smaller
        if len(compressed) < len(data) * 0.9:
            response.set_data(compressed)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = len(compressed)
            response.headers['Vary'] = 'Accept-Encoding'
    except Exception as e:
        # Only log at debug level since this can happen with streaming responses
        logger.debug(f"Compression skipped: {e}")
    
    return response


# =============================================================================
# CACHING HEADERS
# =============================================================================

def add_cache_headers(response, max_age: int = 0, private: bool = True):
    """Add appropriate cache headers to response"""
    if max_age > 0:
        cache_type = 'private' if private else 'public'
        response.headers['Cache-Control'] = f'{cache_type}, max-age={max_age}'
    else:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    
    return response


# =============================================================================
# REQUEST TIMING
# =============================================================================

def add_timing_header(response):
    """Add server timing header for debugging"""
    if hasattr(g, 'request_start_time'):
        elapsed = (time.time() - g.request_start_time) * 1000  # ms
        response.headers['X-Response-Time'] = f'{elapsed:.2f}ms'
    
    return response


# =============================================================================
# PERFORMANCE MIDDLEWARE SETUP
# =============================================================================

def init_performance_middleware(app):
    """
    Initialize performance middleware for Flask app.
    
    Call this in create_app():
        from performance import init_performance_middleware
        init_performance_middleware(app)
    """
    
    @app.before_request
    def before_request():
        g.request_start_time = time.time()
    
    @app.after_request
    def after_request(response):
        # Add timing header
        response = add_timing_header(response)
        
        # Compress if appropriate
        response = compress_response(response)
        
        # Add cache headers for static assets
        if request.path.startswith('/dashboard/static/'):
            response = add_cache_headers(response, max_age=3600, private=False)
        elif request.path.startswith('/api/'):
            # API responses - no cache by default
            response = add_cache_headers(response, max_age=0)
        
        return response
    
    logger.info("[PERF] Performance middleware initialized")


# =============================================================================
# SLOW QUERY LOGGING
# =============================================================================

def log_slow_query(query_name: str, duration: float, threshold: float = 0.5):
    """Log queries that take longer than threshold (seconds)"""
    if duration > threshold:
        logger.warning(f"[SLOW_QUERY] {query_name}: {duration:.3f}s (threshold: {threshold}s)")


# =============================================================================
# BATCH QUERY OPTIMIZATION
# =============================================================================

def batch_query(ids: list, query_func, batch_size: int = 100):
    """
    Execute queries in batches to avoid memory issues with large datasets.
    
    Usage:
        results = batch_query(
            agent_ids,
            lambda batch: Agent.query.filter(Agent.id.in_(batch)).all(),
            batch_size=100
        )
    """
    results = []
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        batch_results = query_func(batch)
        results.extend(batch_results)
    return results


# =============================================================================
# CACHE STATS ENDPOINT
# =============================================================================

def register_cache_stats_endpoint(app):
    """Register endpoint to view cache statistics"""
    
    @app.route('/api/cache/stats', methods=['GET'])
    def cache_stats():
        return {
            'query_cache': query_cache.get_stats()
        }, 200
    
    @app.route('/api/cache/clear', methods=['POST'])
    def cache_clear():
        query_cache.invalidate()
        return {'status': 'cleared'}, 200
