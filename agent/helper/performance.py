"""
Agent Performance Optimization Module
======================================
Provides performance utilities for the SentinelEdge agent:
- Optimized data batching
- Throttled logging
- Memory-efficient caching
- CPU usage reduction during idle states
"""
import time
import logging
from functools import wraps
from collections import deque
from threading import Lock
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# THROTTLED LOGGING
# =============================================================================

class ThrottledLogger:
    """
    Prevents log spam by throttling repeated messages.
    Same message won't be logged more than once per interval.
    """
    
    def __init__(self, interval_seconds: float = 60.0):
        self._interval = interval_seconds
        self._last_log: Dict[str, float] = {}
        self._lock = Lock()
        self._suppressed_counts: Dict[str, int] = {}
    
    def should_log(self, key: str) -> bool:
        """Check if this key should be logged now"""
        with self._lock:
            now = time.time()
            if key not in self._last_log:
                self._last_log[key] = now
                self._suppressed_counts[key] = 0
                return True
            
            if now - self._last_log[key] >= self._interval:
                suppressed = self._suppressed_counts.get(key, 0)
                self._last_log[key] = now
                self._suppressed_counts[key] = 0
                return True
            
            self._suppressed_counts[key] = self._suppressed_counts.get(key, 0) + 1
            return False
    
    def get_suppressed_count(self, key: str) -> int:
        """Get count of suppressed logs for a key"""
        return self._suppressed_counts.get(key, 0)


# Global throttled logger instance
_throttled_logger = ThrottledLogger(interval_seconds=60)

def log_throttled(level: int, message: str, key: str = None):
    """Log a message with throttling to prevent spam"""
    key = key or message
    if _throttled_logger.should_log(key):
        suppressed = _throttled_logger.get_suppressed_count(key)
        if suppressed > 0:
            message = f"{message} (suppressed {suppressed} similar)"
        logger.log(level, message)


# =============================================================================
# TIMING DECORATOR
# =============================================================================

