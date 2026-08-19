"""
Regression tests for server-side screen time span validation.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "server")
)

from server_telemetry import validate_span


def test_rejects_probable_capped_recovery_active_span():
    span = {
        "span_id": "f2f4857c-2f1f-4343-9571-dfa32d2129fc-active-1779914074056",
        "state": "active",
        "start_time": "2026-05-28T02:04:34.056617+05:30",
        "end_time": "2026-05-28T10:04:34.056617+05:30",
        "duration_seconds": 28800,
    }

    error = validate_span(span, "f2f4857c-2f1f-4343-9571-dfa32d2129fc")

    assert error is not None
    assert "capped recovery active span" in error


def test_accepts_normal_active_span():
    span = {
        "span_id": "f2f4857c-2f1f-4343-9571-dfa32d2129fc-active-normal",
        "state": "active",
        "start_time": "2026-05-28T10:04:34.024506+05:30",
        "end_time": "2026-05-28T10:28:46.103980+05:30",
        "duration_seconds": 1452,
    }

    assert validate_span(span, "f2f4857c-2f1f-4343-9571-dfa32d2129fc") is None
