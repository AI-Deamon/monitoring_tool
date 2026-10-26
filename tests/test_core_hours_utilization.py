"""
Tests for _compute_core_hours_utilization and _fmt_duration.

Shift target is always 28800s (8h). Productive = active_s only.
Idle, locked, away are independent loss categories.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from server_dashboard import _compute_core_hours_utilization, _fmt_duration


# ── _fmt_duration ─────────────────────────────────────────────────────────────

def test_fmt_duration_zero():
    assert _fmt_duration(0) == "0m"

def test_fmt_duration_seconds_only():
    assert _fmt_duration(45) == "45s"

def test_fmt_duration_minutes_only():
    assert _fmt_duration(300) == "5m"

def test_fmt_duration_minutes_and_seconds():
    assert _fmt_duration(323) == "5m 23s"

def test_fmt_duration_hours_only():
    assert _fmt_duration(7200) == "2h"

def test_fmt_duration_hours_and_minutes():
    assert _fmt_duration(19320) == "5h 22m"  # 5*3600 + 22*60 = 19320


# ── _compute_core_hours_utilization ──────────────────────────────────────────

CORE = ("09:00", "17:00")  # unused by new logic but required by signature


def test_normal_productive_day():
    r = _compute_core_hours_utilization(21600, 3600, 1800, 0, *CORE)  # 6h active
    assert r["productive_pct"] == 75   # 21600/28800
    assert r["idle_pct"] == 67         # 3600 / (3600+1800) = 66.6% -> 67
    assert r["locked_pct"] == 33       # 1800 / (3600+1800) = 33.3% -> 33
    assert r["away_pct"] == 0
    assert r["productive_time_str"] == "6h"


def test_full_shift_productive():
    r = _compute_core_hours_utilization(28800, 0, 0, 0, *CORE)
    assert r["productive_pct"] == 100
    assert r["idle_pct"] == 0
    assert r["locked_pct"] == 0
    assert r["away_pct"] == 0


def test_productive_pct_capped_at_100():
    r = _compute_core_hours_utilization(36000, 0, 0, 0, *CORE)  # 10h active
    assert r["productive_pct"] == 100


def test_zero_data():
    r = _compute_core_hours_utilization(0, 0, 0, 0, *CORE)
    assert r["productive_pct"] == 0
    assert r["away_pct"] == 0
    assert r["locked_pct"] == 0
    assert r["idle_pct"] == 0
    assert r["productive_time_str"] == "0m"


def test_all_away():
    r = _compute_core_hours_utilization(0, 0, 0, 28800, *CORE)
    assert r["productive_pct"] == 0
    assert r["away_pct"] == 100
    assert r["locked_pct"] == 0
    assert r["idle_pct"] == 0


def test_idle_is_loss_not_productive():
    """Idle must NOT contribute to productive_pct."""
    r = _compute_core_hours_utilization(0, 28800, 0, 0, *CORE)
    assert r["productive_pct"] == 0
    assert r["idle_pct"] == 100


def test_inactive_breakdown_capped_at_100():
    """Inactive breakdown categories never exceed 100% of total inactive time."""
    r = _compute_core_hours_utilization(0, 0, 32400, 0, *CORE)  # 9h locked
    assert r["locked_pct"] == 100  # 32400 / 32400 * 100 = 100
    assert r["productive_pct"] == 0


def test_custom_shift_target():
    """SHIFT_TARGET_HOURS is configurable."""
    r = _compute_core_hours_utilization(27000, 0, 0, 0, *CORE, shift_target_hours=7.5)
    assert r["productive_pct"] == 100  # 27000 / 27000 = 100%


def test_legacy_fields_preserved():
    """Backward-compat fields must still be present."""
    r = _compute_core_hours_utilization(14400, 3600, 1800, 900, *CORE)
    assert "available_seconds" in r
    assert "locked_ch" in r
    assert "away_ch" in r
    assert "utilization_percent" in r
    assert r["available_seconds"] == 14400
    assert r["utilization_percent"] == r["productive_pct"]


def test_none_inputs_treated_as_zero():
    r = _compute_core_hours_utilization(None, None, None, None, *CORE)
    assert r["productive_pct"] == 0
    assert r["productive_time_str"] == "0m"

def test_all_percentages_never_exceed_100():
    r = _compute_core_hours_utilization(21600, 3600, 1800, 0, *CORE)

    assert 0 <= r["productive_pct"] <= 100
    assert 0 <= r["idle_pct"] <= 100
    assert 0 <= r["locked_pct"] <= 100
    assert 0 <= r["away_pct"] <= 100


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main(["-v", __file__]))
