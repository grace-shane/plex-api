"""
Tests for plex_diagnostics — tenant_whoami composite check.

Verifies all 6 logic branches:
  1. Connected to Grace
  2. Connected to G5
  3. Connected to a configured-but-unknown tenant
  4. Connected to an unrecognized tenant
  5. list_tenants returns None (auth failure)
  6. list_tenants returns empty list / no parseable IDs

Plus normalization of dict-wrapped responses (Plex sometimes returns
{"items": [...]}, {"data": [...]}, or a bare list).
"""
import pytest

from plex_diagnostics import (
    GRACE_TENANT_ID,
    GRACE_OLD_TENANT_ID,
    G5_TENANT_ID,
    KNOWN_TENANTS,
    list_tenants,
    get_tenant,
    tenant_whoami,
)


# ─────────────────────────────────────────────
# Constants sanity
# ─────────────────────────────────────────────
class TestKnownTenants:
    def test_grace_tenant_id_is_verified_uuid(self):
        # Verified empirically against the live API on 2026-04-07
        assert GRACE_TENANT_ID == "58f781ba-1691-4f32-b1db-381cdb21300c"

    def test_grace_tenant_id_in_known(self):
        assert GRACE_TENANT_ID in KNOWN_TENANTS
        assert KNOWN_TENANTS[GRACE_TENANT_ID] == "Grace Engineering"

    def test_grace_old_tenant_id_kept_as_stale(self):
        # The wrong UUID from earlier docs is preserved with a "stale" label
        # so anyone hitting it gets a clear signal instead of "unknown"
        assert GRACE_OLD_TENANT_ID == "a6af9c99-bce5-4938-a007-364dc5603d08"
        assert GRACE_OLD_TENANT_ID in KNOWN_TENANTS
        assert "stale" in KNOWN_TENANTS[GRACE_OLD_TENANT_ID].lower()

    def test_g5_tenant_id_in_known(self):
        assert G5_TENANT_ID in KNOWN_TENANTS
        assert KNOWN_TENANTS[G5_TENANT_ID] == "G5"

    def test_all_known_tenants_are_distinct(self):
        ids = [GRACE_TENANT_ID, GRACE_OLD_TENANT_ID, G5_TENANT_ID]
        assert len(set(ids)) == len(ids), "tenant IDs must be unique"


# ─────────────────────────────────────────────
# Raw wrappers — verify they call client.get with the right path
# ─────────────────────────────────────────────
class TestRawWrappers:
    def test_list_tenants_calls_correct_endpoint(self, fake_client):
        fake_client.set_response("tenants", [])
        list_tenants(fake_client)
        assert fake_client.calls[0][:3] == ("mdm", "v1", "tenants")

    def test_get_tenant_calls_correct_endpoint(self, fake_client):
        fake_client.set_default({"id": "abc"})
        get_tenant(fake_client, "abc-123")
        assert fake_client.calls[0][:3] == ("mdm", "v1", "tenants/abc-123")


