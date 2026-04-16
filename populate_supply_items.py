#!/usr/bin/env python
"""
populate_supply_items.py
Compute Plex supply-item payloads from ``tools`` and stage into
``plex_supply_items``.
Grace Engineering -- Datum project  --  Issue #79
=============================================================
For every row in ``tools`` with a non-empty ``product_id`` (the eventual
``supplyItemNumber`` on the Plex wire), compute the 6-field payload and
upsert into ``plex_supply_items``.  **No Plex HTTP calls** — this is
pure Fusion → Supabase staging.

The three DB-defaulted columns (``category``, ``inventory_unit``,
``item_type``) are omitted from the upsert so the migration defaults
govern.  Only the three derived columns are written:

  description        <- tools.description
  item_group         <- mapped from tools.type (default "Machining")
  supply_item_number <- tools.product_id

``plex_id`` and ``posted_to_plex_at`` stay NULL — the writeback worker
(#3) fills those after a successful POST to Plex.

Usage
-----
    py populate_supply_items.py                 # run the populate
    py populate_supply_items.py --dry-run       # compute, no writes
    py populate_supply_items.py -v              # debug logging

Exit codes
----------
    0  All eligible tools staged
    1  One or more rows failed (partial)
    2  Fatal: config missing, no tools, etc.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import bootstrap  # noqa: E402, F401 -- loads .env.local

from supabase_client import SupabaseClient  # noqa: E402

log = logging.getLogger("datum.populate_supply_items")

# ---------------------------------------------------------------
# Type → Plex group mapping
# ---------------------------------------------------------------
# Grace's Plex tenant has two supply-item groups for tooling:
#   "Machining"  (1,039 items) — cutting tools, inserts, drills, etc.
#   "Tool Room"  (104 items)   — holders, collets, fixtures, etc.
# All Fusion tool types that survive the holder/probe exclusion filter
# in sync_supabase.py are cutting tools, so "Machining" is the
# universal default.  Override per-type if needed later.
TYPE_TO_GROUP: dict[str, str] = {
    # Every Fusion tool type maps to "Machining" today.
    # Add overrides here when needed, e.g.:
    #   "holder": "Tool Room",
}

DEFAULT_GROUP = "Machining"


def tool_type_to_group(tool_type: str | None) -> str:
    """Map a ``tools.type`` value to a Plex supply-item group name."""
    if not tool_type:
        return DEFAULT_GROUP
    return TYPE_TO_GROUP.get(tool_type.lower(), DEFAULT_GROUP)


# ---------------------------------------------------------------
# Payload builder (pure — no I/O)
# ---------------------------------------------------------------
def build_supply_item_row(tool: dict[str, Any]) -> dict[str, Any]:
    """Build a ``plex_supply_items`` row dict from a ``tools`` row.

    Only includes the three derived columns plus ``fusion_guid`` (the PK).
    The three defaulted columns (``category``, ``inventory_unit``,
    ``item_type``) are omitted so the DB defaults apply on INSERT, and
    are left untouched on conflict-merge UPDATE.

    Parameters
    ----------
    tool : dict
        A ``tools`` row with at least ``fusion_guid``, ``product_id``,
        ``description``, and ``type``.

    Returns
    -------
    dict
        Row suitable for ``SupabaseClient.upsert("plex_supply_items", ...)``.
    """
    return {
        "fusion_guid": tool["fusion_guid"],
        "description": tool.get("description") or "",
        "item_group": tool_type_to_group(tool.get("type")),
        "supply_item_number": tool.get("product_id") or "",
    }


# ---------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------
@dataclass
class RowResult:
    fusion_guid: str
    status: str  # "staged" | "skipped" | "fail"
    message: str = ""


@dataclass
class PopulateReport:
    results: list[RowResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def staged(self) -> list[RowResult]:
        return [r for r in self.results if r.status == "staged"]

    @property
    def skipped(self) -> list[RowResult]:
        return [r for r in self.results if r.status == "skipped"]

    @property
    def failed(self) -> list[RowResult]:
        return [r for r in self.results if r.status == "fail"]

    @property
    def elapsed(self) -> float:
        return self.end_time - self.start_time

    def print_summary(self) -> None:
        log.info("=" * 60)
        log.info("Supply-item staging complete")
        log.info(
            "  %d staged, %d skipped (no product_id), %d failed",
            len(self.staged),
            len(self.skipped),
            len(self.failed),
        )
        log.info("  Elapsed: %.1fs", self.elapsed)
        log.info("=" * 60)


# ---------------------------------------------------------------
# Main populate
# ---------------------------------------------------------------
def populate_supply_items(
    sb: SupabaseClient,
    *,
    dry_run: bool = False,
) -> PopulateReport:
    """Read ``tools``, compute payloads, upsert into ``plex_supply_items``.

    Tools with an empty ``product_id`` are skipped — the eventual
    ``supplyItemNumber`` would be blank, which Plex rejects.

    Returns a PopulateReport with per-row results.
    """
    report = PopulateReport(start_time=time.monotonic())

    # 1. Fetch all tools
    tools = sb.select(
        "tools",
        columns="fusion_guid,description,product_id,type",
    )
    log.info("Found %d tool(s) in Supabase", len(tools))

    if not tools:
        report.end_time = time.monotonic()
        return report

    # 2. Build rows, skipping tools without a product_id
    rows_to_upsert: list[dict[str, Any]] = []
    for tool in tools:
        fusion_guid = tool["fusion_guid"]
        product_id = (tool.get("product_id") or "").strip()

        if not product_id:
            report.results.append(RowResult(fusion_guid, "skipped", "no product_id"))
            log.debug("  SKIP %s: no product_id", fusion_guid)
            continue

        row = build_supply_item_row(tool)
        rows_to_upsert.append(row)
        report.results.append(RowResult(fusion_guid, "staged"))

    log.info(
        "  %d eligible, %d skipped (no product_id)",
        len(rows_to_upsert),
        len(report.skipped),
    )

    if not rows_to_upsert:
        report.end_time = time.monotonic()
        return report

    if dry_run:
        log.info("  DRY-RUN: would upsert %d row(s)", len(rows_to_upsert))
        report.end_time = time.monotonic()
        return report

    # 3. Batch upsert
    try:
        sb.upsert("plex_supply_items", rows_to_upsert, on_conflict="fusion_guid")
        log.info("  Upserted %d row(s) to plex_supply_items", len(rows_to_upsert))
    except Exception as e:
        log.error("  Supabase upsert failed: %s", e)
        # Mark all staged rows as failed
        for r in report.results:
            if r.status == "staged":
                r.status = "fail"
                r.message = str(e)

    report.end_time = time.monotonic()
    return report


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Datum -- populate plex_supply_items staging table from tools",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute payloads but do not write to Supabase")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug-level logging")
    parser.add_argument("--log-file", type=str, default=None,
                        help="Append logs to this file (in addition to stdout)")
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

    log.info("Supply-item staging starting%s", " (dry-run)" if args.dry_run else "")

    try:
        sb = SupabaseClient()
    except Exception as e:
        log.critical("Config error: %s", e)
        return 2

    try:
        report = populate_supply_items(sb, dry_run=args.dry_run)
    except Exception as e:
        log.critical("Fatal error: %s", e)
        return 2

    report.print_summary()

    if not report.results:
        log.warning("No tools found in Supabase")
        return 2

    return 1 if report.failed else 0


def cli() -> None:
    """Console-script entry point (``datum-populate-supply-items``)."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
