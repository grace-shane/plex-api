"""
Tests for sync_tool_inventory.py -- Plex -> Supabase qty sync.

Focus on:
  - compute_qty(): pre-signed quantity sum, empty records, bad quantities
  - collect_unknown_types(): detection of new transactionType values
  - _unwrap_records(): handles bare-list and {data: [...]} envelopes
  - sync_tool_inventory(): writes qty_on_hand/qty_tracked/qty_synced_at,
    skips writes on --dry-run, logs failures without aborting the batch
  - CLI exit codes: 0 success, 1 partial fail, 2 no linked tools

All Plex + Supabase I/O is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sync_tool_inventory import (
    compute_qty,
    collect_unknown_types,
    _unwrap_records,
    sync_tool_inventory,
    main,
    KNOWN_TRANSACTION_TYPES,
    ToolResult,
)


# ---------------------------------------------------------------
# compute_qty
# ---------------------------------------------------------------
class TestComputeQty:
    def test_pre_signed_positive_and_negative_sum(self):
        # Real-world: PO Receipt +50, Checkout -43, PO Receipt +44 -> +51
        records = [
            {"quantity": 50.0, "transactionType": "PO Receipt"},
            {"quantity": -43.0, "transactionType": "Checkout"},
            {"quantity": 44.0, "transactionType": "Check In"},
        ]
        qty, tracked = compute_qty(records)
        assert qty == pytest.approx(51.0)
        assert tracked is True

    def test_empty_records_zero_and_untracked(self):
        qty, tracked = compute_qty([])
        assert qty == 0.0
        assert tracked is False

    def test_single_record_tracked_even_if_zero(self):
        # A linked tool with one adjustment whose delta nets to zero is
        # still "tracked" -- the distinction is presence of history.
        records = [{"quantity": 0, "transactionType": "Correction"}]
        qty, tracked = compute_qty(records)
        assert qty == 0.0
        assert tracked is True

    def test_missing_quantity_is_skipped(self):
        records = [
            {"quantity": 10, "transactionType": "PO Receipt"},
            {"transactionType": "Correction"},  # no quantity key
            {"quantity": None, "transactionType": "Correction"},
        ]
        qty, tracked = compute_qty(records)
        assert qty == pytest.approx(10.0)
        # tracked counts records, not summable ones -- Plex returned 3 rows
        assert tracked is True

    def test_non_numeric_quantity_is_skipped(self):
        records = [
            {"quantity": 5, "transactionType": "PO Receipt"},
            {"quantity": "not-a-number", "transactionType": "Correction"},
        ]
        qty, _ = compute_qty(records)
        assert qty == pytest.approx(5.0)

    def test_string_numeric_quantity_is_summed(self):
        # PostgREST-style numeric strings should still work.
        records = [{"quantity": "12.5", "transactionType": "PO Receipt"}]
        qty, _ = compute_qty(records)
        assert qty == pytest.approx(12.5)

    def test_negative_running_balance_preserved(self):
        # Plex occasionally returns a net-negative balance (data-quality
        # issue). The sync must preserve it faithfully, not clamp to 0.
        records = [
            {"quantity": 10, "transactionType": "PO Receipt"},
            {"quantity": -50, "transactionType": "Checkout"},
        ]
        qty, _ = compute_qty(records)
        assert qty == pytest.approx(-40.0)


# ---------------------------------------------------------------
# collect_unknown_types
# ---------------------------------------------------------------
class TestCollectUnknownTypes:
    def test_all_known_returns_empty(self):
        records = [
            {"transactionType": "PO Receipt"},
            {"transactionType": "Checkout"},
            {"transactionType": "Correction"},
            {"transactionType": "Check In"},
        ]
        assert collect_unknown_types(records) == set()

    def test_null_transaction_type_is_not_unknown(self):
        # null is an observed data-quality quirk, not a new type.
        assert collect_unknown_types([{"transactionType": None}]) == set()

    def test_new_type_is_flagged(self):
        records = [
            {"transactionType": "PO Receipt"},
            {"transactionType": "Scrap"},
            {"transactionType": "Physical Inventory"},
        ]
        assert collect_unknown_types(records) == {"Scrap", "Physical Inventory"}

    def test_known_set_matches_docs(self):
        # Guard against accidental drift from docs/Plex_API_Reference.md Section 3.6.
        assert KNOWN_TRANSACTION_TYPES == {
            "PO Receipt", "Checkout", "Correction", "Check In",
        }


# ---------------------------------------------------------------
# _unwrap_records
# ---------------------------------------------------------------
class TestUnwrapRecords:
    def test_bare_list(self):
        assert _unwrap_records([{"a": 1}]) == [{"a": 1}]

    def test_data_envelope(self):
        assert _unwrap_records({"data": [{"a": 1}]}) == [{"a": 1}]

    def test_empty_data_envelope(self):
        assert _unwrap_records({"data": []}) == []

    def test_missing_data_key(self):
        assert _unwrap_records({"error": "nope"}) == []

    def test_none(self):
        assert _unwrap_records(None) == []


# ---------------------------------------------------------------
# sync_tool_inventory
# ---------------------------------------------------------------
def _ok_env(body):
    return {"ok": True, "status": 200, "body": body, "error": None}


def _fail_env(status=500, error="HTTP 500"):
    return {"ok": False, "status": status, "body": None, "error": error}


class TestSyncToolInventory:
    def _linked_tools(self, *guids):
        return [
            {"fusion_guid": g, "plex_supply_item_id": f"plex-{g}"}
            for g in guids
        ]

    def test_writes_qty_for_each_linked_tool(self):
        plex = MagicMock()
        sb = MagicMock()
        sb.select.return_value = self._linked_tools("a", "b")
        plex.get_envelope.side_effect = [
            _ok_env([
                {"quantity": 50, "transactionType": "PO Receipt"},
                {"quantity": -10, "transactionType": "Checkout"},
            ]),
            _ok_env([]),  # linked but no history
        ]

        report = sync_tool_inventory(plex, sb)

        assert len(report.succeeded) == 2
        assert len(report.failed) == 0
        # Two update calls, one per tool
        assert sb.update.call_count == 2
        first_call = sb.update.call_args_list[0]
        assert first_call.args[0] == "tools"
        values = first_call.args[1]
        assert values["qty_on_hand"] == pytest.approx(40.0)
        assert values["qty_tracked"] is True
        assert "qty_synced_at" in values
        assert first_call.kwargs["filters"] == {"fusion_guid": "eq.a"}
        # Second tool: empty history -> tracked False, qty 0
        second = sb.update.call_args_list[1]
        assert second.args[1]["qty_on_hand"] == 0.0
        assert second.args[1]["qty_tracked"] is False

    def test_dry_run_does_not_write(self):
        plex = MagicMock()
        sb = MagicMock()
        sb.select.return_value = self._linked_tools("a")
        plex.get_envelope.return_value = _ok_env(
            [{"quantity": 5, "transactionType": "PO Receipt"}]
        )

        report = sync_tool_inventory(plex, sb, dry_run=True)

        sb.update.assert_not_called()
        assert len(report.succeeded) == 1
        assert report.succeeded[0].qty_on_hand == pytest.approx(5.0)

    def test_plex_failure_is_recorded_and_does_not_abort_batch(self):
        plex = MagicMock()
        sb = MagicMock()
        sb.select.return_value = self._linked_tools("a", "b")
        plex.get_envelope.side_effect = [
            _fail_env(500, "boom"),
            _ok_env([{"quantity": 3, "transactionType": "PO Receipt"}]),
        ]

        report = sync_tool_inventory(plex, sb)

        assert len(report.failed) == 1
        assert len(report.succeeded) == 1
        assert report.failed[0].fusion_guid == "a"
        # Only one Supabase write (for the successful tool)
        assert sb.update.call_count == 1

    def test_supabase_update_failure_is_recorded(self):
        plex = MagicMock()
        sb = MagicMock()
        sb.select.return_value = self._linked_tools("a")
        plex.get_envelope.return_value = _ok_env(
            [{"quantity": 1, "transactionType": "PO Receipt"}]
        )
        sb.update.side_effect = RuntimeError("postgrest borked")

        report = sync_tool_inventory(plex, sb)

        assert len(report.failed) == 1
        assert "postgrest borked" in report.failed[0].message

    def test_no_linked_tools_returns_empty_report(self):
        plex = MagicMock()
        sb = MagicMock()
        sb.select.return_value = []

        report = sync_tool_inventory(plex, sb)

        assert report.results == []
        plex.get_envelope.assert_not_called()
        sb.update.assert_not_called()

    def test_unknown_transaction_type_logged_and_still_summed(self):
        plex = MagicMock()
        sb = MagicMock()
        sb.select.return_value = self._linked_tools("a")
        plex.get_envelope.return_value = _ok_env([
            {"quantity": 7, "transactionType": "PO Receipt"},
            {"quantity": -2, "transactionType": "Scrap"},  # new type
        ])

        report = sync_tool_inventory(plex, sb)

        assert report.succeeded[0].qty_on_hand == pytest.approx(5.0)
        assert "Scrap" in report.unknown_transaction_types

    def test_supabase_select_uses_not_null_filter(self):
        plex = MagicMock()
        sb = MagicMock()
        sb.select.return_value = []

        sync_tool_inventory(plex, sb)

        sb.select.assert_called_once()
        kwargs = sb.select.call_args.kwargs
        assert kwargs["filters"] == {"plex_supply_item_id": "not.is.null"}
        assert "fusion_guid" in kwargs["columns"]
        assert "plex_supply_item_id" in kwargs["columns"]


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------
class TestCLI:
    @patch("sync_tool_inventory.SupabaseClient")
    @patch("sync_tool_inventory.PlexClient")
    @patch("sync_tool_inventory.sync_tool_inventory")
    def test_exit_0_on_full_success(self, mock_sync, mock_plex, mock_sb):
        from sync_tool_inventory import SyncReport
        rpt = SyncReport()
        rpt.results.append(ToolResult("a", "p", "success", 5.0, True, 2))
        rpt.end_time = 1.0
        mock_sync.return_value = rpt

        assert main([]) == 0

    @patch("sync_tool_inventory.SupabaseClient")
    @patch("sync_tool_inventory.PlexClient")
    @patch("sync_tool_inventory.sync_tool_inventory")
    def test_exit_1_on_partial_failure(self, mock_sync, mock_plex, mock_sb):
        from sync_tool_inventory import SyncReport
        rpt = SyncReport()
        rpt.results.append(ToolResult("a", "p", "success"))
        rpt.results.append(ToolResult("b", "q", "fail", message="x"))
        rpt.end_time = 1.0
        mock_sync.return_value = rpt

        assert main([]) == 1

    @patch("sync_tool_inventory.SupabaseClient")
    @patch("sync_tool_inventory.PlexClient")
    @patch("sync_tool_inventory.sync_tool_inventory")
    def test_exit_2_on_no_linked_tools(self, mock_sync, mock_plex, mock_sb):
        from sync_tool_inventory import SyncReport
        mock_sync.return_value = SyncReport(end_time=1.0)
        assert main([]) == 2

    @patch("sync_tool_inventory.SupabaseClient")
    @patch("sync_tool_inventory.PlexClient", side_effect=RuntimeError("no key"))
    def test_exit_2_on_config_error(self, _plex, _sb):
        assert main([]) == 2
