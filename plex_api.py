"""
Plex Connect REST API Client
Grace Engineering — CNC Tool Management
========================================
Base URL:  https://connect.plex.com/{collection}/{version}/{resource}
Auth:      X-Plex-Connect-Api-Key header (Consumer Key from Developer Portal)
Rate:      200 calls/minute
"""

# bootstrap MUST be imported before anything reads PLEX_API_KEY/SECRET from
# os.environ — it injects values from .env.local (if present) so the dev
# loop doesn't require setting env vars in every shell. Real shell env
# always wins via setdefault semantics.
import bootstrap  # noqa: F401

import requests
import json
import csv
import time
import os
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION — fill these in
# ─────────────────────────────────────────────
# Credentials come from environment variables — never hardcode/commit.
#   PLEX_API_KEY     — Consumer Key from developers.plex.com → My Apps
#   PLEX_API_SECRET  — Consumer Secret, paired with the key
API_KEY     = os.environ.get("PLEX_API_KEY", "")
API_SECRET  = os.environ.get("PLEX_API_SECRET", "")
# Tenant IDs are not secrets — safe to commit. G5 is what we currently have access to.
TENANT_ID   = "b406c8c4-cef0-4d62-862c-1758b702cd02"  # G5 (read-only) — Grace UUID = a6af9c99-bce5-4938-a007-364dc5603d08
BASE_URL    = "https://connect.plex.com"
TEST_URL    = "https://test.connect.plex.com"
USE_TEST    = True                           # all dev work goes against test.connect.plex.com

OUTPUT_DIR   = "C:/projects/plex-api/outputs"
TOOL_LIB_DIR = "Z:\\Engineering\\Tooling\\Fusion_Libraries"  # Mapped drive path containing JSON files

