"""
Tests for validate_library.py — covers every rule ID in the spec
at docs/validate_library_spec.md.

Tests never touch the network. Supplier API checks use FakePlexClient
from conftest.py.
"""
from __future__ import annotations

import copy
import pytest

from validate_library import (
    KNOWN_TOOL_TYPES,
    NON_SYNC_TYPES,
    ValidationMode,
    ValidationIssue,
    ValidationResult,
    _closest_supplier_names,
    _edit_distance,
    _get_supplier_names,
    _match_vendor,
    _reset_supplier_cache,
    format_result,
    validate_library,
)


# ─────────────────────────────────────────────
# Helpers — minimal valid tool dicts
# ─────────────────────────────────────────────

def make_tool(**overrides) -> dict:
    """A minimal tool that passes every per-tool rule."""
    base = {
        "guid": "tool-guid-0001",
        "type": "flat end mill",
        "description": "1/4 SQ END",
        "product-id": "HARVEY-12345",
        "vendor": "Harvey Tool",
        "geometry": {
            "DC": 0.25,
            "OAL": 2.5,
            "NOF": 4,
        },
        "post-process": {"number": 1},
    }
    base.update(overrides)
    return base


def make_holder(**overrides) -> dict:
    base = {
        "guid": "holder-guid-0001",
        "type": "holder",
        "description": "BT30-SHC.25",
    }
    base.update(overrides)
    return base


