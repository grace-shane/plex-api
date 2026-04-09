"""
Tests for supabase_client.py — thin PostgREST wrapper.

Focuses on the contract:
  - Config errors when env vars are missing
  - Headers are set correctly on the session
  - URL building routes to /rest/v1/<table>
  - delete() refuses unfiltered calls
  - HTTP errors surface as SupabaseHTTPError

All HTTP traffic is patched — no real network calls.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from supabase_client import (
    SupabaseClient,
    SupabaseConfigError,
    SupabaseHTTPError,
)


# ─────────────────────────────────────────────
# Config errors
# ─────────────────────────────────────────────
class TestConfigErrors:
    def test_missing_url_raises(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        with pytest.raises(SupabaseConfigError, match="SUPABASE_URL"):
            SupabaseClient()

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        with pytest.raises(SupabaseConfigError, match="SUPABASE_SERVICE_ROLE_KEY"):
            SupabaseClient()

    def test_explicit_args_override_env(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        client = SupabaseClient(
            url="https://explicit.supabase.co",
            service_role_key="explicit-key",
        )
        assert client.url == "https://explicit.supabase.co"
        assert client.key == "explicit-key"


# ─────────────────────────────────────────────
# Session headers
# ─────────────────────────────────────────────
class TestHeaders:
    def test_both_apikey_and_bearer_set(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "abc123")
        client = SupabaseClient()
        assert client._session.headers["apikey"] == "abc123"
        assert client._session.headers["Authorization"] == "Bearer abc123"

    def test_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co/")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        client = SupabaseClient()
        assert client.url == "https://x.supabase.co"


# ─────────────────────────────────────────────
# URL building
# ─────────────────────────────────────────────
class TestTableUrl:
    def test_table_url_format(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        client = SupabaseClient()
        assert (
            client._table_url("tools")
            == "https://x.supabase.co/rest/v1/tools"
        )


# ─────────────────────────────────────────────
# Delete safety guard
# ─────────────────────────────────────────────
class TestDeleteSafety:
    def test_delete_without_filters_raises(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        client = SupabaseClient()
        with pytest.raises(ValueError, match="at least one filter"):
            client.delete("tools", filters={})


# ─────────────────────────────────────────────
# HTTP error surfacing
# ─────────────────────────────────────────────
class TestErrorHandling:
    def test_non_2xx_raises_supabase_http_error(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        client = SupabaseClient()

        class FakeResponse:
            ok = False
            status_code = 400
            url = "https://x.supabase.co/rest/v1/foo"
            content = b'{"message": "bad request"}'

            def json(self):
                return {"message": "bad request"}

        with patch.object(client._session, "get", return_value=FakeResponse()):
            with pytest.raises(SupabaseHTTPError) as exc_info:
                client.select("foo")
            assert exc_info.value.status == 400
            assert exc_info.value.body == {"message": "bad request"}

    def test_2xx_with_empty_body_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        client = SupabaseClient()

        class FakeResponse:
            ok = True
            status_code = 204
            content = b""

        with patch.object(client._session, "delete", return_value=FakeResponse()):
            result = client.delete("foo", filters={"id": "eq.1"})
            assert result == []


# ─────────────────────────────────────────────
# Upsert request shape
# ─────────────────────────────────────────────
class TestUpsertRequestShape:
    def test_upsert_sends_merge_duplicates_and_on_conflict(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
        client = SupabaseClient()

        captured = {}

        class FakeResponse:
            ok = True
            status_code = 201
            content = b"[]"

            def json(self):
                return []

        def fake_post(url, data=None, headers=None, params=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            captured["params"] = params
            return FakeResponse()

        with patch.object(client._session, "post", side_effect=fake_post):
            client.upsert(
                "tools",
                {"fusion_guid": "abc", "vendor": "V"},
                on_conflict="fusion_guid",
            )

        assert captured["url"].endswith("/rest/v1/tools")
        assert "resolution=merge-duplicates" in captured["headers"]["Prefer"]
        assert captured["params"] == {"on_conflict": "fusion_guid"}
        # Body is JSON-serialized list
        assert json.loads(captured["data"]) == [
            {"fusion_guid": "abc", "vendor": "V"}
        ]
