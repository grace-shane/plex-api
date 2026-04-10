#!/usr/bin/env python
"""
enrich.py
Cross-reference shop tools against the vendor reference catalog
Grace Engineering — Datum project
=============================================================
Matches tools in the ``tools`` table that have empty/missing
``product_id`` against the ``reference_catalog`` table by
geometry fingerprint (type + cutting diameter + flute count).

Usage
-----
    # Preview matches (no writes)
    py enrich.py --dry-run

    # Apply matches — writes product_id + vendor back to tools table
    py enrich.py

    # Verbose logging
    py enrich.py -v
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import bootstrap  # noqa: E402, F401

from supabase_client import SupabaseClient  # noqa: E402

log = logging.getLogger("datum.enrich")

# Geometry tolerance for floating-point matching (mm)
DC_TOLERANCE = 0.01   # 0.01mm ~ 0.0004"
NOF_TOLERANCE = 0.5   # flute count is integer, but stored as float


def find_tools_missing_product_id(client: SupabaseClient) -> list[dict]:
    """Fetch tools where product_id is empty or blank."""
    resp = client.select(
        "tools",
        columns="id,fusion_guid,type,description,geo_dc,geo_nof,geo_oal,vendor,product_id,library_id",
        filters={"or": "(product_id.eq.,product_id.is.null)"},
    )
    return resp


def find_reference_match(
    client: SupabaseClient,
    tool_type: str,
    geo_dc: float | None,
    geo_nof: float | None,
) -> dict | None:
    """
    Find the best match in reference_catalog by (type, DC, NOF).
    Returns the first match or None.
    """
    if geo_dc is None or geo_nof is None:
        return None

    dc_lo = geo_dc - DC_TOLERANCE
    dc_hi = geo_dc + DC_TOLERANCE
    nof_lo = geo_nof - NOF_TOLERANCE
    nof_hi = geo_nof + NOF_TOLERANCE

    resp = client.select(
        "reference_catalog",
        columns="vendor,product_id,description,catalog_name,geo_dc,geo_nof,geo_oal",
        filters={
            "type": f"eq.{tool_type}",
            "geo_dc": f"gte.{dc_lo}",
            "geo_dc": f"lte.{dc_hi}",
            "geo_nof": f"gte.{nof_lo}",
            "geo_nof": f"lte.{nof_hi}",
        },
        limit=5,
    )
    # PostgREST doesn't support duplicate keys in filters dict,
    # so we use raw query params for range queries
    return resp[0] if resp else None


def find_reference_match_raw(
    client: SupabaseClient,
    tool_type: str,
    geo_dc: float | None,
    geo_nof: float | None,
) -> dict | None:
    """
    Find the best match using direct PostgREST range query.
    """
    if geo_dc is None or geo_nof is None:
        return None

    dc_lo = geo_dc - DC_TOLERANCE
    dc_hi = geo_dc + DC_TOLERANCE
    nof_val = round(geo_nof)

    # Build query string manually for range filters
    import requests

    url = client._table_url("reference_catalog")
    params = {
        "select": "vendor,product_id,description,catalog_name,geo_dc,geo_nof,geo_oal",
        "type": f"eq.{tool_type}",
        "geo_dc": f"gte.{dc_lo}",
        "geo_nof": f"eq.{nof_val}",
        "limit": "5",
        "order": "geo_dc.asc",
    }

    resp = client._session.get(
        url,
        params=params,
        headers={
            **client._session.headers,
            "Range": "0-4",
        },
        timeout=client.timeout,
    )

    if not resp.ok:
        return None

    results = resp.json()
    if not results:
        # Retry with just dc range (some tools have wrong NOF in Fusion)
        return None

    # Filter by DC upper bound (params only had gte, add lte check here)
    filtered = [r for r in results if r.get("geo_dc", 0) <= dc_hi]
    return filtered[0] if filtered else None


# ─────────────────────────────────────────────
# Upstream enrichment (raw Fusion JSON, pre-validation)
# ─────────────────────────────────────────────
INCHES_TO_MM = 25.4


def enrich_raw_tools(
    tools: list[dict],
    client: SupabaseClient,
) -> dict[str, int]:
    """
    Enrich raw Fusion tool dicts in-place before validation.

    For each tool missing ``product-id``, queries the reference_catalog
    by (type, DC, NOF) geometry match and fills in ``product-id`` and
    ``vendor`` from the best match.

    Parameters
    ----------
    tools : list[dict]
        Raw Fusion JSON tool dicts (the "data" array). Modified in-place.
    client : SupabaseClient
        Client with access to reference_catalog table.

    Returns
    -------
    dict
        ``{"enriched": N, "skipped": M}`` counts.
    """
    enriched = 0
    skipped = 0

    for t in tools:
        # Skip holders/probes and tools that already have product-id
        if t.get("type") in ("holder", "probe"):
            continue
        pid = t.get("product-id", "")
        if pid and str(pid).strip():
            continue

        # Normalize DC to mm for reference catalog lookup
        geo = t.get("geometry") or {}
        dc_raw = geo.get("DC")
        nof_raw = geo.get("NOF")
        unit = t.get("unit", "inches")

        if dc_raw is None or nof_raw is None:
            skipped += 1
            continue

        try:
            dc_mm = float(dc_raw)
            if isinstance(unit, str) and unit.lower() == "inches":
                dc_mm *= INCHES_TO_MM
            nof = float(nof_raw)
        except (TypeError, ValueError):
            skipped += 1
            continue

        ref = find_reference_match_raw(client, t.get("type", ""), dc_mm, nof)
        if ref:
            t["product-id"] = ref["product_id"]
            if ref.get("vendor") and not t.get("vendor"):
                t["vendor"] = ref["vendor"]
            enriched += 1
            log.info(
                "  ENRICH: %s -> %s %s",
                t.get("description", t.get("type", "")),
                ref["vendor"],
                ref["product_id"],
            )
        else:
            skipped += 1

    return {"enriched": enriched, "skipped": skipped}


def enrich_tools(
    client: SupabaseClient,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Find tools missing product_id and try to match them against
    the reference catalog. Returns counts.
    """
    missing = find_tools_missing_product_id(client)
    log.info("Found %d tools with missing product_id", len(missing))

    matched = 0
    unmatched = 0

    for tool in missing:
        tool_type = tool.get("type", "")
        geo_dc = tool.get("geo_dc")
        geo_nof = tool.get("geo_nof")
        desc = tool.get("description", "")
        tool_id = tool["id"]

        ref = find_reference_match_raw(client, tool_type, geo_dc, geo_nof)

        if ref:
            matched += 1
            log.info(
                "MATCH: %s (DC=%.2f NOF=%s) -> %s %s (%s)",
                desc or tool_type,
                geo_dc or 0,
                int(geo_nof) if geo_nof else "?",
                ref["vendor"],
                ref["product_id"],
                ref["catalog_name"],
            )

            if not dry_run:
                client.update(
                    "tools",
                    {"product_id": ref["product_id"], "vendor": ref["vendor"]},
                    filters={"id": f"eq.{tool_id}"},
                )
        else:
            unmatched += 1
            log.info(
                "NO MATCH: %s (DC=%.2f NOF=%s)",
                desc or tool_type,
                geo_dc or 0,
                int(geo_nof) if geo_nof else "?",
            )

    return {"matched": matched, "unmatched": unmatched, "total": len(missing)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enrich shop tools with product IDs from vendor reference catalog",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matches only, no writes to tools table",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Debug-level logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    client = SupabaseClient()
    start = time.monotonic()

    counts = enrich_tools(client, dry_run=args.dry_run)

    elapsed = time.monotonic() - start
    log.info("=" * 60)
    log.info(
        "Enrichment %s",
        "preview (dry-run)" if args.dry_run else "complete",
    )
    log.info(
        "  %d matched, %d unmatched out of %d",
        counts["matched"],
        counts["unmatched"],
        counts["total"],
    )
    log.info("  Elapsed: %.1fs", elapsed)
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
