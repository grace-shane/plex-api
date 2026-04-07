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
from plex_api import PlexClient, BASE_URL, TEST_URL, GRACE_TENANT_ID


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
