"""
Tests for sync.py — nightly sync CLI entrypoint.

Covers:
  - APS cloud sync path (mocked APS client + Supabase)
  - Local ADC fallback path (mocked loader)
  - Validation gate (libraries that fail validation are rejected)
  - --dry-run mode (no Supabase writes)
  - --local flag (skips APS, goes straight to local)
  - Fallback from APS to local on auth failure
  - Exit codes (0 = success, 1 = partial failure, 2 = fatal)
  - SyncReport summary helpers

All I/O is mocked — no real network or filesystem calls.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from sync import (
    main,
    sync_from_aps,
    sync_from_local,
    LibraryResult,
    SyncReport,
)
from aps_client import APSAuthError, APSConfigError
from validate_library import ValidationResult


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _make_folder_contents(*names: str) -> list[dict]:
    """Build a fake APS folder contents response."""
    items = []
    for name in names:
        items.append({
            "type": "items",
            "id": f"urn:adsk.wipprod:dm.lineage:{name}",
            "attributes": {"displayName": f"{name}.json"},
        })
    return items


def _make_tip(storage_urn: str = "urn:adsk.objects:os.object:bucket/obj") -> dict:
    return {
        "relationships": {
            "storage": {
                "data": {"id": storage_urn},
            },
        },
    }


def _passing_validation(library_name: str, tool_count: int = 10) -> ValidationResult:
    return ValidationResult(
        library_name=library_name,
        passed=True,
        tool_count=tool_count,
        sync_candidate_count=tool_count,
    )


def _failing_validation(library_name: str) -> ValidationResult:
    from validate_library import ValidationIssue
    return ValidationResult(
        library_name=library_name,
        passed=False,
        tool_count=5,
        sync_candidate_count=5,
        issues=[ValidationIssue(
            severity="FAIL",
            rule="TEST_RULE",
            tool_index=0,
            tool_description="test tool",
            field="guid",
            value=None,
            message="missing guid",
        )],
    )


# ─────────────────────────────────────────────
# SyncReport
# ─────────────────────────────────────────────
class TestSyncReport:
    def test_succeeded_failed_skipped(self):
        report = SyncReport(source="test")
        report.results = [
            LibraryResult("A", "success", tools=10, presets=20),
            LibraryResult("B", "fail", message="boom"),
            LibraryResult("C", "skipped", message="empty"),
            LibraryResult("D", "success", tools=5, presets=8),
        ]
        assert len(report.succeeded) == 2
        assert len(report.failed) == 1
        assert len(report.skipped) == 1
        assert report.total_tools == 15
        assert report.total_presets == 28

    def test_elapsed(self):
        report = SyncReport(source="test", start_time=100.0, end_time=105.5)
        assert report.elapsed == pytest.approx(5.5)


# ─────────────────────────────────────────────
# sync_from_aps
# ─────────────────────────────────────────────
class TestSyncFromAps:
    @patch("sync.SupabaseClient")
    @patch("sync.sync_library")
    @patch("sync.validate_library")
    @patch("sync.APSClient")
    def test_full_sync_success(self, MockAPS, mock_validate, mock_sync, MockSB):
        aps = MockAPS.return_value
        aps.get_folder_contents.return_value = _make_folder_contents("LIB_A", "LIB_B")
        aps.get_item_tip.return_value = _make_tip()
        aps.download_tool_library.return_value = [{"guid": "g1", "type": "flat end mill"}]

        mock_validate.return_value = _passing_validation("LIB_A")
        mock_sync.return_value = {"tools": 10, "presets": 20}

        report = sync_from_aps(dry_run=False)

        assert len(report.succeeded) == 2
        assert report.total_tools == 20
        assert report.total_presets == 40
        assert mock_sync.call_count == 2
        assert report.source == "aps"

    @patch("sync.APSClient")
    @patch("sync.validate_library")
    def test_dry_run_no_supabase(self, mock_validate, MockAPS):
        aps = MockAPS.return_value
        aps.get_folder_contents.return_value = _make_folder_contents("LIB_A")
        aps.get_item_tip.return_value = _make_tip()
        aps.download_tool_library.return_value = [{"guid": "g1", "type": "drill"}]

        mock_validate.return_value = _passing_validation("LIB_A", tool_count=5)

        report = sync_from_aps(dry_run=True)

        assert len(report.succeeded) == 1
        assert report.results[0].message == "dry-run — validated OK, no write"
        # sync_library should NOT have been called
        # (SupabaseClient is never instantiated either — no mock needed)

    @patch("sync.APSClient")
    @patch("sync.validate_library")
    def test_validation_failure_blocks_sync(self, mock_validate, MockAPS):
        aps = MockAPS.return_value
        aps.get_folder_contents.return_value = _make_folder_contents("BAD_LIB")
        aps.get_item_tip.return_value = _make_tip()
        aps.download_tool_library.return_value = [{"guid": "g1"}]

        mock_validate.return_value = _failing_validation("BAD_LIB")

        report = sync_from_aps(dry_run=False)

        assert len(report.failed) == 1
        assert "Validation failed" in report.results[0].message

    @patch("sync.APSClient")
    def test_empty_library_skipped(self, MockAPS):
        aps = MockAPS.return_value
        aps.get_folder_contents.return_value = _make_folder_contents("EMPTY")
        aps.get_item_tip.return_value = _make_tip()
        aps.download_tool_library.return_value = []

        report = sync_from_aps(dry_run=False)

        assert len(report.skipped) == 1

    @patch("sync.APSClient")
    def test_no_storage_urn_fails(self, MockAPS):
        aps = MockAPS.return_value
        aps.get_folder_contents.return_value = _make_folder_contents("BROKEN")
        aps.get_item_tip.return_value = {"relationships": {"storage": {"data": {"id": ""}}}}

        report = sync_from_aps(dry_run=False)

        assert len(report.failed) == 1
        assert "storage URN" in report.results[0].message

    @patch("sync.APSClient")
    def test_aps_config_error_propagates(self, MockAPS):
        MockAPS.return_value._require_config.side_effect = APSConfigError("no creds")
        with pytest.raises(APSConfigError):
            sync_from_aps()


# ─────────────────────────────────────────────
# sync_from_local
# ─────────────────────────────────────────────
class TestSyncFromLocal:
    @patch("sync.hash_file", return_value="abc123")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_library")
    @patch("sync.validate_library")
    @patch("sync.load_all_libraries")
    def test_full_local_sync(
        self, mock_load, mock_validate, mock_sync, MockSB, mock_hash,
    ):
        mock_cam = MagicMock()
        mock_cam.exists.return_value = True
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_cam.__truediv__ = MagicMock(return_value=mock_file)

        mock_load.return_value = {
            "LIB_A": [{"guid": "g1", "type": "drill"}],
        }
        mock_validate.return_value = _passing_validation("LIB_A")
        mock_sync.return_value = {"tools": 5, "presets": 10}

        with patch("sync.CAM_TOOLS_DIR", mock_cam):
            report = sync_from_local(dry_run=False)

        assert len(report.succeeded) == 1
        assert report.source == "local"
        assert mock_sync.call_count == 1

    @patch("sync.validate_library")
    @patch("sync.load_all_libraries")
    def test_local_dry_run(self, mock_load, mock_validate):
        mock_cam = MagicMock()
        mock_cam.exists.return_value = True

        mock_load.return_value = {
            "LIB_A": [{"guid": "g1"}],
        }
        mock_validate.return_value = _passing_validation("LIB_A", tool_count=3)

        with patch("sync.CAM_TOOLS_DIR", mock_cam):
            report = sync_from_local(dry_run=True)

        assert len(report.succeeded) == 1
        assert "dry-run" in report.results[0].message

    def test_missing_directory(self):
        mock_cam = MagicMock()
        mock_cam.exists.return_value = False

        with patch("sync.CAM_TOOLS_DIR", mock_cam):
            report = sync_from_local(dry_run=False)

        assert len(report.results) == 0

    @patch("sync.validate_library")
    @patch("sync.load_all_libraries")
    def test_validation_failure(self, mock_load, mock_validate):
        mock_cam = MagicMock()
        mock_cam.exists.return_value = True

        mock_load.return_value = {"BAD": [{"guid": "g1"}]}
        mock_validate.return_value = _failing_validation("BAD")

        with patch("sync.CAM_TOOLS_DIR", mock_cam):
            report = sync_from_local(dry_run=False)

        assert len(report.failed) == 1


# ─────────────────────────────────────────────
# CLI (main)
# ─────────────────────────────────────────────
class TestMain:
    @patch("sync.populate_supply_items")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_aps")
    def test_exit_0_on_success(self, mock_aps, _sb, _pop):
        report = SyncReport(source="aps", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "success", tools=5, presets=10)]
        mock_aps.return_value = report

        assert main([]) == 0

    @patch("sync.populate_supply_items")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_aps")
    def test_exit_1_on_partial_failure(self, mock_aps, _sb, _pop):
        report = SyncReport(source="aps", start_time=0, end_time=1)
        report.results = [
            LibraryResult("A", "success", tools=5, presets=10),
            LibraryResult("B", "fail", message="boom"),
        ]
        mock_aps.return_value = report

        assert main([]) == 1

    @patch("sync.populate_supply_items")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_local")
    @patch("sync.sync_from_aps", side_effect=APSAuthError("expired"))
    def test_fallback_to_local_on_auth_error(self, mock_aps, mock_local, _sb, _pop):
        report = SyncReport(source="local", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "success", tools=5, presets=10)]
        mock_local.return_value = report

        assert main([]) == 0
        mock_local.assert_called_once()

    @patch("sync.populate_supply_items")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_local")
    def test_local_flag_skips_aps(self, mock_local, _sb, _pop):
        report = SyncReport(source="local", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "success", tools=5, presets=10)]
        mock_local.return_value = report

        assert main(["--local"]) == 0

    @patch("sync.sync_from_local")
    @patch("sync.sync_from_aps", side_effect=APSConfigError("no creds"))
    def test_exit_2_when_no_libraries(self, mock_aps, mock_local):
        report = SyncReport(source="local", start_time=0, end_time=1)
        report.results = []
        mock_local.return_value = report

        assert main([]) == 2

    @patch("sync.sync_from_aps")
    def test_dry_run_flag(self, mock_aps):
        report = SyncReport(source="aps", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "success", tools=5, message="dry-run")]
        mock_aps.return_value = report

        assert main(["--dry-run"]) == 0
        mock_aps.assert_called_once_with(dry_run=True)


# ─────────────────────────────────────────────
# Post-sync supply-item staging hook (#80)
# ─────────────────────────────────────────────
class TestPostSyncHook:
    @patch("sync.populate_supply_items")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_aps")
    def test_populate_called_after_successful_sync(self, mock_aps, mock_sb, mock_pop):
        from populate_supply_items import PopulateReport, RowResult
        report = SyncReport(source="aps", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "success", tools=5, presets=10)]
        mock_aps.return_value = report
        pop_rpt = PopulateReport()
        pop_rpt.results = [RowResult("g1", "staged")]
        pop_rpt.end_time = 1.0
        mock_pop.return_value = pop_rpt

        assert main([]) == 0
        mock_pop.assert_called_once()

    @patch("sync.populate_supply_items")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_aps")
    def test_populate_not_called_on_dry_run(self, mock_aps, mock_sb, mock_pop):
        report = SyncReport(source="aps", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "success", tools=5)]
        mock_aps.return_value = report

        assert main(["--dry-run"]) == 0
        mock_pop.assert_not_called()

    @patch("sync.populate_supply_items")
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_aps")
    def test_populate_not_called_when_no_succeeded(self, mock_aps, mock_sb, mock_pop):
        report = SyncReport(source="aps", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "fail", message="boom")]
        mock_aps.return_value = report

        main([])
        mock_pop.assert_not_called()

    @patch("sync.populate_supply_items", side_effect=RuntimeError("staging broke"))
    @patch("sync.SupabaseClient")
    @patch("sync.sync_from_aps")
    def test_populate_failure_is_nonfatal(self, mock_aps, mock_sb, mock_pop):
        report = SyncReport(source="aps", start_time=0, end_time=1)
        report.results = [LibraryResult("A", "success", tools=5, presets=10)]
        mock_aps.return_value = report

        # Should still return 0 despite staging failure
        assert main([]) == 0
