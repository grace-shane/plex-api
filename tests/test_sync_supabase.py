"""
Tests for sync_supabase.py — Fusion → Supabase normalization.

Covers all eight normalization rules from the Supabase Schema Design
(Notion · 2026-04-08):

  1. Unit conversion (inches → mm) on dimensional geometry
  2. product_id whitespace cleanup (external only)
  3. Preset GUID curly-brace strip
  4. Raw vendor casing preserved
  5. JSON null passthrough in presets (do not substitute 0)
  6. Sync filter excludes holder / probe
  7. shaft.segments JSONB passthrough, absent = NULL
  8. post_process.comment uses .get, never direct access

Also covers the batch-level sync_library flow via a fake Supabase
client so no network traffic happens in the test suite.
"""
from __future__ import annotations

import pytest

from sync_supabase import (
    INCHES_TO_MM,
    build_preset_rows,
    build_tool_row,
    normalize_preset_guid,
    normalize_product_id,
    sync_library,
    unit_scale,
)


# ─────────────────────────────────────────────
# Rule 1 — unit conversion
# ─────────────────────────────────────────────
class TestUnitScale:
    def test_inches_value_is_multiplied(self):
        # 0.5 in → 12.7 mm
        assert unit_scale(0.5, is_inches=True) == pytest.approx(12.7)

    def test_millimeters_value_is_unchanged(self):
        assert unit_scale(12.7, is_inches=False) == pytest.approx(12.7)

    def test_integer_value_is_coerced_and_scaled(self):
        assert unit_scale(1, is_inches=True) == pytest.approx(25.4)

    def test_none_passes_through(self):
        assert unit_scale(None, is_inches=True) is None
        assert unit_scale(None, is_inches=False) is None

    def test_bool_is_rejected_as_non_dimensional(self):
        # Python bool is a subclass of int — we want it rejected, not scaled.
        assert unit_scale(True, is_inches=True) is None
        assert unit_scale(False, is_inches=True) is None

    def test_non_numeric_string_returns_none(self):
        assert unit_scale("banana", is_inches=True) is None


# ─────────────────────────────────────────────
# Rule 2 — product_id cleanup
# ─────────────────────────────────────────────
class TestNormalizeProductId:
    def test_strips_leading_and_trailing_whitespace(self):
        assert normalize_product_id("  990910  ") == "990910"

    def test_preserves_internal_space_sandvik(self):
        # Sandvik real example — the space between CK04P and 1640 must survive.
        raw = "RA216.33-0845-CK04P 1640"
        assert normalize_product_id(raw) == raw

    def test_preserves_internal_dots_and_dashes(self):
        assert normalize_product_id("RA216.33-0845") == "RA216.33-0845"

    def test_none_returns_none(self):
        assert normalize_product_id(None) is None

    def test_all_whitespace_returns_none(self):
        assert normalize_product_id("   ") is None

    def test_non_string_is_coerced(self):
        assert normalize_product_id(990910) == "990910"


# ─────────────────────────────────────────────
# Rule 3 — preset GUID brace strip
# ─────────────────────────────────────────────
class TestNormalizePresetGuid:
    def test_strips_matched_braces(self):
        assert normalize_preset_guid("{6a2d224-abc-def}") == "6a2d224-abc-def"

    def test_leaves_plain_guid_alone(self):
        assert normalize_preset_guid("6a2d224-abc-def") == "6a2d224-abc-def"

    def test_unmatched_left_brace_kept(self):
        assert normalize_preset_guid("{6a2d224") == "{6a2d224"

    def test_unmatched_right_brace_kept(self):
        assert normalize_preset_guid("6a2d224}") == "6a2d224}"

    def test_none_returns_none(self):
        assert normalize_preset_guid(None) is None

    def test_empty_braces_returns_none(self):
        assert normalize_preset_guid("{}") is None


# ─────────────────────────────────────────────
# Rule 4 — vendor casing preserved
# ─────────────────────────────────────────────
class TestVendorCasing:
    def test_uppercase_vendor_preserved(self):
        tool = _tool(vendor="HARVEY TOOL")
        assert build_tool_row(tool)["vendor"] == "HARVEY TOOL"

    def test_lowercase_vendor_preserved(self):
        tool = _tool(vendor="deltamill")
        assert build_tool_row(tool)["vendor"] == "deltamill"

    def test_titlecase_vendor_preserved(self):
        tool = _tool(vendor="Garr Tool")
        assert build_tool_row(tool)["vendor"] == "Garr Tool"


