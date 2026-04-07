"""
Tests for the Flask routes in app.py.

These are smoke tests — they verify that each route registers, responds
with the right shape, and doesn't blow up. The actual Plex client and
diagnostics are mocked so no real network calls happen.
"""
from unittest.mock import patch, MagicMock

import pytest

# conftest.py has already injected dummy PLEX_API_KEY/SECRET into env
import app as app_module


@pytest.fixture
def client():
    """Flask test client."""
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


# ─────────────────────────────────────────────
# Index
# ─────────────────────────────────────────────
class TestIndex:
    def test_index_returns_html(self, client):
        rv = client.get("/")
        assert rv.status_code == 200
        assert b"<!DOCTYPE html>" in rv.data
        assert b"plex-api" in rv.data


# ─────────────────────────────────────────────
# /api/config
# ─────────────────────────────────────────────
class TestConfig:
    def test_config_returns_expected_keys(self, client):
        rv = client.get("/api/config")
        assert rv.status_code == 200
        body = rv.get_json()
        for key in ("base_url", "environment", "tenant_id", "has_key", "has_secret"):
            assert key in body

    def test_config_environment_is_test_or_prod(self, client):
        rv = client.get("/api/config")
        body = rv.get_json()
        assert body["environment"] in ("test", "production")

    def test_config_reports_credentials_present(self, client):
        rv = client.get("/api/config")
        body = rv.get_json()
        # conftest.py injects dummy values, so both should be True
        assert body["has_key"] is True
        assert body["has_secret"] is True


# ─────────────────────────────────────────────
# /api/diagnostics/tenant
# ─────────────────────────────────────────────
class TestDiagnosticsTenant:
    def test_returns_success_envelope(self, client):
        with patch.object(app_module, "tenant_whoami") as mock_whoami:
            mock_whoami.return_value = {
                "match": "g5",
                "summary": "test summary",
                "configured_tenant_label": "G5",
            }
            rv = client.get("/api/diagnostics/tenant")
            assert rv.status_code == 200
            body = rv.get_json()
            assert body["status"] == "success"
            assert body["data"]["match"] == "g5"
            assert body["data"]["summary"] == "test summary"

    def test_passes_configured_tenant_id_to_whoami(self, client):
        with patch.object(app_module, "tenant_whoami") as mock_whoami:
            mock_whoami.return_value = {"match": "g5", "summary": ""}
            client.get("/api/diagnostics/tenant")
            mock_whoami.assert_called_once()
            # Second positional arg is the configured tenant ID
            call_args = mock_whoami.call_args
            assert call_args[0][1] == app_module.TENANT_ID

    def test_returns_500_on_exception(self, client):
        with patch.object(app_module, "tenant_whoami", side_effect=RuntimeError("boom")):
            rv = client.get("/api/diagnostics/tenant")
            assert rv.status_code == 500
            body = rv.get_json()
            assert body["status"] == "error"
            assert "boom" in body["message"]


# ─────────────────────────────────────────────
# /api/diagnostics/tenants/list
# ─────────────────────────────────────────────
class TestDiagnosticsTenantsList:
    def test_returns_list_payload(self, client):
        with patch.object(app_module, "list_tenants") as mock_list:
            mock_list.return_value = [{"id": "abc", "code": "TEST"}]
            rv = client.get("/api/diagnostics/tenants/list")
            assert rv.status_code == 200
            body = rv.get_json()
            assert body["status"] == "success"
            assert body["data"] == [{"id": "abc", "code": "TEST"}]


# ─────────────────────────────────────────────
# /api/diagnostics/tenants/<id>
# ─────────────────────────────────────────────
class TestDiagnosticsTenantById:
    def test_passes_id_to_get_tenant(self, client):
        with patch.object(app_module, "get_tenant") as mock_get:
            mock_get.return_value = {"id": "abc-123", "name": "Test"}
            rv = client.get("/api/diagnostics/tenants/abc-123")
            assert rv.status_code == 200
            mock_get.assert_called_once()
            assert mock_get.call_args[0][1] == "abc-123"


