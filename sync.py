#!/usr/bin/env python
"""
sync.py
Nightly sync CLI — APS cloud-first, local ADC fallback
Grace Engineering — Datum project
=============================================================
Downloads Fusion 360 tool libraries from the Autodesk cloud
(APS Data Management API) and upserts them into Supabase.
Falls back to local ADC-synced files when APS OAuth is
unavailable.

Usage
-----
    # Full sync (APS cloud → Supabase)
    py sync.py

    # Dry run — download + validate only, no Supabase writes
    py sync.py --dry-run

    # Force local ADC fallback (skip APS entirely)
    py sync.py --local

    # Verbose logging
    py sync.py -v

Exit codes
----------
    0  All libraries synced (or validated, in dry-run mode)
    1  One or more libraries failed validation or sync
    2  Fatal error (no source available, config missing, etc.)

Scheduling
----------
    # Windows Task Scheduler (daily at 02:00)
    schtasks /create /tn "Datum Nightly Sync" ^
        /tr "py C:\\projects\\Datum\\sync.py" /sc daily /st 02:00

    # Linux cron (daily at 02:00)
    0 2 * * * /opt/datum/sync.py >> /var/log/datum-sync.log 2>&1
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── Anchor working directory to the project root ──────────
# Task Scheduler / cron may launch from any CWD. All local
# imports (bootstrap, aps_client, etc.) and .env.local rely
# on CWD being the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import bootstrap  # noqa: E402, F401 — loads .env.local into os.environ

from aps_client import APSClient, APSAuthError, APSConfigError, APSHTTPError  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402
from sync_supabase import sync_library, hash_file  # noqa: E402
from tool_library_loader import load_all_libraries, CAM_TOOLS_DIR  # noqa: E402
from enrich import enrich_raw_tools  # noqa: E402
from populate_supply_items import populate_supply_items  # noqa: E402
from validate_library import validate_library, ValidationMode  # noqa: E402

log = logging.getLogger("datum.sync")

# Known XWERKS hub IDs (see memory: project_aps_cloud_integration.md)
PROJECT_ID = "a.YnVzaW5lc3M6Z3JhY2Vlbmc0I0QyMDI0MTIyMDg0OTIxNzc3Ng"
CAM_TOOLS_FOLDER = "urn:adsk.wipprod:fs.folder:co.C0zYkNP4TOexre_-hWRhRA"


# ─────────────────────────────────────────────
# Result tracking
# ─────────────────────────────────────────────
@dataclass
class LibraryResult:
    name: str
    status: str  # "success" | "skipped" | "fail"
    tools: int = 0
    presets: int = 0
    message: str = ""


@dataclass
class SyncReport:
    source: str  # "aps" | "local"
    results: list[LibraryResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def succeeded(self) -> list[LibraryResult]:
        return [r for r in self.results if r.status == "success"]

    @property
    def failed(self) -> list[LibraryResult]:
        return [r for r in self.results if r.status == "fail"]

    @property
    def skipped(self) -> list[LibraryResult]:
        return [r for r in self.results if r.status == "skipped"]

    @property
    def total_tools(self) -> int:
        return sum(r.tools for r in self.results)

    @property
    def total_presets(self) -> int:
        return sum(r.presets for r in self.results)

    @property
    def elapsed(self) -> float:
        return self.end_time - self.start_time

    def print_summary(self) -> None:
        log.info("=" * 60)
        log.info("Sync complete — source: %s", self.source)
        log.info(
            "  %d succeeded, %d skipped, %d failed",
            len(self.succeeded),
            len(self.skipped),
            len(self.failed),
        )
        log.info(
            "  Totals: %d tools, %d presets",
            self.total_tools,
            self.total_presets,
        )
        log.info("  Elapsed: %.1fs", self.elapsed)
        log.info("=" * 60)


# ─────────────────────────────────────────────
# APS cloud sync
# ─────────────────────────────────────────────
def sync_from_aps(*, dry_run: bool = False) -> SyncReport:
    """
    Download all cloud tool libraries from APS and sync into Supabase.
    Same pipeline as /api/aps/sync but callable without Flask.
    """
    report = SyncReport(source="aps", start_time=time.monotonic())

    aps = APSClient()
    aps._require_config()
    aps._ensure_token()

    # Supabase client needed for both enrichment (read) and sync (write)
    sb = SupabaseClient()

    contents = aps.get_folder_contents(PROJECT_ID, CAM_TOOLS_FOLDER)

    for item in contents:
        if item.get("type") != "items":
            continue
        name = item.get("attributes", {}).get("displayName", "")
        if not name.endswith(".json"):
            continue

        library_name = name.replace(".json", "")
        log.info("── %s ──", library_name)

        # Get storage URN from the tip
        try:
            item_id = item["id"]
            tip = aps.get_item_tip(PROJECT_ID, item_id)
            storage_urn = (
                tip.get("relationships", {})
                .get("storage", {})
                .get("data", {})
                .get("id", "")
            )
            source_modified_at = (
                tip.get("attributes", {}).get("lastModifiedTime", "")
            ) or None
            if not storage_urn:
                report.results.append(LibraryResult(
                    library_name, "fail", message="No storage URN in tip",
                ))
                log.error("  FAIL: no storage URN in tip")
                continue

            # Download and parse
            tools = aps.download_tool_library(storage_urn)
        except (APSHTTPError, Exception) as e:
            report.results.append(LibraryResult(
                library_name, "fail", message=str(e),
            ))
            log.error("  FAIL download: %s", e)
            continue

        if not tools:
            report.results.append(LibraryResult(
                library_name, "skipped", message="Empty library",
            ))
            log.info("  SKIP: empty library")
            continue

        # Enrich tools missing product-id from reference catalog
        try:
            ec = enrich_raw_tools(tools, sb)
            if ec["enriched"]:
                log.info("  Enriched %d tools from reference catalog", ec["enriched"])
        except Exception as e:
            log.warning("  Enrichment failed (non-fatal): %s", e)

        # Validation gate
        vr = validate_library(
            tools=tools,
            library_name=library_name,
            mode=ValidationMode.PRODUCTION,
            use_api=False,
        )
        if not vr.passed:
            report.results.append(LibraryResult(
                library_name, "fail",
                message=f"Validation failed: {len(vr.fails)} issue(s)",
            ))
            log.error("  FAIL validation: %s", vr.summary())
            for issue in vr.fails:
                log.error("    %s: %s", issue.rule, issue.message)
            continue

        log.info("  Validated: %s", vr.summary())

        if dry_run:
            report.results.append(LibraryResult(
                library_name, "success",
                tools=vr.sync_candidate_count,
                message="dry-run — validated OK, no write",
            ))
            log.info("  DRY-RUN: %d tools validated, skipping write", vr.sync_candidate_count)
            continue

        # Sync to Supabase
        try:
            counts = sync_library(
                library_name,
                tools,
                client=sb,
                file_path=f"aps://{item_id}",
                source_modified_at=source_modified_at,
            )
            report.results.append(LibraryResult(
                library_name, "success",
                tools=counts["tools"],
                presets=counts["presets"],
            ))
            log.info("  OK: %d tools, %d presets", counts["tools"], counts["presets"])
        except Exception as e:
            report.results.append(LibraryResult(
                library_name, "fail", message=str(e),
            ))
            log.error("  FAIL sync: %s", e)

    report.end_time = time.monotonic()
    return report


# ─────────────────────────────────────────────
# Local ADC fallback
# ─────────────────────────────────────────────
def sync_from_local(*, dry_run: bool = False) -> SyncReport:
    """
    Load tool libraries from the local ADC sync path and sync into Supabase.
    Fallback when APS OAuth is unavailable.
    """
    report = SyncReport(source="local", start_time=time.monotonic())

    log.info("Loading libraries from local path: %s", CAM_TOOLS_DIR)

    if not CAM_TOOLS_DIR.exists():
        log.error("CAMTools directory not found: %s", CAM_TOOLS_DIR)
        report.end_time = time.monotonic()
        return report

    libraries = load_all_libraries(
        CAM_TOOLS_DIR,
        abort_on_stale=False,
        validate=False,  # We run validation ourselves below
    )

    if not libraries:
        log.error("No libraries loaded from %s", CAM_TOOLS_DIR)
        report.end_time = time.monotonic()
        return report

    sb = SupabaseClient()

    for library_name, tools in libraries.items():
        log.info("── %s ──", library_name)

        # Enrich tools missing product-id from reference catalog
        try:
            ec = enrich_raw_tools(tools, sb)
            if ec["enriched"]:
                log.info("  Enriched %d tools from reference catalog", ec["enriched"])
        except Exception as e:
            log.warning("  Enrichment failed (non-fatal): %s", e)

        # Validation gate
        vr = validate_library(
            tools=tools,
            library_name=library_name,
            mode=ValidationMode.PRODUCTION,
            use_api=False,
        )
        if not vr.passed:
            report.results.append(LibraryResult(
                library_name, "fail",
                message=f"Validation failed: {len(vr.fails)} issue(s)",
            ))
            log.error("  FAIL validation: %s", vr.summary())
            for issue in vr.fails:
                log.error("    %s: %s", issue.rule, issue.message)
            continue

        log.info("  Validated: %s", vr.summary())

        if dry_run:
            report.results.append(LibraryResult(
                library_name, "success",
                tools=vr.sync_candidate_count,
                message="dry-run — validated OK, no write",
            ))
            log.info("  DRY-RUN: %d tools validated, skipping write", vr.sync_candidate_count)
            continue

        # Sync to Supabase
        try:
            file_path = CAM_TOOLS_DIR / f"{library_name}.json"
            fh = hash_file(file_path) if file_path.exists() else None
            counts = sync_library(
                library_name,
                tools,
                client=sb,
                file_path=str(file_path),
                file_hash=fh,
            )
            report.results.append(LibraryResult(
                library_name, "success",
                tools=counts["tools"],
                presets=counts["presets"],
            ))
            log.info("  OK: %d tools, %d presets", counts["tools"], counts["presets"])
        except Exception as e:
            report.results.append(LibraryResult(
                library_name, "fail", message=str(e),
            ))
            log.error("  FAIL sync: %s", e)

    report.end_time = time.monotonic()
    return report


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Datum nightly sync -- Fusion tool libraries to Supabase",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and validate only, no Supabase writes",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local ADC fallback (skip APS cloud)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Append logs to this file (in addition to stdout)",
    )
    args = parser.parse_args(argv)

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        fh = logging.FileHandler(args.log_file, encoding="utf-8")
        handlers.append(fh)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

    log.info("Datum sync starting%s", " (dry-run)" if args.dry_run else "")

    report: SyncReport | None = None

    if not args.local:
        # Try APS cloud first
        try:
            log.info("Attempting APS cloud sync...")
            report = sync_from_aps(dry_run=args.dry_run)
        except (APSConfigError, APSAuthError) as e:
            log.warning("APS unavailable: %s — falling back to local", e)
        except Exception as e:
            log.warning("APS error: %s — falling back to local", e)

    if report is None:
        # Fallback to local ADC
        log.info("Using local ADC path...")
        try:
            report = sync_from_local(dry_run=args.dry_run)
        except Exception as e:
            log.critical("Local sync failed: %s", e)
            return 2

    report.print_summary()

    # Post-sync: refresh plex_supply_items staging table (#80).
    # Non-fatal — a failure here should not change the sync exit code.
    if not args.dry_run and report.succeeded:
        try:
            sb = SupabaseClient()
            pop = populate_supply_items(sb)
            log.info(
                "Supply-item staging: %d staged, %d skipped, %d failed",
                len(pop.staged), len(pop.skipped), len(pop.failed),
            )
        except Exception as e:
            log.warning("Supply-item staging failed (non-fatal): %s", e)

    if not report.results:
        log.error("No libraries processed from any source")
        return 2

    if report.failed:
        log.error(
            "Failed libraries: %s",
            ", ".join(r.name for r in report.failed),
        )
        return 1

    return 0


def cli() -> None:
    """Console-script entry point (called by ``datum-sync`` after pip install)."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
