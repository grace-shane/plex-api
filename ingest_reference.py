#!/usr/bin/env python
"""
ingest_reference.py
Load vendor catalog JSON files into the reference_catalog table
Grace Engineering — Datum project
=============================================================
Reads Fusion 360 tool library JSON files (the large hsmtools
vendor catalogs) and upserts them into the ``reference_catalog``
Supabase table for geometry-based cross-referencing.

Usage
-----
    # Ingest all catalogs from a directory
    py ingest_reference.py C:\\Users\\shanewaid\\Downloads

    # Ingest specific files
    py ingest_reference.py "Harvey Tool-End Mills (1).json" "Garr Tool-Garr Tool.json"

    # Dry run — parse and count, no Supabase writes
    py ingest_reference.py --dry-run C:\\Users\\shanewaid\\Downloads
"""
from __future__ import annotations

import argparse
import json
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
from sync_supabase import INCHES_TO_MM, EXCLUDED_TYPES  # noqa: E402

log = logging.getLogger("datum.ingest_reference")

# Minimum file size to consider (skip empty / tiny files)
MIN_FILE_SIZE = 1024  # 1 KB

# Batch size for Supabase upserts (PostgREST has payload limits)
BATCH_SIZE = 500


def _normalize_dc(value, unit: str) -> float | None:
    """Normalize cutting diameter to mm."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if unit.lower() == "inches":
        v *= INCHES_TO_MM
    return round(v, 6)


def _maybe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_reference_rows(
    catalog_name: str,
    tools: list[dict],
    unit_default: str = "inches",
) -> list[dict]:
    """
    Convert raw Fusion tool dicts into reference_catalog rows.
    Skips holders, probes, and tools without product-id.
    """
    rows = []
    for t in tools:
        tool_type = t.get("type", "")
        if tool_type in EXCLUDED_TYPES:
            continue

        pid = t.get("product-id", "")
        if not pid or not str(pid).strip():
            continue  # can't be a reference without a product-id

        unit = t.get("unit") or unit_default
        geo = t.get("geometry") or {}
        is_inches = isinstance(unit, str) and unit.lower() == "inches"

        row = {
            "catalog_name": catalog_name,
            "vendor": (t.get("vendor") or "").strip(),
            "product_id": str(pid).strip(),
            "description": (t.get("description") or "").strip(),
            "type": tool_type,
            "geo_dc": _normalize_dc(geo.get("DC"), unit) if is_inches
                else _maybe_float(geo.get("DC")),
            "geo_nof": _maybe_float(geo.get("NOF")),
            "geo_oal": _normalize_dc(geo.get("OAL"), unit) if is_inches
                else _maybe_float(geo.get("OAL")),
            "geo_lcf": _normalize_dc(geo.get("LCF"), unit) if is_inches
                else _maybe_float(geo.get("LCF")),
            "geo_sig": _maybe_float(geo.get("SIG")),
            "unit_original": unit,
        }
        rows.append(row)

    return rows


def ingest_catalog_file(
    path: Path,
    *,
    client: SupabaseClient | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Load one vendor catalog JSON and upsert into reference_catalog.

    Returns {"tools": N, "skipped": M} counts.
    """
    catalog_name = path.stem
    # Strip trailing copy numbers: "Harvey Tool-End Mills (1)" -> "Harvey Tool-End Mills"
    for suffix in (" (1)", " (2)", " (3)"):
        if catalog_name.endswith(suffix):
            catalog_name = catalog_name[: -len(suffix)]
            break

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    tools = raw.get("data", [])
    if not isinstance(tools, list):
        log.error("No 'data' array in %s", path.name)
        return {"tools": 0, "skipped": 0}

    rows = build_reference_rows(catalog_name, tools)
    skipped = len(tools) - len(rows)

    log.info(
        "%s: %d tools -> %d reference rows (%d skipped)",
        catalog_name,
        len(tools),
        len(rows),
        skipped,
    )

    if dry_run or not rows:
        return {"tools": len(rows), "skipped": skipped}

    # Upsert in batches
    total_upserted = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        client.upsert(
            "reference_catalog",
            batch,
            on_conflict="catalog_name,product_id",
        )
        total_upserted += len(batch)
        if i + BATCH_SIZE < len(rows):
            log.info("  ... %d / %d upserted", total_upserted, len(rows))

    return {"tools": total_upserted, "skipped": skipped}


def find_catalog_files(paths: list[str]) -> list[Path]:
    """
    Resolve CLI arguments to a list of JSON files.
    Accepts files or directories (scans for large .json files).
    """
    result = []
    for p in paths:
        path = Path(p)
        if path.is_file() and path.suffix == ".json":
            if path.stat().st_size >= MIN_FILE_SIZE:
                result.append(path)
        elif path.is_dir():
            for f in sorted(path.glob("*.json")):
                if f.stat().st_size >= MIN_FILE_SIZE:
                    result.append(f)
    return result


# Known hsmtools vendor catalog patterns (to filter out shop-specific files)
VENDOR_CATALOG_PATTERNS = [
    "Harvey Tool",
    "Helical Solutions",
    "Garr Tool",
    "Guhring",
    "Sandvik",
    "Delta Tools",
    "XEBEC",
    "Kennametal",
    "OSG",
    "Dormer",
    "Iscar",
    "Mitsubishi",
    "Walter",
    "Seco",
    "YG-1",
    "Kyocera",
    "Micro 100",
    "Widia",
    "Emuge",
    "Nachi",
    "Multi_Vendor",
]


def is_vendor_catalog(path: Path) -> bool:
    """Check if a file looks like a vendor catalog (not a shop-specific library)."""
    name = path.stem
    return any(pat.lower() in name.lower() for pat in VENDOR_CATALOG_PATTERNS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest vendor tool catalogs into Supabase reference_catalog",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="JSON files or directories to ingest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count only, no Supabase writes",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include all JSON files (not just recognized vendor catalogs)",
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

    files = find_catalog_files(args.paths)

    if not args.all:
        files = [f for f in files if is_vendor_catalog(f)]

    if not files:
        log.error("No catalog files found in %s", args.paths)
        return 2

    log.info("Found %d catalog file(s) to ingest", len(files))

    client = None if args.dry_run else SupabaseClient()
    start = time.monotonic()

    total_tools = 0
    total_skipped = 0
    errors = 0

    for f in files:
        try:
            counts = ingest_catalog_file(f, client=client, dry_run=args.dry_run)
            total_tools += counts["tools"]
            total_skipped += counts["skipped"]
        except Exception as e:
            log.error("Failed to ingest %s: %s", f.name, e)
            errors += 1

    elapsed = time.monotonic() - start
    log.info("=" * 60)
    log.info("Reference catalog ingest complete")
    log.info("  %d tools ingested, %d skipped, %d errors", total_tools, total_skipped, errors)
    log.info("  Elapsed: %.1fs", elapsed)
    log.info("=" * 60)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