def timed(threshold_ms: float = 100):
    """
    Decorator to log slow function calls.
    
    Only logs if execution time exceeds threshold.
    
    Usage:
        @timed(threshold_ms=50)
        def slow_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                if elapsed_ms > threshold_ms:
                    log_throttled(
                        logging.WARNING,
                        f"[SLOW] {func.__name__} took {elapsed_ms:.1f}ms (threshold: {threshold_ms}ms)",
                        key=f"slow_{func.__name__}"
                    )
        return wrapper
    return decorator


# =============================================================================
# BATCH ACCUMULATOR
# =============================================================================

class BatchAccumulator:
    """
    Accumulates items and yields batches for efficient processing.
    
    Features:
    - Max batch size limit
    - Time-based flushing
    - Memory limit protection
    """
    
    def __init__(self, max_size: int = 100, max_age_seconds: float = 30.0, max_memory_bytes: int = 1_000_000):
        self._items: deque = deque(maxlen=max_size * 2)  # Safety buffer
        self._max_size = max_size
        self._max_age = max_age_seconds
        self._max_memory = max_memory_bytes
        self._first_item_time: Optional[float] = None
        self._lock = Lock()
        self._approximate_size = 0
    
    def add(self, item: Any) -> bool:
        """
        Add item to batch.
        Returns True if batch is ready to flush.
        """
        with self._lock:
            if self._first_item_time is None:
                self._first_item_time = time.time()
            
            self._items.append(item)
            
            # Rough size estimate
            try:
                import sys
                self._approximate_size += sys.getsizeof(item)
            except:
                self._approximate_size += 100  # Fallback estimate
            
            return self._should_flush()
    
    def _should_flush(self) -> bool:
        """Check if batch should be flushed"""
        # Size limit
        if len(self._items) >= self._max_size:
            return True
        
        # Memory limit
        if self._approximate_size >= self._max_memory:
            return True
        
        # Age limit
        if self._first_item_time and (time.time() - self._first_item_time) >= self._max_age:
            return True
        
        return False
    
    def should_flush(self) -> bool:
        """Public check if batch is ready"""
        with self._lock:
            return self._should_flush()
    
    def flush(self) -> list:
        """Get all items and reset batch"""
        with self._lock:
            items = list(self._items)
            self._items.clear()
            self._first_item_time = None
            self._approximate_size = 0
            return items
    
    @property
    def count(self) -> int:
        """Number of items in batch"""
        return len(self._items)


# =============================================================================
# ADAPTIVE SLEEP
# =============================================================================

class AdaptiveSleep:
    """
    Adaptive sleep that adjusts based on system state.
    
    - Active: Short sleeps for responsive data collection
    - Idle: Medium sleeps to reduce CPU
    - Locked: Long sleeps (minimal activity needed)
    """
    
    # State -> (min_sleep, max_sleep) in seconds
    PROFILES = {
        'active': (0.5, 2.0),
        'idle': (2.0, 10.0),
        'locked': (5.0, 60.0),
    }
    
    def __init__(self):
        self._current_state = 'active'
        self._last_sleep = 1.0
    
    def set_state(self, state: str):
        """Set current system state"""
        if state in self.PROFILES:
            self._current_state = state
    
    def get_sleep_duration(self, base_interval: float = 1.0) -> float:
        """Get recommended sleep duration based on state"""
        min_sleep, max_sleep = self.PROFILES.get(self._current_state, (1.0, 5.0))
        
        # Clamp to profile range
        duration = max(min_sleep, min(base_interval, max_sleep))
        self._last_sleep = duration
        return duration
    
    def sleep(self, base_interval: float = 1.0):
        """Sleep for adaptive duration"""
        duration = self.get_sleep_duration(base_interval)
        time.sleep(duration)


# =============================================================================
# STATISTICS TRACKER
# =============================================================================

class StatsTracker:
    """
    Track performance statistics for monitoring.
    """
    
    def __init__(self, max_samples: int = 1000):
        self._samples: Dict[str, deque] = {}
        self._max_samples = max_samples
        self._lock = Lock()
    
    def record(self, metric: str, value: float):
        """Record a metric value"""
        with self._lock:
            if metric not in self._samples:
                self._samples[metric] = deque(maxlen=self._max_samples)
            self._samples[metric].append((time.time(), value))
    
    def get_stats(self, metric: str) -> Dict[str, float]:
        """Get statistics for a metric"""
        with self._lock:
            if metric not in self._samples or not self._samples[metric]:
                return {'count': 0}
            
            values = [v for _, v in self._samples[metric]]
            return {
                'count': len(values),
                'min': min(values),
                'max': max(values),
                'avg': sum(values) / len(values),
                'last': values[-1] if values else 0
            }
    
    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Get statistics for all metrics"""
        with self._lock:
            return {metric: self.get_stats(metric) for metric in self._samples}


# Global stats tracker
stats = StatsTracker()


# =============================================================================
# MEMORY MONITOR
# =============================================================================

def get_memory_usage_mb() -> float:
    """Get current process memory usage in MB"""
    try:
        import os
        # Windows
        if hasattr(os, 'memory_info'):
            return os.memory_info().rss / (1024 * 1024)
        
        # Try psutil if available
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            pass
        
        # Linux fallback
        try:
            with open('/proc/self/statm', 'r') as f:
                return int(f.read().split()[1]) * 4096 / (1024 * 1024)
        except:
            pass
        
    except Exception as e:
        logger.debug(f"Could not get memory usage: {e}")
    
    return 0.0


def log_memory_if_high(threshold_mb: float = 100):
    """Log warning if memory usage exceeds threshold"""
    usage = get_memory_usage_mb()
    if usage > threshold_mb:
        log_throttled(
            logging.WARNING,
            f"[MEMORY] High memory usage: {usage:.1f} MB (threshold: {threshold_mb} MB)",
            key="high_memory"
        )
    stats.record('memory_mb', usage)


# =============================================================================
# INITIALIZATION
# =============================================================================

def init_performance_monitoring():
    """Initialize performance monitoring for agent"""
    logger.info("[PERF] Agent performance monitoring initialized")
    
    # Record baseline memory
    log_memory_if_high(threshold_mb=150)
    
    return {
        'throttled_logger': _throttled_logger,
        'stats': stats,
    }
