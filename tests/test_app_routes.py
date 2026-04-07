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