# ─────────────────────────────────────────────
# tenant_whoami — match logic
# ─────────────────────────────────────────────
class TestTenantWhoami:
    def test_grace_match(self, fake_client):
        fake_client.set_response("tenants", [
            {"id": GRACE_TENANT_ID, "code": "GRACE", "name": "Grace Engineering"}
        ])
        report = tenant_whoami(fake_client, GRACE_TENANT_ID)
        assert report["match"] == "grace"
        assert "Grace Engineering" in report["summary"]
        assert "[OK]" in report["summary"]

    def test_g5_match(self, fake_client):
        fake_client.set_response("tenants", [
            {"id": G5_TENANT_ID, "code": "G5", "name": "G5 Manufacturing"}
        ])
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "g5"
        assert "G5" in report["summary"]
        assert "[WARN]" in report["summary"]

    def test_no_data_when_list_returns_none(self, fake_client):
        # No set_response → FakePlexClient.get_envelope synthesizes a 200 OK
        # with body=None → tenant_whoami should still report no_data because
        # there are no parseable IDs to work with.
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "no_data"
        assert "no data" in report["summary"].lower()

    def test_no_data_when_list_returns_empty(self, fake_client):
        fake_client.set_response("tenants", [])
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "no_data"
        assert "no data" in report["summary"].lower()

    def test_unknown_tenant_match(self, fake_client):
        unknown_id = "11111111-2222-3333-4444-555555555555"
        fake_client.set_response("tenants", [
            {"id": unknown_id, "code": "UNK", "name": "Unknown Co"}
        ])
        report = tenant_whoami(fake_client, unknown_id)
        assert report["match"] == "configured"
        assert "Verify this is intentional" in report["summary"]

    def test_other_match_when_visible_unrecognized_and_no_config(self, fake_client):
        unknown_id = "11111111-2222-3333-4444-555555555555"
        fake_client.set_response("tenants", [
            {"id": unknown_id, "code": "UNK"}
        ])
        report = tenant_whoami(fake_client, "")
        assert report["match"] == "other"

    def test_grace_takes_priority_over_configured_g5(self, fake_client):
        # Edge case: visible tenants include Grace, but TENANT_ID is still G5.
        # The match should be "grace" because the routing has actually landed.
        fake_client.set_response("tenants", [
            {"id": GRACE_TENANT_ID, "code": "GRACE"}
        ])
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "grace"


# ─────────────────────────────────────────────
# Response shape normalization
# ─────────────────────────────────────────────
class TestResponseNormalization:
    def test_handles_bare_list_response(self, fake_client):
        fake_client.set_response("tenants", [
            {"id": G5_TENANT_ID, "code": "G5"}
        ])
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert len(report["visible_tenants"]) == 1

    def test_handles_dict_data_wrapper(self, fake_client):
        fake_client.set_response("tenants", {
            "data": [{"id": G5_TENANT_ID, "code": "G5"}]
        })
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert len(report["visible_tenants"]) == 1
        assert report["match"] == "g5"

    def test_handles_dict_items_wrapper(self, fake_client):
        fake_client.set_response("tenants", {
            "items": [{"id": G5_TENANT_ID, "code": "G5"}]
        })
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert len(report["visible_tenants"]) == 1

    def test_handles_dict_rows_wrapper(self, fake_client):
        fake_client.set_response("tenants", {
            "rows": [{"id": G5_TENANT_ID, "code": "G5"}]
        })
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert len(report["visible_tenants"]) == 1

    def test_handles_single_object_response(self, fake_client):
        # Some endpoints return a bare object instead of a list
        fake_client.set_response("tenants", {
            "id": G5_TENANT_ID, "code": "G5"
        })
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert len(report["visible_tenants"]) == 1
        assert report["match"] == "g5"


# ─────────────────────────────────────────────
# Report structure
# ─────────────────────────────────────────────
class TestReportStructure:
    def test_report_has_required_keys(self, fake_client):
        fake_client.set_response("tenants", [{"id": G5_TENANT_ID}])
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        for key in (
            "configured_tenant_id",
            "configured_tenant_label",
            "visible_tenants",
            "list_tenants_raw",
            "get_tenant_raw",
            "match",
            "summary",
        ):
            assert key in report

    def test_report_records_configured_label(self, fake_client):
        fake_client.set_response("tenants", [{"id": G5_TENANT_ID}])
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["configured_tenant_label"] == "G5"

    def test_report_records_unknown_label_for_unknown_id(self, fake_client):
        unknown = "deadbeef-dead-beef-dead-beefdeadbeef"
        fake_client.set_response("tenants", [{"id": unknown}])
        report = tenant_whoami(fake_client, unknown)
        assert report["configured_tenant_label"] == "unknown"

    def test_get_tenant_called_when_configured_id_provided(self, fake_client):
        fake_client.set_response("tenants", [{"id": G5_TENANT_ID}])
        fake_client.set_response(f"tenants/{G5_TENANT_ID}", {"id": G5_TENANT_ID, "name": "G5 Detail"})
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["get_tenant_raw"] is not None
        # Two calls should have been made: list + get
        assert any(c[2] == "tenants" for c in fake_client.calls)
        assert any(c[2] == f"tenants/{G5_TENANT_ID}" for c in fake_client.calls)

    def test_get_tenant_skipped_when_no_configured_id(self, fake_client):
        fake_client.set_response("tenants", [{"id": G5_TENANT_ID}])
        report = tenant_whoami(fake_client, "")
        assert report["get_tenant_raw"] is None

    def test_report_includes_envelope_metadata(self, fake_client):
        fake_client.set_response("tenants", [{"id": G5_TENANT_ID}])
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        env = report["list_tenants_envelope"]
        assert env is not None
        assert env["ok"] is True
        assert env["status"] == 200
        assert env["error"] is None


