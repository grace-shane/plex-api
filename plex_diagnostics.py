"""
plex_diagnostics.py
Plex Connect — diagnostic checks
================================
Small suite of read-only checks against the Plex API to verify connectivity,
authentication, and tenant routing. Used as a sanity layer before any sync
work and as the visible "is the right tenant connected?" indicator in the UI.

All functions are read-only and safe to run against any tenant — including
G5, where we have read access only.
"""

from typing import Any

# ─────────────────────────────────────────────
# Known tenants
# Tenant IDs are not secrets — committing them is fine. These labels are
# used to make the whoami report human-readable.
#
# History: an earlier version of BRIEFING.md listed a different Grace UUID
# (a6af9c99-bce5-4938-a007-364dc5603d08). That value is dead — verified
# empirically against the live API. The real Grace tenant ID is the one
# below, which the Plex API itself returns when you GET mdm/v1/tenants
# with the Fusion2Plex Consumer Key. The old UUID is kept here labeled
# "Grace (stale)" so anyone hitting it gets a clear signal.
# ─────────────────────────────────────────────
GRACE_TENANT_ID         = "58f781ba-1691-4f32-b1db-381cdb21300c"  # verified Apr 2026
GRACE_OLD_TENANT_ID     = "a6af9c99-bce5-4938-a007-364dc5603d08"  # dead, kept for diagnostics
G5_TENANT_ID            = "b406c8c4-cef0-4d62-862c-1758b702cd02"

KNOWN_TENANTS = {
    GRACE_TENANT_ID:     "Grace Engineering",
    GRACE_OLD_TENANT_ID: "Grace (stale UUID — replace with verified one)",
    G5_TENANT_ID:        "G5",
}


# ─────────────────────────────────────────────
# Raw endpoint wrappers
# ─────────────────────────────────────────────
def list_tenants(client) -> Any:
    """
    GET /mdm/v1/tenants

    Returns the list of tenants visible to the active credential.
    For a correctly-scoped credential this is typically a single tenant
    (the one your API key is bound to). Useful for confirming which
    tenant the credential actually lands on.
    """
    return client.get("mdm", "v1", "tenants")


def get_tenant(client, tenant_id: str) -> Any:
    """
    GET /mdm/v1/tenants/{id}

    Returns the full record for a specific tenant. 404 if the tenant
    does not exist or is not visible to the credential.
    """
    return client.get("mdm", "v1", f"tenants/{tenant_id}")


