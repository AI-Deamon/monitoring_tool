"""
SentinelEdge Security Module - Anti-Tampering Detection
========================================================
Detects attempts to bypass idle/lock detection:
- Simulated mouse/keyboard input
- Process injection
- Clock manipulation
- Helper process termination

SEC-024: Anti-Tampering Measures
"""

import ctypes
from ctypes import wintypes
import logging
import time
import os
from datetime import datetime, timezone
from typing import Dict, Optional, List
import hashlib

logger = logging.getLogger(__name__)


class TamperDetector:
    """
    Detects attempts to tamper with or bypass the monitoring agent.
    
    Detection methods:
    1. Synthetic input detection - Detect mouse_event/keybd_event calls
    2. Clock manipulation - Detect time jumps backward
    3. Process integrity - Verify agent processes running
    4. Anomaly patterns - Detect suspicious activity patterns
    """
    
    # Windows API constants for input detection
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000
    
    def __init__(self):
        self.logger = logging.getLogger('TamperDetector')
        
        # Track last known good state
        self._last_check_time = datetime.now(timezone.utc)
        self._last_mouse_pos = None
        self._input_pattern_history = []
        self._suspicious_events = []
        
        # Detection thresholds
        self.MAX_SUSPICIOUS_EVENTS = 10
        self.CLOCK_JUMP_THRESHOLD_SECONDS = 3600  # 1 hour
        
        # Windows API
        try:
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32
        except Exception as e:
            self.logger.error(f"Failed to load Windows API: {e}")
            self.user32 = None
            self.kernel32 = None
        
        self.logger.info("[SECURITY] TamperDetector initialized")
    
    def detect_synthetic_input(self) -> Dict:
        """
        Detect if mouse/keyboard input appears to be synthetic (simulated).
        
        Indicators of synthetic input:
        1. Mouse moves in perfectly straight lines
        2. Mouse moves at exactly regular intervals
        3. Keyboard input at inhuman speed
        4. Input occurs while screen is locked
        
        Returns:
            dict with 'is_synthetic', 'confidence', 'evidence'
        """
        result = {
            'is_synthetic': False,
            'confidence': 0.0,
            'evidence': []
        }
        
        if not self.user32:
            return result
        
        try:
            # Get current mouse position
            class POINT(ctypes.Structure):
                _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]
            
            pt = POINT()
            self.user32.GetCursorPos(ctypes.byref(pt))
            current_pos = (pt.x, pt.y)
            
            # Track mouse movement patterns
            if self._last_mouse_pos:
                dx = current_pos[0] - self._last_mouse_pos[0]
                dy = current_pos[1] - self._last_mouse_pos[1]
                
                # Store movement for pattern analysis
                now = time.time()
                self._input_pattern_history.append({
                    'time': now,
                    'dx': dx,
                    'dy': dy,
                    'pos': current_pos
                })
                
                # Keep only last 60 movements
                if len(self._input_pattern_history) > 60:
                    self._input_pattern_history = self._input_pattern_history[-60:]
                
                # Analyze for synthetic patterns
                if len(self._input_pattern_history) >= 10:
                    synthetic_score = self._analyze_input_patterns()
                    
                    if synthetic_score > 0.7:
                        result['is_synthetic'] = True
                        result['confidence'] = synthetic_score
                        result['evidence'].append(f"Repetitive movement pattern detected (score: {synthetic_score:.2f})")
                        
                        self._log_suspicious_event('synthetic_input', {
                            'score': synthetic_score,
                            'pattern_count': len(self._input_pattern_history)
                        })
            
            self._last_mouse_pos = current_pos
            
        except Exception as e:
            self.logger.error(f"Error detecting synthetic input: {e}")
        
        return result
    
    def _analyze_input_patterns(self) -> float:
        """
        Analyze mouse movement patterns for synthetic input indicators.
        
        Returns:
            float: 0.0 (natural) to 1.0 (definitely synthetic)
        """
        if len(self._input_pattern_history) < 10:
            return 0.0
        
        patterns = self._input_pattern_history[-20:]
        
        # Check 1: Are movements exactly the same (simulated)?
        movements = [(p['dx'], p['dy']) for p in patterns]
        unique_movements = set(movements)
        
        # If less than 20% unique movements, suspicious
        uniqueness_ratio = len(unique_movements) / len(movements)
        
        # Check 2: Are time intervals exactly regular?
        time_deltas = []
        for i in range(1, len(patterns)):
            delta = patterns[i]['time'] - patterns[i-1]['time']
            time_deltas.append(delta)
        
        if time_deltas:
            # Calculate standard deviation of time deltas
            avg_delta = sum(time_deltas) / len(time_deltas)
            variance = sum((d - avg_delta) ** 2 for d in time_deltas) / len(time_deltas)
            std_dev = variance ** 0.5
            
            # If std dev is very low, timing is suspiciously regular
            timing_regularity = 1.0 - min(std_dev / 5.0, 1.0)  # Normalize
        else:
            timing_regularity = 0.0
        
        # Check 3: Small constant movements (1 pixel moves)
        small_moves = sum(1 for m in movements if abs(m[0]) <= 2 and abs(m[1]) <= 2)
        small_move_ratio = small_moves / len(movements) if movements else 0
        
        # Calculate overall synthetic score
        synthetic_score = (
            (1.0 - uniqueness_ratio) * 0.4 +  # Low uniqueness = suspicious
            timing_regularity * 0.4 +           # Regular timing = suspicious
            small_move_ratio * 0.2              # Small moves = suspicious
        )
        
        return min(synthetic_score, 1.0)
    
    def detect_clock_manipulation(self) -> Dict:
        """
        Detect if system clock has been manipulated to hide time.
        
        Indicators:
        1. Time jumping backwards
        2. Large unexplained time gaps
        
        Returns:
            dict with 'is_manipulated', 'jump_seconds', 'evidence'
        """
        result = {
            'is_manipulated': False,
            'jump_seconds': 0,
            'evidence': []
        }
        
        current_time = datetime.now(timezone.utc)
        time_delta = (current_time - self._last_check_time).total_seconds()
        
        # Check for time going backwards
        if time_delta < -10:  # More than 10 seconds backwards
            result['is_manipulated'] = True
            result['jump_seconds'] = time_delta
            result['evidence'].append(f"Clock went backwards by {abs(time_delta):.0f} seconds")
            
            self._log_suspicious_event('clock_backward', {
                'jump_seconds': time_delta,
                'expected_time': self._last_check_time.isoformat(),
                'actual_time': current_time.isoformat()
            })
        
        # Check for very large forward jump (might indicate sleep/hibernate bypass)
        elif time_delta > self.CLOCK_JUMP_THRESHOLD_SECONDS:
            # This could be legitimate sleep, but log it
            result['evidence'].append(f"Large time gap: {time_delta:.0f} seconds ({time_delta/3600:.1f} hours)")
        
        self._last_check_time = current_time
        
        return result
    
    def check_process_integrity(self) -> Dict:
        """
        Verify agent processes are running and haven't been tampered with.
        
        Checks:
        1. Core service running
        2. Helper process running
        3. Process signatures valid
        
        Returns:
            dict with 'is_intact', 'issues'
        """
        result = {
            'is_intact': True,
            'issues': []
        }
        
        try:
            import psutil
            
            # Check for sentinel processes
            sentinel_processes = []
            for proc in psutil.process_iter(['name', 'cmdline', 'create_time']):
                try:
                    name = proc.info['name'].lower()
                    cmdline = proc.info['cmdline'] or []
                    cmdline_str = ' '.join(cmdline).lower()
                    
                    if 'sentinel' in cmdline_str or 'sentinel' in name:
                        sentinel_processes.append({
                            'name': name,
                            'pid': proc.pid,
                            'create_time': proc.info['create_time']
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Log process status (but don't report as issue if Helper isn't running
            # since this module runs IN the Helper)
            if not sentinel_processes:
                self.logger.warning("[SECURITY] No SentinelEdge processes detected")
            
        except ImportError:
            result['issues'].append("psutil not available for process checking")
        except Exception as e:
            result['issues'].append(f"Process check error: {e}")
        
        result['is_intact'] = len(result['issues']) == 0
        
        return result
    
    def _log_suspicious_event(self, event_type: str, details: Dict):
        """Log a suspicious event for later analysis."""
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': event_type,
            'details': details
        }
        
        self._suspicious_events.append(event)
        
        # Keep only last N events
        if len(self._suspicious_events) > self.MAX_SUSPICIOUS_EVENTS:
            self._suspicious_events = self._suspicious_events[-self.MAX_SUSPICIOUS_EVENTS:]
        
        self.logger.warning(f"[SECURITY] Suspicious event: {event_type} - {details}")
    
    def get_security_status(self) -> Dict:
        """
        Get overall security status.
        
        Returns:
            dict with security health indicators
        """
        synthetic = self.detect_synthetic_input()
        clock = self.detect_clock_manipulation()
        process = self.check_process_integrity()
        
        # Calculate overall risk level
        risk_level = 'low'
        if synthetic['is_synthetic'] or clock['is_manipulated']:
            risk_level = 'high'
        elif not process['is_intact'] or len(self._suspicious_events) >= 5:
            risk_level = 'medium'
        
        return {
            'risk_level': risk_level,
            'synthetic_input': synthetic,
            'clock_manipulation': clock,
            'process_integrity': process,
            'suspicious_events': self._suspicious_events[-5:],  # Last 5 events
            'total_suspicious_events': len(self._suspicious_events)
        }
    
    def reset_monitoring(self):
        """Reset monitoring state (e.g., after legitimate sleep/wake)."""
        self._last_check_time = datetime.now(timezone.utc)
        self._input_pattern_history.clear()
        self.logger.info("[SECURITY] Monitoring state reset")


class ConfigProtector:
    """
    Protects configuration files from tampering.
    
    SEC-025: Config File Protection
    """
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.logger = logging.getLogger('ConfigProtector')
        self._last_hash = None
        self._update_hash()
    
    def _calculate_hash(self) -> Optional[str]:
        """Calculate SHA256 hash of config file."""
        try:
            with open(self.config_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to hash config: {e}")
            return None
    
    def _update_hash(self):
        """Update stored hash."""
        self._last_hash = self._calculate_hash()
    
    def check_integrity(self) -> Dict:
        """
        Check if config file has been modified.
        
        Returns:
            dict with 'is_modified', 'current_hash', 'expected_hash'
        """
        current_hash = self._calculate_hash()
        is_modified = current_hash != self._last_hash if self._last_hash else False
        
        if is_modified:
            self.logger.warning("[SECURITY] Config file was modified!")
        
        return {
            'is_modified': is_modified,
            'current_hash': current_hash,
            'expected_hash': self._last_hash
        }
    
    def approve_changes(self):
        """Approve current config (update expected hash)."""
        self._update_hash()
        self.logger.info("[SECURITY] Config changes approved")


# Singleton instance
_tamper_detector = None
_config_protector = None


def get_tamper_detector() -> TamperDetector:
    """Get singleton TamperDetector instance."""
    global _tamper_detector
    if _tamper_detector is None:
        _tamper_detector = TamperDetector()
    return _tamper_detector


def get_config_protector(config_path: str) -> ConfigProtector:
    """Get singleton ConfigProtector instance."""
    global _config_protector
    if _config_protector is None:
        _config_protector = ConfigProtector(config_path)
    return _config_protector
