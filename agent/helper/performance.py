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
# CPU THROTTLER - Prevents agent from consuming excessive CPU
# =============================================================================

class CPUThrottler:
    """
    Monitors and throttles CPU usage to prevent impacting user experience.
    
    Best Practice: Monitoring agents should use < 5% CPU during active collection
    and < 1% during idle periods.
    """
    
    # Default limits
    DEFAULT_MAX_CPU_ACTIVE = 5.0    # Max 5% when user is active
    DEFAULT_MAX_CPU_IDLE = 2.0      # Max 2% when user is idle
    DEFAULT_MAX_CPU_LOCKED = 1.0    # Max 1% when screen is locked
    
    def __init__(self, max_cpu_percent: float = 5.0):
        self.max_cpu = max_cpu_percent
        self.current_limit = max_cpu_percent
        self._process = None
        self._throttle_count = 0
        self._last_check = 0
        self.logger = logging.getLogger('CPUThrottler')
        
        # Initialize process handle
        try:
            import psutil
            self._process = psutil.Process()
            # Initial CPU measurement (needs warm-up)
            self._process.cpu_percent(interval=None)
        except ImportError:
            self.logger.warning("[CPU] psutil not available, throttling disabled")
        except Exception as e:
            self.logger.error(f"[CPU] Failed to initialize: {e}")
    
    def set_state(self, state: str):
        """Adjust CPU limit based on system state"""
        if state == 'active':
            self.current_limit = self.DEFAULT_MAX_CPU_ACTIVE
        elif state == 'idle':
            self.current_limit = self.DEFAULT_MAX_CPU_IDLE
        elif state == 'locked':
            self.current_limit = self.DEFAULT_MAX_CPU_LOCKED
    
    def get_cpu_percent(self) -> float:
        """Get current CPU usage percentage"""
        if not self._process:
            return 0.0
        
        try:
            # Non-blocking call (uses cached value)
            return self._process.cpu_percent(interval=None)
        except Exception:
            return 0.0
    
    def throttle_if_needed(self) -> bool:
        """
        Check CPU usage and sleep if exceeding limit.
        
        Returns:
            bool: True if throttling was applied
        """
        if not self._process:
            return False
        
        try:
            # Don't check too frequently
            now = time.time()
            if now - self._last_check < 0.5:
                return False
            self._last_check = now
            
            cpu = self.get_cpu_percent()
            stats.record('cpu_percent', cpu)
            
            if cpu > self.current_limit:
                self._throttle_count += 1
                
                # Log only occasionally to prevent spam
                if self._throttle_count % 10 == 1:
                    log_throttled(
                        logging.WARNING,
                        f"[CPU] Usage {cpu:.1f}% exceeds limit {self.current_limit}%, throttling",
                        key="cpu_throttle"
                    )
                
                # Back off - sleep proportional to how much over limit
                excess = cpu - self.current_limit
                sleep_time = min(0.5 + (excess * 0.1), 2.0)  # 0.5s to 2s
                time.sleep(sleep_time)
                return True
            
            return False
            
        except Exception as e:
            self.logger.debug(f"CPU check error: {e}")
            return False
    
    def get_stats(self) -> dict:
        """Get throttling statistics"""
        return {
            'current_limit': self.current_limit,
            'throttle_count': self._throttle_count,
            'current_cpu': self.get_cpu_percent()
        }


# Global CPU throttler instance
_cpu_throttler = None

def get_cpu_throttler() -> CPUThrottler:
    """Get singleton CPU throttler instance"""
    global _cpu_throttler
    if _cpu_throttler is None:
        _cpu_throttler = CPUThrottler()
    return _cpu_throttler


# =============================================================================
# MEMORY LIMIT ENFORCER - Prevents runaway memory consumption
# =============================================================================

