#!/usr/bin/env python
"""
sync_tool_inventory.py
Plex -> Supabase nightly sync of tool on-hand quantities.
Grace Engineering -- Datum project  --  Issue #75
=============================================================
For every row in ``tools`` with a non-NULL ``plex_supply_item_id``, call
``inventory/v1-beta1/inventory-history/item-adjustments`` and update:

  qty_on_hand   -- sum of adjustment quantities (quantity is pre-signed by Plex)
  qty_tracked   -- TRUE iff Plex returned >=1 adjustment record
  qty_synced_at -- now()

See docs/Plex_API_Reference.md Section 3.6 for the transactionType sign
table. The contract: ``quantity`` is delivered pre-signed, so we sum it
directly -- no lookup from transactionType required.

Usage
-----
    py sync_tool_inventory.py                 # run the sync
    py sync_tool_inventory.py --dry-run       # fetch + compute, no Supabase writes
    py sync_tool_inventory.py -v              # debug logging
    py sync_tool_inventory.py --log-file f.log

Exit codes
----------
    0  All linked tools synced
    1  One or more tools failed (partial)
    2  Fatal: config missing, no tools linked, etc.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import bootstrap  # noqa: E402, F401 -- loads .env.local

from plex_api import PlexClient, API_KEY, API_SECRET, TENANT_ID, USE_TEST  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402

log = logging.getLogger("datum.sync_tool_inventory")

# History window. 2015-01-01 predates Grace's Plex go-live; using a wide
# window means we capture the full running balance, not just recent deltas.
# Plex requires full ISO with Z suffix -- plain dates return 400.
DEFAULT_START = "2015-01-01T00:00:00Z"

# Known transactionType values as of 2026-04-15 probe. Unknown values are
# still summed (quantity is pre-signed) but we log a warning so new types
# can be reviewed and added to the docs.
KNOWN_TRANSACTION_TYPES = frozenset({
    "PO Receipt",
    "Checkout",
    "Correction",
    "Check In",
})


# ---------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------
@dataclass
class ToolResult:
    fusion_guid: str
    plex_supply_item_id: str
    status: str  # "success" | "fail"
    qty_on_hand: float | None = None
    qty_tracked: bool | None = None
    n_records: int = 0
    message: str = ""


@dataclass
class SyncReport:
    results: list[ToolResult] = field(default_factory=list)
    unknown_transaction_types: set[str] = field(default_factory=set)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def succeeded(self) -> list[ToolResult]:
        return [r for r in self.results if r.status == "success"]

    @property
    def failed(self) -> list[ToolResult]:
        return [r for r in self.results if r.status == "fail"]

    @property
    def tracked(self) -> list[ToolResult]:
        return [r for r in self.succeeded if r.qty_tracked]

    @property
    def elapsed(self) -> float:
        return self.end_time - self.start_time

    def print_summary(self) -> None:
        log.info("=" * 60)
        log.info("Tool inventory sync complete")
        log.info(
            "  %d succeeded (%d with history, %d empty), %d failed",
            len(self.succeeded),
            len(self.tracked),
            len(self.succeeded) - len(self.tracked),
            len(self.failed),
        )
        log.info("  Elapsed: %.1fs", self.elapsed)
        if self.unknown_transaction_types:
            log.warning(
                "  Unknown transactionType values encountered: %s "
                "-- review and update docs/Plex_API_Reference.md Section 3.6",
                sorted(self.unknown_transaction_types),
            )
        log.info("=" * 60)


# ---------------------------------------------------------------
# Pure helpers (easy to unit-test)
# ---------------------------------------------------------------
def compute_qty(records: list[dict]) -> tuple[float, bool]:
    """Return (qty_on_hand, qty_tracked) for a list of adjustment records.

    ``quantity`` is delivered pre-signed by Plex (positive for receipts/
    check-ins, negative for checkouts), so we sum directly. Missing or
    non-numeric quantities are skipped silently.

    qty_tracked is TRUE iff ``records`` is non-empty -- a linked tool with
    zero history is a valid, distinct state from "not linked".
    """
    total = 0.0
    for r in records:
        q = r.get("quantity")
        if q is None:
            continue
        try:
            total += float(q)
        except (TypeError, ValueError):
            continue
    return total, len(records) > 0


def collect_unknown_types(records: list[dict]) -> set[str]:
    """Return the set of transactionType values not in KNOWN_TRANSACTION_TYPES."""
    unknown = set()
    for r in records:
        tt = r.get("transactionType")
        if tt is not None and tt not in KNOWN_TRANSACTION_TYPES:
            unknown.add(tt)
    return unknown


def _unwrap_records(body: Any) -> list[dict]:
    """Plex inventory-history returns either a bare list or {data: [...]}."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return data
    return []


