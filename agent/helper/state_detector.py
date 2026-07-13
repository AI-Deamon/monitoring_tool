"""
Production-Grade State Detection System
Uses Windows Session Events for lock/unlock detection
"""

# Try to import pywin32 modules - if not available, use fallback
try:
    import win32api
    import win32con
    import win32gui
    import winerror

    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    win32api = None
    win32con = None
    win32gui = None
    winerror = None

import ctypes
from ctypes import Structure, windll, byref, sizeof, c_uint
from ctypes import wintypes
from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
import logging
import time
import os
from enum import Enum
from typing import Callable, Optional

# PHASE 2: Import state machine (single source of truth)
from core.state_machine import ScreenTimeEngine, ScreenState, LastEvent

logger = logging.getLogger(__name__)

# Windows Constants
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WM_WTSSESSION_CHANGE = 0x02B1
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016


class SystemState(Enum):
    """System state enum"""

    ACTIVE = "active"
    IDLE = "idle"
    LOCKED = "locked"
    AWAY = "away"
    UNKNOWN = "unknown"


# High-confidence lock screen processes
LOCK_APPS = ["lockapp.exe", "logonui.exe"]


class StateAuthority:
    """
    Central gatekeeper for state transitions.
    Enforces rules like 'LOCKED is terminal' to prevent lower-confidence
    detectors (idle) from overriding higher-confidence ones (OS lock).
    """

    def __init__(self):
        self.current_state = SystemState.ACTIVE
        self.lock_source = None  # os | desktop | process | idle
        self._lock = threading.Lock()

    def can_transition(
        self, new_state: SystemState, source: str, remote_session_active: bool = False
    ) -> bool:
        """Rule engine for state transitions"""
        if self.current_state == SystemState.LOCKED:
            # LOCKED can only be exited by:
            # 1. OS unlock event (highest authority)
            # 2. RDP override (user is active remotely)
            # if new_state == SystemState.ACTIVE and (
            #     source == "os" or remote_session_active
            # ):
            if new_state == SystemState.ACTIVE and (source == "os"):
                return True
            return False

        return True

    def set_state(
        self, new_state: SystemState, source: str, remote_session_active: bool = False
    ) -> bool:
        """Atomically update state if allowed"""
        with self._lock:
            if not self.can_transition(new_state, source, remote_session_active):
                return False

            self.current_state = new_state
            if new_state == SystemState.LOCKED:
                self.lock_source = source
            elif new_state == SystemState.ACTIVE:
                self.lock_source = None
            return True

    @property
    def state(self) -> SystemState:
        return self.current_state


class LASTINPUTINFO(Structure):
    """Structure for GetLastInputInfo"""

    _fields_ = [("cbSize", c_uint), ("dwTime", c_uint)]


