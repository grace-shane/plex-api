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

    Two parallel canned-response stores:
      - ``set_response(resource, body)`` — body returned by both ``get()``
        and ``get_envelope()`` (the latter wraps the body in a synthetic
        200 OK envelope).
      - ``set_envelope(resource, envelope)`` — full envelope dict returned
        by ``get_envelope()`` only. Use this to test error branches like
        401/403/network failure.

    If both are set for the same resource, ``set_envelope`` wins for
    ``get_envelope()`` calls and ``set_response`` is used for ``get()``.
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
        self._envelopes = {}
        self._default = None

    def set_response(self, resource, payload):
        """Canned body for a specific resource string (last segment)."""
        self._responses[resource] = payload

    def set_envelope(self, resource, envelope):
        """Canned full envelope (overrides set_response for get_envelope)."""
        self._envelopes[resource] = envelope

    def set_default(self, payload):
        """Canned body for any resource not explicitly set."""
        self._default = payload

    def _lookup_body(self, resource):
        if resource in self._responses:
            return self._responses[resource]
        head = resource.split("/")[0]
        if head in self._responses:
            return self._responses[head]
        return self._default

    def get(self, collection, version, resource, params=None):
        self.calls.append((collection, version, resource, params))
        return self._lookup_body(resource)

    def get_envelope(self, collection, version, resource, params=None):
        self.calls.append((collection, version, resource, params))
        # Explicit envelope override wins
        if resource in self._envelopes:
            return self._envelopes[resource]
        head = resource.split("/")[0]
        if head in self._envelopes:
            return self._envelopes[head]
        # Otherwise synthesize a 200 OK envelope wrapping the canned body
        body = self._lookup_body(resource)
        return {
            "ok": True,
            "status": 200,
            "reason": "OK",
            "body": body,
            "elapsed_ms": 0,
            "url": f"{self.base}/{collection}/{version}/{resource}",
            "error": None,
        }


@pytest.fixture
def fake_client():
    """A fresh FakePlexClient for each test."""
    return FakePlexClient()