# ─────────────────────────────────────────────
# BASE CLIENT
# ─────────────────────────────────────────────
class PlexClient:
    def __init__(self, api_key, api_secret="", tenant_id="", use_test=False):
        self.base = TEST_URL if use_test else BASE_URL
        self.headers = {
            "X-Plex-Connect-Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if api_secret:
            self.headers["X-Plex-Connect-Api-Secret"] = api_secret
        if tenant_id:
            self.headers["X-Plex-Connect-Tenant-Id"] = tenant_id

        self._call_count = 0
        self._window_start = time.time()

    def _throttle(self):
        """Stay under 200 calls/minute rate limit"""
        self._call_count += 1
        elapsed = time.time() - self._window_start
        if elapsed < 60 and self._call_count >= 190:
            wait = 60 - elapsed
            print(f"  Rate limit approaching — waiting {wait:.1f}s...")
            time.sleep(wait)
            self._call_count = 0
            self._window_start = time.time()
        elif elapsed >= 60:
            self._call_count = 1
            self._window_start = time.time()

    def get(self, collection, version, resource, params=None):
        """
        GET request with auto-throttling.

        Returns the parsed JSON body on success, or None on any failure.
        Backward-compatible legacy interface — callers that need to know
        WHY a request failed (auth error vs network error vs 404 vs JSON
        parse failure) should use ``get_envelope()`` instead.
        """
        env = self.get_envelope(collection, version, resource, params)
        if not env["ok"]:
            # Preserve the historical "log to stdout" behaviour for the
            # legacy callers, then collapse to None.
            print(f"  HTTP Error {env['status']}: {env['url']}")
            if env["body"] is not None:
                snippet = str(env["body"])[:300]
                print(f"  Response: {snippet}")
            return None
        return env["body"]

    def get_envelope(self, collection, version, resource, params=None):
        """
        GET request returning a structured envelope.

        Unlike ``get()`` (which returns parsed JSON on success and None on
        any failure), this method returns a dict so callers can distinguish:

          - successful empty / null responses
          - authentication errors (401, 403)
          - other HTTP errors (404, 5xx, ...)
          - network failures (DNS, timeout, connection refused, ...)
          - JSON parse failures (response was text/html instead of JSON)

        Returns
        -------
        dict
            {
                "ok":         bool,        # True iff response was 2xx
                "status":     int,         # HTTP status; 0 if no response
                "reason":     str,         # HTTP reason phrase or
                                           # exception class name
                "body":       Any,         # parsed JSON if possible,
                                           # else text, else None
                "elapsed_ms": int,
                "url":        str,
                "error":      str | None,  # human-readable error if not ok
            }
        """
        self._throttle()
        url = f"{self.base}/{collection}/{version}/{resource}"
        started = time.perf_counter()

        try:
            r = requests.get(url, headers=self.headers, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            return {
                "ok": False,
                "status": 0,
                "reason": e.__class__.__name__,
                "body": None,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "url": url,
                "error": str(e),
            }

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # Try JSON first; fall back to text; fall back to None.
        try:
            body = r.json()
        except ValueError:
            body = r.text or None

        return {
            "ok": r.ok,
            "status": r.status_code,
            "reason": r.reason or "",
            "body": body,
            "elapsed_ms": elapsed_ms,
            "url": r.url,
            "error": None if r.ok else f"HTTP {r.status_code} {r.reason}".strip(),
        }

    def get_paginated(self, collection, version, resource, params=None, limit=100):
        """GET all pages of a paginated endpoint"""
        params = params or {}
        params["limit"] = limit
        params["offset"] = 0
        results = []

        while True:
            data = self.get(collection, version, resource, params)
            if not data:
                break

            # Handle both list and dict responses
            if isinstance(data, list):
                batch = data
            elif isinstance(data, dict):
                # Common Plex patterns: data["items"], data["rows"], or data itself
                batch = (data.get("items") or
                         data.get("rows") or
                         data.get("data") or
                         [data])
            else:
                break

            if not batch:
                break

            results.extend(batch)
            print(f"  Fetched {len(results)} records...")

            if len(batch) < limit:
                break  # last page

            params["offset"] += limit

        return results


# ─────────────────────────────────────────────
# ENDPOINT EXPLORER
# Helps discover what endpoints are available
# and what fields they return
# ─────────────────────────────────────────────
def explore_endpoint(client, collection, version, resource, params=None, max_records=3):
    """
    Fetch a small sample from an endpoint and pretty-print the structure.
    Use this to understand field names before writing extraction code.
    """
    print(f"\n{'='*60}")
    print(f"Exploring: {collection}/{version}/{resource}")
    print(f"{'='*60}")

    params = params or {}
    params["limit"] = max_records

    data = client.get(collection, version, resource, params)

    if data is None:
        print("  No response / endpoint may not exist or not be subscribed")
        return None

    print(f"  Response type: {type(data).__name__}")
    print(f"  Content:\n{json.dumps(data, indent=2)[:2000]}")
    return data


# ─────────────────────────────────────────────
# EXTRACTION FUNCTIONS
# ─────────────────────────────────────────────
def extract_purchase_orders(client, supplier=None, date_from=None):
    """
    Pull PO data — primary source for tool numbers already in system.
    Goal: find all tool-related POs to seed Tool Assembly records.
    """
    print("\nExtracting Purchase Orders...")
    params = {}
    if supplier:
        params["supplier"] = supplier
    if date_from:
        params["updatedAfter"] = f"{date_from}T00:00:00.000Z"

    # Try common Plex PO endpoint patterns
    # Actual endpoint confirmed from developer portal subscription
    results = client.get_paginated("purchasing", "v1", "purchase-orders", params)

    if results:
        out = os.path.join(OUTPUT_DIR, "plex_purchase_orders.csv")
        write_csv(results, out)
        print(f"  Saved {len(results)} POs → {out}")
    return results


def extract_parts(client, part_type=None):
    """
    Pull part master records.
    Goal: confirm part numbers for Tool BOM linkage.
    """
    print("\nExtracting Parts...")
    params = {}
    if part_type:
        params["type"] = part_type

    results = client.get_paginated("mdm", "v1", "parts", params)

    if results:
        out = os.path.join(OUTPUT_DIR, "plex_parts.csv")
        write_csv(results, out)
        print(f"  Saved {len(results)} parts → {out}")
    return results


def extract_workcenters(client):
    """
    Pull workcenter records.
    Goal: confirm workcenter codes for Tool BOM Station assignments.
    """
    print("\nExtracting Workcenters...")
    results = client.get_paginated("production", "v1/control", "workcenters")

    if results:
        out = os.path.join(OUTPUT_DIR, "plex_workcenters.csv")
        write_csv(results, out)
        print(f"  Saved {len(results)} workcenters → {out}")
    return results


def extract_operations(client):
    """
    Pull operation codes.
    Goal: confirm operation codes for Tool BOM and routing linkage.
    """
    print("\nExtracting Operations...")
    results = client.get_paginated("manufacturing", "v1", "operations")

    if results:
        out = os.path.join(OUTPUT_DIR, "plex_operations.csv")
        write_csv(results, out)
        print(f"  Saved {len(results)} operations → {out}")
    return results


# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────
def write_csv(records, filepath):
    """Write list of dicts to CSV, auto-detecting headers"""
    if not records:
        print("  Nothing to write")
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    headers = list(records[0].keys()) if records else []
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


# ─────────────────────────────────────────────
# ENDPOINT DISCOVERY
# Run this first to see what's available
# ─────────────────────────────────────────────
ENDPOINTS_TO_PROBE = [
    # collection        version  resource
    ("purchasing",      "v1",    "purchase-orders"),
    ("purchasing",      "v1",    "purchase-order-lines"),
    ("mdm",             "v1",    "parts"),
    ("production",      "v1/control", "workcenters"),
    ("manufacturing",   "v1",    "operations"),
    ("manufacturing",   "v1",    "routings"),
    ("inventory",       "v1",    "inventory"),
    ("tooling",         "v1",    "tools"),
    ("tooling",         "v1",    "tool-assemblies"),
    ("tooling",         "v1",    "tool-inventory"),
]


def discover_all(client):
    """
    Probe all known endpoint patterns.
    Shows which ones your API subscription covers.
    Saves a discovery report.
    """
    print("\nDiscovering available endpoints...")
    report = []

    for collection, version, resource in ENDPOINTS_TO_PROBE:
        url = f"{client.base}/{collection}/{version}/{resource}"
        client._throttle()
        try:
            r = requests.get(
                url,
                headers=client.headers,
                params={"limit": 1},
                timeout=15
            )
            status = r.status_code
            note = ""
            if status == 200:
                note = "[OK] Available"
            elif status == 401:
                note = "[ERR] Auth error"
            elif status == 403:
                note = "[LOCK] Not subscribed"
            elif status == 404:
                note = "[?] Not found"
            else:
                note = f"[!] HTTP {status}"
        except Exception as e:
            status = 0
            note = f"[ERR] Exception: {e}"

        print(f"  {note:25s} {collection}/{version}/{resource}")
        report.append({
            "Collection": collection,
            "Version": version,
            "Resource": resource,
            "Status": status,
            "Note": note.strip(),
        })
        time.sleep(0.3)  # be polite

    out = os.path.join(OUTPUT_DIR, "plex_api_discovery.csv")
    write_csv(report, out)
    print(f"\nDiscovery report saved → {out}")
    return report


# ─────────────────────────────────────────────
# MAIN — edit what you want to run
# ─────────────────────────────────────────────
def explore_parts(client):
    """
    Hit the Parts endpoint raw — no params — and dump everything.
    """
    print(f"\n{'='*60}")
    print("PARTS ENDPOINT — RAW RESPONSE")
    print(f"{'='*60}")

    url = f"{client.base}/mdm/v1/parts"
    print(f"\n  GET {url}")
    r = requests.get(url, headers=client.headers, timeout=30)
    print(f"  Status: {r.status_code}")
    print(f"  Content-Type: {r.headers.get('Content-Type')}")

    if r.status_code != 200:
        print(f"  Body: {r.text[:500]}")
        return

    data = r.json()

    # Dump full raw response
    raw = json.dumps(data, indent=2)
    print(f"  Response length: {len(raw)} chars")
    print(f"\n{raw[:5000]}")
    if len(raw) > 5000:
        print(f"\n  ... truncated ({len(raw)} total chars) ...")

    # Save full response to file for inspection
    out = os.path.join(OUTPUT_DIR, "plex_parts_raw.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Full response saved → {out}")

    return data


if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        raise SystemExit(
            "Missing credentials. Set PLEX_API_KEY and PLEX_API_SECRET environment variables."
        )

    client = PlexClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        tenant_id=TENANT_ID,
        use_test=USE_TEST,
    )

    print(f"Plex API Client — {'TEST' if USE_TEST else 'PRODUCTION'}")
    print(f"Base URL: {client.base}")
    print(f"Key: {API_KEY[:8]}{'*' * 20}")

    # ── Focus: Parts endpoint exploration
    explore_parts(client)

    # ── Other exploration (uncomment as needed)
    # discover_all(client)
    # extract_parts(client)
    # explore_endpoint(client, "mdm", "v1", "parts", max_records=2)
