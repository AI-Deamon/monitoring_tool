"""
Screen Time State Machine - Single Source of Truth
===================================================

CRITICAL CONTRACT (2026-02-03):
- Agent calculates screen time ONCE, here
- Server only stores (never calculates)
- Reliability > Accuracy (ignore gaps, don't fabricate)

States: ACTIVE | IDLE | LOCKED | AWAY
- Shutdown is NOT a state (gap ignored)
- Sleep/Hibernate → LOCKED if was locked before sleep, else AWAY
- LOCKED is terminal — sleep cannot override it
- Crash → gap ignored (reliability > accuracy)

This module is the ONLY place that calculates screen time deltas.
All other modules MUST call this, never calculate independently.
"""

import json
import time
import logging
import threading
from enum import Enum
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Standardize day-boundary logic to IST (UTC+05:30).
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _now_ist() -> datetime:
    return datetime.now(IST)


class ScreenState(Enum):
    """Screen time states - exhaustive list"""
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    LOCKED = "LOCKED"
    AWAY = "AWAY"


class LastEvent(Enum):
    """Last event types for gap handling"""
    NORMAL = "normal"      # Regular operation
    SLEEP = "sleep"        # Sleep/Hibernate/Suspend
    SHUTDOWN = "shutdown"  # Power off / shutdown
    CRASH = "crash"        # Agent crash / unexpected stop


