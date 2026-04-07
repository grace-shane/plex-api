"""
Shared pytest fixtures and setup for the plex-api test suite.

Sets PLEX_API_KEY and PLEX_API_SECRET to dummy values BEFORE any test
imports app.py — otherwise the import-time guard at the bottom of
plex_api.py will reject empty credentials and break test collection.

Tests must NEVER hit the real Plex API. All requests should be patched
or routed through fake clients.
"""
import os
import sys
from pathlib import Path

# Make the project root importable so `import plex_api` works regardless
# of where pytest is invoked from.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Inject dummy credentials before any module-level reads happen.
os.environ.setdefault("PLEX_API_KEY", "test-key-do-not-use")
os.environ.setdefault("PLEX_API_SECRET", "test-secret-do-not-use")


# ─────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────
import pytest


class FakePlexClient:
    """
    Drop-in replacement for plex_api.PlexClient that records calls
    and returns canned responses without ever touching the network.

    Usage:
        c = FakePlexClient()
        c.set_response("tenants", [{"id": "...", "code": "G5"}])
        result = c.get("mdm", "v1", "tenants")  # returns the canned response
        assert c.calls == [("mdm", "v1", "tenants")]
    """

    def __init__(self, base="https://test.connect.plex.com"):
        self.base = base
        self.headers = {
            "X-Plex-Connect-Api-Key": "test-key",
            "X-Plex-Connect-Api-Secret": "test-secret",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.calls = []
        self._responses = {}
        self._default = None

    def set_response(self, resource, payload):
        """Canned response for a specific resource string (last segment)."""
        self._responses[resource] = payload

    def set_default(self, payload):
        """Canned response for any resource not explicitly set."""
        self._default = payload

    def get(self, collection, version, resource, params=None):
        self.calls.append((collection, version, resource, params))
        # Match by full resource string first, then by leading segment
        if resource in self._responses:
            return self._responses[resource]
        head = resource.split("/")[0]
        if head in self._responses:
            return self._responses[head]
        return self._default


@pytest.fixture
def fake_client():
    """A fresh FakePlexClient for each test."""
    return FakePlexClient()
