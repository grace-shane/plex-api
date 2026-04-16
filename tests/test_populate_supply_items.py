"""
Tests for populate_supply_items.py -- tools → plex_supply_items staging.

Focus on:
  - build_supply_item_row(): 3 derived columns + fusion_guid, DB defaults omitted
  - tool_type_to_group(): type → group mapping, default "Machining"
  - populate_supply_items(): upserts eligible rows, skips tools without
    product_id, dry-run suppresses writes, Supabase failure marks rows failed
  - CLI exit codes: 0 success, 1 partial fail, 2 no tools
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from populate_supply_items import (
    build_supply_item_row,
    tool_type_to_group,
    populate_supply_items,
    main,
    DEFAULT_GROUP,
    RowResult,
)


# ---------------------------------------------------------------
# tool_type_to_group
# ---------------------------------------------------------------
class TestToolTypeToGroup:
    def test_default_for_standard_type(self):
        assert tool_type_to_group("flat end mill") == "Machining"

    def test_default_for_none(self):
        assert tool_type_to_group(None) == "Machining"

    def test_default_for_empty_string(self):
        assert tool_type_to_group("") == "Machining"

    def test_case_insensitive(self):
        assert tool_type_to_group("Flat End Mill") == "Machining"

    def test_default_group_constant(self):
        assert DEFAULT_GROUP == "Machining"


# ---------------------------------------------------------------
# build_supply_item_row
# ---------------------------------------------------------------
class TestBuildSupplyItemRow:
    def test_maps_three_derived_columns(self):
        tool = {
            "fusion_guid": "abc-123",
            "description": "1/2 in 3FL end mill",
            "product_id": "HVN-12345",
            "type": "flat end mill",
        }
        row = build_supply_item_row(tool)
        assert row == {
            "fusion_guid": "abc-123",
            "description": "1/2 in 3FL end mill",
            "item_group": "Machining",
            "supply_item_number": "HVN-12345",
        }

    def test_omits_defaulted_columns(self):
        tool = {
            "fusion_guid": "abc-123",
            "description": "x",
            "product_id": "y",
            "type": "drill",
        }
        row = build_supply_item_row(tool)
        # category, inventory_unit, item_type should NOT be in the row
        assert "category" not in row
        assert "inventory_unit" not in row
        assert "item_type" not in row

    def test_missing_description_defaults_to_empty(self):
        tool = {"fusion_guid": "g", "product_id": "p", "type": "drill"}
        row = build_supply_item_row(tool)
        assert row["description"] == ""

    def test_none_description_defaults_to_empty(self):
        tool = {
            "fusion_guid": "g",
            "description": None,
            "product_id": "p",
            "type": "drill",
        }
        row = build_supply_item_row(tool)
        assert row["description"] == ""

    def test_missing_product_id_defaults_to_empty(self):
        tool = {"fusion_guid": "g", "description": "d", "type": "drill"}
        row = build_supply_item_row(tool)
        assert row["supply_item_number"] == ""

    def test_missing_type_uses_default_group(self):
        tool = {"fusion_guid": "g", "description": "d", "product_id": "p"}
        row = build_supply_item_row(tool)
        assert row["item_group"] == "Machining"


# ---------------------------------------------------------------
# populate_supply_items
# ---------------------------------------------------------------
def _make_tool(guid: str, product_id: str = "P-123", **kwargs) -> dict:
    return {
        "fusion_guid": guid,
        "description": f"Tool {guid}",
        "product_id": product_id,
        "type": "flat end mill",
        **kwargs,
    }


class TestPopulateSupplyItems:
    def test_upserts_eligible_tools(self):
        sb = MagicMock()
        sb.select.return_value = [_make_tool("a"), _make_tool("b")]
        sb.upsert.return_value = []

        report = populate_supply_items(sb)

        assert len(report.staged) == 2
        assert len(report.skipped) == 0
        assert len(report.failed) == 0
        sb.upsert.assert_called_once()
        call_args = sb.upsert.call_args
        assert call_args.args[0] == "plex_supply_items"
        rows = call_args.args[1]
        assert len(rows) == 2
        assert call_args.kwargs["on_conflict"] == "fusion_guid"

    def test_skips_tools_without_product_id(self):
        sb = MagicMock()
        sb.select.return_value = [
            _make_tool("a", product_id="HVN-1"),
            _make_tool("b", product_id=""),
            _make_tool("c", product_id="  "),  # whitespace-only
        ]
        sb.upsert.return_value = []

        report = populate_supply_items(sb)

        assert len(report.staged) == 1
        assert len(report.skipped) == 2
        # Only one row upserted
        rows = sb.upsert.call_args.args[1]
        assert len(rows) == 1
        assert rows[0]["fusion_guid"] == "a"

    def test_skips_tools_with_none_product_id(self):
        sb = MagicMock()
        sb.select.return_value = [_make_tool("a", product_id=None)]
        sb.upsert.return_value = []

        report = populate_supply_items(sb)

        assert len(report.skipped) == 1
        sb.upsert.assert_not_called()

    def test_dry_run_does_not_write(self):
        sb = MagicMock()
        sb.select.return_value = [_make_tool("a")]

        report = populate_supply_items(sb, dry_run=True)

        sb.upsert.assert_not_called()
        assert len(report.staged) == 1

    def test_no_tools_returns_empty_report(self):
        sb = MagicMock()
        sb.select.return_value = []

        report = populate_supply_items(sb)

        assert report.results == []
        sb.upsert.assert_not_called()

    def test_supabase_upsert_failure_marks_rows_failed(self):
        sb = MagicMock()
        sb.select.return_value = [_make_tool("a"), _make_tool("b")]
        sb.upsert.side_effect = RuntimeError("postgrest borked")

        report = populate_supply_items(sb)

        assert len(report.failed) == 2
        assert len(report.staged) == 0
        assert "postgrest borked" in report.failed[0].message

    def test_all_skipped_no_upsert_call(self):
        sb = MagicMock()
        sb.select.return_value = [
            _make_tool("a", product_id=""),
            _make_tool("b", product_id=""),
        ]

        report = populate_supply_items(sb)

        assert len(report.skipped) == 2
        sb.upsert.assert_not_called()

    def test_select_requests_correct_columns(self):
        sb = MagicMock()
        sb.select.return_value = []

        populate_supply_items(sb)

        sb.select.assert_called_once()
        kwargs = sb.select.call_args.kwargs
        cols = kwargs["columns"]
        for c in ("fusion_guid", "description", "product_id", "type"):
            assert c in cols


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------
class TestCLI:
    @patch("populate_supply_items.SupabaseClient")
    @patch("populate_supply_items.populate_supply_items")
    def test_exit_0_on_success(self, mock_pop, mock_sb):
        from populate_supply_items import PopulateReport
        rpt = PopulateReport()
        rpt.results.append(RowResult("a", "staged"))
        rpt.end_time = 1.0
        mock_pop.return_value = rpt

        assert main([]) == 0

    @patch("populate_supply_items.SupabaseClient")
    @patch("populate_supply_items.populate_supply_items")
    def test_exit_1_on_partial_failure(self, mock_pop, mock_sb):
        from populate_supply_items import PopulateReport
        rpt = PopulateReport()
        rpt.results.append(RowResult("a", "staged"))
        rpt.results.append(RowResult("b", "fail", "boom"))
        rpt.end_time = 1.0
        mock_pop.return_value = rpt

        assert main([]) == 1

    @patch("populate_supply_items.SupabaseClient")
    @patch("populate_supply_items.populate_supply_items")
    def test_exit_2_on_no_tools(self, mock_pop, mock_sb):
        from populate_supply_items import PopulateReport
        mock_pop.return_value = PopulateReport(end_time=1.0)

        assert main([]) == 2

    @patch("populate_supply_items.SupabaseClient", side_effect=RuntimeError("no key"))
    def test_exit_2_on_config_error(self, _sb):
        assert main([]) == 2