class MemoryLimitEnforcer:
    """
    Monitors memory usage and takes action when limits are exceeded.
    
    Actions:
    - 'warn': Log critical warning only
    - 'gc': Force garbage collection
    - 'restart': Request graceful restart (raises exception)
    """
    
    DEFAULT_SOFT_LIMIT_MB = 100   # Warning threshold
    DEFAULT_HARD_LIMIT_MB = 150   # Action threshold
    
    def __init__(self, soft_limit_mb: float = 100, hard_limit_mb: float = 150, action: str = 'gc'):
        self.soft_limit = soft_limit_mb
        self.hard_limit = hard_limit_mb
        self.action = action  # 'warn', 'gc', 'restart'
        self.logger = logging.getLogger('MemoryLimit')
        self._exceeded_count = 0
        self._gc_count = 0
    
    def check_and_enforce(self) -> dict:
        """
        Check memory and enforce limits.
        
        Returns:
            dict: Status with 'exceeded', 'usage_mb', 'action_taken'
        """
        usage = get_memory_usage_mb()
        result = {
            'exceeded': False,
            'usage_mb': usage,
            'action_taken': None
        }
        
        # Check soft limit (warning)
        if usage > self.soft_limit:
            log_throttled(
                logging.WARNING,
                f"[MEMORY] Usage {usage:.1f}MB exceeds soft limit {self.soft_limit}MB",
                key="memory_soft"
            )
        
        # Check hard limit (action)
        if usage > self.hard_limit:
            self._exceeded_count += 1
            result['exceeded'] = True
            
            if self.action == 'warn':
                self.logger.critical(
                    f"[MEMORY] CRITICAL: {usage:.1f}MB exceeds hard limit {self.hard_limit}MB"
                )
                result['action_taken'] = 'warn'
                
            elif self.action == 'gc':
                # Force garbage collection
                self.logger.warning(
                    f"[MEMORY] {usage:.1f}MB exceeds limit, forcing garbage collection"
                )
                self._force_gc()
                self._gc_count += 1
                result['action_taken'] = 'gc'
                
                # Check if GC helped
                new_usage = get_memory_usage_mb()
                result['post_gc_usage_mb'] = new_usage
                
                if new_usage > self.hard_limit:
                    self.logger.critical(
                        f"[MEMORY] Still at {new_usage:.1f}MB after GC, consider restart"
                    )
                    
            elif self.action == 'restart':
                self.logger.critical(
                    f"[MEMORY] {usage:.1f}MB exceeds limit, requesting restart"
                )
                result['action_taken'] = 'restart'
                # Raise exception to trigger restart
                raise MemoryError(f"Memory limit exceeded: {usage:.1f}MB > {self.hard_limit}MB")
        
        return result
    
    def _force_gc(self):
        """Force garbage collection"""
        import gc
        gc.collect()
        gc.collect()  # Run twice for thorough cleanup
    
    def get_stats(self) -> dict:
        """Get memory limit statistics"""
        return {
            'soft_limit_mb': self.soft_limit,
            'hard_limit_mb': self.hard_limit,
            'exceeded_count': self._exceeded_count,
            'gc_count': self._gc_count,
            'current_usage_mb': get_memory_usage_mb()
        }


# Global memory enforcer instance
_memory_enforcer = None

def get_memory_enforcer() -> MemoryLimitEnforcer:
    """Get singleton memory enforcer instance"""
    global _memory_enforcer
    if _memory_enforcer is None:
        _memory_enforcer = MemoryLimitEnforcer(action='gc')
    return _memory_enforcer


# =============================================================================
# INITIALIZATION
# =============================================================================

def init_performance_monitoring():
    """Initialize performance monitoring for agent"""
    logger.info("[PERF] Agent performance monitoring initialized")
    
    # Initialize CPU throttler
    cpu = get_cpu_throttler()
    
    # Initialize memory enforcer
    memory = get_memory_enforcer()
    
    # Record baseline
    log_memory_if_high(threshold_mb=150)
    
    return {
        'throttled_logger': _throttled_logger,
        'stats': stats,
        'cpu_throttler': cpu,
        'memory_enforcer': memory,
    }

