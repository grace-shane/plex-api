"""
supabase_client.py
Thin Supabase REST client for the Datum ingest layer
Grace Engineering — Datum project
=============================================================
Minimal PostgREST wrapper that talks to Supabase over plain HTTP.
Deliberately avoids the `supabase-py` SDK because its transitive
dependency tree (pyiceberg etc.) requires MSVC on Windows + Python
3.14 and is overkill for the three tables we touch.

Why a hand-rolled client
------------------------
- Same HTTP pattern as ``plex_api.py`` — one library to understand
- No compiled deps, installs cleanly on any platform
- Easy to stub in tests (patch ``requests.Session``)
- We only need five verbs: select, insert, upsert, delete, rpc-free

Credentials come from environment variables loaded via ``bootstrap.py``:

  SUPABASE_URL                e.g. ``https://uhmpkprcxrajbtkvqmwg.supabase.co``
  SUPABASE_SERVICE_ROLE_KEY   service role JWT (bypasses RLS — server-side only)

**Never ship the service role key to a browser.** It is intended for
back-end ingest scripts and should never leave the server.
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable, Mapping

import requests

import bootstrap  # noqa: F401 — loads .env.local into os.environ on import

DEFAULT_TIMEOUT = 30  # seconds


class SupabaseConfigError(RuntimeError):
    """Raised when SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing."""


class SupabaseHTTPError(RuntimeError):
    """Raised when PostgREST returns a non-2xx response."""

    def __init__(self, status: int, body: Any, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"Supabase {status} on {url}: {body}")


class SupabaseClient:
    """
    Minimal PostgREST client.

    Parameters
    ----------
    url : str | None
        Supabase project URL, e.g. ``https://<ref>.supabase.co``. Defaults
        to the ``SUPABASE_URL`` env var.
    service_role_key : str | None
        Service role JWT. Defaults to ``SUPABASE_SERVICE_ROLE_KEY``.
    timeout : int
        Per-request timeout in seconds. Defaults to 30.

    The service role key bypasses RLS. Do not pass it to the browser.
    """

    def __init__(
        self,
        url: str | None = None,
        service_role_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = service_role_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.timeout = timeout

        if not self.url:
            raise SupabaseConfigError(
                "SUPABASE_URL is not set. Add it to .env.local or the shell env."
            )
        if not self.key:
            raise SupabaseConfigError(
                "SUPABASE_SERVICE_ROLE_KEY is not set. Add it to .env.local "
                "(the service role key is server-side only — never ship it "
                "to the browser)."
            )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ─────────────────────────────────────────────
    # URL building
    # ─────────────────────────────────────────────
    def _table_url(self, table: str) -> str:
        return f"{self.url}/rest/v1/{table}"

    # ─────────────────────────────────────────────
    # Response handling
    # ─────────────────────────────────────────────
    def _handle(self, response: requests.Response) -> Any:
        if not response.ok:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            raise SupabaseHTTPError(response.status_code, body, response.url)

        # 204 No Content (e.g. delete with no return) → empty list
        if not response.content:
            return []

        try:
            return response.json()
        except ValueError:
            return response.text

    # ─────────────────────────────────────────────
    # Operations
    # ─────────────────────────────────────────────
    def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Mapping[str, str] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """
        GET /rest/v1/{table}?select=...&<filters>&limit=...

        ``filters`` is a mapping of PostgREST filter clauses, e.g.
        ``{"library_id": "eq.abc-123"}``.
        """
        params: dict[str, str] = {"select": columns}
        if filters:
            params.update(filters)
        if limit is not None:
            params["limit"] = str(limit)

        response = self._session.get(
            self._table_url(table), params=params, timeout=self.timeout
        )
        return self._handle(response) or []

    def insert(
        self,
        table: str,
        rows: Mapping[str, Any] | Iterable[Mapping[str, Any]],
        *,
        returning: str = "representation",
    ) -> list[dict]:
        """
        POST /rest/v1/{table} — insert one row or many.

        ``returning`` is passed through as the ``Prefer: return=<value>``
        header. Defaults to "representation" (return inserted rows).
        """
        if isinstance(rows, Mapping):
            body = [dict(rows)]
        else:
            body = [dict(r) for r in rows]

        headers = {"Prefer": f"return={returning}"}
        response = self._session.post(
            self._table_url(table),
            data=json.dumps(body),
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle(response) or []

    def upsert(
        self,
        table: str,
        rows: Mapping[str, Any] | Iterable[Mapping[str, Any]],
        *,
        on_conflict: str,
        returning: str = "representation",
    ) -> list[dict]:
        """
        POST with ``Prefer: resolution=merge-duplicates``.

        Parameters
        ----------
        on_conflict : str
            Column name (or comma-separated columns) that backs a UNIQUE
            constraint to resolve against, e.g. ``"fusion_guid"``.
        """
        if isinstance(rows, Mapping):
            body = [dict(rows)]
        else:
            body = [dict(r) for r in rows]

        headers = {
            "Prefer": f"resolution=merge-duplicates,return={returning}",
        }
        params = {"on_conflict": on_conflict}
        response = self._session.post(
            self._table_url(table),
            data=json.dumps(body),
            headers=headers,
            params=params,
            timeout=self.timeout,
        )
        return self._handle(response) or []

    def delete(
        self,
        table: str,
        *,
        filters: Mapping[str, str],
    ) -> list[dict]:
        """
        DELETE /rest/v1/{table}?<filters>

        ``filters`` is REQUIRED — PostgREST refuses unfiltered deletes by
        default and we want to keep it that way to avoid wiping tables.
        """
        if not filters:
            raise ValueError(
                "delete() requires at least one filter — refusing to "
                "issue an unfiltered DELETE."
            )
        headers = {"Prefer": "return=representation"}
        response = self._session.delete(
            self._table_url(table),
            params=dict(filters),
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle(response) or []

    def update(
        self,
        table: str,
        values: Mapping[str, Any],
        *,
        filters: Mapping[str, str],
    ) -> list[dict]:
        """
        PATCH /rest/v1/{table}?<filters> — update matching rows.

        ``filters`` is REQUIRED to prevent accidental full-table updates.
        ``values`` is the dict of columns to set.
        """
        if not filters:
            raise ValueError(
                "update() requires at least one filter — refusing to "
                "issue an unfiltered PATCH."
            )
        headers = {"Prefer": "return=representation"}
        response = self._session.patch(
            self._table_url(table),
            data=json.dumps(dict(values)),
            params=dict(filters),
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle(response) or []
