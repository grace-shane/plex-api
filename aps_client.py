"""
aps_client.py
Autodesk Platform Services (APS) OAuth + Data Management client
Grace Engineering — Datum project
=============================================================
Handles 3-legged OAuth 2.0 with Autodesk and provides methods to
traverse Fusion Team hubs to locate and download cloud tool library
files (.tools / .json).

This eliminates the need for Fusion 360 or Autodesk Desktop Connector
to be installed locally. The pipeline is:

  APS Hub -> download .tools file -> unzip -> parse JSON
  -> same schema as local CAMTools files -> Supabase ingest

Credentials come from environment variables loaded via ``bootstrap.py``:

  APS_CLIENT_ID        App client ID from aps.autodesk.com
  APS_CLIENT_SECRET    App client secret
  APS_CALLBACK_URL     OAuth redirect URI (default: http://localhost:5000/api/aps/callback)

Token state is persisted to a local file (``.aps_tokens.json``, gitignored)
so tokens survive Flask debug reloads and process restarts. A production
deploy would use an encrypted store or database instead.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

import bootstrap  # noqa: F401 — loads .env.local into os.environ on import

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
APS_CLIENT_ID = os.environ.get("APS_CLIENT_ID", "")
APS_CLIENT_SECRET = os.environ.get("APS_CLIENT_SECRET", "")
APS_CALLBACK_URL = os.environ.get(
    "APS_CALLBACK_URL", "http://localhost:5000/api/aps/callback"
)

APS_AUTH_BASE = "https://developer.api.autodesk.com/authentication/v2"
APS_DM_BASE = "https://developer.api.autodesk.com"

# Scopes needed for reading hub data (tool libraries live in the hub)
DEFAULT_SCOPES = "data:read"

DEFAULT_TIMEOUT = 30  # seconds


# ─────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────
class APSConfigError(RuntimeError):
    """Raised when APS_CLIENT_ID or APS_CLIENT_SECRET is missing."""


class APSAuthError(RuntimeError):
    """Raised when OAuth flow fails (bad code, expired token, etc.)."""


class APSHTTPError(RuntimeError):
    """Raised when an APS API call returns a non-2xx response."""

    def __init__(self, status: int, body: Any, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"APS {status} on {url}: {body}")


# ─────────────────────────────────────────────
# Token store (file-backed, single-user)
# ─────────────────────────────────────────────
# Default token file lives next to .env.local — both are gitignored.
_DEFAULT_TOKEN_PATH = Path(__file__).resolve().parent / ".aps_tokens.json"


class TokenStore:
    """
    Persists OAuth tokens to a local JSON file so they survive Flask
    debug reloads and process restarts.

    Parameters
    ----------
    path : Path | None
        File to persist tokens to. ``None`` disables persistence
        (pure in-memory, useful for tests).
    """

    def __init__(self, path: Path | None = _DEFAULT_TOKEN_PATH):
        self._path = path
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at: float = 0.0  # epoch seconds
        self._load()

    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at

    def update(self, data: dict) -> None:
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        self.expires_at = time.time() + data.get("expires_in", 3600) - 60
        self._save()

    def clear(self) -> None:
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0.0
        if self._path and self._path.exists():
            self._path.unlink()

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.write_text(json.dumps({
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at,
            }), encoding="utf-8")
        except OSError as e:
            log.warning("Could not persist APS tokens: %s", e)

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            self.expires_at = data.get("expires_at", 0.0)
        except (OSError, json.JSONDecodeError, KeyError) as e:
            log.warning("Could not load APS tokens from %s: %s", self._path, e)


# ─────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────
class APSClient:
    """
    Autodesk Platform Services client for OAuth and Data Management API.

    Parameters
    ----------
    client_id : str | None
        APS app client ID. Defaults to ``APS_CLIENT_ID`` env var.
    client_secret : str | None
        APS app client secret. Defaults to ``APS_CLIENT_SECRET`` env var.
    callback_url : str | None
        OAuth redirect URI. Defaults to ``APS_CALLBACK_URL`` env var.
    timeout : int
        Per-request timeout in seconds.
    token_path : Path | None | str
        File to persist tokens to. Pass ``None`` to disable persistence
        (in-memory only, useful for tests). Defaults to ``.aps_tokens.json``.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        callback_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        token_path: Path | None | str = _DEFAULT_TOKEN_PATH,
    ):
        self.client_id = client_id or APS_CLIENT_ID
        self.client_secret = client_secret or APS_CLIENT_SECRET
        self.callback_url = callback_url or APS_CALLBACK_URL
        self.timeout = timeout
        self.tokens = TokenStore(path=Path(token_path) if token_path else None)
        self._session = requests.Session()

    # ─────────────────────────────────────────
    # Config validation
    # ─────────────────────────────────────────
    def _require_config(self) -> None:
        if not self.client_id:
            raise APSConfigError(
                "APS_CLIENT_ID is not set. Register an app at "
                "https://aps.autodesk.com and add the client ID to .env.local."
            )
        if not self.client_secret:
            raise APSConfigError(
                "APS_CLIENT_SECRET is not set. Add it to .env.local."
            )

    def _require_token(self) -> None:
        if not self.tokens.is_valid:
            raise APSAuthError(
                "No valid APS access token. Complete the OAuth flow first "
                "by visiting /api/aps/login in your browser."
            )

    # ─────────────────────────────────────────
    # OAuth 2.0 — 3-legged flow
    # ─────────────────────────────────────────
    def get_authorize_url(self, scopes: str = DEFAULT_SCOPES) -> str:
        """
        Build the Autodesk authorization URL. Redirect the user's browser here.
        After consent, Autodesk redirects back to ``callback_url`` with a code.
        """
        self._require_config()
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.callback_url,
            "scope": scopes,
        }
        return f"{APS_AUTH_BASE}/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """
        Exchange an authorization code for access + refresh tokens.
        Called from the OAuth callback handler.
        """
        self._require_config()
        resp = self._session.post(
            f"{APS_AUTH_BASE}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.callback_url,
            },
            timeout=self.timeout,
        )
        if not resp.ok:
            raise APSAuthError(
                f"Token exchange failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        self.tokens.update(data)
        log.info("APS OAuth tokens acquired (expires in %ss)", data.get("expires_in"))
        return data

    def refresh_access_token(self) -> dict:
        """Use the refresh token to get a new access token."""
        self._require_config()
        if not self.tokens.refresh_token:
            raise APSAuthError(
                "No refresh token available. Re-authenticate via /api/aps/login."
            )
        resp = self._session.post(
            f"{APS_AUTH_BASE}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.tokens.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout,
        )
        if not resp.ok:
            raise APSAuthError(
                f"Token refresh failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        self.tokens.update(data)
        log.info("APS tokens refreshed")
        return data

    def _ensure_token(self) -> None:
        """Auto-refresh if the current token is expired but we have a refresh token."""
        if self.tokens.is_valid:
            return
        if self.tokens.refresh_token:
            self.refresh_access_token()
            return
        raise APSAuthError(
            "APS token expired and no refresh token available. "
            "Re-authenticate via /api/aps/login."
        )

    # ─────────────────────────────────────────
    # Authenticated API calls
    # ─────────────────────────────────────────
    def _authed_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tokens.access_token}",
            "Content-Type": "application/json",
        }

    def _get(self, url: str, params: dict | None = None) -> Any:
        """Authenticated GET. Returns parsed JSON."""
        self._ensure_token()
        resp = self._session.get(
            url,
            headers=self._authed_headers(),
            params=params,
            timeout=self.timeout,
        )
        if not resp.ok:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise APSHTTPError(resp.status_code, body, resp.url)
        return resp.json()

    def _get_binary(self, url: str) -> bytes:
        """Authenticated GET returning raw bytes (for file downloads)."""
        self._ensure_token()
        resp = self._session.get(
            url,
            headers={"Authorization": f"Bearer {self.tokens.access_token}"},
            timeout=self.timeout,
        )
        if not resp.ok:
            raise APSHTTPError(resp.status_code, resp.text, resp.url)
        return resp.content

    # ─────────────────────────────────────────
    # Data Management API — hub traversal
    # ─────────────────────────────────────────
    def get_hubs(self) -> list[dict]:
        """List all hubs the authenticated user can access."""
        data = self._get(f"{APS_DM_BASE}/project/v1/hubs")
        return data.get("data", [])

    def get_projects(self, hub_id: str) -> list[dict]:
        """List projects within a hub."""
        data = self._get(f"{APS_DM_BASE}/project/v1/hubs/{hub_id}/projects")
        return data.get("data", [])

    def get_top_folders(self, hub_id: str, project_id: str) -> list[dict]:
        """List top-level folders in a project."""
        data = self._get(
            f"{APS_DM_BASE}/project/v1/hubs/{hub_id}/projects/{project_id}/topFolders"
        )
        return data.get("data", [])

    def get_folder_contents(
        self, project_id: str, folder_id: str
    ) -> list[dict]:
        """List items in a folder."""
        data = self._get(
            f"{APS_DM_BASE}/data/v1/projects/{project_id}/folders/{folder_id}/contents"
        )
        return data.get("data", [])

    def search_folder(
        self, project_id: str, folder_id: str, filter_name: str = ""
    ) -> list[dict]:
        """
        Search within a folder. Useful for finding .tools files by name.
        """
        params = {}
        if filter_name:
            params["filter[displayName]"] = filter_name
        data = self._get(
            f"{APS_DM_BASE}/data/v1/projects/{project_id}/folders/{folder_id}/search",
            params=params,
        )
        return data.get("data", [])

    def get_item_versions(self, project_id: str, item_id: str) -> list[dict]:
        """List versions of an item (to get download links)."""
        data = self._get(
            f"{APS_DM_BASE}/data/v1/projects/{project_id}/items/{item_id}/versions"
        )
        return data.get("data", [])

    def get_item_tip(self, project_id: str, item_id: str) -> dict:
        """Get the latest version (tip) of an item."""
        data = self._get(
            f"{APS_DM_BASE}/data/v1/projects/{project_id}/items/{item_id}/tip"
        )
        return data.get("data", {})

    # ─────────────────────────────────────────
    # File download + parsing
    # ─────────────────────────────────────────
    def download_version(self, storage_url: str) -> bytes:
        """
        Download a file by its storage info.

        Accepts either:
        - An ``urn:adsk.objects:os.object:BUCKET/OBJECT`` URN
          (from ``relationships.storage.data.id``)
        - A legacy ``/oss/v2/buckets/...`` URL
          (from ``relationships.storage.meta.link.href``)

        Uses the signed S3 download endpoint (the old direct OSS v2
        GET is deprecated and returns 403).
        """
        # Parse bucket and object key from URN or URL
        bucket, obj_key = self._parse_storage_id(storage_url)
        if not bucket or not obj_key:
            raise APSHTTPError(
                400,
                f"Cannot parse storage reference: {storage_url}",
                storage_url,
            )

        # Get a signed S3 download URL
        sign_resp = self._get(
            f"{APS_DM_BASE}/oss/v2/buckets/{bucket}/objects/{obj_key}/signeds3download"
        )
        signed_url = sign_resp.get("url")
        if not signed_url:
            raise APSHTTPError(
                500,
                f"No signed URL returned for {bucket}/{obj_key}",
                storage_url,
            )

        # Download from S3 (no auth header needed — the URL is pre-signed)
        resp = self._session.get(signed_url, timeout=self.timeout)
        if not resp.ok:
            raise APSHTTPError(resp.status_code, resp.text, signed_url)
        return resp.content

    @staticmethod
    def _parse_storage_id(ref: str) -> tuple[str, str]:
        """
        Extract (bucket, object_key) from a storage URN or URL.

        URN format: ``urn:adsk.objects:os.object:wip.dm.prod/abc-123.json``
        URL format: ``.../oss/v2/buckets/wip.dm.prod/objects/abc-123.json?...``
        """
        # URN form
        if ref.startswith("urn:adsk.objects:os.object:"):
            path = ref.split("urn:adsk.objects:os.object:")[-1]
            parts = path.split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]

        # URL form
        if "/oss/v2/buckets/" in ref:
            # .../oss/v2/buckets/{bucket}/objects/{object}?...
            segment = ref.split("/oss/v2/buckets/")[-1]
            segment = segment.split("?")[0]  # strip query params
            parts = segment.split("/objects/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]

        return "", ""

    def download_tool_library(self, storage_url: str) -> list[dict]:
        """
        Download a .tools file and extract the JSON tool data.

        .tools files are ZIP archives containing a single JSON file
        with the same schema as local Fusion tool library exports:
        ``{"data": [<tool objects>], ...}``

        Returns the list of tool dicts (the "data" array), matching
        the return type of ``tool_library_loader.load_library()``.
        """
        raw_bytes = self.download_version(storage_url)

        # Try ZIP first (.tools files are typically zipped)
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                names = zf.namelist()
                # Find the JSON file inside
                json_name = next(
                    (n for n in names if n.endswith(".json")), names[0]
                )
                with zf.open(json_name) as jf:
                    parsed = json.load(jf)
        except zipfile.BadZipFile:
            # Not a ZIP — might be raw JSON (some exports)
            parsed = json.loads(raw_bytes)

        # Extract the "data" array
        if isinstance(parsed, dict) and "data" in parsed:
            tools = parsed["data"]
        elif isinstance(parsed, list):
            tools = parsed
        else:
            log.warning(
                "Unexpected tool library structure from %s — no 'data' key",
                storage_url,
            )
            return []

        if not isinstance(tools, list):
            return []

        log.info(
            "Downloaded tool library from APS: %d entries", len(tools)
        )
        return tools

    # ─────────────────────────────────────────
    # High-level: find tool libraries in hub
    # ─────────────────────────────────────────
    def find_tool_libraries(
        self, hub_id: str | None = None
    ) -> list[dict]:
        """
        Walk the hub to find .tools files. Returns a list of dicts:

            [{"name": "MyLibrary.tools",
              "item_id": "urn:...",
              "project_id": "...",
              "hub_id": "...",
              "storage_url": "https://..."}, ...]

        If ``hub_id`` is None, searches all accessible hubs.
        """
        results = []
        hubs = [{"id": hub_id}] if hub_id else self.get_hubs()

        for hub in hubs:
            hid = hub["id"]
            projects = self.get_projects(hid)

            for project in projects:
                pid = project["id"]
                try:
                    top_folders = self.get_top_folders(hid, pid)
                except APSHTTPError:
                    log.debug("Skipping project %s — can't list folders", pid)
                    continue

                for folder in top_folders:
                    fid = folder["id"]
                    self._scan_folder_for_tools(
                        hid, pid, fid, results, depth=0
                    )

        return results

    def _scan_folder_for_tools(
        self,
        hub_id: str,
        project_id: str,
        folder_id: str,
        results: list[dict],
        depth: int = 0,
        max_depth: int = 5,
    ) -> None:
        """Recursively scan folders for .tools files."""
        if depth > max_depth:
            return

        try:
            contents = self.get_folder_contents(project_id, folder_id)
        except APSHTTPError:
            return

        for item in contents:
            item_type = item.get("type", "")
            name = item.get("attributes", {}).get("displayName", "")

            if item_type == "folders":
                # Recurse into subfolders
                self._scan_folder_for_tools(
                    hub_id, project_id, item["id"], results, depth + 1
                )

            elif item_type == "items" and (
                name.endswith(".tools") or name.endswith(".json")
            ):
                # Found a tool library file — get its download URL
                try:
                    tip = self.get_item_tip(project_id, item["id"])
                    storage = (
                        tip.get("relationships", {})
                        .get("storage", {})
                        .get("meta", {})
                        .get("link", {})
                        .get("href", "")
                    )
                    results.append({
                        "name": name,
                        "item_id": item["id"],
                        "project_id": project_id,
                        "hub_id": hub_id,
                        "storage_url": storage,
                    })
                except APSHTTPError as e:
                    log.warning("Could not get tip for %s: %s", name, e)
