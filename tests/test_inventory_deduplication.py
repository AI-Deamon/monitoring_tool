"""
T063 + T064 / D15 / FR-018, FR-019 — application inventory uniqueness.

## What D15 actually is

QA repro: Reports -> App Inventory -> "All Agents Combined" -> download report.
Actual result: "agents app inventories are displaying again and again."

Investigation found this is **not** an ingestion duplication bug. The ingest path
(`server_api.py`) deletes an agent's whole inventory and re-inserts it, skipping
repeats within the batch, and the table carries a uniqueness constraint. The DB
cannot hold two identical rows for one agent.

The repetition QA saw is the combined export flattening every agent's inventory
into one undivided list. Common applications (browsers, runtimes, Office) exist
on most machines, so each appears once per agent — hundreds of times across a
fleet — with nothing separating one agent from the next. That is why QA's own
suggestion was "one sheet per agent". The fix is FR-025b, covered by
test_inventory_xlsx_export.py, not a change to ingestion.

## What is genuinely broken (FR-019)

Uniqueness was keyed on `(agent_id, name)` alone, and the batch de-duplicator
keyed on name alone. Two genuinely distinct installations of the same
application — different versions, or the same version in different locations —
therefore collapsed into one row. FR-019 requires them to stay distinguishable.
That is a real defect, in the opposite direction to the one reported.
"""
import pytest

from server_api import inventory_dedup_key
import server_models


CHROME_128 = {
    "name": "Google Chrome",
    "version": "128.0.6613.120",
    "install_location": r"C:\Program Files\Google\Chrome",
}
CHROME_129 = {
    "name": "Google Chrome",
    "version": "129.0.6668.71",
    "install_location": r"C:\Program Files\Google\Chrome",
}
CHROME_128_USER = {
    "name": "Google Chrome",
    "version": "128.0.6613.120",
    "install_location": r"C:\Users\alice\AppData\Local\Google\Chrome",
}


class TestBatchDeduplication:
    """FR-018: an application appears exactly once per agent, however many times reported."""

    def test_identical_entries_share_a_key(self):
        """A repeated report of the same install must collapse to one row."""
        assert inventory_dedup_key(CHROME_128) == inventory_dedup_key(dict(CHROME_128))

    def test_five_successive_reports_yield_one_entry(self):
        """
        SC-009: no duplicates after at least five successive inventory reports.
        Ingestion replaces the agent's inventory wholesale, so five identical
        reports must leave exactly one row per application.
        """
        seen = set()
        kept = []
        for _ in range(5):
            for app in (CHROME_128, CHROME_128, CHROME_128):
                key = inventory_dedup_key(app)
                if key in seen:
                    continue
                seen.add(key)
                kept.append(app)
        assert len(kept) == 1, "five successive reports produced duplicate inventory rows"

    def test_entry_without_name_has_no_key(self):
        """Nameless entries are skipped rather than collapsing together."""
        assert inventory_dedup_key({"name": ""}) is None
        assert inventory_dedup_key({}) is None

    def test_name_matching_ignores_case_and_padding(self):
        """
        The same application reported with inconsistent casing or stray padding
        is one application, not two.
        """
        a = inventory_dedup_key({"name": "Google Chrome", "version": "1.0"})
        b = inventory_dedup_key({"name": "  google chrome  ", "version": "1.0"})
        assert a == b


class TestDistinctInstallationsStayDistinct:
    """FR-019: differing version or install location must remain distinguishable."""

    def test_different_versions_are_distinct(self):
        assert inventory_dedup_key(CHROME_128) != inventory_dedup_key(CHROME_129), (
            "two versions of the same application collapsed into one entry (FR-019)"
        )

    def test_different_install_locations_are_distinct(self):
        assert inventory_dedup_key(CHROME_128) != inventory_dedup_key(CHROME_128_USER), (
            "per-machine and per-user installs collapsed into one entry (FR-019)"
        )

    def test_missing_version_does_not_collide_with_a_real_version(self):
        assert inventory_dedup_key({"name": "Tool"}) != inventory_dedup_key(
            {"name": "Tool", "version": "2.1"}
        )


class TestUniquenessConstraint:
    """
    The database constraint must agree with the batch de-duplicator. If the
    constraint stays narrower than the key, ingestion computes distinct entries
    and then the insert fails — so these must be widened together.
    """

    def _unique_columns(self):
        for constraint in server_models.AppInventory.__table_args__:
            cols = getattr(constraint, "columns", None)
            if cols is not None and getattr(constraint, "name", "").startswith("uq_"):
                return {c.name for c in cols}
        return set()

    def test_constraint_covers_agent_and_name(self):
        cols = self._unique_columns()
        assert "agent_id" in cols and "name" in cols

    def test_constraint_covers_version_and_install_location(self):
        cols = self._unique_columns()
        assert "version" in cols, (
            "uniqueness ignores version, so two versions of one application "
            "cannot coexist (FR-019)"
        )
        assert "install_location" in cols, (
            "uniqueness ignores install location, so per-machine and per-user "
            "installs cannot coexist (FR-019)"
        )
