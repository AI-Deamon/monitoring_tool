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
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Day-boundary logic uses the agent-local offset owned by core.agent_time
# (defaults to IST). Every module must agree on "what day is it" or the same
# activity lands on different dates in different tables.
#
# Read the timezone through _local_tz() rather than caching it in a module
# constant: config load calls agent_time.set_offset_minutes() *after* this
# module is imported, and a cached tzinfo would keep the stale offset.
from . import agent_time as _agent_time


def _local_tz() -> timezone:
    return _agent_time.get_timezone()


def _now_ist() -> datetime:
    return _agent_time.now()


class ScreenState(Enum):
    """Screen time states - exhaustive list"""

    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    LOCKED = "LOCKED"
    AWAY = "AWAY"


class LastEvent(Enum):
    """Last event types for gap handling"""

    NORMAL = "normal"  # Regular operation
    SLEEP = "sleep"  # Sleep/Hibernate/Suspend
    SHUTDOWN = "shutdown"  # Power off / shutdown
    CRASH = "crash"  # Agent crash / unexpected stop


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

    def __init__(
        self,
        data_dir: Path,
        agent_id: str = "unknown",
        user_active_fn: Optional[Callable[[], bool]] = None,
    ):
        self.agent_id = agent_id
        self.current_state = ScreenState.ACTIVE
        self.last_timestamp = time.time()
        self.last_event = LastEvent.NORMAL

        # US1 (anti-fabrication): input-recentcy predicate. When set and
        # reporting unattended while ACTIVE, tick() credits IDLE instead of
        # ACTIVE. None => legacy behavior (Core service, no input sensing).
        self.user_active_fn = user_active_fn

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

    def transition(
        self, new_state: ScreenState, event_type: LastEvent = LastEvent.NORMAL
    ) -> Dict:
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

            was_unmonitored_gap = False
            UNMONITORED_GAP_THRESHOLD = 120  # 2 minutes

            if old_state == ScreenState.ACTIVE:
                if delta >= UNMONITORED_GAP_THRESHOLD:
                    was_unmonitored_gap = True
                    logger.info(
                        f"[STATE_MACHINE] Un-monitored active transition gap ({delta:.1f}s >= {UNMONITORED_GAP_THRESHOLD}s) "
                        f"redirected to LOCK/AWAY progression"
                    )
                    self._add_to_current_bucket(delta, ScreenState.LOCKED)
                else:
                    self.active_seconds += delta
            elif old_state == ScreenState.IDLE:
                if delta >= UNMONITORED_GAP_THRESHOLD:
                    was_unmonitored_gap = True
                    logger.info(
                        f"[STATE_MACHINE] Un-monitored idle transition gap ({delta:.1f}s >= {UNMONITORED_GAP_THRESHOLD}s) "
                        f"redirected to LOCK/AWAY progression"
                    )
                    self._add_to_current_bucket(delta, ScreenState.LOCKED)
                else:
                    self.idle_seconds += delta
            elif old_state == ScreenState.LOCKED:
                # Do NOT directly add to locked_seconds
                self.pending_locked_seconds += delta
            elif old_state == ScreenState.AWAY:
                self.away_seconds += delta

            # Handle LOCKED exit inside transition() (or finalize unmonitored gap redirected to LOCKED)
            if (old_state == ScreenState.LOCKED or was_unmonitored_gap) and new_state != ScreenState.LOCKED:
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
                if was_unmonitored_gap:
                    logger.info(
                        f"[STATE_MACHINE] {old_state.value} -> {new_state.value} "
                        f"(+{delta:.1f}s redirected to locked_seconds)"
                    )
                else:
                    logger.info(
                        f"[STATE_MACHINE] {old_state.value} -> {new_state.value} "
                        f"(+{delta:.1f}s to {old_state.value.lower()}_seconds)"
                    )

            return {
                "from": old_state.value,
                "to": new_state.value,
                "delta_seconds": delta,
                "event_type": event_type.value,
                "was_unmonitored_gap": was_unmonitored_gap,
            }

    def _add_to_current_bucket(
        self, delta: float, state: Optional[ScreenState] = None
    ):
        """Add delta seconds to the given state's bucket (default: current)."""
        if state is None:
            state = self.current_state

        # Un-monitored gap protection: gaps >= UNMONITORED_GAP_THRESHOLD while ACTIVE must not be active time
        UNMONITORED_GAP_THRESHOLD = 120  # 2 minutes
        if state == ScreenState.ACTIVE and delta >= UNMONITORED_GAP_THRESHOLD:
            logger.info(
                f"[STATE_MACHINE] Un-monitored active gap ({delta:.1f}s >= {UNMONITORED_GAP_THRESHOLD}s) "
                f"redirected to LOCK/AWAY progression"
            )
            state = ScreenState.LOCKED

        if state == ScreenState.ACTIVE:
            self.active_seconds += delta
        elif state == ScreenState.IDLE:
            self.idle_seconds += delta
        elif state == ScreenState.LOCKED:
            self.pending_locked_seconds += delta
            AWAY_THRESHOLD = 7200  # 2 hours
            if self.pending_locked_seconds >= AWAY_THRESHOLD:
                self.away_seconds += self.pending_locked_seconds
                logger.info(
                    f"[STATE_MACHINE] 2h+ lock → AWAY "
                    f"({self.pending_locked_seconds:.1f}s)"
                )
                self.pending_locked_seconds = 0.0
        elif state == ScreenState.AWAY:
            self.away_seconds += delta

    def _route_to_idle(self) -> bool:
        """True when tick() must credit IDLE instead of the current state.

        US1 (anti-fabrication): an ACTIVE state with an input-recentcy
        predicate reporting the user unattended must not accrue ACTIVE time.
        """
        return (
            self.current_state == ScreenState.ACTIVE
            and self.user_active_fn is not None
            and not self.user_active_fn()
        )

    def tick(self):
        """
        Update counter for current state (MANDATORY - prevents time freezing).

        CRITICAL: This is the SOLE place that updates time counters between
        state transitions. Must be called before get_daily_totals().

        Called every heartbeat (~30s) by state_detector.get_cumulative_totals().

        US1: when `user_active_fn` is set and reports unattended while ACTIVE,
        the whole delta (including any IST-midnight split segment) is credited
        to IDLE. `current_state` is never mutated.
        """
        with self._lock:
            now = time.time()
            delta = now - self.last_timestamp

            # Evaluate the predicate ONCE so both midnight-split segments below
            # share the same routing decision.
            bucket_state = (
                ScreenState.IDLE if self._route_to_idle() else self.current_state
            )

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

            # Split delta at IST midnight if we crossed a day boundary.
            # This prevents overnight sleep/resume from dumping the entire
            # gap onto one calendar day.
            last_date = datetime.fromtimestamp(
                self.last_timestamp, tz=_local_tz()
            ).date()
            today = _now_ist().date()
            if last_date != today:
                # Compute local midnight of the day the gap started
                midnight_ts = (
                    datetime.combine(
                        last_date, datetime.min.time(), tzinfo=_local_tz()
                    ).timestamp()
                    + 86400
                )
                pre_midnight_delta = max(0.0, midnight_ts - self.last_timestamp)
                self._add_to_current_bucket(pre_midnight_delta, bucket_state)
                self.last_timestamp = midnight_ts
                delta = now - midnight_ts

            self._add_to_current_bucket(delta, bucket_state)

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

            # JSON round-trips whole numbers as int; normalize once here so
            # everything downstream can rely on the float annotations.
            try:
                last_timestamp = float(last_timestamp)
            except (TypeError, ValueError):
                logger.warning(
                    f"[STATE_MACHINE] Unusable last_timestamp in persisted state: "
                    f"{last_timestamp!r}"
                )
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
                logger.warning(
                    f"[STATE_MACHINE] Unknown last_event: {last_event_str}, treating as CRASH"
                )
                last_event = LastEvent.CRASH

            # Best-effort crash/sleep disambiguation.
            if last_event == LastEvent.CRASH and self._was_system_asleep_during_gap(
                last_timestamp, now
            ):
                logger.info(
                    "[STATE_MACHINE] Crash gap inferred as sleep from uptime heuristic"
                )
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
                        float(persisted_state.get("pending_locked_seconds", 0)),
                    )
                    total_lock_time = pending_before + gap
                    AWAY_THRESHOLD = 7200
                    if total_lock_time >= AWAY_THRESHOLD:
                        self.away_seconds += total_lock_time
                        self.pending_locked_seconds = 0.0
                        logger.info(
                            f"[STATE_MACHINE] Sleep gap: {gap:.1f}s + pending {pending_before:.1f}s "
                            f"= {total_lock_time:.1f}s ({total_lock_time / 3600:.1f}h) "
                            f"counted as AWAY (was LOCKED, >= 2h threshold)"
                        )
                        return {
                            "action": "counted_as_away",
                            "gap_seconds": gap,
                            "gap_hours": gap / 3600,
                        }
                    else:
                        self.locked_seconds += total_lock_time
                        self.pending_locked_seconds = 0.0
                        logger.info(
                            f"[STATE_MACHINE] Sleep gap: {gap:.1f}s + pending {pending_before:.1f}s "
                            f"= {total_lock_time:.1f}s ({total_lock_time / 3600:.1f}h) "
                            f"counted as LOCKED (was LOCKED, < 2h threshold)"
                        )
                        return {
                            "action": "counted_as_locked",
                            "gap_seconds": gap,
                            "gap_hours": gap / 3600,
                        }
                else:
                    self.away_seconds += gap
                    logger.info(
                        f"[STATE_MACHINE] Sleep gap: {gap:.1f}s ({gap / 3600:.1f}h) "
                        f"counted as AWAY (was {pre_sleep_state} before sleep)"
                    )
                    return {
                        "action": "counted_as_away",
                        "gap_seconds": gap,
                        "gap_hours": gap / 3600,
                    }

            elif last_event == LastEvent.SHUTDOWN:
                # Shutdown → ignore gap
                logger.info(
                    f"[STATE_MACHINE] Shutdown gap: {gap:.1f}s ({gap / 3600:.1f}h) "
                    f"IGNORED (not counted)"
                )
                return {
                    "action": "ignored_shutdown_gap",
                    "gap_seconds": gap,
                    "gap_hours": gap / 3600,
                }

            elif last_event == LastEvent.CRASH:
                # Crash → ignore gap (reliability > accuracy)
                logger.info(
                    f"[STATE_MACHINE] Crash gap: {gap:.1f}s ({gap / 3600:.1f}h) "
                    f"IGNORED (reliability > accuracy)"
                )
                return {
                    "action": "ignored_crash_gap",
                    "gap_seconds": gap,
                    "gap_hours": gap / 3600,
                }

            else:
                # Unknown/Normal gap: route to LOCKED (or AWAY if >= 2h threshold)
                pre_gap_state = last_state_str.upper()
                pending_before = (
                    max(
                        self.pending_locked_seconds,
                        float(persisted_state.get("pending_locked_seconds", 0)),
                    )
                    if pre_gap_state == "LOCKED"
                    else 0.0
                )
                total_lock_time = pending_before + gap
                AWAY_THRESHOLD = 7200
                if total_lock_time >= AWAY_THRESHOLD:
                    self.away_seconds += total_lock_time
                    self.pending_locked_seconds = 0.0
                    logger.info(
                        f"[STATE_MACHINE] Unknown/Normal gap (was {pre_gap_state}): {gap:.1f}s + pending {pending_before:.1f}s "
                        f"= {total_lock_time:.1f}s ({total_lock_time / 3600:.1f}h) "
                        f"counted as AWAY (>= 2h threshold)"
                    )
                    return {
                        "action": "counted_as_away",
                        "gap_seconds": gap,
                        "gap_hours": gap / 3600,
                    }
                else:
                    self.locked_seconds += total_lock_time
                    self.pending_locked_seconds = 0.0
                    logger.info(
                        f"[STATE_MACHINE] Unknown/Normal gap (was {pre_gap_state}): {gap:.1f}s + pending {pending_before:.1f}s "
                        f"= {total_lock_time:.1f}s ({total_lock_time / 3600:.1f}h) "
                        f"counted as LOCKED (< 2h threshold)"
                    )
                    return {
                        "action": "counted_as_locked",
                        "gap_seconds": gap,
                        "gap_hours": gap / 3600,
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
            boot_time = psutil.boot_time()

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
        visible_locked = int(
            self.locked_seconds + (pending if pending < AWAY_THRESHOLD else 0)
        )
        visible_away = int(
            self.away_seconds + (pending if pending >= AWAY_THRESHOLD else 0)
        )

        totals = {
            "active_seconds": int(self.active_seconds),
            "idle_seconds": int(self.idle_seconds),
            "locked_seconds": visible_locked,
            "away_seconds": visible_away,
        }

        # Calculate total
        totals["total_seconds"] = (
            totals["active_seconds"]
            + totals["idle_seconds"]
            + totals["locked_seconds"]
            + totals["away_seconds"]
        )

        # Validation and clamp
        if totals["total_seconds"] > 86400:
            overflow = totals["total_seconds"] - 86400
            trim_from_away = min(overflow, totals["away_seconds"])
            totals["away_seconds"] -= trim_from_away
            overflow -= trim_from_away
            if overflow > 0:
                totals["locked_seconds"] -= min(overflow, totals["locked_seconds"])
            totals["total_seconds"] = 86400
            logger.warning(
                f"[STATE_MACHINE] Total exceeded 24h ({totals['total_seconds'] + overflow + trim_from_away}s), "
                f"clamped to 86400s (trimmed {trim_from_away}s from away, "
                f"{overflow if overflow > 0 else 0}s from locked)"
            )

        return totals

    def check_daily_boundary(self) -> tuple[bool, Optional[dict]]:
        """
        Check if we crossed midnight (IST).

        IMPORTANT: Uses IST time, not UTC.
        - Midnight boundary is 00:00 IST (not UTC)
        - Daily totals align with server/business-day expectations in IST

        CRITICAL: At midnight:
        1. Send final totals to server (VIA HEARTBEAT with is_final=True)
        2. Reset counters
        3. Keep current state (continuity)
        4. Reset last_timestamp to now

        Returns:
            Tuple of (boundary_crossed: bool, final_totals: dict or None)
            - If boundary crossed: (True, final_totals_dict)
            - If not crossed: (False, None)
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
                    f"Total={final_totals['total_seconds']}s ({final_totals['total_seconds'] / 3600:.1f}h)"
                )

                # Save final totals before reset (to send to server)
                final_totals_to_send = final_totals.copy() if final_totals else None

                # Reset for new day but keep current state continuity.
                self.reset_daily()
                self.current_date = current_date
                self._persist()

                return True, final_totals_to_send

            return False, None

    def reset_daily(self, on_final_totals_callback: Optional[Callable[[Dict], None]] = None):
        """
        Reset counters at midnight (IDEMPOTENT).

        CRITICAL:
        - Only fires once per calendar day (_last_reset_date guard)
        - Calls callback with final totals BEFORE resetting (for offline persistence)
        - Reset counters to 0
        - Keep current_state (LOCKED/AWAY continuity matters)
        - Reset last_timestamp to now
        
        Args:
            on_final_totals_callback: Optional callback(final_totals: dict) called before reset
                                     to persist data for offline resilience
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

            # FIX: Classify pending locked time BEFORE resetting at midnight
            # If user was locked at midnight, classify based on 2h threshold
            # Store final values BEFORE reset so they can be sent to server
            final_locked = 0.0
            final_away = 0.0
            if self.pending_locked_seconds > 0:
                AWAY_THRESHOLD = 7200  # 2 hours
                if self.pending_locked_seconds >= AWAY_THRESHOLD:
                    final_away = self.pending_locked_seconds
                    logger.info(
                        f"[STATE_MACHINE] Midnight: pending {self.pending_locked_seconds:.0f}s → AWAY "
                        f"(crossed midnight)"
                    )
                else:
                    final_locked = self.pending_locked_seconds
                    logger.info(
                        f"[STATE_MACHINE] Midnight: pending {self.pending_locked_seconds:.0f}s → LOCKED "
                        f"(crossed midnight)"
                    )
                self.pending_locked_seconds = 0.0

            # Add to daily counters BEFORE reset - these will be sent via heartbeat
            self.locked_seconds += final_locked
            self.away_seconds += final_away
            
            # C-03 FIX: Call callback with final totals BEFORE clearing
            # This ensures offline agents persist the data to buffer before losing it
            if on_final_totals_callback:
                try:
                    final_data = self.get_daily_totals()
                    on_final_totals_callback(final_data)
                    logger.info("[STATE_MACHINE] Final totals queued via callback for offline persistence")
                except Exception as e:
                    logger.error(f"[STATE_MACHINE] Callback error during reset: {e}", exc_info=True)

            # Now reset ALL counters for the new day.
            # The accumulated locked/away values have been incorporated into
            # final_totals_to_send (returned from check_daily_boundary) and will
            # be flushed to the server via the next heartbeat. Resetting them
            # here prevents cross-day contamination if the agent goes offline
            # and cannot upload for multiple days.
            self.active_seconds = 0.0
            self.idle_seconds = 0.0
            self.locked_seconds = 0.0
            self.away_seconds = 0.0

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
                    logger.info(
                        f"[STATE_MACHINE] Restored _last_reset_date: {self._last_reset_date}"
                    )
                except (ValueError, TypeError):
                    self._last_reset_date = None

            # Restore counters if same date
            saved_date = data.get("current_date")
            if saved_date == self.current_date.isoformat():
                self.active_seconds = float(data.get("active_seconds", 0))
                self.idle_seconds = float(data.get("idle_seconds", 0))
                self.locked_seconds = float(data.get("locked_seconds", 0))
                self.away_seconds = float(data.get("away_seconds", 0))
                self.pending_locked_seconds = float(
                    data.get("pending_locked_seconds", 0)
                )  # FIX #1: Restore buffer
                
                # VALIDATION: Clamp restored values to prevent stale overflow data
                total_restored = self.active_seconds + self.idle_seconds + self.locked_seconds + self.away_seconds
                if total_restored > 86400:
                    overflow = total_restored - 86400
                    logger.warning(
                        f"[STATE_MACHINE] Restored counters exceeded 24h ({total_restored:.0f}s), "
                        f"trimming {overflow:.0f}s to prevent validation errors"
                    )
                    # Trim from away_seconds first, then locked_seconds
                    trim_away = min(overflow, self.away_seconds)
                    self.away_seconds -= trim_away
                    overflow -= trim_away
                    if overflow > 0:
                        self.locked_seconds -= min(overflow, self.locked_seconds)
                        overflow = 0
                    self.pending_locked_seconds = 0  # Clear pending to prevent double-count
                
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
        try:
            self.tick()
        except Exception as e:
            logger.error(f"[STATE_MACHINE] Error ticking before shutdown: {e}")
        self.last_event = LastEvent.SHUTDOWN
        self._persist()
        logger.info("[STATE_MACHINE] Marked as SHUTDOWN (gap will be ignored)")

    def mark_crash(self):
        """Mark that agent crashed (for gap handling)"""
        try:
            self.tick()
        except Exception as e:
            logger.error(f"[STATE_MACHINE] Error ticking before crash: {e}")
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
