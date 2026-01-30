"""
StateDetector Span Generation Methods
Add these methods to the StateDetector class in state_detector.py
"""

# ========================================================================
# SPAN GENERATION (NEW) - Add after _update_state() method
# ========================================================================

def _create_span(self, state: str, start_time: float, end_time: float, duration: float) -> dict:
    """
    Create an immutable span record with clock drift detection.
    
    Args:
        state: 'active', 'idle', or 'locked'
        start_time: Unix timestamp (float)
        end_time: Unix timestamp (float)
        duration: Measured duration in seconds
    
    Returns:
        Span dict or None if invalid
    """
    try:
        from datetime import datetime, timezone
        
        # Detect suspicious clock jumps
        calculated_duration = end_time - start_time
        drift = abs(calculated_duration - duration)
        
        if drift > 5.0:  # More than 5 second drift
            logger.warning(
                f"[SPAN] Clock drift detected: {drift:.1f}s "
                f"(calculated={calculated_duration:.1f}s, measured={duration:.1f}s)"
            )
            # Use the more conservative value
            duration = min(calculated_duration, duration)
        
        # Validate duration range
        if duration < 1.0:
            logger.debug(f"[SPAN] Skipping span < 1s: {duration:.1f}s")
            return None
        if duration > 86400:  # 24 hours
            logger.warning(f"[SPAN] Capping span > 24h: {duration:.1f}s")
            duration = 86400
        
        start_dt = datetime.fromtimestamp(start_time, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_time, tz=timezone.utc)
        
        # Idempotency key: deterministic, collision-free
        span_id = f"{self.agent_id}-{state}-{int(start_time * 1000)}"
        
        return {
            'span_id': span_id,
            'state': state,
            'start_time': start_dt.isoformat(),
            'end_time': end_dt.isoformat(),
            'duration_seconds': int(duration),
            'created_at': datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"[SPAN] Failed to create span: {e}")
        return None

def get_pending_spans(self) -> list:
    """Return and clear pending spans (called by Collector)."""
    spans = self.pending_spans.copy()
    self.pending_spans.clear()
    if spans:
        logger.debug(f"[SPAN] Collected {len(spans)} spans")
    return spans

# ========================================================================
# CRASH RECOVERY (NEW) - Add after get_pending_spans()
# ========================================================================

def _load_persisted_state(self):
    """Recover in-progress session on startup."""
    try:
        import json
        
        if not self.state_file.exists():
            return
        
        with open(self.state_file) as f:
            data = json.load(f)
        
        if 'current_state' in data and 'session_start' in data:
            prev_state = data['current_state']
            session_start = float(data['session_start'])
            now = time.time()
            
            duration = now - session_start
            if duration > 60:  # Only if > 1 minute
                # Create span for the interrupted session
                # Use 5% safety margin to be conservative
                span = self._create_span(
                    state=prev_state,
                    start_time=session_start,
                    end_time=now,
                    duration=duration * 0.95
                )
                if span:
                    self.pending_spans.append(span)
                    logger.info(f"[RECOVERY] Recovered {prev_state} session: {duration:.1f}s")
    except Exception as e:
        logger.error(f"[RECOVERY] Failed to load state: {e}")

def _persist_current_state(self):
    """Save current session for crash recovery."""
    try:
        import json
        
        data = {
            'current_state': self.current_state,
            'session_start': self._last_state_change_time,
            'timestamp': time.time()
        }
        
        with open(self.state_file, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"[STATE] Failed to persist state: {e}")


# ========================================================================
# CHANGES TO __init__() - Add these lines
# ========================================================================

"""
In StateDetector.__init__(), add these parameters and initialization:

def __init__(self, 
             idle_threshold_seconds: int = 120,
             on_state_change: Optional[Callable] = None,
             agent_id: str = None,              # NEW
             data_dir: str = None):             # NEW
    ...
    self.agent_id = agent_id or "unknown"      # NEW
    ...
    # NEW: Span generation
    self.pending_spans = []
    
    # NEW: Crash recovery
    import os
    from pathlib import Path
    if data_dir:
        self.state_file = Path(data_dir) / 'current_state.json'
    else:
        self.state_file = Path(os.path.expanduser('~')) / '.sentineledge' / 'current_state.json'
    self.state_file.parent.mkdir(parents=True, exist_ok=True)
    ...
    # At end of __init__, add:
    self._load_persisted_state()
"""