# ─────────────────────────────────────────────
# Composite check — the main diagnostic
# ─────────────────────────────────────────────
def tenant_whoami(client, configured_tenant_id: str = "") -> dict:
    """
    Composite tenant diagnostic.

    Calls list_tenants() and (if a configured ID is provided) get_tenant(),
    then compares the visible tenant(s) against the known Grace and G5 UUIDs
    so the UI can show a clear "is this the right tenant?" status.

    Uses ``client.get_envelope()`` so HTTP errors (401, 403, 404, 5xx) and
    network failures surface as distinct ``match`` values instead of being
    swallowed into ``no_data``.

    Returns a structured report:
        {
            "configured_tenant_id":    "<uuid or ''>",
            "configured_tenant_label": "Grace Engineering" | "G5" | "unknown",
            "visible_tenants":         [{id, code, name, label}, ...],
            "list_tenants_raw":        <raw API body>,
            "list_tenants_envelope":   {ok, status, reason, elapsed_ms, error},
            "get_tenant_raw":          <raw API body or None>,
            "match":                   "grace" | "g5" | "configured" |
                                       "other" | "no_data" |
                                       "auth_failed" | "request_failed",
            "summary":                 "<one-line human-readable status>",
        }
    """
    report: dict = {
        "configured_tenant_id":    configured_tenant_id or "",
        "configured_tenant_label": KNOWN_TENANTS.get(configured_tenant_id, "unknown"),
        "visible_tenants":         [],
        "list_tenants_raw":        None,
        "list_tenants_envelope":   None,
        "get_tenant_raw":          None,
        "match":                   "no_data",
        "summary":                 "",
    }

    # ── Step 1: list_tenants via get_envelope so HTTP errors surface ────
    list_env = client.get_envelope("mdm", "v1", "tenants")
    report["list_tenants_envelope"] = {
        "ok":         list_env["ok"],
        "status":     list_env["status"],
        "reason":     list_env["reason"],
        "elapsed_ms": list_env["elapsed_ms"],
        "error":      list_env["error"],
    }
    report["list_tenants_raw"] = list_env["body"]

    if not list_env["ok"]:
        status = list_env["status"]
        if status in (401, 403):
            report["match"] = "auth_failed"
            report["summary"] = (
                f"[ERROR] list_tenants returned HTTP {status} {list_env['reason']}. "
                f"Check that PLEX_API_KEY and PLEX_API_SECRET are valid in .env.local "
                f"or your shell environment. Underlying error: {list_env['error']}"
            )
        elif status == 0:
            report["match"] = "request_failed"
            report["summary"] = (
                f"[ERROR] list_tenants could not reach Plex: {list_env['error']}. "
                f"Check network connectivity and that {client.base} is reachable."
            )
        else:
            report["match"] = "request_failed"
            report["summary"] = (
                f"[ERROR] list_tenants returned HTTP {status} {list_env['reason']}: "
                f"{list_env['error']}"
            )
        return report

    listed = list_env["body"]

    # Normalize the response. Plex sometimes wraps lists in {data|items|rows}.
    if isinstance(listed, list):
        items = listed
    elif isinstance(listed, dict):
        items = (
            listed.get("items")
            or listed.get("data")
            or listed.get("rows")
            or [listed]   # single tenant returned as a bare object
        )
    else:
        items = []

    visible: list[dict] = []
    for t in items:
        if not isinstance(t, dict):
            continue
        tid = t.get("id") or t.get("tenantId") or t.get("Id")
        visible.append({
            "id":    tid,
            "code":  t.get("code") or t.get("Code"),
            "name":  t.get("name") or t.get("Name"),
            "label": KNOWN_TENANTS.get(tid, "unknown"),
        })
    report["visible_tenants"] = visible

    # ── Step 2: get_tenant for the configured ID ────────────────
    if configured_tenant_id:
        report["get_tenant_raw"] = get_tenant(client, configured_tenant_id)

    # ── Step 3: match logic ─────────────────────
    visible_ids = {t["id"] for t in visible if t.get("id")}

    if not visible_ids:
        report["match"] = "no_data"
        report["summary"] = (
            "list_tenants returned no data — the response was empty or "
            "contained no parseable tenant IDs. Check the raw response "
            "in this report."
        )
        return report

    if GRACE_TENANT_ID in visible_ids:
        report["match"] = "grace"
        report["summary"] = (
            "[OK] Connected to Grace Engineering. Tenant routing is resolved — "
            "you may flip TENANT_ID in plex_api.py to the Grace UUID and "
            "begin write-path testing."
        )
        return report

    if G5_TENANT_ID in visible_ids:
        report["match"] = "g5"
        report["summary"] = (
            "[WARN] Connected to G5 (read-only, another company's data). "
            "Awaiting IT (Courtney) to complete tenant routing for Grace. "
            "All writes are prohibited until this resolves — see issue #1."
        )
        return report

    if configured_tenant_id and configured_tenant_id in visible_ids:
        report["match"] = "configured"
        report["summary"] = (
            f"Connected to the configured tenant "
            f"({report['configured_tenant_label']}), which is neither "
            f"Grace nor G5. Verify this is intentional."
        )
        return report

    report["match"] = "other"
    report["summary"] = (
        "Connected to an unrecognized tenant. Inspect visible_tenants in "
        "this report and confirm the credential routing is what you expect."
    )
    return report


# ─────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys

    # Force UTF-8 stdout so em-dashes / brackets in summary strings don't
    # blow up on a Windows cp1252 console.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    from plex_api import PlexClient, API_KEY, API_SECRET, TENANT_ID, USE_TEST

    if not API_KEY or not API_SECRET:
        raise SystemExit(
            "Missing credentials. Set PLEX_API_KEY and PLEX_API_SECRET "
            "environment variables before running this diagnostic."
        )

    client = PlexClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        tenant_id=TENANT_ID,
        use_test=USE_TEST,
    )

    print(f"Plex Diagnostics — {'TEST' if USE_TEST else 'PRODUCTION'}")
    print(f"Base URL: {client.base}")
    print(f"Configured TENANT_ID: {TENANT_ID}\n")

    report = tenant_whoami(client, TENANT_ID)

    print("─" * 60)
    print(report["summary"])
    print("─" * 60)
    print(json.dumps(report, indent=2, default=str))