# ---------------------------------------------------------------
# Main sync
# ---------------------------------------------------------------
def sync_tool_inventory(
    plex: PlexClient,
    sb: SupabaseClient,
    *,
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
    dry_run: bool = False,
) -> SyncReport:
    """Sync qty_on_hand / qty_tracked / qty_synced_at from Plex to Supabase.

    Fetches every ``tools`` row with a non-NULL ``plex_supply_item_id``,
    calls ``inventory/v1-beta1/inventory-history/item-adjustments`` for
    each, and writes the computed totals back. Returns a SyncReport.
    """
    report = SyncReport(start_time=time.monotonic())

    if end_date is None:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Fetch linked tools from Supabase
    linked = sb.select(
        "tools",
        columns="fusion_guid,plex_supply_item_id",
        filters={"plex_supply_item_id": "not.is.null"},
    )
    log.info("Found %d linked tool(s) in Supabase", len(linked))

    if not linked:
        report.end_time = time.monotonic()
        return report

    # 2. For each, fetch adjustments and update Supabase
    for tool in linked:
        fusion_guid = tool["fusion_guid"]
        plex_id = tool["plex_supply_item_id"]

        env = plex.get_envelope(
            "inventory", "v1-beta1", "inventory-history/item-adjustments",
            params={"ItemId": plex_id, "StartDate": start_date, "EndDate": end_date},
        )

        if not env["ok"]:
            report.results.append(ToolResult(
                fusion_guid=fusion_guid,
                plex_supply_item_id=plex_id,
                status="fail",
                message=f"Plex {env['status']}: {env.get('error') or env.get('body')}",
            ))
            log.error("  FAIL %s: Plex HTTP %s", fusion_guid, env["status"])
            continue

        records = _unwrap_records(env["body"])
        qty_on_hand, qty_tracked = compute_qty(records)
        unknown = collect_unknown_types(records)
        if unknown:
            report.unknown_transaction_types.update(unknown)
            log.warning(
                "  %s: unknown transactionType(s) %s (still summing; pre-signed quantity)",
                fusion_guid, sorted(unknown),
            )

        result = ToolResult(
            fusion_guid=fusion_guid,
            plex_supply_item_id=plex_id,
            status="success",
            qty_on_hand=qty_on_hand,
            qty_tracked=qty_tracked,
            n_records=len(records),
        )

        if dry_run:
            log.info(
                "  DRY-RUN %s: qty=%s tracked=%s n=%d",
                fusion_guid, qty_on_hand, qty_tracked, len(records),
            )
            report.results.append(result)
            continue

        # 3. Write back to Supabase
        try:
            sb.update(
                "tools",
                {
                    "qty_on_hand": qty_on_hand,
                    "qty_tracked": qty_tracked,
                    "qty_synced_at": datetime.now(timezone.utc).isoformat(),
                },
                filters={"fusion_guid": f"eq.{fusion_guid}"},
            )
            log.info(
                "  OK %s: qty=%s tracked=%s n=%d",
                fusion_guid, qty_on_hand, qty_tracked, len(records),
            )
            report.results.append(result)
        except Exception as e:
            result.status = "fail"
            result.message = f"Supabase update: {e}"
            log.error("  FAIL %s: Supabase update: %s", fusion_guid, e)
            report.results.append(result)

    report.end_time = time.monotonic()
    return report


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Datum -- sync tool on-hand qty from Plex to Supabase",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and compute, but do not write to Supabase")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug-level logging")
    parser.add_argument("--log-file", type=str, default=None,
                        help="Append logs to this file (in addition to stdout)")
    parser.add_argument("--start-date", type=str, default=DEFAULT_START,
                        help=f"ISO start date (default: {DEFAULT_START})")
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

    log.info("Tool inventory sync starting%s", " (dry-run)" if args.dry_run else "")

    try:
        plex = PlexClient(API_KEY, API_SECRET, TENANT_ID, use_test=USE_TEST)
        sb = SupabaseClient()
    except Exception as e:
        log.critical("Config error: %s", e)
        return 2

    try:
        report = sync_tool_inventory(
            plex, sb,
            start_date=args.start_date,
            dry_run=args.dry_run,
        )
    except Exception as e:
        log.critical("Fatal sync error: %s", e)
        return 2

    report.print_summary()

    if not report.results:
        log.warning("No linked tools to sync -- populate tools.plex_supply_item_id first")
        return 2

    return 1 if report.failed else 0


def cli() -> None:
    """Console-script entry point (``datum-sync-inventory``)."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
