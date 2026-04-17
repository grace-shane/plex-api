"""
Tests for plex_api.PlexClient — header construction, configuration,
and the get_envelope() method.
"""
import importlib
import os
from unittest.mock import MagicMock, patch

import pytest
import requests

import plex_api
from plex_api import (
    PlexClient,
    BASE_URL,
    TEST_URL,
    GRACE_TENANT_ID,
    extract_supply_items,
    TOOLING_CATEGORY,
)


# ─────────────────────────────────────────────
# Header construction
# ─────────────────────────────────────────────
class TestPlexClientHeaders:
    def test_sets_api_key_header(self):
        c = PlexClient(api_key="my-key")
        assert c.headers["X-Plex-Connect-Api-Key"] == "my-key"

    def test_sets_api_secret_header_when_provided(self):
        c = PlexClient(api_key="k", api_secret="my-secret")
        assert c.headers["X-Plex-Connect-Api-Secret"] == "my-secret"

    def test_omits_api_secret_header_when_empty(self):
        c = PlexClient(api_key="k", api_secret="")
        assert "X-Plex-Connect-Api-Secret" not in c.headers

    def test_omits_api_secret_header_by_default(self):
        c = PlexClient(api_key="k")
        assert "X-Plex-Connect-Api-Secret" not in c.headers

    def test_sets_tenant_id_header_when_provided(self):
        c = PlexClient(api_key="k", tenant_id="abc-123")
        assert c.headers["X-Plex-Connect-Tenant-Id"] == "abc-123"

    def test_omits_tenant_id_header_when_empty(self):
        c = PlexClient(api_key="k", tenant_id="")
        assert "X-Plex-Connect-Tenant-Id" not in c.headers

    def test_sets_content_type_and_accept_headers(self):
        c = PlexClient(api_key="k")
        assert c.headers["Content-Type"] == "application/json"
        assert c.headers["Accept"] == "application/json"

    def test_all_three_auth_headers_when_full_credentials(self):
        c = PlexClient(api_key="k", api_secret="s", tenant_id="t")
        assert c.headers["X-Plex-Connect-Api-Key"] == "k"
        assert c.headers["X-Plex-Connect-Api-Secret"] == "s"
        assert c.headers["X-Plex-Connect-Tenant-Id"] == "t"


# ─────────────────────────────────────────────
# Environment routing
# ─────────────────────────────────────────────
class TestPlexClientEnvironment:
    @pytest.fixture(autouse=True)
    def _no_base_url_override(self, monkeypatch):
        """Ensure PLEX_BASE_URL is unset + module reloaded so OVERRIDE_URL == ''."""
        monkeypatch.delenv("PLEX_BASE_URL", raising=False)
        import importlib
        importlib.reload(plex_api)
        yield
        importlib.reload(plex_api)

    def test_use_test_true_uses_test_url(self):
        c = PlexClient(api_key="k", use_test=True)
        assert c.base == TEST_URL
        assert "test." in c.base

    def test_use_test_false_uses_prod_url(self):
        c = PlexClient(api_key="k", use_test=False)
        assert c.base == BASE_URL
        assert "test." not in c.base

    def test_use_test_default_is_prod(self):
        # Default constructor arg is use_test=False
        c = PlexClient(api_key="k")
        assert c.base == BASE_URL

    def test_explicit_base_url_arg_wins(self):
        c = PlexClient(api_key="k", base_url="http://localhost:8080")
        assert c.base == "http://localhost:8080"

    def test_explicit_base_url_arg_wins_even_over_use_test(self):
        c = PlexClient(api_key="k", use_test=True, base_url="http://localhost:8080")
        assert c.base == "http://localhost:8080"

    def test_empty_base_url_falls_through_to_default(self, monkeypatch):
        monkeypatch.delenv("PLEX_BASE_URL", raising=False)
        import importlib
        importlib.reload(plex_api)
        c = plex_api.PlexClient(api_key="k", base_url="")
        assert c.base == plex_api.BASE_URL
        c = plex_api.PlexClient(api_key="k", base_url="   ")
        assert c.base == plex_api.BASE_URL
        importlib.reload(plex_api)


