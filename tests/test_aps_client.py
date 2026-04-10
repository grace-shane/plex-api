"""
Tests for aps_client.py — APS OAuth + Data Management client.

Focuses on:
  - Config errors when env vars are missing
  - OAuth URL generation
  - Token exchange and refresh mechanics
  - Token persistence to file
  - Hub/project/folder traversal (mocked HTTP)
  - .tools file download via signed S3 URL
  - Storage ID parsing (URN and URL formats)
  - Auto-refresh on expired tokens

All HTTP traffic is patched — no real network calls.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from aps_client import (
    APSClient,
    APSConfigError,
    APSAuthError,
    APSHTTPError,
    TokenStore,
)


# ─────────────────────────────────────────────
# Token store — in-memory (path=None)
# ─────────────────────────────────────────────
class TestTokenStore:
    def test_initially_invalid(self):
        store = TokenStore(path=None)
        assert not store.is_valid

    def test_update_makes_valid(self):
        store = TokenStore(path=None)
        store.update({
            "access_token": "tok123",
            "refresh_token": "ref456",
            "expires_in": 3600,
        })
        assert store.is_valid
        assert store.access_token == "tok123"
        assert store.refresh_token == "ref456"

    def test_expired_token_is_invalid(self):
        store = TokenStore(path=None)
        store.update({
            "access_token": "tok",
            "expires_in": 0,  # already expired (minus 60s buffer)
        })
        assert not store.is_valid

    def test_clear_invalidates(self):
        store = TokenStore(path=None)
        store.update({"access_token": "tok", "expires_in": 3600})
        store.clear()
        assert not store.is_valid


# ─────────────────────────────────────────────
# Token store — file persistence
# ─────────────────────────────────────────────
class TestTokenPersistence:
    def test_save_and_load(self, tmp_path):
        token_file = tmp_path / ".aps_tokens.json"

        # Save tokens
        store1 = TokenStore(path=token_file)
        store1.update({
            "access_token": "persisted-at",
            "refresh_token": "persisted-rt",
            "expires_in": 3600,
        })
        assert token_file.exists()

        # Load into a new store
        store2 = TokenStore(path=token_file)
        assert store2.access_token == "persisted-at"
        assert store2.refresh_token == "persisted-rt"
        assert store2.is_valid

    def test_clear_deletes_file(self, tmp_path):
        token_file = tmp_path / ".aps_tokens.json"
        store = TokenStore(path=token_file)
        store.update({"access_token": "tok", "expires_in": 3600})
        assert token_file.exists()
        store.clear()
        assert not token_file.exists()

    def test_missing_file_is_ok(self, tmp_path):
        token_file = tmp_path / "nonexistent.json"
        store = TokenStore(path=token_file)
        assert not store.is_valid

    def test_corrupt_file_is_ok(self, tmp_path):
        token_file = tmp_path / ".aps_tokens.json"
        token_file.write_text("not json", encoding="utf-8")
        store = TokenStore(path=token_file)
        assert not store.is_valid


# ─────────────────────────────────────────────
# Config errors
# ─────────────────────────────────────────────
class TestConfigErrors:
    def test_missing_client_id_raises(self, monkeypatch):
        monkeypatch.delenv("APS_CLIENT_ID", raising=False)
        monkeypatch.delenv("APS_CLIENT_SECRET", raising=False)
        monkeypatch.setattr("aps_client.APS_CLIENT_ID", "")
        monkeypatch.setattr("aps_client.APS_CLIENT_SECRET", "s")
        client = APSClient(client_id="", client_secret="s", token_path=None)
        with pytest.raises(APSConfigError, match="APS_CLIENT_ID"):
            client._require_config()

    def test_missing_client_secret_raises(self, monkeypatch):
        monkeypatch.setattr("aps_client.APS_CLIENT_ID", "id")
        monkeypatch.setattr("aps_client.APS_CLIENT_SECRET", "")
        client = APSClient(client_id="id", client_secret="", token_path=None)
        with pytest.raises(APSConfigError, match="APS_CLIENT_SECRET"):
            client._require_config()

    def test_explicit_args_work(self):
        client = APSClient(
            client_id="my-id",
            client_secret="my-secret",
            callback_url="http://localhost:9999/cb",
            token_path=None,
        )
        assert client.client_id == "my-id"
        assert client.client_secret == "my-secret"
        assert client.callback_url == "http://localhost:9999/cb"


# ─────────────────────────────────────────────
# OAuth URL generation
# ─────────────────────────────────────────────
class TestAuthorizeURL:
    def test_url_contains_client_id(self):
        client = APSClient(client_id="test-id", client_secret="test-secret", token_path=None)
        url = client.get_authorize_url()
        assert "client_id=test-id" in url
        assert "response_type=code" in url
        assert "scope=data%3Aread" in url

    def test_url_contains_callback(self):
        client = APSClient(
            client_id="id",
            client_secret="s",
            callback_url="http://example.com/cb",
            token_path=None,
        )
        url = client.get_authorize_url()
        assert "redirect_uri=http%3A%2F%2Fexample.com%2Fcb" in url


# ─────────────────────────────────────────────
# Token exchange
# ─────────────────────────────────────────────
class TestExchangeCode:
    def test_successful_exchange(self):
        client = APSClient(client_id="id", client_secret="secret", token_path=None)
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
        }

        with patch.object(client._session, "post", return_value=mock_resp):
            data = client.exchange_code("authcode123")

        assert data["access_token"] == "at"
        assert client.tokens.is_valid

    def test_failed_exchange_raises(self):
        client = APSClient(client_id="id", client_secret="secret", token_path=None)
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.text = "invalid_grant"

        with patch.object(client._session, "post", return_value=mock_resp):
            with pytest.raises(APSAuthError, match="401"):
                client.exchange_code("badcode")


class TestRefreshToken:
    def test_refresh_updates_tokens(self):
        client = APSClient(client_id="id", client_secret="secret", token_path=None)
        client.tokens.refresh_token = "old-rt"

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "expires_in": 3600,
        }

        with patch.object(client._session, "post", return_value=mock_resp):
            client.refresh_access_token()

        assert client.tokens.access_token == "new-at"
        assert client.tokens.refresh_token == "new-rt"

    def test_no_refresh_token_raises(self):
        client = APSClient(client_id="id", client_secret="secret", token_path=None)
        with pytest.raises(APSAuthError, match="No refresh token"):
            client.refresh_access_token()


# ─────────────────────────────────────────────
# Data Management API calls
# ─────────────────────────────────────────────
def _authed_client() -> APSClient:
    """Return a client with a valid (fake) token, no file persistence."""
    client = APSClient(client_id="id", client_secret="secret", token_path=None)
    client.tokens.update({
        "access_token": "valid-token",
        "expires_in": 3600,
    })
    return client


class TestGetHubs:
    def test_returns_hub_list(self):
        client = _authed_client()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": [{"id": "hub1", "type": "hubs"}]
        }

        with patch.object(client._session, "get", return_value=mock_resp):
            hubs = client.get_hubs()

        assert len(hubs) == 1
        assert hubs[0]["id"] == "hub1"


class TestGetProjects:
    def test_returns_project_list(self):
        client = _authed_client()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": [{"id": "proj1", "type": "projects"}]
        }

        with patch.object(client._session, "get", return_value=mock_resp):
            projects = client.get_projects("hub1")

        assert len(projects) == 1
        assert projects[0]["id"] == "proj1"


class TestHTTPErrors:
    def test_non_2xx_raises_aps_http_error(self):
        client = _authed_client()
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"reason": "Forbidden"}
        mock_resp.url = "https://developer.api.autodesk.com/project/v1/hubs"

        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(APSHTTPError) as exc_info:
                client.get_hubs()
            assert exc_info.value.status == 403


# ─────────────────────────────────────────────
# Storage ID parsing
# ─────────────────────────────────────────────
class TestParseStorageId:
    def test_urn_format(self):
        bucket, key = APSClient._parse_storage_id(
            "urn:adsk.objects:os.object:wip.dm.prod/abc-123.json"
        )
        assert bucket == "wip.dm.prod"
        assert key == "abc-123.json"

    def test_url_format(self):
        bucket, key = APSClient._parse_storage_id(
            "https://developer.api.autodesk.com/oss/v2/buckets/wip.dm.prod/objects/abc-123.json?scopes=global"
        )
        assert bucket == "wip.dm.prod"
        assert key == "abc-123.json"

    def test_unknown_format_returns_empty(self):
        bucket, key = APSClient._parse_storage_id("something-else")
        assert bucket == ""
        assert key == ""


# ─────────────────────────────────────────────
# Tool library download + parsing (signed S3)
# ─────────────────────────────────────────────
class TestDownloadToolLibrary:
    def _make_tools_zip(self, tools: list[dict]) -> bytes:
        """Create a fake .tools ZIP containing a JSON file."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("library.json", json.dumps({"data": tools}))
        return buf.getvalue()

    def _mock_signed_download(self, client, content_bytes):
        """
        Mock the two-step signed S3 download:
        1. GET /oss/v2/buckets/.../signeds3download → {"url": "https://s3..."}
        2. GET https://s3... → raw bytes
        """
        sign_resp = MagicMock()
        sign_resp.ok = True
        sign_resp.json.return_value = {"url": "https://s3.signed.example.com/file"}

        dl_resp = MagicMock()
        dl_resp.ok = True
        dl_resp.content = content_bytes

        def side_effect(url, **kwargs):
            if "signeds3download" in url:
                return sign_resp
            return dl_resp

        return patch.object(client._session, "get", side_effect=side_effect)

    def test_zip_extraction(self):
        client = _authed_client()
        tools_data = [
            {"guid": "a", "type": "flat end mill", "vendor": "Acme"},
            {"guid": "b", "type": "ball end mill", "vendor": "Acme"},
        ]
        zip_bytes = self._make_tools_zip(tools_data)

        with self._mock_signed_download(client, zip_bytes):
            result = client.download_tool_library(
                "urn:adsk.objects:os.object:wip.dm.prod/lib.json"
            )

        assert len(result) == 2
        assert result[0]["guid"] == "a"

    def test_raw_json_fallback(self):
        """If the file isn't a ZIP, try parsing as raw JSON."""
        client = _authed_client()
        raw = json.dumps({"data": [{"guid": "c", "type": "drill"}]}).encode()

        with self._mock_signed_download(client, raw):
            result = client.download_tool_library(
                "urn:adsk.objects:os.object:wip.dm.prod/lib.json"
            )

        assert len(result) == 1
        assert result[0]["type"] == "drill"

    def test_empty_data_returns_empty_list(self):
        client = _authed_client()
        raw = json.dumps({"version": 1}).encode()  # no "data" key

        with self._mock_signed_download(client, raw):
            result = client.download_tool_library(
                "urn:adsk.objects:os.object:wip.dm.prod/lib.json"
            )

        assert result == []

    def test_unparseable_storage_ref_raises(self):
        client = _authed_client()
        with pytest.raises(APSHTTPError, match="Cannot parse"):
            client.download_tool_library("not-a-valid-ref")


# ─────────────────────────────────────────────
# Auto-refresh
# ─────────────────────────────────────────────
class TestAutoRefresh:
    def test_ensure_token_refreshes_when_expired(self):
        client = APSClient(client_id="id", client_secret="secret", token_path=None)
        client.tokens.access_token = "old"
        client.tokens.refresh_token = "rt"
        client.tokens.expires_at = time.time() - 100

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "access_token": "refreshed",
            "refresh_token": "new-rt",
            "expires_in": 3600,
        }

        with patch.object(client._session, "post", return_value=mock_resp):
            client._ensure_token()

        assert client.tokens.access_token == "refreshed"

    def test_ensure_token_raises_when_no_refresh(self):
        client = APSClient(client_id="id", client_secret="secret", token_path=None)
        client.tokens.access_token = "old"
        client.tokens.expires_at = time.time() - 100

        with pytest.raises(APSAuthError, match="expired"):
            client._ensure_token()