class ScreenTimeEngine:
    """
    Single authoritative screen time calculator.
    
    RULES:
    1. All state transitions go through transition()
    2. Only this class updates counters
    3. Server receives get_daily_totals() output
    4. Gaps are handled by handle_startup()
    
    CRITICAL:
    - Sleep gaps → counted as LOCKED (if locked before sleep) or AWAY
    - Shutdown gaps → ignored
    - Crash gaps → ignored (reliability > accuracy)
    - reset_daily() is idempotent — only fires once per calendar day
    """
    
    def __init__(self, data_dir: Path, agent_id: str = "unknown"):
        self.agent_id = agent_id
        self.current_state = ScreenState.ACTIVE
        self.last_timestamp = time.time()
        self.last_event = LastEvent.NORMAL
        
        # RACE-002 FIX: Thread lock for state mutation safety
        self._lock = threading.RLock()
        
        # Daily counters (seconds) - ONLY place these exist
        self.active_seconds = 0.0
        self.idle_seconds = 0.0
        self.locked_seconds = 0.0
        self.away_seconds = 0.0
        
        # Persistence
        self.state_file = data_dir / "screentime_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Current date tracking (for midnight detection)
        self.current_date = _now_ist().date()
        
        # Idempotency guard: only allow one reset per calendar day
        self._last_reset_date = None

        # ✅ NEW: Track pending locked seconds for 2-hour Away rule
        self.pending_locked_seconds = 0.0

        logger.info("[STATE_MACHINE] Screen Time Engine initialized")
        logger.info(f"[STATE_MACHINE] State file: {self.state_file}")
    
    def transition(self, new_state: ScreenState, event_type: LastEvent = LastEvent.NORMAL) -> Dict:
        """
        Transition to new state and update counters.
        
        This is the ONLY method that updates time counters.
        
        Args:
            new_state: Target state
            event_type: Event causing transition (for persistence)
            
        Returns:
            Transition info dict (for logging only)
        """
        with self._lock:
            now = time.time()
            delta = now - self.last_timestamp
            
            # Sanity check: cap delta at 24 hours (clock jump protection)
            if delta > 86400:
                logger.warning(
                    f"[STATE_MACHINE] Suspicious delta: {delta:.1f}s (>24h), "
                    f"capping to 86400s"
                )
                delta = 86400
            elif delta < 0:
                logger.error(
                    f"[STATE_MACHINE] Negative delta: {delta:.1f}s (clock went backward), "
                    f"ignoring"
                )
                delta = 0
            
            # Update counter for PREVIOUS state
            old_state = self.current_state
            
            if old_state == ScreenState.ACTIVE:
                self.active_seconds += delta
            elif old_state == ScreenState.IDLE:
                self.idle_seconds += delta
            elif old_state == ScreenState.LOCKED:
                # Do NOT directly add to locked_seconds
                self.pending_locked_seconds += delta
            elif old_state == ScreenState.AWAY:
                self.away_seconds += delta

            # Handle LOCKED exit inside transition()
            if old_state == ScreenState.LOCKED and new_state != ScreenState.LOCKED:
                AWAY_THRESHOLD = 7200

                if self.pending_locked_seconds >= AWAY_THRESHOLD:
                    self.away_seconds += self.pending_locked_seconds
                    logger.info(
                        f"[STATE_MACHINE] Lock session → AWAY "
                        f"({self.pending_locked_seconds:.1f}s)"
                    )
                else:
                    self.locked_seconds += self.pending_locked_seconds
                    logger.info(
                        f"[STATE_MACHINE] Lock session → LOCKED "
                        f"({self.pending_locked_seconds:.1f}s)"
                    )

                self.pending_locked_seconds = 0.0

            # Transition
            self.current_state = new_state
            self.last_timestamp = now
            self.last_event = event_type

            # ❌ REMOVED: Track lock session start (not needed anymore)
            # if new_state == ScreenState.LOCKED:
            #     self.lock_session_start = now
            #     logger.debug(f"[STATE_MACHINE] Lock session started at {now}")
            # elif old_state == ScreenState.LOCKED:
            #     self.lock_session_start = None
            #     logger.debug("[STATE_MACHINE] Lock session ended/cleared")

            # Persist immediately
            self._persist()
            
            # Log transition
            if old_state != new_state:
                logger.info(
                    f"[STATE_MACHINE] {old_state.value} -> {new_state.value} "
                    f"(+{delta:.1f}s to {old_state.value.lower()}_seconds)"
                )
            
            return {
                "from": old_state.value,
                "to": new_state.value,
                "delta_seconds": delta,
                "event_type": event_type.value
            }
    
    def tick(self):
        """
        Update counter for current state (MANDATORY - prevents time freezing).
        
        CRITICAL: This is the SOLE place that updates time counters between
        state transitions. Must be called before get_daily_totals().
        
        Called every heartbeat (~30s) by state_detector.get_cumulative_totals().
        """
        with self._lock:
            now = time.time()
            delta = now - self.last_timestamp
            
            # Sanity check: cap delta at 24 hours (clock jump protection)
            if delta > 86400:
                logger.warning(
                    f"[STATE_MACHINE] Tick delta too large: {delta:.1f}s (>24h), "
                    f"capping to 86400s"
                )
                delta = 86400
            elif delta < 0:
                logger.error(
                    f"[STATE_MACHINE] Negative tick delta: {delta:.1f}s (clock went backward), "
                    f"ignoring"
                )
                return
            
            # Add to current state's counter (no threshold — tick is sole updater)
            if self.current_state == ScreenState.ACTIVE:
                self.active_seconds += delta
            elif self.current_state == ScreenState.IDLE:
                self.idle_seconds += delta
            elif self.current_state == ScreenState.LOCKED:
                self.pending_locked_seconds += delta

                AWAY_THRESHOLD = 7200  # 2 hours

                if self.pending_locked_seconds >= AWAY_THRESHOLD:
                    # Entire session becomes AWAY
                    self.away_seconds += self.pending_locked_seconds

                    logger.info(
                        f"[STATE_MACHINE] 2h+ lock → AWAY "
                        f"({self.pending_locked_seconds:.1f}s)"
                    )

                    # Reset buffer
                    self.pending_locked_seconds = 0.0

                    # Move to AWAY state
                    self.current_state = ScreenState.AWAY
            elif self.current_state == ScreenState.AWAY:
                self.away_seconds += delta
            
            # Update timestamp
            self.last_timestamp = now
            
            # Persist on every tick (called ~30s, acceptable I/O)
            self._persist()
            
            logger.debug(
                f"[STATE_MACHINE] Tick: +{delta:.1f}s to {self.current_state.value.lower()}_seconds"
            )
    
    def handle_startup(self, persisted_state: Optional[Dict] = None) -> Dict:
        """
        Handle agent startup/restart with gap handling.
        
        CRITICAL GAP HANDLING RULES:
        1. Sleep → count as LOCKED (if locked before sleep) or AWAY
        2. Shutdown → ignore gap
        3. Crash → ignore gap (reliability > accuracy)
        4. Unknown → ignore gap (reliability > accuracy)
        
        Args:
            persisted_state: Previously persisted state (or None for fresh start)
            
        Returns:
            Gap handling decision dict (for logging)
        """
        if not persisted_state:
            logger.info("[STATE_MACHINE] Fresh start (no persisted state)")
            return {"action": "fresh_start", "gap_seconds": 0}
        
        try:
            last_event_str = persisted_state.get("last_event", "normal")
            last_timestamp = persisted_state.get("last_timestamp")
            last_state_str = persisted_state.get("current_state", "ACTIVE")
            
            if not last_timestamp:
                logger.warning("[STATE_MACHINE] No last_timestamp in persisted state")
                return {"action": "no_timestamp", "gap_seconds": 0}
            
            now = time.time()

            # ✅ PHASE 2 FIX: Split gap at midnight boundary (IST).
            # Only count the portion of the gap that belongs to TODAY's totals.
            # This prevents overnight sleep/lock time from carrying over.
            now_ist = _now_ist()
            midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
            midnight_ts = midnight_ist.timestamp()

            # Gap today is the time between (midnight today) and (now),
            # capped by when the gap actually started.
            effective_start = max(last_timestamp, midnight_ts)
            gap = now - effective_start

            # Sanity check: cap gap at 24 hours (cannot be more than today's elapsed time anyway)
            if gap > 86400:
                logger.warning(
                    f"[STATE_MACHINE] Gap today too large: {gap:.1f}s (>24h), capping"
                )
                gap = 86400
            elif gap < 0:
                logger.warning(
                    f"[STATE_MACHINE] Negative gap today: {gap:.1f}s, ignoring"
                )
                gap = 0

            # Parse last event
            try:
                last_event = LastEvent(last_event_str)
            except ValueError:
                logger.warning(f"[STATE_MACHINE] Unknown last_event: {last_event_str}, treating as CRASH")
                last_event = LastEvent.CRASH

            # Best-effort crash/sleep disambiguation.
            if last_event == LastEvent.CRASH and self._was_system_asleep_during_gap(last_timestamp, now):
                logger.info("[STATE_MACHINE] Crash gap inferred as sleep from uptime heuristic")
                last_event = LastEvent.SLEEP
            
            # ✅ CRITICAL: Gap handling logic
            if last_event == LastEvent.SLEEP:
                # Sleep/Hibernate → If agent was locked before sleep, apply 2h rule.
                # Otherwise count gap as AWAY.
                pre_sleep_state = last_state_str.upper()
                if pre_sleep_state == "LOCKED":
                    # FIX #2: Apply the same 2-hour Away rule here as tick() does.
                    # A long lock-before-sleep must become AWAY, not LOCKED.
                    # Read pending from the persisted dict directly so handle_startup()
                    # is self-contained (works even if load_persisted_state() was skipped).
                    pending_before = max(
                        self.pending_locked_seconds,
                        float(persisted_state.get("pending_locked_seconds", 0))
                    )
                    total_lock_time = pending_before + gap
                    AWAY_THRESHOLD = 7200
                    if total_lock_time >= AWAY_THRESHOLD:
                        self.away_seconds += total_lock_time
                        self.pending_locked_seconds = 0.0
                        logger.info(
                            f"[STATE_MACHINE] Sleep gap: {gap:.1f}s + pending {pending_before:.1f}s "
                            f"= {total_lock_time:.1f}s ({total_lock_time/3600:.1f}h) "
                            f"counted as AWAY (was LOCKED, >= 2h threshold)"
                        )
                        return {
                            "action": "counted_as_away",
                            "gap_seconds": gap,
                            "gap_hours": gap / 3600
                        }
                    else:
                        self.locked_seconds += total_lock_time
                        self.pending_locked_seconds = 0.0
                        logger.info(
                            f"[STATE_MACHINE] Sleep gap: {gap:.1f}s + pending {pending_before:.1f}s "
                            f"= {total_lock_time:.1f}s ({total_lock_time/3600:.1f}h) "
                            f"counted as LOCKED (was LOCKED, < 2h threshold)"
                        )
                        return {
                            "action": "counted_as_locked",
                            "gap_seconds": gap,
                            "gap_hours": gap / 3600
                        }
                else:
                    self.away_seconds += gap
                    logger.info(
                        f"[STATE_MACHINE] Sleep gap: {gap:.1f}s ({gap/3600:.1f}h) "
                        f"counted as AWAY (was {pre_sleep_state} before sleep)"
                    )
                    return {
                        "action": "counted_as_away",
                        "gap_seconds": gap,
                        "gap_hours": gap / 3600
                    }
            
            elif last_event == LastEvent.SHUTDOWN:
                # Shutdown → ignore gap
                logger.info(
                    f"[STATE_MACHINE] Shutdown gap: {gap:.1f}s ({gap/3600:.1f}h) "
                    f"IGNORED (not counted)"
                )
                return {
                    "action": "ignored_shutdown_gap",
                    "gap_seconds": gap,
                    "gap_hours": gap / 3600
                }
            
            elif last_event == LastEvent.CRASH:
                # Crash → ignore gap (reliability > accuracy)
                logger.info(
                    f"[STATE_MACHINE] Crash gap: {gap:.1f}s ({gap/3600:.1f}h) "
                    f"IGNORED (reliability > accuracy)"
                )
                return {
                    "action": "ignored_crash_gap",
                    "gap_seconds": gap,
                    "gap_hours": gap / 3600
                }
            
            else:
                # Unknown/Normal → ignore gap (reliability > accuracy)
                logger.warning(
                    f"[STATE_MACHINE] Unknown gap: {gap:.1f}s ({gap/3600:.1f}h) "
                    f"IGNORED (reliability > accuracy)"
                )
                return {
                    "action": "ignored_unknown_gap",
                    "gap_seconds": gap,
                    "gap_hours": gap / 3600
                }
        
        except Exception as e:
            logger.error(f"[STATE_MACHINE] Error handling startup: {e}", exc_info=True)
            return {"action": "error", "error": str(e)}
        finally:
            # ✅ CRITICAL: Reset last_event to NORMAL after startup handling
            # This prevents future restarts from misclassifying gaps
            self.last_event = LastEvent.NORMAL
            self.last_timestamp = time.time()
            self._persist()
            logger.debug("[STATE_MACHINE] Reset last_event to NORMAL after startup")

    def _was_system_asleep_during_gap(self, start_time: float, end_time: float) -> bool:
        """
        Best-effort crash/sleep disambiguation using system boot time.
        Returns True only when heuristic confidence is high.
        """
        try:
            import psutil  # Optional dependency
        except Exception:
            return False

        try:
            boot_time = float(psutil.boot_time())
            start_time = float(start_time)
            end_time = float(end_time)

            # Reboot during the gap means shutdown/crash path, not sleep.
            if boot_time > start_time:
                return False

            expected_delta = end_time - start_time
            uptime_delta = (end_time - boot_time) - (start_time - boot_time)

            # If wall-clock advanced much more than uptime, sleep likely occurred.
            return (expected_delta - uptime_delta) > 60
        except Exception:
            return False

    def get_daily_totals(self) -> Dict:
        """
        Get current daily totals (READ-ONLY).
        
        CRITICAL: tick() MUST be called before this to flush current state time.
        This method only reads persisted counters — no on-the-fly calculation.
        
        Returns:
            Daily totals dict with all counters
        """
        # FIX #3: Include pending_locked_seconds in reported totals.
        # While a lock session is in progress and below the 2h threshold,
        # the time is invisible otherwise (neither in locked_seconds nor away_seconds).
        # If pending >= 2h, it will be classified as AWAY on the next tick — report it as away.
        # If pending < 2h, it's still potentially LOCKED — report it as locked.
        AWAY_THRESHOLD = 7200
        pending = self.pending_locked_seconds
        visible_locked = int(self.locked_seconds + (pending if pending < AWAY_THRESHOLD else 0))
        visible_away = int(self.away_seconds + (pending if pending >= AWAY_THRESHOLD else 0))

        totals = {
            "active_seconds": int(self.active_seconds),
            "idle_seconds": int(self.idle_seconds),
            "locked_seconds": visible_locked,
            "away_seconds": visible_away
        }
        
        # Calculate total
        totals["total_seconds"] = (
            totals["active_seconds"] +
            totals["idle_seconds"] +
            totals["locked_seconds"] +
            totals["away_seconds"]
        )
        
        # Validation
        if totals["total_seconds"] > 86400:
            logger.warning(
                f"[STATE_MACHINE] Total exceeds 24h: {totals['total_seconds']}s "
                f"({totals['total_seconds']/3600:.1f}h)"
            )
        
        return totals
    
    def check_daily_boundary(self) -> bool:
        """
        Check if we crossed midnight (IST).
        
        IMPORTANT: Uses IST time, not UTC.
        - Midnight boundary is 00:00 IST (not UTC)
        - Daily totals align with server/business-day expectations in IST
        
        CRITICAL: At midnight:
        1. Send final totals to server
        2. Reset counters
        3. Keep current state (continuity)
        4. Reset last_timestamp to now
        
        Returns:
            True if boundary crossed, False otherwise
        """
        with self._lock:
            current_date = _now_ist().date()
            
            if current_date != self.current_date:
                logger.info(
                    f"[STATE_MACHINE] Daily boundary crossed: "
                    f"{self.current_date} -> {current_date}"
                )

                # Flush current state time before reading final totals
                self.tick()

                # Get final totals for yesterday (before reset)
                final_totals = self.get_daily_totals()
                logger.info(
                    f"[STATE_MACHINE] Final totals for {self.current_date}: "
                    f"A={final_totals['active_seconds']}s, "
                    f"I={final_totals['idle_seconds']}s, "
                    f"L={final_totals['locked_seconds']}s, "
                    f"W={final_totals['away_seconds']}s, "
                    f"Total={final_totals['total_seconds']}s ({final_totals['total_seconds']/3600:.1f}h)"
                )

                # Reset for new day but keep current state continuity.
                self.reset_daily()
                self.current_date = current_date
                self._persist()
                
                return True
            
            return False
    
    def reset_daily(self):
        """
        Reset counters at midnight (IDEMPOTENT).
        
        CRITICAL:
        - Only fires once per calendar day (_last_reset_date guard)
        - Reset counters to 0
        - Keep current_state (LOCKED/AWAY continuity matters)
        - Reset last_timestamp to now
        """
        with self._lock:
            current_date = _now_ist().date()
            if self._last_reset_date == current_date:
                logger.info(
                    f"[STATE_MACHINE] Daily reset already done for {current_date}, "
                    f"skipping (idempotent guard)"
                )
                return

            self._last_reset_date = current_date

            logger.info(
                f"[STATE_MACHINE] Resetting daily counters "
                f"(keeping state={self.current_state.value})"
            )

            self.active_seconds = 0.0
            self.idle_seconds = 0.0
            self.locked_seconds = 0.0
            self.away_seconds = 0.0
            self.pending_locked_seconds = 0.0  # FIX #4: Reset pending buffer on day boundary
            self.last_timestamp = time.time()

            # Persist immediately
            self._persist()

            logger.info("[STATE_MACHINE] Daily reset complete")

    def _persist(self):
        """
        Persist current state for crash recovery.

        Saved data:
        - current_state
        - last_timestamp
        - last_event (for gap handling)
        - daily counters
        - current_date
        """
        try:
            data = {
                "current_state": self.current_state.value,
                "last_timestamp": self.last_timestamp,
                "last_event": self.last_event.value,
                "active_seconds": self.active_seconds,
                "idle_seconds": self.idle_seconds,
                "locked_seconds": self.locked_seconds,
                "away_seconds": self.away_seconds,
                "pending_locked_seconds": self.pending_locked_seconds,  # FIX #1: Persist buffer
                "current_date": self.current_date.isoformat(),
                "last_reset_date": self._last_reset_date.isoformat()
                if self._last_reset_date
                else None,
                "agent_id": self.agent_id,
                "persisted_at": time.time(),
            }

            # Atomic write
            temp_file = self.state_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.state_file)

        except Exception as e:
            logger.error(f"[STATE_MACHINE] Failed to persist state: {e}")

    def load_persisted_state(self) -> Optional[Dict]:
        """
        Load persisted state from disk.

        Returns:
            Persisted state dict or None if not found
        """
        try:
            if not self.state_file.exists():
                logger.info("[STATE_MACHINE] No persisted state file found")
                return None

            with open(self.state_file, "r") as f:
                data = json.load(f)

            logger.info(
                f"[STATE_MACHINE] Loaded persisted state: "
                f"state={data.get('current_state')}, "
                f"event={data.get('last_event')}, "
                f"date={data.get('current_date')}"
            )
            
            # Restore idempotency guard
            saved_reset_date = data.get("last_reset_date")
            if saved_reset_date:
                try:
                    from datetime import date as date_type
                    self._last_reset_date = date_type.fromisoformat(saved_reset_date)
                    logger.info(f"[STATE_MACHINE] Restored _last_reset_date: {self._last_reset_date}")
                except (ValueError, TypeError):
                    self._last_reset_date = None
            
            # Restore counters if same date
            saved_date = data.get('current_date')
            if saved_date == self.current_date.isoformat():
                self.active_seconds = float(data.get('active_seconds', 0))
                self.idle_seconds = float(data.get('idle_seconds', 0))
                self.locked_seconds = float(data.get('locked_seconds', 0))
                self.away_seconds = float(data.get('away_seconds', 0))
                self.pending_locked_seconds = float(data.get('pending_locked_seconds', 0))  # FIX #1: Restore buffer
                logger.info(
                    f"[STATE_MACHINE] Restored daily counters: "
                    f"A={self.active_seconds:.0f}s, "
                    f"I={self.idle_seconds:.0f}s, "
                    f"L={self.locked_seconds:.0f}s, "
                    f"W={self.away_seconds:.0f}s, "
                    f"pending={self.pending_locked_seconds:.0f}s"
                )
            else:
                logger.info(
                    f"[STATE_MACHINE] Discarding counters from previous day "
                    f"({saved_date}) - starting fresh for {self.current_date.isoformat()}"
                )

            # Restore lock session start
            self.lock_session_start = data.get("lock_session_start")
            if self.lock_session_start:
                logger.info(
                    f"[STATE_MACHINE] Restored lock_session_start: {self.lock_session_start}"
                )

            return data
            
        except Exception as e:
            logger.error(f"[STATE_MACHINE] Failed to load persisted state: {e}")
            return None
    
    def mark_sleep(self):
        """Mark that system is going to sleep (for gap handling)"""
        self.last_event = LastEvent.SLEEP
        self._persist()
        logger.info(
            f"[STATE_MACHINE] Marked as SLEEP "
            f"(gap will be counted as {'LOCKED' if self.current_state == ScreenState.LOCKED else 'AWAY'})"
        )
    
    def mark_shutdown(self):
        """Mark that system is shutting down (for gap handling)"""
        self.last_event = LastEvent.SHUTDOWN
        self._persist()
        logger.info("[STATE_MACHINE] Marked as SHUTDOWN (gap will be ignored)")
    
    def mark_crash(self):
        """Mark that agent crashed (for gap handling)"""
        self.last_event = LastEvent.CRASH
        self._persist()
        logger.info("[STATE_MACHINE] Marked as CRASH (gap will be ignored)")
    
    def mark_resume(self):
        """
        Mark that system resumed from sleep.
        
        CRITICAL: Resets last_event to NORMAL to prevent future gap misclassification.
        """
        self.last_event = LastEvent.NORMAL
        self.last_timestamp = time.time()
        self._persist()
        logger.info("[STATE_MACHINE] Resumed from sleep, reset last_event to NORMAL")

