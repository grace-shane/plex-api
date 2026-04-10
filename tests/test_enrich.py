"""
Tests for enrich.py — geometry-based tool enrichment from reference catalog.

Covers:
  - find_tools_missing_product_id query
  - find_reference_match_raw matching
  - enrich_tools dry-run and live update
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import json

import pytest

from enrich import (
    enrich_tools,
    find_tools_missing_product_id,
)


def _mock_client():
    client = MagicMock()
    return client


class TestFindToolsMissing:
    def test_calls_select_with_filter(self):
        client = _mock_client()
        client.select.return_value = [
            {"id": "t1", "type": "drill", "product_id": "", "geo_dc": 3.45, "geo_nof": 2},
        ]
        result = find_tools_missing_product_id(client)
        assert len(result) == 1
        client.select.assert_called_once()
        call_kwargs = client.select.call_args
        assert "tools" in call_kwargs[0]


class TestEnrichTools:
    def test_dry_run_no_update(self):
        client = _mock_client()
        client.select.return_value = [
            {"id": "t1", "type": "drill", "description": "#29 drill",
             "geo_dc": 3.45, "geo_nof": 2, "vendor": "", "product_id": ""},
        ]

        # Mock the raw HTTP call for reference lookup
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = [
            {"vendor": "Garr Tool", "product_id": "19230",
             "description": "#29", "catalog_name": "Garr Tool", "geo_dc": 3.45,
             "geo_nof": 2, "geo_oal": None},
        ]
        client._session.get.return_value = mock_resp
        client._table_url.return_value = "http://test/rest/v1/reference_catalog"

        counts = enrich_tools(client, dry_run=True)

        assert counts["matched"] == 1
        assert counts["unmatched"] == 0
        # update() should NOT have been called in dry-run
        client.update.assert_not_called()

    def test_live_update(self):
        client = _mock_client()
        client.select.return_value = [
            {"id": "t1", "type": "flat end mill", "description": "1/4 endmill",
             "geo_dc": 6.35, "geo_nof": 3, "vendor": "", "product_id": ""},
        ]

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = [
            {"vendor": "Harvey Tool", "product_id": "978412",
             "description": "1/4 flat", "catalog_name": "Harvey", "geo_dc": 6.35,
             "geo_nof": 3, "geo_oal": None},
        ]
        client._session.get.return_value = mock_resp
        client._table_url.return_value = "http://test/rest/v1/reference_catalog"

        counts = enrich_tools(client, dry_run=False)

        assert counts["matched"] == 1
        client.update.assert_called_once_with(
            "tools",
            {"product_id": "978412", "vendor": "Harvey Tool"},
            filters={"id": "eq.t1"},
        )

    def test_no_match_returns_unmatched(self):
        client = _mock_client()
        client.select.return_value = [
            {"id": "t1", "type": "tap right hand", "description": "#8-32",
             "geo_dc": 4.16, "geo_nof": 2, "vendor": "", "product_id": ""},
        ]

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = []
        client._session.get.return_value = mock_resp
        client._table_url.return_value = "http://test/rest/v1/reference_catalog"

        counts = enrich_tools(client, dry_run=True)

        assert counts["matched"] == 0
        assert counts["unmatched"] == 1

    def test_none_geometry_skipped(self):
        client = _mock_client()
        client.select.return_value = [
            {"id": "t1", "type": "drill", "description": "mystery",
             "geo_dc": None, "geo_nof": None, "vendor": "", "product_id": ""},
        ]

        counts = enrich_tools(client, dry_run=True)

        assert counts["unmatched"] == 1
        # Should not have tried the HTTP lookup
        client._session.get.assert_not_called()