class StateDetector:
    """
    Production-grade state detection
    - Uses WTSRegisterSessionNotification for lock/unlock
    - Uses GetLastInputInfo for idle detection
    """

    def __init__(
        self,
        idle_threshold_seconds: int = 120,
        on_state_change: Optional[Callable] = None,
        agent_id: str = None,
        data_dir: Path = None,
    ):
        self.idle_threshold = idle_threshold_seconds
        self.on_state_change = on_state_change
        self.agent_id = agent_id or "unknown"

        self._hwnd = None
        self._thread = None
        self._running = False
        self.authority = StateAuthority()
        self._state_lock = threading.Lock()
        self._monitor_thread = None
        self._suspended = False
        self._suspend_started_at = None
        self._last_wts_unlock_time = 0  # Grace period after WTS unlock event
        self._last_unlock_transition_time = (
            0  # Grace period after any unlock transition
        )
        self._transition_lock = (
            threading.RLock()
        )  # Serialize transitions across threads

        self._foreground_app = None
        self._foreground_app_sample_time = 0

        # Centralized state machine (NEW ARCHITECTURE)
        self.current_state = "active"  # active | idle | locked | away
        self.idle_start_ts = None  # monotonic timestamp

        # NEW: Duration tracking
        self._last_state_change_time = time.time()  # Track time of last transition

        # NEW: Final totals for midnight boundary upload
        self._final_totals_for_upload = None  # Set at midnight, sent via next heartbeat
        self._final_totals_day_for_upload = None  # YYYY-MM-DD (IST day being finalized)

        # NEW: Span generation
        self.pending_spans = []  # List of completed spans awaiting collection

        # NEW: Crash recovery
        import os

        if data_dir:
            self.state_file = Path(data_dir) / "current_state.json"
        else:
            self.state_file = (
                Path(os.path.expanduser("~")) / ".sentineledge" / "current_state.json"
            )

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
        except:
            pass

        # Link to collector for event emission
        self.collector = None

        # Reference to IdleDetector for synchronization (set by main.py)
        self.idle_detector = None

        # PHASE 2: Initialize state machine (ONLY place that calculates time)
        self.screen_time_engine = ScreenTimeEngine(
            data_dir=data_dir or Path(os.path.expanduser("~")) / ".sentineledge",
            agent_id=self.agent_id,
        )

        # ✅ OFFLINE-FIRST: Cached BufferDB instance (avoids connection leaks)
        self._buffer_db = None
        self._buffer_db_lock = threading.Lock()

        # Check if pywin32 is available
        if not HAS_WIN32:
            logger.warning(
                "[STATE] pywin32 not available - using fallback (always ACTIVE)"
            )
            return

        # FIX #1: Detect initial lock state on startup
        if self._is_session_locked():
            self.authority.set_state(SystemState.LOCKED, source="desktop")
            logger.info("[STATE] Started in LOCKED state")
            self.current_state = "locked"
        else:
            logger.info("[STATE] Started in ACTIVE state")
            self.current_state = "active"

        # PHASE 2: Load persisted state and handle startup gap
        persisted = self.screen_time_engine.load_persisted_state()
        if persisted:
            gap_info = self.screen_time_engine.handle_startup(persisted)
            logger.info(f"[STATE] Startup gap handling: {gap_info}")

        # Recover crash-safe helper state (pending final-day payload + interrupted span).
        self._load_persisted_state(persisted)

    def _is_session_locked(self) -> bool:
        """Check if workstation is locked OR fast user switched (no lock event).

        Uses two redundant methods:
        1. OpenInputDesktop — checks if input desktop is accessible
        2. Foreground window process — checks for lockapp.exe / logonui.exe

        Either method returning True is enough to declare the session locked.
        This prevents the race where OpenInputDesktop briefly succeeds during
        the lock-screen animation while lockapp.exe is already foreground.
        """
        try:
            # Method 1: Desktop accessibility (classic)
            hdesk = windll.user32.OpenInputDesktop(0, False, 0)
            if hdesk:
                windll.user32.CloseDesktop(hdesk)
                desktop_accessible = True
            else:
                desktop_accessible = False
        except Exception:
            desktop_accessible = False

        if not desktop_accessible:
            return True  # No desktop = locked OR user switched

        # Method 2: Foreground window process check (Win11 lock screen)
        # OpenInputDesktop can briefly succeed during lock animation,
        # but lockapp.exe/logonui.exe will already be foreground.
        try:
            hwnd = windll.user32.GetForegroundWindow()
            if hwnd:
                pid = wintypes.DWORD()
                windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    proc_handle = windll.kernel32.OpenProcess(
                        0x0410,  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
                        False,
                        pid.value,
                    )
                    if proc_handle:
                        buf = ctypes.create_unicode_buffer(260)
                        size = wintypes.DWORD(260)
                        windll.psapi.GetModuleBaseNameW(proc_handle, None, buf, size)
                        windll.kernel32.CloseHandle(proc_handle)
                        exe = buf.value.lower()
                        if exe in ("lockapp.exe", "logonui.exe"):
                            return True
        except Exception:
            pass

        return False

    def start(self):
        """Start detection"""
        if self._running:
            return

        # If pywin32 not available, skip WTS event loop but still start monitor loop
        # The monitor loop uses ctypes only (OpenInputDesktop, GetLastInputInfo)
        if not HAS_WIN32:
            logger.warning(
                "[STATE] pywin32 not available - WTS events disabled, using polling fallback"
            )
            self._running = True

            # Start idle monitoring (uses ctypes, not pywin32)
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self._monitor_thread.start()

            logger.info("[STATE] Fallback monitor loop started (polling every 5s)")
            return

        self._running = True

        # Start Windows event loop
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()

        # Start idle monitoring
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        if self.idle_detector and self.authority.state == SystemState.LOCKED:
            try:
                # Standardized FIX 2: Startup lock sync
                self.idle_detector.set_locked(True)
                logger.info("[STATE] Synced IdleDetector to initial LOCKED state")
            except Exception as e:
                logger.error(f"[STATE] Failed to sync initial state: {e}")

        # New: Notify of initial state for timeline alignment
        if self.on_state_change:
            try:
                self.on_state_change(
                    SystemState.UNKNOWN, self.authority.state, 0.0
                )  # duration=0 for initial state
                logger.debug(
                    f"[STATE] Dispatched initial state notification: {self.authority.state.value}"
                )
            except Exception as e:
                logger.error(f"[STATE] Initial notification callback error: {e}")

        logger.info("[STATE] Production state detector started")

    def stop(self):
        """Stop detection"""
        self._running = False
        if self._hwnd:
            try:
                win32gui.DestroyWindow(self._hwnd)
            except:
                pass

    def get_state(self) -> SystemState:
        """Get current state from authority"""
        return self.authority.state

    @property
    def is_locked(self) -> bool:
        """Authority check for locked state"""
        return self.authority.state == SystemState.LOCKED

    def _get_idle_seconds(self) -> float:
        """Standardized FIX 2: Single Windows idle clock authority"""
        try:
            lii = LASTINPUTINFO()
            lii.cbSize = sizeof(LASTINPUTINFO)
            if windll.user32.GetLastInputInfo(byref(lii)):
                tick = windll.kernel32.GetTickCount()
                millis = tick - lii.dwTime
                if millis < 0:  # Tick overflow
                    millis += 2**32
                return max(0, millis / 1000.0)
            return 0.0
        except:
            return 0.0

    def _transition(
        self, new_state: str, source: str = "poll", remote_session_active: bool = False
    ):
        """PHASE 2: Use state machine for ALL time calculations"""
        callback_args = None
        with self._transition_lock:
            prev_state = self.current_state
            if prev_state == new_state:
                return
            try:
                new_state_enum = SystemState(new_state)
            except ValueError:
                logger.warning(
                    f"[STATE] Invalid transition target ignored: {new_state}"
                )
                return
            if not self.authority.set_state(
                new_state_enum,
                source=source,
                remote_session_active=remote_session_active,
            ):
                logger.info(
                    f"[STATE] Transition blocked by authority: "
                    f"{prev_state} -> {new_state} (source={source}, remote={remote_session_active})"
                )
                return

            # Calculate duration in previous state (for span generation only)
            now = time.time()
            duration_seconds = now - self._last_state_change_time

            # NEW: CREATE SPAN for the exiting state (timeline visualization only)
            if (
                prev_state in ("active", "idle", "locked", "away")
                and self._last_state_change_time > 0
                and duration_seconds >= 1.0
            ):
                span = self._create_span(
                    state=prev_state,
                    start_time=self._last_state_change_time,
                    end_time=now,
                    duration=duration_seconds,
                )
                if span:
                    self.pending_spans.append(span)
                    # ✅ OFFLINE-FIRST: Persist span to SQLite buffer immediately
                    # This ensures spans survive midnight resets and offline periods
                    self.persist_span_to_buffer(span)

            # PHASE 2: ONLY place time is calculated - call state machine
            # Map local state names to ScreenState enum
            state_map = {
                "active": ScreenState.ACTIVE,
                "idle": ScreenState.IDLE,
                "locked": ScreenState.LOCKED,
                "away": ScreenState.AWAY,
            }

            if new_state in state_map:
                try:
                    transition_info = self.screen_time_engine.transition(
                        state_map[new_state]
                    )
                    logger.debug(f"[STATE] State machine transition: {transition_info}")
                except Exception as e:
                    logger.error(
                        f"[STATE] State machine transition error: {e}", exc_info=True
                    )

            self._last_state_change_time = now

            # SOLE AUTHORITY: Close idle and emit event exactly once
            if prev_state == "idle" and new_state in ("active", "locked"):
                if self.idle_detector:
                    duration = self.idle_detector.complete_idle(time.time())
                    if duration:
                        suffix = " (lock boundary)" if new_state == "locked" else ""
                        logger.info(f"Idle session completed: {duration:.1f}s{suffix}")
                        if self.collector and hasattr(
                            self.collector, "send_idle_event"
                        ):
                            try:
                                self.collector.send_idle_event(duration)
                            except Exception as e:
                                logger.error(f"[STATE] Error sending idle event: {e}")

            if new_state == "locked":
                if self.idle_detector:
                    self.idle_detector.set_locked(True)

            if prev_state == "locked" and new_state == "active":
                # Any successful unlock path gets a short grace window, not only WTS.
                self._last_unlock_transition_time = now
                # Foreground app can still be stale lockapp.exe after unlock.
                self._foreground_app = None
                self._foreground_app_sample_time = 0
                if self.idle_detector:
                    self.idle_detector.set_locked(False)

            # Mirror authority state locally
            self.current_state = new_state
            # NEW: Persist current state for crash recovery
            self._persist_current_state()

            # Capture callback args — invoke outside the lock to avoid blocking
            # other threads on a slow/unreachable network request.
            if self.on_state_change:
                prev_state_enum = (
                    SystemState(prev_state)
                    if prev_state != "unknown"
                    else SystemState.UNKNOWN
                )
                new_state_enum = SystemState(new_state)
                callback_args = (prev_state_enum, new_state_enum, duration_seconds)

            logger.info(
                f"[STATE] {prev_state} -> {new_state} "
                f"(source={source}, remote={remote_session_active})"
            )

        # Invoke callback outside the lock
        if callback_args:
            try:
                self.on_state_change(*callback_args)
            except Exception as e:
                logger.error(f"[STATE] Callback error: {e}", exc_info=True)

    def _handle_enter(self, prev_state, new_state):
        pass

    def _handle_exit(self, prev_state, new_state):
        pass

    def _event_loop(self):
        """Windows message loop for lock/unlock events"""
        try:
            # Create hidden window
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wnd_proc
            wc.lpszClassName = "SentinelStateDetector"
            wc.hInstance = win32api.GetModuleHandle(None)

            try:
                class_atom = win32gui.RegisterClass(wc)
            except Exception as e:
                if (
                    hasattr(e, "winerror")
                    and e.winerror == winerror.ERROR_CLASS_ALREADY_EXISTS
                ):
                    class_atom = win32gui.RegisterClass(wc)
                else:
                    raise

            self._hwnd = win32gui.CreateWindow(
                class_atom,
                "SentinelStateDetector",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                wc.hInstance,
                None,
            )

            # Register for session notifications
            WTSRegisterSessionNotification = (
                ctypes.windll.wtsapi32.WTSRegisterSessionNotification
            )
            result = WTSRegisterSessionNotification(self._hwnd, 0)

            if result:
                logger.info("[STATE] Registered for lock/unlock events")
            else:
                err = ctypes.get_last_error()
                logger.error(
                    f"[STATE] WTS registration FAILED (error: {err}) - lock/unlock events will not be detected"
                )

            # Message pump
            import time

            while self._running:
                try:
                    win32gui.PumpWaitingMessages()
                except:
                    pass
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"[STATE] Event loop error: {e}", exc_info=True)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Handle Windows messages"""
        if msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                logger.info("[STATE] Screen LOCKED (OS Event)")
                self._transition("locked", source="os")

            elif wparam == WTS_SESSION_UNLOCK:
                logger.info("[STATE] Screen UNLOCKED (OS Event)")
                self._last_wts_unlock_time = time.time()
                self._transition("active", source="os")
        elif msg == WM_POWERBROADCAST:
            if wparam == PBT_APMSUSPEND:
                self._handle_suspend()
                return 1
            elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                self._handle_resume()
                return 1
        elif msg == WM_QUERYENDSESSION:
            # Windows is asking if we can shut down - mark shutdown before process dies
            try:
                self.screen_time_engine.mark_shutdown()
                logger.info(
                    "[STATE] WM_QUERYENDSESSION: marked shutdown in state machine"
                )
            except Exception as e:
                logger.error(f"[STATE] Error marking shutdown on QUERYENDSESSION: {e}")
            return 1  # Allow shutdown
        elif msg == WM_ENDSESSION:
            if wparam:  # Session is actually ending
                try:
                    self.screen_time_engine.mark_shutdown()
                    logger.info("[STATE] WM_ENDSESSION: confirmed shutdown")
                except Exception as e:
                    logger.error(f"[STATE] Error marking shutdown on ENDSESSION: {e}")

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def is_suspended(self) -> bool:
        """Return True if the system is currently suspended (sleep/hibernate)."""
        return self._suspended

    def _handle_suspend(self):
        """Handle OS suspend event. LOCKED is terminal - sleep cannot override it."""
        try:
            if self._suspended:
                return
            self._suspended = True
            self._suspend_started_at = time.time()
            logger.info("[STATE] System SUSPEND detected (OS Event)")

            # Force-close active domain session to avoid runaway durations.
            try:
                if self.collector and getattr(
                    self.collector, "active_domain_tracker", None
                ):
                    self.collector.active_domain_tracker.end_session_for_sleep()
            except Exception as e:
                logger.debug(f"[STATE] Suspend domain close failed: {e}")

            # Mark sleep for gap handling on resume/restart.
            self.screen_time_engine.mark_sleep()

            # LOCKED is terminal - sleep cannot override it.
            # If already locked (Win+L before lid close), stay LOCKED.
            # If not locked, transition to AWAY.
            if self.current_state == "locked":
                logger.info(
                    "[STATE] System suspending while LOCKED - keeping LOCKED state"
                )
                # Don't transition - stay LOCKED through sleep
            else:
                self._transition("away", source="os")

            # Prevent stale elapsed time from being turned into active/idle spans on resume.
            self._last_state_change_time = self._suspend_started_at
            self._persist_current_state()
        except Exception as e:
            logger.error(f"[STATE] Suspend handling error: {e}", exc_info=True)

    def _handle_resume(self):
        """Handle OS resume and reconcile immediately to LOCKED/ACTIVE."""
        try:
            if not self._suspended:
                return
            self._suspended = False
            logger.info("[STATE] System RESUME detected (OS Event)")

            # Reconcile elapsed suspend gap into screen-time counters BEFORE any
            # transition/last-timestamp reset. This keeps cumulative totals aligned
            # with state-change durations (especially long locked intervals).
            try:
                self.screen_time_engine.tick()
            except Exception as e:
                logger.error(f"[STATE] Resume gap reconciliation failed: {e}", exc_info=True)

            # Reconcile final state based on lock status right after resume.
            # RDP Logic Disabled: ignoring _is_remote_session()
            # if self._is_session_locked() and not self._is_remote_session():
            if self._is_session_locked():
                self._transition("locked", source="os")
            else:
                self._transition("active", source="os")

            # Reset sleep marker after reconciliation + transition.
            self.screen_time_engine.mark_resume()

            self._persist_current_state()
        except Exception as e:
            logger.error(f"[STATE] Resume handling error: {e}", exc_info=True)

    def _monitor_loop(self):
        """Monitor idle time"""
        import time

        while self._running:
            try:
                self._update_state()
            except Exception as e:
                logger.error(f"[STATE] Monitor error: {e}")
            time.sleep(5)

    # def _is_remote_session(self) -> bool:
    #     """FIX #6: Check if current session is a remote desktop session"""
    #     try:
    #         # Method 1: Check GetSystemMetrics for remote session
    #         SM_REMOTESESSION = 0x1000
    #         is_remote = windll.user32.GetSystemMetrics(SM_REMOTESESSION) != 0
    #         if is_remote:
    #             logger.debug("[STATE] Remote session detected via GetSystemMetrics")
    #             return True

    #         # Method 2: Check session ID (0xFFFFFFFF = no console = remote)
    #         try:
    #             import win32ts

    #             session_id = win32ts.WTSGetActiveConsoleSessionId()
    #             if session_id == 0xFFFFFFFF:
    #                 logger.debug("[STATE] Remote session detected via WTS")
    #                 return True
    #         except ImportError:
    #             pass  # win32ts not available
    #         except Exception:
    #             pass

    #         return False
    #     except Exception as e:
    #         logger.debug(f"[STATE] Could not detect remote session: {e}")
    #         return False  # Assume console session

    def set_foreground_app(self, app_name: str):
        """Update current foreground app (called by collector each tick)"""
        self._foreground_app = app_name
        self._foreground_app_sample_time = time.time()

    def _update_state(self):
        """Drive transitions using single clock with multi-layer lock detection"""
        with self._transition_lock:
            self._check_daily_boundary()

            if self._suspended:
                return

            now = time.time()

            # Grace period after any unlock path (WTS or fallback unlock transition).
            UNLOCK_GRACE_SECONDS = 10
            latest_unlock_hint = max(
                self._last_wts_unlock_time, self._last_unlock_transition_time
            )
            unlock_grace_active = (
                latest_unlock_hint > 0
                and (now - latest_unlock_hint) < UNLOCK_GRACE_SECONDS
            )

            if not unlock_grace_active:
                # Layer 1: Foreground app lock detection (Win11 fallback).
                # Only trust collector-fed app data while it is fresh.
                LOCK_APP_SAMPLE_MAX_AGE_SECONDS = 15
                foreground_fresh = (
                    self._foreground_app_sample_time > 0
                    and (now - self._foreground_app_sample_time)
                    <= LOCK_APP_SAMPLE_MAX_AGE_SECONDS
                )

                if (
                    foreground_fresh
                    and self._foreground_app
                    and self._foreground_app.lower() in LOCK_APPS
                ):
                    self._transition("locked", source="process")
                    return

                # Layer 2: Desktop accessibility check (classic method)
                # RDP Logic Disabled: remote_session_active forced to False
                # remote_session_active = self._is_remote_session()
                remote_session_active = False
                if self._is_session_locked() and not remote_session_active:
                    self._transition("locked", source="desktop")
                    return
            else:
                # remote_session_active = self._is_remote_session()
                remote_session_active = False

            # If we reach here, neither lock detection triggered.
            # If currently locked, only OS unlock or remote-session activity may unlock.
            if self.authority.state == SystemState.LOCKED:
                if remote_session_active:
                    # Logic commented out - RDP will not wake up the session
                    # logger.info("[STATE] Exiting LOCKED due to active remote session")
                    # self._transition("active", source="remote", remote_session_active=True)
                    pass
                elif not HAS_WIN32:
                    # Fallback mode: no WTS unlock events available, use polling unlock.
                    logger.info(
                        "[STATE] Fallback unlock via polling (pywin32 unavailable)"
                    )
                    self._transition("active", source="os")
                else:
                    logger.debug("[STATE] Staying LOCKED until OS unlock event")
                return  # Skip idle check for this tick

            if self.idle_detector:
                # Centralized Timing (SOLE Authority)
                idle_for = self._get_idle_seconds()

                # Drive the idle engine exactly once per tick
                self.idle_detector.update(now - idle_for, now)

                if self.idle_detector.is_idle():
                    self._transition("idle", source="idle")
                else:
                    self._transition("active", source="idle")
            else:
                self._transition("active", source="idle")

    # ========================================================================
    # SPAN GENERATION
    # ========================================================================

    def _create_span(
        self, state: str, start_time: float, end_time: float, duration: float
    ) -> Optional[dict]:
        """
        Create an immutable span record with clock drift detection.
        Ensures timestamp consistency by adjusting end_time when capping duration.
        """
        try:
            from datetime import datetime, timezone

            # Calculate duration from timestamps (source of truth)
            calculated_duration = end_time - start_time

            # Detect suspicious clock jumps
            drift = abs(calculated_duration - duration)

            if drift > 5.0:  # More than 5 second drift
                logger.warning(
                    f"[SPAN] Clock drift detected: {drift:.1f}s "
                    f"(calculated={calculated_duration:.1f}s, measured={duration:.1f}s)"
                )
                # Use calculated duration as source of truth
                duration = calculated_duration

            # Validate duration range
            if duration < 1.0:
                return None

            # Cap duration AND adjust end_time to maintain consistency
            if duration > 86400:  # 24 hours
                logger.warning(f"[SPAN] Capping span >24h: {duration:.1f}s -> 86400s")
                duration = 86400
                end_time = (
                    start_time + 86400
                )  # Adjust end_time to match capped duration

            start_dt = datetime.fromtimestamp(start_time, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end_time, tz=timezone.utc)

            # Idempotency key: deterministic, collision-free
            span_id = f"{self.agent_id}-{state}-{int(start_time * 1000)}"

            return {
                "span_id": span_id,
                "state": state,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "duration_seconds": int(duration),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"[SPAN] Failed to create span: {e}")
            return None

    def get_pending_spans(self) -> list:
        """Return and clear pending spans (called by Collector)."""
        with self._transition_lock:
            spans = self.pending_spans.copy()
            self.pending_spans.clear()
            return spans

    # ========================================================================
    # SPAN PERSISTENCE TO SQLITE BUFFER (OFFLINE RESILIENCE)
    # ========================================================================

    def _get_buffer_db(self):
        """
        Lazy-init cached BufferDB instance.
        Prevents connection leaks from creating new instances per span.
        """
        if self._buffer_db is not None:
            return self._buffer_db
        
        with self._buffer_db_lock:
            # Double-check after acquiring lock
            if self._buffer_db is not None:
                return self._buffer_db
            
            try:
                from pathlib import Path
                from core.buffer import BufferDB
                
                # H-01 FIX: Prioritize dynamic buffer path from state_file location
                # This handles custom installation directories correctly
                possible_paths = []
                
                # Primary: Use state_file.parent (same directory as helper state)
                if hasattr(self, 'state_file') and self.state_file:
                    possible_paths.append(self.state_file.parent / "buffer.db")
                
                # Fallback: Standard installation paths (only if primary unavailable)
                possible_paths.extend([
                    Path("C:\\ProgramData\\SentinelEdge\\buffer.db"),
                    Path("C:\\ProgramData\\SentinelEdge\\data\\buffer.db"),
                ])
                
                for path in possible_paths:
                    if path.exists():
                        self._buffer_db = BufferDB(path)
                        logger.info(f"[SPAN] BufferDB initialized: {path}")
                        return self._buffer_db
                
                logger.warning("[SPAN] Buffer database not found in any known location")
                return None
                
            except Exception as e:
                logger.error(f"[SPAN] Failed to initialize BufferDB: {e}", exc_info=True)
                return None

    def persist_span_to_buffer(self, span: dict) -> bool:
        """
        Persist a single span to SQLite buffer for offline resilience.
        Ensures spans survive midnight resets and offline periods.
        
        Returns:
            True if successfully persisted, False otherwise
        """
        try:
            # Validate timestamps before persisting
            start_time = span.get('start_time')
            end_time = span.get('end_time')
            if not start_time or not end_time:
                logger.warning(f"[SPAN] Missing timestamps in span, skipping persist")
                return False
            
            # Get cached buffer instance (no connection leaks)
            buffer = self._get_buffer_db()
            if not buffer:
                logger.warning("[SPAN] Buffer database not available, skipping persist")
                return False
            
            # Prepare span data with agent_id
            span_data = {
                'span_id': span.get('span_id'),
                'agent_id': self.agent_id,
                'state': span.get('state'),
                'start_time': start_time,
                'end_time': end_time,
                'duration_seconds': span.get('duration_seconds'),
                'created_at': span.get('created_at')
            }
            
            success = buffer.store_state_span(span_data)
            
            if success:
                logger.debug(
                    f"[SPAN] Persisted to buffer: {span['state']} "
                    f"{span['duration_seconds']}s (id={span['span_id'][:32]})"
                )
            else:
                logger.error(f"[SPAN] Failed to store span in buffer (duplicate or error)")
            
            return success
            
        except Exception as e:
            logger.error(f"[SPAN] Failed to persist span to buffer: {e}", exc_info=True)
            return False

    def persist_all_pending_spans(self) -> int:
        """
        Persist all pending spans to SQLite buffer.
        Called before midnight reset to ensure spans survive.
        
        Returns:
            Number of spans successfully persisted
        """
        with self._transition_lock:
            if not self.pending_spans:
                logger.debug("[SPAN] No pending spans to persist")
                return 0
            
            persisted_count = 0
            
            for span in self.pending_spans:
                if self.persist_span_to_buffer(span):
                    persisted_count += 1
            
            logger.info(
                f"[SPAN] Persisted {persisted_count}/{len(self.pending_spans)} "
                f"spans to buffer"
            )
            
            return persisted_count

    # ========================================================================
    # CRASH RECOVERY
    # ========================================================================

    def _load_persisted_state(self, state_machine_state: Optional[dict] = None):
        """Recover in-progress session on startup."""
        try:
            import json

            if not self.state_file.exists():
                return

            with open(self.state_file, "r") as f:
                data = json.load(f)

            # Track whether we discarded stale data that needs a deferred persist.
            # We CANNOT call _persist_current_state() here yet — current_state and
            # session_start have not been restored yet.  Writing now would save a
            # blank session state that would break continuity on the next restart.
            _needs_stale_persist = False

            # Recover pending final-day totals (midnight rollover) if present.
            pending_final = data.get("final_totals_for_upload")
            pending_day = data.get("final_totals_day_for_upload")
            if isinstance(pending_final, dict) and pending_day:
                # Validate totals before restoring to prevent stale overflow data
                total = (pending_final.get('active_seconds', 0) +
                         pending_final.get('idle_seconds', 0) +
                         pending_final.get('locked_seconds', 0) +
                         pending_final.get('away_seconds', 0))
                if total > 86400:
                    logger.warning(
                        f"[RECOVERY] Discarding stale final-day totals (total={total}s > 86400s) "
                        f"- will send fresh data instead"
                    )
                    # Clear in-memory; deferred persist happens after full recovery.
                    self._final_totals_for_upload = None
                    self._final_totals_day_for_upload = None
                    _needs_stale_persist = True
                else:
                    self._final_totals_for_upload = pending_final
                    self._final_totals_day_for_upload = str(pending_day)
                    logger.info(
                        f"[RECOVERY] Restored pending final-day totals for {self._final_totals_day_for_upload}: "
                        f"A={pending_final.get('active_seconds', 0)}s, "
                        f"I={pending_final.get('idle_seconds', 0)}s, "
                        f"L={pending_final.get('locked_seconds', 0)}s, "
                        f"W={pending_final.get('away_seconds', 0)}s"
                    )

            # 1. Recover Current Session Span
            # Use while-False so we can 'break' out early without 'return',
            # letting the deferred persist below always run.
            while True:
                if "current_state" not in data or "session_start" not in data:
                    break

                prev_state = data["current_state"]
                session_start = float(data["session_start"])
                now = time.time()

                duration = now - session_start

                last_event = (
                    str((state_machine_state or {}).get("last_event") or "")
                    .strip()
                    .lower()
                )
                if last_event in {
                    LastEvent.SHUTDOWN.value,
                    LastEvent.CRASH.value,
                    LastEvent.SLEEP.value,
                }:
                    logger.info(
                        f"[RECOVERY] Skipping interrupted {prev_state} span after "
                        f"{last_event}; gap is handled by ScreenTimeEngine"
                    )
                    break

                saved_day = str(data.get("date") or "")
                today = datetime.now().date().isoformat()
                if saved_day and saved_day != today:
                    logger.info(
                        f"[RECOVERY] Skipping interrupted {prev_state} span from "
                        f"previous day {saved_day}; today is {today}"
                    )
                    break

                if prev_state not in ("active", "idle", "locked"):
                    logger.info(
                        f"[RECOVERY] Skipping unsupported interrupted state: {prev_state}"
                    )
                    break

                if duration < 0:
                    logger.warning(
                        f"[RECOVERY] Skipping interrupted {prev_state} span with "
                        f"negative duration: {duration:.1f}s"
                    )
                    break

                # Long gaps are ambiguous after restart. Do not rewrite them to
                # "now - 8h"; that fabricates overnight activity after shutdown.
                MAX_RECOVERY_DURATION = 8 * 3600  # 8 hours

                if duration > MAX_RECOVERY_DURATION:
                    logger.warning(
                        f"[RECOVERY] Interrupted session too long ({duration:.1f}s), "
                        f"skipping recovery"
                    )
                    break

                if duration > 60:  # Only if > 1 minute
                    # Create span for the interrupted session
                    span = self._create_span(
                        state=prev_state,
                        start_time=session_start,
                        end_time=now,
                        duration=duration,
                    )
                    if span:
                        # Use _transition_lock (not _state_lock) - it's the lock
                        # every other reader/writer of pending_spans uses
                        # (_transition, get_pending_spans, persist_all_pending_spans).
                        with self._transition_lock:
                            self.pending_spans.append(span)
                        logger.info(
                            f"[RECOVERY] Recovered {prev_state} session: {duration:.1f}s"
                        )
                break  # end of while True — always exit after one pass

            # Deferred persist: now that current_state, session_start, and pending
            # spans are all restored, it is safe to write the cleared stale data.
            # This block always runs even when span recovery used 'break'.
            if _needs_stale_persist:
                self._persist_current_state()
                logger.info("[RECOVERY] Persisted cleared stale final-day totals")

        except Exception as e:
            logger.error(f"[RECOVERY] Failed to load state: {e}")

    def _persist_current_state(self):
        """Save current session metadata for crash recovery."""
        try:
            import json

            data = {
                "current_state": self.current_state,
                "session_start": self._last_state_change_time,
                "date": datetime.now().date().isoformat(),
                "timestamp": time.time(),
                "final_totals_for_upload": self._final_totals_for_upload,
                "final_totals_day_for_upload": self._final_totals_day_for_upload,
            }
            with open(self.state_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"[STATE] Failed to persist state: {e}")

    # ========================================================================
    # CUMULATIVE TIME TRACKING (for heartbeat deltas)
    # ========================================================================

    def _check_daily_boundary(self):
        """Trigger state-machine midnight rollover while preserving current state continuity."""
        try:
            crossed, final_totals = self.screen_time_engine.check_daily_boundary()
            if crossed and final_totals:
                logger.info(
                    f"[STATE] Daily boundary handled by state machine "
                    f"(state preserved: {self.current_state})"
                )
                # Store final totals to send via next heartbeat (for yesterday's final data)
                self._final_totals_for_upload = final_totals
                # "Yesterday" must use the same agent-local day boundary the
                # state machine rolled over on (core.agent_time), not a
                # second hardcoded IST offset.
                from core.agent_time import now as _local_now
                self._final_totals_day_for_upload = (
                    _local_now().date() - timedelta(days=1)
                ).isoformat()
                logger.info(
                    f"[STATE] Final totals ready for upload: "
                    f"A={final_totals.get('active_seconds', 0)}s, "
                    f"I={final_totals.get('idle_seconds', 0)}s, "
                    f"L={final_totals.get('locked_seconds', 0)}s, "
                    f"W={final_totals.get('away_seconds', 0)}s"
                )
                self._persist_current_state()
        except Exception as e:
            logger.error(f"[STATE] Daily boundary check error: {e}", exc_info=True)

    def get_cumulative_totals(self) -> dict:
        """
        Read cumulative totals from state machine (ONLY source of truth).
        Calls tick() first to flush current state time.
        """
        # Handle midnight/day rollover before reading counters.
        self._check_daily_boundary()

        # CRITICAL: Call tick() to update counters before reading
        try:
            self.screen_time_engine.tick()
        except Exception as e:
            logger.error(f"[STATE] State machine tick error: {e}", exc_info=True)

        # Read totals from state machine (ONLY place that calculates time)
        try:
            totals = self.screen_time_engine.get_daily_totals()

            # Return cumulative totals (no delta_ prefix)
            return {
                "active_seconds": totals.get("active_seconds", 0),
                "idle_seconds": totals.get("idle_seconds", 0),
                "locked_seconds": totals.get("locked_seconds", 0),
                "away_seconds": totals.get("away_seconds", 0),
            }
        except Exception as e:
            logger.error(
                f"[STATE] Error reading state machine totals: {e}", exc_info=True
            )
            return {
                "active_seconds": 0,
                "idle_seconds": 0,
                "locked_seconds": 0,
                "away_seconds": 0,
            }

    def reset_cumulative(self):
        """PHASE 2: Reset via state machine (ONLY place that manages counters)"""
        try:
            self.screen_time_engine.reset_daily()
            logger.info("[STATE] Daily counters reset via state machine")
        except Exception as e:
            logger.error(f"[STATE] Error resetting state machine: {e}", exc_info=True)