# ─────────────────────────────────────────────
# Rule 5 — JSON null passthrough
# ─────────────────────────────────────────────
class TestPresetNullPassthrough:
    def test_explicit_null_becomes_sql_null(self):
        tool = _tool(
            presets=[
                {
                    "guid": "p1",
                    "name": "Default",
                    "f_n": None,
                    "f_z": None,
                    "v_c": None,
                }
            ]
        )
        rows = build_preset_rows(tool, tool_id="tool-uuid")
        assert len(rows) == 1
        assert rows[0]["f_n"] is None
        assert rows[0]["f_z"] is None
        assert rows[0]["v_c"] is None

    def test_real_values_preserved(self):
        tool = _tool(
            presets=[{"guid": "p1", "name": "D", "v_c": 120.5, "n": 12000.0}]
        )
        rows = build_preset_rows(tool, tool_id="tool-uuid")
        assert rows[0]["v_c"] == 120.5
        assert rows[0]["n"] == 12000.0

    def test_absent_field_becomes_null(self):
        tool = _tool(presets=[{"guid": "p1", "name": "D"}])
        rows = build_preset_rows(tool, tool_id="tool-uuid")
        assert rows[0]["f_n"] is None
        assert rows[0]["v_c"] is None


# ─────────────────────────────────────────────
# Rule 6 — sync filter (holder + probe excluded)
# ─────────────────────────────────────────────
class TestSyncFilter:
    def test_holders_excluded_from_tool_rows(self, fake_supabase):
        tools = [
            _tool(guid="t1", type="flat end mill"),
            _tool(guid="h1", type="holder"),
            _tool(guid="p1", type="probe"),
            _tool(guid="t2", type="drill"),
        ]
        result = sync_library("sample", tools, client=fake_supabase)
        assert result["tools"] == 2

        tool_inserts = fake_supabase.inserts_for("tools")
        guids = sorted(r["fusion_guid"] for r in tool_inserts)
        assert guids == ["t1", "t2"]

    def test_library_tool_count_reflects_filter(self, fake_supabase):
        tools = [
            _tool(guid="t1", type="flat end mill"),
            _tool(guid="h1", type="holder"),
        ]
        sync_library("sample", tools, client=fake_supabase)
        lib_row = fake_supabase.inserts_for("libraries")[0]
        assert lib_row["tool_count"] == 1


# ─────────────────────────────────────────────
# Rule 7 — shaft segments passthrough
# ─────────────────────────────────────────────
class TestShaftPassthrough:
    def test_missing_shaft_is_null(self):
        tool = _tool()
        tool.pop("shaft", None)
        row = build_tool_row(tool)
        assert row["shaft_segments"] is None

    def test_shaft_without_segments_is_null(self):
        tool = _tool()
        tool["shaft"] = {"type": "shaft"}
        row = build_tool_row(tool)
        assert row["shaft_segments"] is None

    def test_shaft_with_segments_is_passthrough(self):
        segments = [{"lower": 0.0, "upper": 10.0, "diameter": 6.0}]
        tool = _tool()
        tool["shaft"] = {"type": "shaft", "segments": segments}
        row = build_tool_row(tool)
        assert row["shaft_segments"] == segments

    def test_empty_segments_list_is_preserved_not_nulled(self):
        # Helical ships stubs with segments=[] — we store the empty list,
        # not NULL, so we can distinguish "stub present" from "no shaft key".
        tool = _tool()
        tool["shaft"] = {"type": "shaft", "segments": []}
        row = build_tool_row(tool)
        assert row["shaft_segments"] == []


# ─────────────────────────────────────────────
# Rule 8 — pp comment .get access
# ─────────────────────────────────────────────
class TestPostProcessCommentSafe:
    def test_missing_comment_does_not_raise(self):
        # Sandvik omits post-process.comment entirely.
        tool = _tool()
        tool["post-process"] = {"number": 0}
        row = build_tool_row(tool)
        assert row["pp_comment"] is None

    def test_comment_present(self):
        tool = _tool()
        tool["post-process"] = {"number": 0, "comment": "(Corner Chamfer 0.2x45°)"}
        row = build_tool_row(tool)
        assert row["pp_comment"] == "(Corner Chamfer 0.2x45°)"

    def test_missing_post_process_does_not_raise(self):
        tool = _tool()
        tool.pop("post-process", None)
        row = build_tool_row(tool)
        assert row["pp_comment"] is None
        assert row["pp_number"] is None


