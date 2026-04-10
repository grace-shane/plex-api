"""
Tests for ingest_reference.py — vendor catalog ingest into reference_catalog.

Covers:
  - build_reference_rows: normalization, filtering, unit conversion
  - is_vendor_catalog: pattern matching on filenames
  - ingest_catalog_file: dry-run and live upsert (mocked)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingest_reference import (
    build_reference_rows,
    is_vendor_catalog,
    ingest_catalog_file,
    INCHES_TO_MM,
)


# ─────────────────────────────────────────────
# build_reference_rows
# ─────────────────────────────────────────────
class TestBuildReferenceRows:
    def test_basic_tool(self):
        tools = [{
            "type": "flat end mill",
            "vendor": "Harvey Tool",
            "product-id": "978412",
            "description": "1/4 endmill",
            "unit": "inches",
            "geometry": {"DC": 0.25, "NOF": 3, "OAL": 2.5, "LCF": 0.7},
        }]
        rows = build_reference_rows("Test Catalog", tools)
        assert len(rows) == 1
        assert rows[0]["catalog_name"] == "Test Catalog"
        assert rows[0]["vendor"] == "Harvey Tool"
        assert rows[0]["product_id"] == "978412"
        assert rows[0]["type"] == "flat end mill"
        assert rows[0]["geo_dc"] == pytest.approx(0.25 * INCHES_TO_MM, abs=0.001)
        assert rows[0]["geo_nof"] == 3.0

    def test_skips_holders(self):
        tools = [
            {"type": "holder", "product-id": "H123", "vendor": "X"},
            {"type": "flat end mill", "product-id": "E456", "vendor": "X",
             "geometry": {"DC": 0.5, "NOF": 4}, "unit": "inches"},
        ]
        rows = build_reference_rows("Cat", tools)
        assert len(rows) == 1
        assert rows[0]["product_id"] == "E456"

    def test_skips_no_product_id(self):
        tools = [
            {"type": "drill", "vendor": "X", "geometry": {"DC": 0.1, "NOF": 2},
             "unit": "inches"},
            {"type": "drill", "product-id": "", "vendor": "X",
             "geometry": {"DC": 0.2, "NOF": 2}, "unit": "inches"},
        ]
        rows = build_reference_rows("Cat", tools)
        assert len(rows) == 0

    def test_mm_units_no_conversion(self):
        tools = [{
            "type": "drill",
            "vendor": "Guhring",
            "product-id": "9005",
            "unit": "millimeters",
            "geometry": {"DC": 6.35, "NOF": 2},
        }]
        rows = build_reference_rows("Cat", tools)
        assert rows[0]["geo_dc"] == pytest.approx(6.35)


# ─────────────────────────────────────────────
# is_vendor_catalog
# ─────────────────────────────────────────────
class TestIsVendorCatalog:
    def test_recognized_vendors(self):
        assert is_vendor_catalog(Path("Harvey Tool-End Mills.json"))
        assert is_vendor_catalog(Path("Guhring-Solid Hole Making (1).json"))
        assert is_vendor_catalog(Path("Garr Tool-Garr Tool.json"))
        assert is_vendor_catalog(Path("Sandvik Coromant-Solid End Mills.json"))

    def test_shop_specific_rejected(self):
        assert not is_vendor_catalog(Path("848 (HAAS VF2SSYT).json"))
        assert not is_vendor_catalog(Path("BROTHER SPEEDIO ALUMINUM.json"))
        assert not is_vendor_catalog(Path("MAZAK C600.json"))


# ─────────────────────────────────────────────
# ingest_catalog_file
# ─────────────────────────────────────────────
class TestIngestCatalogFile:
    def test_dry_run_no_client(self, tmp_path):
        import json
        f = tmp_path / "Harvey Tool-End Mills (1).json"
        f.write_text(json.dumps({"data": [
            {"type": "flat end mill", "vendor": "Harvey", "product-id": "123",
             "unit": "inches", "geometry": {"DC": 0.25, "NOF": 3}},
            {"type": "holder", "vendor": "Harvey", "product-id": "H1"},
        ]}))

        counts = ingest_catalog_file(f, dry_run=True)
        assert counts["tools"] == 1
        assert counts["skipped"] == 1

    def test_strips_copy_suffix_from_catalog_name(self, tmp_path):
        import json
        f = tmp_path / "Garr Tool-Garr Tool (2).json"
        f.write_text(json.dumps({"data": [
            {"type": "drill", "vendor": "Garr", "product-id": "19230",
             "unit": "inches", "geometry": {"DC": 0.136, "NOF": 2}},
        ]}))

        with patch("ingest_reference.SupabaseClient") as MockSB:
            client = MockSB.return_value
            client.upsert.return_value = [{"id": "abc"}]
            counts = ingest_catalog_file(f, client=client, dry_run=False)

        assert counts["tools"] == 1
        # Verify catalog_name had suffix stripped
        call_args = client.upsert.call_args
        rows = call_args[0][1]
        assert rows[0]["catalog_name"] == "Garr Tool-Garr Tool"
