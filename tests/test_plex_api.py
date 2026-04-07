"""
Tests for plex_api.PlexClient — header construction and configuration.

These tests verify the BRIEFING item 1 fix: that the constructor accepts
api_secret and adds the X-Plex-Connect-Api-Secret header. They also lock
in the test/prod URL switch and tenant header behaviour.
"""
from plex_api import PlexClient, BASE_URL, TEST_URL


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