# ─────────────────────────────────────────────
# Throttle initialization
# ─────────────────────────────────────────────
class TestPlexClientThrottle:
    def test_throttle_state_initialized(self):
        c = PlexClient(api_key="k")
        assert c._call_count == 0
        assert c._window_start > 0

    def test_throttle_increments_call_count(self):
        c = PlexClient(api_key="k")
        c._throttle()
        assert c._call_count == 1
        c._throttle()
        assert c._call_count == 2


# ─────────────────────────────────────────────
# Module-level config: env-var driven defaults
# ─────────────────────────────────────────────
class TestModuleDefaults:
    def test_grace_tenant_id_constant_is_verified_uuid(self):
        # The verified Grace tenant ID returned by the live API on 2026-04-07
        assert GRACE_TENANT_ID == "58f781ba-1691-4f32-b1db-381cdb21300c"

    def test_tenant_id_defaults_to_grace_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("PLEX_TENANT_ID", raising=False)
        importlib.reload(plex_api)
        assert plex_api.TENANT_ID == GRACE_TENANT_ID
        # Restore for downstream tests
        importlib.reload(plex_api)

    def test_tenant_id_uses_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("PLEX_TENANT_ID", "custom-tenant-uuid")
        importlib.reload(plex_api)
        assert plex_api.TENANT_ID == "custom-tenant-uuid"
        importlib.reload(plex_api)

    def test_use_test_defaults_false(self, monkeypatch):
        monkeypatch.delenv("PLEX_USE_TEST", raising=False)
        importlib.reload(plex_api)
        assert plex_api.USE_TEST is False
        importlib.reload(plex_api)

    def test_use_test_true_when_env_var_is_1(self, monkeypatch):
        monkeypatch.setenv("PLEX_USE_TEST", "1")
        importlib.reload(plex_api)
        assert plex_api.USE_TEST is True
        importlib.reload(plex_api)

    def test_use_test_true_when_env_var_is_true(self, monkeypatch):
        monkeypatch.setenv("PLEX_USE_TEST", "true")
        importlib.reload(plex_api)
        assert plex_api.USE_TEST is True
        importlib.reload(plex_api)

    def test_use_test_false_when_env_var_is_garbage(self, monkeypatch):
        monkeypatch.setenv("PLEX_USE_TEST", "nope")
        importlib.reload(plex_api)
        assert plex_api.USE_TEST is False
        importlib.reload(plex_api)

    def test_override_url_empty_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("PLEX_BASE_URL", raising=False)
        importlib.reload(plex_api)
        assert plex_api.OVERRIDE_URL == ""
        importlib.reload(plex_api)

    def test_override_url_set_from_env(self, monkeypatch):
        monkeypatch.setenv("PLEX_BASE_URL", "http://localhost:8080")
        importlib.reload(plex_api)
        assert plex_api.OVERRIDE_URL == "http://localhost:8080"
        importlib.reload(plex_api)

    def test_client_uses_override_url_when_env_set(self, monkeypatch):
        monkeypatch.setenv("PLEX_BASE_URL", "http://localhost:8080")
        importlib.reload(plex_api)
        c = plex_api.PlexClient(api_key="k")
        assert c.base == "http://localhost:8080"
        importlib.reload(plex_api)

    def test_client_override_url_wins_over_use_test(self, monkeypatch):
        monkeypatch.setenv("PLEX_BASE_URL", "http://localhost:8080")
        importlib.reload(plex_api)
        c = plex_api.PlexClient(api_key="k", use_test=True)
        assert c.base == "http://localhost:8080"
        importlib.reload(plex_api)

    def test_client_unchanged_when_override_unset(self, monkeypatch):
        monkeypatch.delenv("PLEX_BASE_URL", raising=False)
        importlib.reload(plex_api)
        c = plex_api.PlexClient(api_key="k")
        assert c.base == plex_api.BASE_URL
        importlib.reload(plex_api)


