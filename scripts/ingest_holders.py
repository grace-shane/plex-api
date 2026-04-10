"""
Ingest a Fusion 360 holder library JSON into the holder_catalog table.

Usage:
    py scripts/ingest_holders.py "path/to/holders.json" [--catalog-name "Haas Holders"]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Anchor to project root for imports
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import bootstrap  # noqa: E402, F401
from supabase_client import SupabaseClient  # noqa: E402

INCHES_TO_MM = 25.4

# Parse bore diameter from description — multiple patterns:
#   CT40 1/2" END MILL HOLDER ...     → 1/2
#   BT30 ER16 COLLET CHUCK ...        → ER16 (no bore)
#   CT40 3/4" SHRINK FIT HOLDER ...   → 3/4
#   20MM END MILL HOLDER ...           → 20mm
#   BT50 1" SHELL MILL ARBOR ...      → 1
BORE_INCH_RE = re.compile(
    r"(\d+(?:-\d+/\d+|\d*/\d+)?)"  # fraction or whole
    r'"'                             # inch mark
)

BORE_MM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*MM"  # metric bore
)

TAPER_RE = re.compile(r"((?:CT|BT|CAT)\d+)")


def parse_fraction(s: str) -> float | None:
    """Parse '1/2', '1-1/4', '3/4', '1' etc. to float inches."""
    s = s.strip()
    if not s:
        return None

    # Mixed number: 1-1/4
    if "-" in s and "/" in s:
        parts = s.split("-", 1)
        try:
            whole = float(parts[0])
            num, den = parts[1].split("/")
            return whole + float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None

    # Simple fraction: 1/2
    if "/" in s:
        try:
            num, den = s.split("/")
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None

    # Whole number
    try:
        return float(s)
    except ValueError:
        return None


def parse_bore_mm(desc: str) -> float | None:
    """Extract bore diameter in mm from holder description."""
    # Try inch fraction first
    m = BORE_INCH_RE.search(desc)
    if m:
        val = parse_fraction(m.group(1))
        if val is not None:
            return val * INCHES_TO_MM

    # Try metric
    m = BORE_MM_RE.search(desc)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def parse_holder(h: dict, catalog_name: str) -> dict:
    desc = h.get("description", "")
    pid = h.get("product-id", "")

    # Taper type
    taper_match = TAPER_RE.search(desc)
    taper_type = taper_match.group(1) if taper_match else None

    # Bore diameter (mm)
    bore_mm = parse_bore_mm(desc)

    # Gauge length (inches → mm)
    gl_in = h.get("gaugeLength")
    gl_mm = gl_in * INCHES_TO_MM if gl_in is not None else None

    return {
        "catalog_name": catalog_name,
        "vendor": "Haas",
        "product_id": pid,
        "description": desc,
        "taper_type": taper_type,
        "bore_diameter": bore_mm,
        "gauge_length": gl_mm,
        "product_link": h.get("product-link", ""),
        "guid": h.get("guid", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest holder library into Supabase")
    parser.add_argument("file", type=Path, help="Path to .json holder library")
    parser.add_argument("--catalog-name", default="Haas Holders", help="Catalog label")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    args = parser.parse_args()

    with open(args.file) as f:
        data = json.load(f)["data"]

    print(f"Loaded {len(data)} holders from {args.file.name}")

    rows = [parse_holder(h, args.catalog_name) for h in data]

    # Stats
    with_bore = sum(1 for r in rows if r["bore_diameter"] is not None)
    tapers: dict[str, int] = {}
    for r in rows:
        t = r["taper_type"] or "unknown"
        tapers[t] = tapers.get(t, 0) + 1

    print(f"  Bore parsed: {with_bore}/{len(rows)}")
    print(f"  Taper types: {tapers}")

    if args.dry_run:
        for r in rows[:10]:
            bore_str = f"bore={r['bore_diameter']:.2f}mm" if r["bore_diameter"] else "bore=?"
            print(f"    {r['product_id']:10s} {r['taper_type'] or '?':5s} "
                  f"{bore_str:16s}  {r['description'][:55]}")
        print("  (dry run, no write)")
        return

    sb = SupabaseClient()

    # Delete existing entries for this catalog, then insert fresh
    sb.delete("holder_catalog", filters={"catalog_name": f"eq.{args.catalog_name}"})

    # Batch insert in chunks of 50
    for i in range(0, len(rows), 50):
        chunk = rows[i : i + 50]
        sb.insert("holder_catalog", chunk)
        print(f"  Inserted {min(i + 50, len(rows))}/{len(rows)}")

    print(f"Done — {len(rows)} holders ingested as '{args.catalog_name}'")


if __name__ == "__main__":
    main()