def make_probe(**overrides) -> dict:
    base = {
        "guid": "probe-guid-0001",
        "type": "probe",
        "description": "Renishaw OMP40",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _clear_supplier_cache():
    """Reset the module-level supplier cache between tests."""
    _reset_supplier_cache()
    yield
    _reset_supplier_cache()


# ─────────────────────────────────────────────
# Library-level rules
# ─────────────────────────────────────────────

class TestLibraryLevelStructure:
    def test_passes_on_valid_library(self):
        result = validate_library(
            tools=[make_tool()],
            library_name="test",
        )
        assert result.passed is True
        assert result.tool_count == 1
        assert result.sync_candidate_count == 1
        assert result.fails == []

    def test_struct_root_key_fail_on_none(self):
        result = validate_library(tools=None, library_name="test")
        assert result.passed is False
        assert any(i.rule == "STRUCT_ROOT_KEY" for i in result.fails)

    def test_struct_data_list_fail_on_non_list(self):
        result = validate_library(tools={"foo": "bar"}, library_name="test")
        assert result.passed is False
        assert any(i.rule == "STRUCT_DATA_LIST" for i in result.fails)

    def test_struct_empty_fail_on_empty_list(self):
        result = validate_library(tools=[], library_name="test")
        assert result.passed is False
        assert any(i.rule == "STRUCT_EMPTY" for i in result.fails)

    def test_sync_candidates_zero_fail_on_all_holders(self):
        result = validate_library(
            tools=[make_holder(), make_probe()],
            library_name="test",
        )
        assert result.passed is False
        assert any(i.rule == "SYNC_CANDIDATES_ZERO" for i in result.fails)

    def test_library_level_fail_skips_per_tool_checks(self):
        # An empty library should produce only STRUCT_EMPTY, not a swarm
        # of per-tool errors.
        result = validate_library(tools=[], library_name="test")
        assert len(result.fails) == 1
        assert result.fails[0].rule == "STRUCT_EMPTY"


class TestDuplicateDetection:
    def test_duplicate_guid_fail(self):
        a = make_tool(guid="dup-guid", product_id="A")
        a["product-id"] = "PROD-A"
        b = make_tool(guid="dup-guid", product_id="B")
        b["product-id"] = "PROD-B"
        result = validate_library(tools=[a, b], library_name="test")
        assert result.passed is False
        assert any(i.rule == "DUPLICATE_GUID" for i in result.fails)

    def test_duplicate_product_id_fail(self):
        a = make_tool(guid="guid-a")
        a["product-id"] = "DUP-PID"
        b = make_tool(guid="guid-b")
        b["product-id"] = "DUP-PID"
        result = validate_library(tools=[a, b], library_name="test")
        assert result.passed is False
        assert any(i.rule == "DUPLICATE_PRODUCT_ID" for i in result.fails)

    def test_duplicate_product_id_only_on_sync_candidates(self):
        # Holders are not sync candidates, so shared "product-id" on holders
        # should NOT trip DUPLICATE_PRODUCT_ID.
        a = make_holder(guid="h1")
        a["product-id"] = "SAME"
        b = make_holder(guid="h2")
        b["product-id"] = "SAME"
        # Need at least one sync candidate so we don't trip SYNC_CANDIDATES_ZERO
        t = make_tool()
        result = validate_library(tools=[a, b, t], library_name="test")
        assert result.passed is True
        assert not any(i.rule == "DUPLICATE_PRODUCT_ID" for i in result.fails)

    def test_cross_library_duplicate_warn(self):
        tool = make_tool()
        tool["product-id"] = "SHARED-PID"
        result = validate_library(
            tools=[tool],
            library_name="current",
            cross_library_product_ids={"SHARED-PID": "other-library"},
        )
        assert result.passed is True  # WARN only
        assert any(
            i.rule == "CROSS_LIBRARY_DUPLICATE" for i in result.warns
        )

    def test_cross_library_duplicate_no_fire_when_dict_none(self):
        tool = make_tool()
        result = validate_library(
            tools=[tool],
            library_name="current",
            cross_library_product_ids=None,
        )
        assert not any(
            i.rule == "CROSS_LIBRARY_DUPLICATE" for i in result.warns
        )


class TestUnknownType:
    def test_unknown_type_warns_but_still_passes(self):
        tool = make_tool(type="taper shank wizard")
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is True
        assert any(i.rule == "UNKNOWN_TYPE_PRESENT" for i in result.warns)

    def test_known_type_does_not_warn(self):
        for t in KNOWN_TOOL_TYPES - NON_SYNC_TYPES:
            tool = make_tool(type=t)
            result = validate_library(tools=[tool], library_name="test")
            assert not any(
                i.rule == "UNKNOWN_TYPE_PRESENT" for i in result.warns
            )


# ─────────────────────────────────────────────
# Per-tool rules — required fields
# ─────────────────────────────────────────────

class TestRequiredFields:
    @pytest.mark.parametrize("field_name", ["guid", "type", "description", "product-id"])
    def test_missing_required_field_fails(self, field_name):
        tool = make_tool()
        del tool[field_name]
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is False
        assert any(
            i.rule == "REQUIRED_FIELD" and i.field == field_name
            for i in result.fails
        )

    @pytest.mark.parametrize("field_name", ["guid", "type", "description", "product-id"])
    def test_empty_string_required_field_fails(self, field_name):
        tool = make_tool(**{field_name: ""})
        result = validate_library(tools=[tool], library_name="test")
        assert any(
            i.rule == "REQUIRED_FIELD" and i.field == field_name
            for i in result.fails
        )

    def test_holders_skip_required_field_checks(self):
        # Holders have no product-id and should still pass as long as a
        # sync candidate exists in the library.
        tools = [make_tool(), make_holder()]
        result = validate_library(tools=tools, library_name="test")
        assert result.passed is True


# ─────────────────────────────────────────────
# Per-tool rules — vendor
# ─────────────────────────────────────────────

class TestVendorRules:
    def test_missing_vendor_warns(self):
        tool = make_tool()
        del tool["vendor"]
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is True
        assert any(i.rule == "VENDOR_MISSING" for i in result.warns)

    def test_empty_vendor_warns(self):
        tool = make_tool(vendor="")
        result = validate_library(tools=[tool], library_name="test")
        assert any(i.rule == "VENDOR_MISSING" for i in result.warns)

    def test_vendor_not_in_plex_warns(self, fake_client):
        fake_client.set_response(
            "suppliers",
            [{"name": "Harvey Tool"}, {"name": "Sandvik"}],
        )
        tool = make_tool(vendor="GARR TOOL")  # not in list
        result = validate_library(
            tools=[tool],
            library_name="test",
            use_api=True,
            client=fake_client,
        )
        assert result.passed is True
        assert any(i.rule == "VENDOR_NOT_IN_PLEX" for i in result.warns)

    def test_vendor_case_insensitive_match(self, fake_client):
        fake_client.set_response("suppliers", [{"name": "Harvey Tool"}])
        tool = make_tool(vendor="HARVEY TOOL")
        result = validate_library(
            tools=[tool],
            library_name="test",
            use_api=True,
            client=fake_client,
        )
        assert not any(i.rule == "VENDOR_NOT_IN_PLEX" for i in result.warns)

    def test_vendor_api_disabled_skips_check(self, fake_client):
        fake_client.set_response("suppliers", [{"name": "OnlyThis"}])
        tool = make_tool(vendor="NotInList")
        result = validate_library(
            tools=[tool],
            library_name="test",
            use_api=False,
            client=fake_client,
        )
        assert not any(i.rule == "VENDOR_NOT_IN_PLEX" for i in result.warns)

    def test_supplier_api_failure_does_not_abort(self, fake_client):
        fake_client.set_response("suppliers", None)  # API returned nothing
        tool = make_tool(vendor="Anyone")
        result = validate_library(
            tools=[tool],
            library_name="test",
            use_api=True,
            client=fake_client,
        )
        # Validation still runs and passes; vendor check is silently skipped
        assert result.passed is True


# ─────────────────────────────────────────────
# Per-tool rules — geometry
# ─────────────────────────────────────────────

class TestGeometryRules:
    def test_missing_geometry_warns(self):
        tool = make_tool()
        del tool["geometry"]
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is True
        assert any(i.rule == "GEOMETRY_MISSING" for i in result.warns)

    def test_dc_missing_warns(self):
        tool = make_tool()
        del tool["geometry"]["DC"]
        result = validate_library(tools=[tool], library_name="test")
        assert any(i.rule == "GEOMETRY_DC_MISSING" for i in result.warns)

    def test_dc_zero_fails(self):
        tool = make_tool()
        tool["geometry"]["DC"] = 0
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is False
        assert any(i.rule == "GEOMETRY_DC_NONPOSITIVE" for i in result.fails)

    def test_dc_negative_fails(self):
        tool = make_tool()
        tool["geometry"]["DC"] = -0.125
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is False
        assert any(i.rule == "GEOMETRY_DC_NONPOSITIVE" for i in result.fails)

    def test_oal_missing_warns(self):
        tool = make_tool()
        del tool["geometry"]["OAL"]
        result = validate_library(tools=[tool], library_name="test")
        assert any(i.rule == "GEOMETRY_OAL_MISSING" for i in result.warns)

    def test_oal_shorter_than_dc_warns(self):
        tool = make_tool()
        tool["geometry"]["DC"] = 1.0
        tool["geometry"]["OAL"] = 0.5
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is True
        assert any(
            i.rule == "GEOMETRY_OAL_SHORTER_THAN_DC" for i in result.warns
        )

    def test_nof_missing_warns(self):
        tool = make_tool()
        del tool["geometry"]["NOF"]
        result = validate_library(tools=[tool], library_name="test")
        assert any(i.rule == "GEOMETRY_NOF_MISSING" for i in result.warns)

    def test_nof_zero_fails(self):
        tool = make_tool()
        tool["geometry"]["NOF"] = 0
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is False
        assert any(i.rule == "GEOMETRY_NOF_NONPOSITIVE" for i in result.fails)


# ─────────────────────────────────────────────
# Per-tool rules — post-process
# ─────────────────────────────────────────────

class TestPostProcessRules:
    def test_missing_post_process_warns(self):
        tool = make_tool()
        del tool["post-process"]
        result = validate_library(tools=[tool], library_name="test")
        assert result.passed is True
        assert any(i.rule == "POSTPROCESS_NUMBER_MISSING" for i in result.warns)

    def test_post_process_number_missing_warns(self):
        tool = make_tool()
        tool["post-process"] = {}
        result = validate_library(tools=[tool], library_name="test")
        assert any(i.rule == "POSTPROCESS_NUMBER_MISSING" for i in result.warns)

    def test_post_process_number_zero_warns(self):
        tool = make_tool()
        tool["post-process"]["number"] = 0
        result = validate_library(tools=[tool], library_name="test")
        assert any(
            i.rule == "POSTPROCESS_NUMBER_NONPOSITIVE" for i in result.warns
        )

    def test_post_process_number_negative_warns(self):
        tool = make_tool()
        tool["post-process"]["number"] = -3
        result = validate_library(tools=[tool], library_name="test")
        assert any(
            i.rule == "POSTPROCESS_NUMBER_NONPOSITIVE" for i in result.warns
        )


# ─────────────────────────────────────────────
# Filtering — holders and probes skipped
# ─────────────────────────────────────────────

class TestSyncCandidateFiltering:
    def test_holders_and_probes_not_per_tool_checked(self):
        # A bare-bones holder (no geometry, no vendor, no product-id) must
        # NOT produce any per-tool issues when a valid sync candidate exists.
        tools = [make_tool(), make_holder(), make_probe()]
        result = validate_library(tools=tools, library_name="test")
        assert result.passed is True
        assert result.sync_candidate_count == 1

    def test_sync_candidate_count_correct(self):
        tools = [
            make_tool(),
            make_tool(guid="t2"),
            make_holder(),
            make_probe(),
        ]
        # Ensure product-ids are unique to avoid DUPLICATE_PRODUCT_ID
        tools[1]["product-id"] = "DIFFERENT-PID"
        result = validate_library(tools=tools, library_name="test")
        assert result.sync_candidate_count == 2
        assert result.tool_count == 4


# ─────────────────────────────────────────────
# ValidationResult + format_result
# ─────────────────────────────────────────────

class TestResultObject:
    def test_summary_pass(self):
        result = validate_library(tools=[make_tool()], library_name="LIB1")
        assert "PASS" in result.summary()
        assert "LIB1" in result.summary()

    def test_summary_fail(self):
        result = validate_library(tools=[], library_name="LIB1")
        assert "FAIL" in result.summary()

    def test_to_dict_roundtrip(self):
        result = validate_library(tools=[make_tool()], library_name="LIB1")
        d = result.to_dict()
        assert d["library_name"] == "LIB1"
        assert d["passed"] is True
        assert isinstance(d["issues"], list)

    def test_debug_mode_populates_trace(self):
        result = validate_library(
            tools=[make_tool()],
            library_name="LIB1",
            mode=ValidationMode.DEBUG,
        )
        assert result.debug_trace is not None
        assert len(result.debug_trace) > 0

    def test_production_mode_trace_is_none(self):
        result = validate_library(
            tools=[make_tool()],
            library_name="LIB1",
            mode=ValidationMode.PRODUCTION,
        )
        assert result.debug_trace is None

    def test_format_result_pass(self):
        result = validate_library(tools=[make_tool()], library_name="LIB1")
        output = format_result(result, ValidationMode.PRODUCTION)
        assert "PASS" in output
        assert "LIB1" in output

    def test_format_result_fail_shows_error(self):
        tool = make_tool()
        del tool["product-id"]
        result = validate_library(tools=[tool], library_name="LIB1")
        output = format_result(result, ValidationMode.PRODUCTION)
        assert "FAIL" in output
        assert "REQUIRED_FIELD" in output
        assert "product-id" in output

    def test_format_result_verbose_shows_warns(self):
        tool = make_tool()
        del tool["vendor"]
        result = validate_library(tools=[tool], library_name="LIB1")
        prod_out = format_result(result, ValidationMode.PRODUCTION)
        verbose_out = format_result(result, ValidationMode.VERBOSE)
        assert "VENDOR_MISSING" not in prod_out
        assert "VENDOR_MISSING" in verbose_out


# ─────────────────────────────────────────────
# Edit distance helper
# ─────────────────────────────────────────────

class TestEditDistance:
    def test_zero_for_identical(self):
        assert _edit_distance("abc", "abc") == 0

    def test_one_for_single_edit(self):
        assert _edit_distance("abc", "abd") == 1

    def test_closest_supplier_names(self):
        names = ["Sandvik", "Garr Tool Co.", "OSG"]
        closest = _closest_supplier_names("Garr Tool", names, n=2)
        assert len(closest) == 2
        # "Garr Tool Co." shares the full "Garr Tool" prefix (distance 4)
        # and should be the closest match by a wide margin.
        assert closest[0][0] == "Garr Tool Co."


# ─────────────────────────────────────────────
# Supplier cache
# ─────────────────────────────────────────────

class TestSupplierCache:
    def test_cache_populated_on_first_call(self, fake_client):
        fake_client.set_response("suppliers", [{"name": "A"}, {"name": "B"}])
        names1 = _get_supplier_names(fake_client)
        assert set(names1) == {"A", "B"}

    def test_cache_returns_same_on_second_call(self, fake_client):
        fake_client.set_response("suppliers", [{"name": "First"}])
        _get_supplier_names(fake_client)
        # Change the canned response — cache should still return the first set
        fake_client.set_response("suppliers", [{"name": "Changed"}])
        names2 = _get_supplier_names(fake_client)
        assert "First" in names2
        assert "Changed" not in names2

    def test_cache_resets_with_helper(self, fake_client):
        fake_client.set_response("suppliers", [{"name": "First"}])
        _get_supplier_names(fake_client)
        _reset_supplier_cache()
        fake_client.set_response("suppliers", [{"name": "Second"}])
        names2 = _get_supplier_names(fake_client)
        assert "Second" in names2


# ─────────────────────────────────────────────
# Integration with tool_library_loader
# ─────────────────────────────────────────────

class TestLoaderIntegration:
    def test_loader_returns_none_on_validation_failure(self, tmp_path):
        import json
        from tool_library_loader import load_library

        bad = {
            "data": [
                {"guid": "g1", "type": "flat end mill", "description": "test"}
                # no product-id → REQUIRED_FIELD FAIL
            ]
        }
        f = tmp_path / "bad.json"
        f.write_text(json.dumps(bad), encoding="utf-8")
        result = load_library(f, validate=True)
        assert result is None

    def test_loader_returns_tools_on_validation_pass(self, tmp_path):
        import json
        from tool_library_loader import load_library

        good = {"data": [make_tool()]}
        f = tmp_path / "good.json"
        f.write_text(json.dumps(good), encoding="utf-8")
        result = load_library(f, validate=True)
        assert result is not None
        assert len(result) == 1

    def test_loader_validate_false_is_default(self, tmp_path):
        # Ensure validate defaults to False and does not break existing
        # test fixtures that use partial tool dicts.
        import json
        from tool_library_loader import load_library

        partial = {
            "data": [
                {"guid": "g1", "type": "drill", "description": "1/4 drill"}
            ]
        }
        f = tmp_path / "partial.json"
        f.write_text(json.dumps(partial), encoding="utf-8")
        result = load_library(f)  # no validate kwarg
        assert result is not None
        assert len(result) == 1