# ─────────────────────────────────────────────
# get_envelope() — structured success/error envelope
# ─────────────────────────────────────────────
def _mock_response(status, json_body=None, text="", reason="", url=""):
    """Build a MagicMock that mimics a requests.Response."""
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.reason = reason or {200: "OK", 401: "Unauthorized", 403: "Forbidden",
                          404: "Not Found", 500: "Internal Server Error"}.get(status, "")
    r.ok = 200 <= status < 300
    r.text = text
    r.url = url or "https://test.connect.plex.com/mdm/v1/x"
    if json_body is not None:
        r.json.return_value = json_body
    else:
        r.json.side_effect = ValueError("no json")
    return r


class TestGetEnvelopeSuccess:
    def test_returns_ok_envelope_for_200(self):
        c = PlexClient(api_key="k", api_secret="s", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(
            200, json_body=[{"id": "abc", "code": "G5"}]
        )):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["ok"] is True
        assert env["status"] == 200
        assert env["reason"] == "OK"
        assert env["body"] == [{"id": "abc", "code": "G5"}]
        assert env["error"] is None
        assert env["elapsed_ms"] >= 0

    def test_envelope_contains_url(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(
            200, json_body={}, url="https://test.connect.plex.com/mdm/v1/parts"
        )):
            env = c.get_envelope("mdm", "v1", "parts")
        assert "mdm/v1/parts" in env["url"]

    def test_text_body_when_json_parse_fails(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(
            200, json_body=None, text="not json"
        )):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["ok"] is True
        assert env["body"] == "not json"

    def test_none_body_when_text_empty_and_no_json(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(
            200, json_body=None, text=""
        )):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["body"] is None


class TestGetEnvelopeHttpErrors:
    def test_401_returns_error_envelope(self):
        c = PlexClient(api_key="k", api_secret="s", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(
            401, json_body={"code": "REQUEST_NOT_AUTHENTICATED"}
        )):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["ok"] is False
        assert env["status"] == 401
        assert env["reason"] == "Unauthorized"
        assert env["body"] == {"code": "REQUEST_NOT_AUTHENTICATED"}
        assert "401" in env["error"]
        assert "Unauthorized" in env["error"]

    def test_403_returns_error_envelope(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(403, json_body={})):
            env = c.get_envelope("tooling", "v1", "tools")
        assert env["ok"] is False
        assert env["status"] == 403

    def test_404_returns_error_envelope(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(404, json_body={})):
            env = c.get_envelope("mdm", "v1", "tenants/nonexistent")
        assert env["ok"] is False
        assert env["status"] == 404

    def test_500_returns_error_envelope(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(500, json_body={})):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["ok"] is False
        assert env["status"] == 500


