"""
T065 + T069 + T121 / D15 / FR-025b–h — multi-sheet inventory spreadsheet export.

QA repro: Reports -> App Inventory -> "All Agents Combined" -> download report.
Actual: "agents app inventories are displaying again and again."
Suggested: "better to print agent app inventory list in separate sheets
            (for one agent one sheet)."

The repetition is the combined export flattening every agent's inventory into
one undivided CSV. Common applications exist on most machines, so each appears
once per agent with nothing marking where one agent ends and the next begins.
Splitting by agent is the fix (see test_inventory_deduplication.py for why this
is not an ingestion bug).

Worksheet naming is the part that actually breaks. Excel caps names at 31
characters, forbids : \\ / ? * [ ], and requires uniqueness within a workbook.
Real agent names violate all three, so a naive `ws.title = agent_name` either
raises or silently produces colliding sheets. FR-025c forbids both.
"""
import pytest

openpyxl = pytest.importorskip("openpyxl", reason="openpyxl is required for FR-025b")

from report_engine import (  # noqa: E402
    MAX_COMBINED_EXPORT_AGENTS,
    InventoryExportTooLarge,
    build_inventory_workbook,
    safe_sheet_name,
)

ILLEGAL = set(r':\/?*[]')


def _row(agent_id, hostname, name, version="1.0", publisher="ACME", source="Registry-HKLM"):
    """One row in the shape /dashboard/api/inventory/fleet-export returns."""
    return {
        "agent_id": agent_id,
        "agent_hostname": hostname,
        "name": name,
        "version": version,
        "publisher": publisher,
        "source": source,
        "install_date": "2026-01-05",
    }


def _fleet(n_agents, apps_per_agent=3):
    return [
        _row(f"agent-{a:03d}", f"PC-{a:03d}", f"App {i}")
        for a in range(n_agents)
        for i in range(apps_per_agent)
    ]


class TestSheetNaming:
    """FR-025c: unique, readable, legal worksheet names — never silently wrong."""

    def test_plain_name_is_kept(self):
        assert safe_sheet_name("PC-ALICE", set()) == "PC-ALICE"

    @pytest.mark.parametrize("bad", [r"DOMAIN\PC01", "PC/01", "PC:01", "PC?01", "PC*01", "PC[01]"])
    def test_illegal_characters_are_removed(self, bad):
        result = safe_sheet_name(bad, set())
        assert not (ILLEGAL & set(result)), f"{result!r} still contains an illegal character"
        assert result, "sanitising must not produce an empty sheet name"

    def test_name_is_capped_at_excel_limit(self):
        result = safe_sheet_name("A" * 80, set())
        assert len(result) <= 31, f"sheet name is {len(result)} chars, Excel allows 31"

    def test_long_names_sharing_a_prefix_do_not_collide(self):
        """
        Truncation alone maps distinct agents onto one name. FR-025c forbids
        silently colliding or truncating into duplicates.
        """
        used = set()
        a = safe_sheet_name("WORKSTATION-FINANCE-DEPT-001", used)
        used.add(a)
        b = safe_sheet_name("WORKSTATION-FINANCE-DEPT-002", used)
        assert a != b, "two distinct agents were given the same worksheet name (FR-025c)"
        assert len(b) <= 31

    def test_exact_duplicates_are_disambiguated(self):
        used = set()
        first = safe_sheet_name("PC-01", used)
        used.add(first)
        second = safe_sheet_name("PC-01", used)
        assert first != second

    def test_blank_name_falls_back(self):
        result = safe_sheet_name("", set())
        assert result, "an unnamed agent must still get a usable sheet name"