# ─────────────────────────────────────────────
# Geometry unit conversion end-to-end
# ─────────────────────────────────────────────
class TestBuildToolRowGeometry:
    def test_inches_library_converts_length_fields(self):
        tool = _tool(
            unit="inches",
            geometry={"DC": 0.25, "OAL": 2.0, "NOF": 4, "HAND": True, "SIG": 118},
        )
        row = build_tool_row(tool)
        assert row["geo_dc"] == pytest.approx(0.25 * INCHES_TO_MM)
        assert row["geo_oal"] == pytest.approx(2.0 * INCHES_TO_MM)
        # NOF and SIG are dimensionless — must not scale.
        assert row["geo_nof"] == 4.0
        assert row["geo_sig"] == 118.0
        assert row["geo_hand"] is True

    def test_millimeters_library_preserves_length_fields(self):
        tool = _tool(
            unit="millimeters",
            geometry={"DC": 6.0, "OAL": 60.0, "NOF": 3, "HAND": True},
        )
        row = build_tool_row(tool)
        assert row["geo_dc"] == 6.0
        assert row["geo_oal"] == 60.0
        assert row["geo_nof"] == 3.0

    def test_missing_geometry_field_is_null(self):
        tool = _tool(unit="millimeters", geometry={"DC": 6.0})
        row = build_tool_row(tool)
        assert row["geo_dc"] == 6.0
        assert row["geo_oal"] is None
        assert row["geo_re"] is None


# ─────────────────────────────────────────────
# Idempotent re-sync
# ─────────────────────────────────────────────
class TestIdempotency:
    def test_rerun_flushes_presets_before_reinsert(self, fake_supabase):
        tools = [
            _tool(
                guid="t1",
                presets=[
                    {"guid": "p1", "name": "Aluminum", "n": 12000},
                    {"guid": "p2", "name": "Steel", "n": 8000},
                ],
            )
        ]
        sync_library("lib1", tools, client=fake_supabase)
        sync_library("lib1", tools, client=fake_supabase)

        # Each run issues one delete per tool BEFORE inserting its presets.
        deletes = [op for op in fake_supabase.ops if op["kind"] == "delete"]
        assert len(deletes) == 2
        assert deletes[0]["table"] == "cutting_presets"
        assert deletes[0]["filters"]["tool_id"].startswith("eq.")


# ─────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────
def _tool(**overrides) -> dict:
    """Build a minimal valid tool dict with sensible defaults."""
    base = {
        "guid": overrides.pop("guid", "default-guid"),
        "type": overrides.pop("type", "flat end mill"),
        "description": overrides.pop("description", "test tool"),
        "product-id": overrides.pop("product_id", "TEST-001"),
        "vendor": overrides.pop("vendor", "Test Vendor"),
        "unit": overrides.pop("unit", "millimeters"),
        "BMC": overrides.pop("bmc", "carbide"),
        "geometry": overrides.pop("geometry", {"DC": 6.0, "OAL": 60.0, "NOF": 3}),
        "post-process": overrides.pop(
            "post_process", {"number": 0, "comment": ""}
        ),
        "start-values": {"presets": overrides.pop("presets", [])},
    }
    base.update(overrides)
    return base


class FakeSupabaseClient:
    """
    In-memory stand-in for SupabaseClient used by sync_library tests.
    Records every call and returns synthesized ids so the ingest
    pipeline can complete end-to-end without any network traffic.
    """

    def __init__(self):
        self.ops: list[dict] = []
        self._next_id = 0

    def _make_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id:04d}"

    def inserts_for(self, table: str) -> list[dict]:
        """All rows sent to ``table`` across insert + upsert ops."""
        rows: list[dict] = []
        for op in self.ops:
            if op["kind"] in ("insert", "upsert") and op["table"] == table:
                rows.extend(op["rows"])
        return rows

    # ── SupabaseClient interface ───────────────────────────────────
    def upsert(self, table, rows, *, on_conflict, returning="representation"):
        if isinstance(rows, dict):
            rows = [rows]
        rows = [dict(r) for r in rows]
        self.ops.append(
            {"kind": "upsert", "table": table, "rows": rows, "on_conflict": on_conflict}
        )
        # Synthesize ids mirroring the on_conflict key for deterministic
        # lookups (guid → id).
        echoed = []
        for r in rows:
            new = dict(r)
            if "id" not in new:
                new["id"] = self._make_id(table.split("_")[-1])
            echoed.append(new)
        return echoed

    def insert(self, table, rows, *, returning="representation"):
        if isinstance(rows, dict):
            rows = [rows]
        rows = [dict(r) for r in rows]
        self.ops.append({"kind": "insert", "table": table, "rows": rows})
        return [{**r, "id": self._make_id(table.split("_")[-1])} for r in rows]

    def delete(self, table, *, filters):
        self.ops.append({"kind": "delete", "table": table, "filters": dict(filters)})
        return []

    def select(self, table, **kwargs):
        self.ops.append({"kind": "select", "table": table, "kwargs": dict(kwargs)})
        return []


@pytest.fixture
def fake_supabase():
    return FakeSupabaseClient()