class TestGetEnvelopeNetworkErrors:
    def test_connection_error_returns_status_zero(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["ok"] is False
        assert env["status"] == 0
        assert env["reason"] == "ConnectionError"
        assert env["body"] is None
        assert "refused" in env["error"]

    def test_timeout_returns_status_zero(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", side_effect=requests.exceptions.Timeout("timed out")):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["ok"] is False
        assert env["status"] == 0
        assert env["reason"] == "Timeout"

    def test_dns_failure_returns_status_zero(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", side_effect=requests.exceptions.ConnectionError("dns")):
            env = c.get_envelope("mdm", "v1", "tenants")
        assert env["status"] == 0


# ─────────────────────────────────────────────
# get() (legacy) — verify backward compat after refactor
# ─────────────────────────────────────────────
class TestGetLegacy:
    def test_get_returns_body_on_success(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(
            200, json_body={"items": [1, 2, 3]}
        )):
            result = c.get("mdm", "v1", "tenants")
        assert result == {"items": [1, 2, 3]}

    def test_get_returns_none_on_4xx(self, capsys):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", return_value=_mock_response(401, json_body={"code": "X"})):
            result = c.get("mdm", "v1", "tenants")
        assert result is None
        # Legacy stdout logging is preserved
        captured = capsys.readouterr()
        assert "401" in captured.out

    def test_get_returns_none_on_network_error(self):
        c = PlexClient(api_key="k", use_test=True)
        with patch("plex_api.requests.get", side_effect=requests.exceptions.ConnectionError("x")):
            result = c.get("mdm", "v1", "tenants")
        assert result is None


# ─────────────────────────────────────────────
# extract_supply_items — issue #2
# ─────────────────────────────────────────────
class TestExtractSupplyItems:
    SAMPLE_TOOLS_AND_INSERTS = [
        {"category": "Tools & Inserts", "supplyItemNumber": "990910", "description": "5/8 SQ END", "group": "Machining", "id": "u1", "inventoryUnit": "Each", "type": "SUPPLY"},
        {"category": "Tools & Inserts", "supplyItemNumber": "ABC123", "description": "1/4 drill", "group": "Tool Room", "id": "u2", "inventoryUnit": "Each", "type": "SUPPLY"},
    ]
    SAMPLE_OFFICE = [
        {"category": "Office Supplies", "supplyItemNumber": "PEN-01", "description": "Blue pen", "group": "Office", "id": "u3", "inventoryUnit": "Each", "type": "OFFICE"},
    ]

    def _full_set(self):
        return self.SAMPLE_TOOLS_AND_INSERTS + self.SAMPLE_OFFICE

    def test_default_filters_to_tools_and_inserts(self, fake_client, tmp_path, monkeypatch):
        # Redirect OUTPUT_DIR so the CSV write goes to tmp
        monkeypatch.setattr(plex_api, "OUTPUT_DIR", str(tmp_path))
        fake_client.set_response("inventory-definitions/supply-items", self._full_set())
        result = extract_supply_items(fake_client)
        assert result is not None
        assert len(result) == 2
        for r in result:
            assert r["category"] == TOOLING_CATEGORY

    def test_filter_can_be_disabled_with_empty_string(self, fake_client, tmp_path, monkeypatch):
        monkeypatch.setattr(plex_api, "OUTPUT_DIR", str(tmp_path))
        fake_client.set_response("inventory-definitions/supply-items", self._full_set())
        result = extract_supply_items(fake_client, category="")
        # All 3 records returned, no filter
        assert len(result) == 3

    def test_filter_can_be_overridden(self, fake_client, tmp_path, monkeypatch):
        monkeypatch.setattr(plex_api, "OUTPUT_DIR", str(tmp_path))
        fake_client.set_response("inventory-definitions/supply-items", self._full_set())
        result = extract_supply_items(fake_client, category="Office Supplies")
        assert len(result) == 1
        assert result[0]["category"] == "Office Supplies"

    def test_returns_none_on_network_error(self, fake_client):
        # No response set on the fake client → get returns None
        result = extract_supply_items(fake_client)
        assert result is None

    def test_calls_correct_endpoint(self, fake_client, tmp_path, monkeypatch):
        monkeypatch.setattr(plex_api, "OUTPUT_DIR", str(tmp_path))
        fake_client.set_response("inventory-definitions/supply-items", [])
        extract_supply_items(fake_client)
        # The fake client should have recorded a call to inventory/v1/inventory-definitions/supply-items
        calls = [c for c in fake_client.calls if c[0] == "inventory" and c[1] == "v1"]
        assert len(calls) == 1
        assert calls[0][2] == "inventory-definitions/supply-items"

    def test_normalizes_dict_data_wrapper(self, fake_client, tmp_path, monkeypatch):
        # Some Plex endpoints wrap the list in a dict — extract_supply_items
        # should handle either shape gracefully
        monkeypatch.setattr(plex_api, "OUTPUT_DIR", str(tmp_path))
        fake_client.set_response(
            "inventory-definitions/supply-items",
            {"data": self.SAMPLE_TOOLS_AND_INSERTS},
        )
        result = extract_supply_items(fake_client)
        assert len(result) == 2

    def test_writes_csv_snapshot(self, fake_client, tmp_path, monkeypatch):
        monkeypatch.setattr(plex_api, "OUTPUT_DIR", str(tmp_path))
        fake_client.set_response("inventory-definitions/supply-items", self._full_set())
        extract_supply_items(fake_client)
        csv_path = tmp_path / "plex_supply_items.csv"
        assert csv_path.exists()
        content = csv_path.read_text(encoding="utf-8")
        # Should have the 2 tools-and-inserts records, not the office one
        assert "990910" in content
        assert "ABC123" in content
        assert "PEN-01" not in content