# ─────────────────────────────────────────────
# /api/plex/raw — proxy
# ─────────────────────────────────────────────
class TestPlexRawProxy:
    def test_missing_path_returns_400(self, client):
        rv = client.get("/api/plex/raw")
        assert rv.status_code == 400
        body = rv.get_json()
        assert "Missing required" in body["message"]

    def test_forwards_get_to_plex(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.ok = True
        mock_response.content = b'{"items":[]}'
        mock_response.json.return_value = {"items": []}
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.url = "https://test.connect.plex.com/mdm/v1/parts"

        with patch.object(app_module.requests, "request", return_value=mock_response) as mock_req:
            rv = client.get("/api/plex/raw?path=mdm/v1/parts")
            assert rv.status_code == 200
            body = rv.get_json()
            assert body["status"] == "success"
            assert body["http_status"] == 200
            assert body["method"] == "GET"
            assert body["body"] == {"items": []}

            # Verify the proxy actually forwarded to the right URL with the
            # client's auth headers
            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args.kwargs
            assert "mdm/v1/parts" in call_kwargs["url"]
            assert "X-Plex-Connect-Api-Key" in call_kwargs["headers"]

    def test_strips_path_query_param_from_forwarded_params(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.ok = True
        mock_response.content = b"{}"
        mock_response.json.return_value = {}
        mock_response.headers = {}
        mock_response.url = "https://test.connect.plex.com/mdm/v1/parts"

        with patch.object(app_module.requests, "request", return_value=mock_response) as mock_req:
            client.get("/api/plex/raw?path=mdm/v1/parts&limit=5&status=Active")
            forwarded = mock_req.call_args.kwargs["params"]
            assert "path" not in forwarded
            assert forwarded["limit"] == "5"
            assert forwarded["status"] == "Active"

    def test_error_response_propagates_status(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.reason = "Forbidden"
        mock_response.ok = False
        mock_response.content = b'{"error":"forbidden"}'
        mock_response.json.return_value = {"error": "forbidden"}
        mock_response.headers = {}
        mock_response.url = "https://test.connect.plex.com/tooling/v1/tools"

        with patch.object(app_module.requests, "request", return_value=mock_response):
            rv = client.get("/api/plex/raw?path=tooling/v1/tools")
            assert rv.status_code == 200  # envelope status, not the inner one
            body = rv.get_json()
            assert body["status"] == "error"
            assert body["http_status"] == 403


# ─────────────────────────────────────────────
# /api/plex/discover
# ─────────────────────────────────────────────
class TestDiscover:
    def test_calls_discover_all(self, client):
        with patch.object(app_module, "discover_all") as mock_discover:
            mock_discover.return_value = [{"endpoint": "x", "status": 200}]
            rv = client.get("/api/plex/discover")
            assert rv.status_code == 200
            body = rv.get_json()
            assert body["status"] == "success"
            assert body["data"] == [{"endpoint": "x", "status": 200}]


# ─────────────────────────────────────────────
# Production write guard
# ─────────────────────────────────────────────
class TestProductionWriteGuard:
    """
    The /api/plex/raw proxy must refuse mutating methods (POST/PUT/PATCH/
    DELETE) when running against a production Plex environment unless
    PLEX_ALLOW_WRITES is explicitly enabled.

    These tests temporarily flip the module-level IS_PRODUCTION and
    WRITES_ALLOWED constants since they're computed at import time from
    env vars (which conftest.py has already locked in).
    """

    def test_get_always_allowed_in_production(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.ok = True
        mock_response.content = b"{}"
        mock_response.json.return_value = {}
        mock_response.headers = {}
        mock_response.url = "https://connect.plex.com/mdm/v1/tenants"

        with patch.object(app_module.requests, "request", return_value=mock_response):
            rv = client.get("/api/plex/raw?path=mdm/v1/tenants")
            assert rv.status_code == 200
            assert rv.get_json()["status"] == "success"

    def test_post_blocked_in_production_without_writes_allowed(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)

        rv = client.post("/api/plex/raw?path=mdm/v1/parts", json={"foo": "bar"})
        assert rv.status_code == 403
        body = rv.get_json()
        assert body["status"] == "error"
        assert body["guard"] == "PLEX_ALLOW_WRITES"
        assert body["is_production"] is True
        assert body["writes_allowed"] is False
        assert "PLEX_ALLOW_WRITES" in body["message"]
        assert "POST" in body["message"]

    def test_put_blocked_in_production_without_writes_allowed(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)

        rv = client.put("/api/plex/raw?path=mdm/v1/parts/x", json={"foo": "bar"})
        assert rv.status_code == 403
        assert rv.get_json()["guard"] == "PLEX_ALLOW_WRITES"

    def test_patch_blocked_in_production_without_writes_allowed(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)

        rv = client.patch("/api/plex/raw?path=mdm/v1/parts/x", json={"foo": "bar"})
        assert rv.status_code == 403

    def test_delete_blocked_in_production_without_writes_allowed(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)

        rv = client.delete("/api/plex/raw?path=mdm/v1/parts/x")
        assert rv.status_code == 403

    def test_post_allowed_in_production_when_writes_enabled(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", True)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.reason = "Created"
        mock_response.ok = True
        mock_response.content = b'{"id":"new"}'
        mock_response.json.return_value = {"id": "new"}
        mock_response.headers = {}
        mock_response.url = "https://connect.plex.com/mdm/v1/parts"

        with patch.object(app_module.requests, "request", return_value=mock_response):
            rv = client.post("/api/plex/raw?path=mdm/v1/parts", json={"foo": "bar"})
            assert rv.status_code == 200  # envelope is 200; inner http_status is 201
            body = rv.get_json()
            assert body["status"] == "success"
            assert body["http_status"] == 201

    def test_post_allowed_in_test_environment_regardless(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", False)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.ok = True
        mock_response.content = b"{}"
        mock_response.json.return_value = {}
        mock_response.headers = {}
        mock_response.url = "https://test.connect.plex.com/mdm/v1/parts"

        with patch.object(app_module.requests, "request", return_value=mock_response):
            rv = client.post("/api/plex/raw?path=mdm/v1/parts", json={"foo": "bar"})
            assert rv.status_code == 200

    def test_config_endpoint_exposes_guard_state(self, client):
        rv = client.get("/api/config")
        body = rv.get_json()
        assert "is_production" in body
        assert "writes_allowed" in body
        assert isinstance(body["is_production"], bool)
        assert isinstance(body["writes_allowed"], bool)


# ─────────────────────────────────────────────
# Helper function _is_write_blocked
# ─────────────────────────────────────────────
class TestIsWriteBlocked:
    def test_get_never_blocked_in_production(self, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)
        blocked, reason = app_module._is_write_blocked("GET")
        assert blocked is False
        assert reason == ""

    def test_get_never_blocked_in_test(self, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", False)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)
        blocked, reason = app_module._is_write_blocked("GET")
        assert blocked is False

    def test_post_blocked_in_production_default(self, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)
        blocked, reason = app_module._is_write_blocked("POST")
        assert blocked is True
        assert "PLEX_ALLOW_WRITES" in reason

    def test_post_unblocked_in_test(self, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", False)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)
        blocked, reason = app_module._is_write_blocked("POST")
        assert blocked is False

    def test_post_unblocked_when_writes_enabled(self, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", True)
        blocked, reason = app_module._is_write_blocked("POST")
        assert blocked is False

    def test_method_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(app_module, "IS_PRODUCTION", True)
        monkeypatch.setattr(app_module, "WRITES_ALLOWED", False)
        blocked, _ = app_module._is_write_blocked("post")
        assert blocked is True
        blocked, _ = app_module._is_write_blocked("Delete")
        assert blocked is True
