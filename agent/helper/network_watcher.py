"""
Event-driven network change detection using the Windows IP Helper API.

Replaces polling: instead of periodically re-collecting network info and
diffing it, this blocks on NotifyAddrChange/NotifyRouteChange (iphlpapi.dll)
in background threads with near-zero CPU usage, and fires a callback the
moment Windows reports the IP address table or route table changed —
Wi-Fi/Ethernet switch, DHCP renewal, adapter up/down, VPN connect, etc.
"""

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


def _load_bindings():
    """Load and type the iphlpapi/kernel32 functions we need. Raises on failure."""
    iphlpapi = ctypes.WinDLL("iphlpapi.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")

    for func_name in ("NotifyAddrChange", "NotifyRouteChange"):
        func = getattr(iphlpapi, func_name)
        func.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(_OVERLAPPED)]
        func.restype = wintypes.DWORD

    kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, ctypes.c_wchar_p
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    return iphlpapi, kernel32


class NetworkChangeWatcher:
    """
    Watches for OS-level network changes and invokes `on_change` immediately
    when one occurs, instead of relying on a periodic poll to notice it.

    Two daemon threads are started (one for address-table changes, one for
    route-table changes); each blocks in WaitForSingleObject — parked at
    ~zero CPU — until Windows signals a change or `stop()` is called.
    Rapid bursts (e.g. DHCP renegotiation firing several events in a row,
    or addr+route changing together) are coalesced via a debounce + a
    minimum interval between triggers.

    If the Windows API bindings can't be loaded (unexpected platform/
    environment), `start()` logs a warning and does nothing — callers
    should keep their existing periodic poll as a fallback in that case.
    """

    def __init__(
        self,
        on_change: Callable[[], None],
        debounce_seconds: float = 2.0,
        min_interval_seconds: float = 3.0,
    ):
        self._on_change = on_change
        self._debounce_seconds = debounce_seconds
        self._min_interval_seconds = min_interval_seconds
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._trigger_lock = threading.Lock()
        self._last_triggered = 0.0
        self._iphlpapi = None
        self._kernel32 = None

    def start(self):
        if self._threads:
            return

        try:
            self._iphlpapi, self._kernel32 = _load_bindings()
        except Exception as e:
            logger.warning(
                f"[NETWATCH] Could not load IP Helper API bindings, "
                f"real-time network change detection disabled (poll fallback still active): {e}"
            )
            return

        self._stop_event.clear()
        watchers = (
            ("NetworkChangeWatcher-Addr", self._iphlpapi.NotifyAddrChange),
            ("NetworkChangeWatcher-Route", self._iphlpapi.NotifyRouteChange),
        )
        for name, notify_func in watchers:
            t = threading.Thread(
                target=self._watch_loop, args=(notify_func,), daemon=True, name=name
            )
            t.start()
            self._threads.append(t)

        logger.info("[NETWATCH] Network change watcher started (address + route)")

    def stop(self):
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=5)
        self._threads = []

    def _watch_loop(self, notify_func):
        while not self._stop_event.is_set():
            try:
                changed = self._wait_for_change(notify_func)
            except Exception as e:
                logger.warning(f"[NETWATCH] Notify call failed, retrying in 15s: {e}")
                self._stop_event.wait(15)
                continue

            if changed and not self._stop_event.is_set():
                self._debounced_trigger()

    def _wait_for_change(self, notify_func) -> bool:
        """Block until the OS signals a change on this notification type, or stop() is called."""
        kernel32 = self._kernel32
        overlapped = _OVERLAPPED()
        overlapped.hEvent = kernel32.CreateEventW(None, True, False, None)
        if not overlapped.hEvent:
            raise ctypes.WinError()

        try:
            handle = wintypes.HANDLE()
            result = notify_func(ctypes.byref(handle), ctypes.byref(overlapped))
            if result != ERROR_IO_PENDING:
                raise ctypes.WinError(result)

            # Wait in short slices so shutdown (stop_event) stays responsive
            # without busy-polling.
            while not self._stop_event.is_set():
                wait_result = kernel32.WaitForSingleObject(overlapped.hEvent, 1000)
                if wait_result == WAIT_OBJECT_0:
                    return True
                if wait_result == WAIT_TIMEOUT:
                    continue
                raise ctypes.WinError()
            return False
        finally:
            kernel32.CloseHandle(overlapped.hEvent)

    def _debounced_trigger(self):
        # Let rapid-fire events (DHCP renegotiation, addr+route changing
        # together) settle before checking, then collapse into one trigger.
        self._stop_event.wait(self._debounce_seconds)
        if self._stop_event.is_set():
            return

        with self._trigger_lock:
            now = time.monotonic()
            if now - self._last_triggered < self._min_interval_seconds:
                return
            self._last_triggered = now

        try:
            self._on_change()
        except Exception as e:
            logger.error(f"[NETWATCH] on_change callback failed: {e}", exc_info=True)