# ─────────────────────────────────────────────
# HTTP error visibility — the whole reason for this PR
# ─────────────────────────────────────────────
def _err_envelope(status, reason, error_msg, body=None):
    """Build a fake error envelope as PlexClient.get_envelope would return."""
    return {
        "ok": False,
        "status": status,
        "reason": reason,
        "body": body,
        "elapsed_ms": 100,
        "url": "https://test.connect.plex.com/mdm/v1/tenants",
        "error": error_msg,
    }


class TestAuthFailureBranch:
    def test_401_maps_to_auth_failed(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            401, "Unauthorized", "HTTP 401 Unauthorized",
            body={"code": "REQUEST_NOT_AUTHENTICATED"}
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "auth_failed"
        assert "401" in report["summary"]
        assert "PLEX_API_KEY" in report["summary"]
        assert "PLEX_API_SECRET" in report["summary"]

    def test_403_maps_to_auth_failed(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            403, "Forbidden", "HTTP 403 Forbidden"
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "auth_failed"
        assert "403" in report["summary"]

    def test_auth_failed_preserves_envelope_metadata(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            401, "Unauthorized", "HTTP 401 Unauthorized"
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        env = report["list_tenants_envelope"]
        assert env["ok"] is False
        assert env["status"] == 401
        assert env["error"] == "HTTP 401 Unauthorized"

    def test_auth_failed_does_not_call_get_tenant(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            401, "Unauthorized", "x"
        ))
        tenant_whoami(fake_client, G5_TENANT_ID)
        # Only the list call should have been made, not the by-id call
        list_calls = [c for c in fake_client.calls if c[2] == "tenants"]
        get_calls = [c for c in fake_client.calls if c[2] == f"tenants/{G5_TENANT_ID}"]
        assert len(list_calls) == 1
        assert len(get_calls) == 0


class TestRequestFailedBranch:
    def test_network_error_maps_to_request_failed(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            0, "ConnectionError", "Connection refused"
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "request_failed"
        assert "could not reach" in report["summary"].lower()
        assert "Connection refused" in report["summary"]

    def test_timeout_maps_to_request_failed(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            0, "Timeout", "Read timed out"
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "request_failed"

    def test_404_maps_to_request_failed(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            404, "Not Found", "HTTP 404 Not Found"
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "request_failed"
        assert "404" in report["summary"]

    def test_500_maps_to_request_failed(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            500, "Internal Server Error", "HTTP 500 Internal Server Error"
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        assert report["match"] == "request_failed"
        assert "500" in report["summary"]

    def test_request_failed_preserves_envelope_metadata(self, fake_client):
        fake_client.set_envelope("tenants", _err_envelope(
            500, "Internal Server Error", "HTTP 500"
        ))
        report = tenant_whoami(fake_client, G5_TENANT_ID)
        env = report["list_tenants_envelope"]
        assert env["status"] == 500
        assert env["ok"] is False