class TestWorkbookStructure:
    """FR-025b: one worksheet per agent."""

    def test_one_sheet_per_agent(self):
        wb = build_inventory_workbook(_fleet(5))
        assert len(wb.worksheets) == 5, (
            f"expected 5 worksheets for 5 agents, got {len(wb.worksheets)} (FR-025b)"
        )

    def test_sheet_names_are_unique(self):
        wb = build_inventory_workbook(_fleet(12))
        titles = [ws.title for ws in wb.worksheets]
        assert len(set(titles)) == len(titles), "worksheet names collided (FR-025c)"

    def test_colliding_agent_names_still_produce_distinct_sheets(self):
        """SC-009a: verified with names that cannot be used verbatim."""
        rows = [
            _row("a1", "WORKSTATION-FINANCE-DEPARTMENT-001", "Chrome"),
            _row("a2", "WORKSTATION-FINANCE-DEPARTMENT-002", "Chrome"),
            _row("a3", r"DOMAIN\WORKSTATION-FINANCE-DEPT", "Chrome"),
        ]
        wb = build_inventory_workbook(rows)
        titles = [ws.title for ws in wb.worksheets]
        assert len(wb.worksheets) == 3
        assert len(set(titles)) == 3, f"colliding names produced duplicate sheets: {titles}"
        for t in titles:
            assert len(t) <= 31 and not (ILLEGAL & set(t))

    def test_each_sheet_identifies_its_agent(self):
        """FR-025c: identifiable by sheet name AND within the sheet itself."""
        wb = build_inventory_workbook([_row("agent-xyz", "PC-ALICE", "Chrome")])
        ws = wb.worksheets[0]
        cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
        blob = " ".join(cells)
        assert "PC-ALICE" in blob, "sheet does not name its agent (FR-025c)"
        assert "agent-xyz" in blob, "sheet does not carry its agent id (FR-025c)"

    def test_empty_fleet_produces_a_readable_workbook(self):
        """An empty result is an empty-state document, not a crash (FR-022 in spirit)."""
        wb = build_inventory_workbook([])
        assert len(wb.worksheets) >= 1


class TestContentParity:
    """FR-025d: same data as the existing download; FR-018 de-duplication applies."""

    def test_every_application_appears_for_its_agent(self):
        rows = [
            _row("a1", "PC-1", "Chrome"),
            _row("a1", "PC-1", "Firefox"),
            _row("a2", "PC-2", "Chrome"),
        ]
        wb = build_inventory_workbook(rows)
        by_title = {ws.title: ws for ws in wb.worksheets}
        pc1 = " ".join(
            str(c.value) for row in by_title["PC-1"].iter_rows() for c in row if c.value
        )
        assert "Chrome" in pc1 and "Firefox" in pc1

    def test_no_application_leaks_between_agents(self):
        rows = [_row("a1", "PC-1", "Chrome"), _row("a2", "PC-2", "Firefox")]
        wb = build_inventory_workbook(rows)
        by_title = {ws.title: ws for ws in wb.worksheets}
        pc1 = " ".join(
            str(c.value) for row in by_title["PC-1"].iter_rows() for c in row if c.value
        )
        assert "Firefox" not in pc1, "another agent's application appeared on this sheet"

    def test_duplicate_rows_collapse_within_a_sheet(self):
        """FR-025d: FR-018 de-duplication applies to this format equally."""
        rows = [_row("a1", "PC-1", "Chrome"), _row("a1", "PC-1", "Chrome")]
        wb = build_inventory_workbook(rows)
        ws = wb.worksheets[0]
        chrome_cells = [
            c for row in ws.iter_rows() for c in row if str(c.value or "") == "Chrome"
        ]
        assert len(chrome_cells) == 1, "the same application was listed twice on one sheet"

    def test_distinct_versions_are_both_listed(self):
        """FR-019 holds in this format too — two versions are two entries."""
        rows = [
            _row("a1", "PC-1", "Chrome", version="128.0"),
            _row("a1", "PC-1", "Chrome", version="129.0"),
        ]
        wb = build_inventory_workbook(rows)
        ws = wb.worksheets[0]
        blob = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
        assert "128.0" in blob and "129.0" in blob


class TestExportSizeLimit:
    """
    FR-025f/g, SC-009b: an oversized export is refused with a clear message
    rather than running past the worker timeout. Background job infrastructure
    is explicitly out of scope (FR-025h).
    """

    def test_limit_is_defined_and_plausible(self):
        assert isinstance(MAX_COMBINED_EXPORT_AGENTS, int)
        assert MAX_COMBINED_EXPORT_AGENTS > 0

    def test_over_limit_export_is_refused(self):
        rows = _fleet(MAX_COMBINED_EXPORT_AGENTS + 1, apps_per_agent=1)
        with pytest.raises(InventoryExportTooLarge):
            build_inventory_workbook(rows)

    def test_refusal_states_the_limit(self):
        rows = _fleet(MAX_COMBINED_EXPORT_AGENTS + 1, apps_per_agent=1)
        with pytest.raises(InventoryExportTooLarge) as exc:
            build_inventory_workbook(rows)
        assert str(MAX_COMBINED_EXPORT_AGENTS) in str(exc.value), (
            "the refusal must state the limit so the user knows what to do (FR-025f)"
        )

    def test_at_limit_still_succeeds(self):
        rows = _fleet(MAX_COMBINED_EXPORT_AGENTS, apps_per_agent=1)
        wb = build_inventory_workbook(rows)
        assert len(wb.worksheets) == MAX_COMBINED_EXPORT_AGENTS
