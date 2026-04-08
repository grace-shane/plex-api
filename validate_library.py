"""
validate_library.py
Fusion 360 Tool Library Pre-Sync Validator
Grace Engineering — plex-api project
===========================================
Pre-sync validation gate for Fusion 360 tool library JSON files. Runs
before any data touches Plex or Supabase. Three entry points share one
validation engine:

  1. CLI           — ``python validate_library.py --file <path>``
  2. Programmatic  — ``validate_library(tools=..., library_name=..., ...)``
                     called from ``tool_library_loader.load_library()`` as
                     a pre-sync gate
  3. Flask         — ``GET/POST /api/fusion/validate`` in app.py

A ``FAIL`` aborts the sync. ``WARN`` entries are surfaced in verbose/debug
output and the Flask UI but do not block the sync.

Full spec: docs/validate_library_spec.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

# Known tool types observed in Fusion 360 libraries. Anything outside this
# set triggers UNKNOWN_TYPE_PRESENT (WARN) — the sync will still include
# it unless it matches NON_SYNC_TYPES below.
KNOWN_TOOL_TYPES = {
    "flat end mill",
    "bull nose end mill",
    "drill",
    "face mill",
    "form mill",
    "slot mill",
    "holder",
    "probe",
}

# Types excluded from sync. Holders are the geometric collision shapes
# and probes are measurement devices; neither represents a purchasable
# cutting consumable in Plex's supply-items schema.
NON_SYNC_TYPES = {"holder", "probe"}

# ── Geometry bounds ──────────────────────────────────────────────────
# TODO: confirm real shop-floor bounds with Shane before enabling range
# WARN rules. Non-positive FAIL rules (DC <= 0, NOF <= 0) are always
# active regardless of these values.
DC_MIN: float | None = None   # cutting diameter min, inches
DC_MAX: float | None = None   # cutting diameter max, inches
OAL_MIN: float | None = None  # overall length min, inches
OAL_MAX: float | None = None  # overall length max, inches
NOF_MIN: int | None = None    # number of flutes min
NOF_MAX: int | None = None    # number of flutes max


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

class ValidationMode(Enum):
    PRODUCTION = "production"   # PASS/FAIL only
    VERBOSE    = "verbose"      # + WARNs
    DEBUG      = "debug"        # + field trace


@dataclass
class ValidationIssue:
    severity: Literal["FAIL", "WARN"]
    rule: str
    tool_index: int | None
    tool_description: str | None
    field: str | None
    value: Any
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "rule": self.rule,
            "tool_index": self.tool_index,
            "tool_description": self.tool_description,
            "field": self.field,
            "value": self.value,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    library_name: str
    passed: bool
    tool_count: int
    sync_candidate_count: int
    issues: list[ValidationIssue] = field(default_factory=list)
    debug_trace: list[str] | None = None

    @property
    def fails(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "FAIL"]

    @property
    def warns(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "WARN"]

    def summary(self) -> str:
        n_fail = len(self.fails)
        n_warn = len(self.warns)
        if self.passed and n_warn == 0:
            return (
                f"PASS {self.library_name} — "
                f"{self.sync_candidate_count} tools valid, ready to sync"
            )
        if self.passed:
            return (
                f"PASS {self.library_name} — "
                f"{self.sync_candidate_count} tools valid "
                f"({n_warn} warning{'s' if n_warn != 1 else ''})"
            )
        parts = [f"{n_fail} error{'s' if n_fail != 1 else ''}"]
        if n_warn:
            parts.append(f"{n_warn} warning{'s' if n_warn != 1 else ''}")
        return f"FAIL {self.library_name} — FAILED ({', '.join(parts)})"

    def to_dict(self) -> dict:
        return {
            "library_name": self.library_name,
            "passed": self.passed,
            "tool_count": self.tool_count,
            "sync_candidate_count": self.sync_candidate_count,
            "issues": [i.to_dict() for i in self.issues],
            "debug_trace": self.debug_trace,
        }


# ─────────────────────────────────────────────
# SUPPLIER LOOKUP (cached)
# ─────────────────────────────────────────────

_supplier_cache: list[str] | None = None


def _get_supplier_names(client, debug: bool = False) -> list[str]:
    """
    Fetch supplier names from ``mdm/v1/suppliers``.

    Cached after first call. Returns empty list on API failure — vendor
    checks are silently skipped in that case rather than aborting the
    validation run.
    """
    global _supplier_cache
    if _supplier_cache is not None:
        return _supplier_cache

    try:
        raw = client.get("mdm", "v1", "suppliers")
    except Exception as e:
        log.warning("Supplier lookup failed: %s — skipping vendor checks", e)
        _supplier_cache = []
        return _supplier_cache

    if raw is None:
        log.warning(
            "Supplier lookup returned None — skipping vendor checks"
        )
        _supplier_cache = []
        return _supplier_cache

    if isinstance(raw, dict):
        records = raw.get("data") or raw.get("items") or raw.get("rows") or []
    else:
        records = raw or []

    names: list[str] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        # Try common name field variations
        name = (
            r.get("name")
            or r.get("supplierName")
            or r.get("supplier_name")
            or r.get("displayName")
        )
        if name:
            names.append(str(name))

    _supplier_cache = names
    if debug:
        log.debug("Loaded %d supplier names from mdm/v1/suppliers", len(names))
    return names


def _reset_supplier_cache() -> None:
    """Test helper — reset the module-level cache between runs."""
    global _supplier_cache
    _supplier_cache = None


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance — small/simple implementation for debug output."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,       # insert
                prev[j] + 1,            # delete
                prev[j - 1] + cost,     # substitute
            )
        prev = curr
    return prev[-1]


def _closest_supplier_names(
    target: str, supplier_names: list[str], n: int = 3
) -> list[tuple[str, int]]:
    """Return the n closest supplier names to ``target`` by edit distance."""
    scored = [(name, _edit_distance(target.lower(), name.lower()))
              for name in supplier_names]
    scored.sort(key=lambda x: x[1])
    return scored[:n]


def _match_vendor(vendor: str, supplier_names: list[str]) -> bool:
    """Case-insensitive exact match against the supplier master list."""
    if not vendor or not supplier_names:
        return False
    target = vendor.strip().lower()
    return any(target == name.strip().lower() for name in supplier_names)


# ─────────────────────────────────────────────
# VALIDATION ENGINE
# ─────────────────────────────────────────────

def _tool_desc(tool: dict) -> str | None:
    """Short description label for issue messages."""
    desc = tool.get("description")
    return desc if isinstance(desc, str) and desc else None


def _is_sync_candidate(tool: dict) -> bool:
    t = tool.get("type")
    if not isinstance(t, str):
        return True  # unknown/missing type — still a candidate; caught by REQUIRED_FIELD
    return t.strip().lower() not in NON_SYNC_TYPES


def _check_library_rules(
    data: Any,
    issues: list[ValidationIssue],
    cross_library_product_ids: dict[str, str] | None,
    debug_trace: list[str] | None,
) -> tuple[list[dict], bool]:
    """
    Run library-level rules. Returns (sync_candidates, safe_to_iterate).

    If safe_to_iterate is False, a library-level FAIL blocked iteration
    and per-tool rules should NOT run.
    """
    if debug_trace is not None:
        debug_trace.append("[DEBUG] Running library-level rules")

    # STRUCT_ROOT_KEY — data must be a list (callers pass ``tools``, which
    # is already the unwrapped ``data`` array — we check structure here)
    if data is None:
        issues.append(ValidationIssue(
            severity="FAIL",
            rule="STRUCT_ROOT_KEY",
            tool_index=None,
            tool_description=None,
            field=None,
            value=None,
            message='Root "data" key missing — not a valid Fusion tool library',
        ))
        return [], False

    if not isinstance(data, list):
        issues.append(ValidationIssue(
            severity="FAIL",
            rule="STRUCT_DATA_LIST",
            tool_index=None,
            tool_description=None,
            field=None,
            value=type(data).__name__,
            message='Root "data" is not a list',
        ))
        return [], False

    if len(data) == 0:
        issues.append(ValidationIssue(
            severity="FAIL",
            rule="STRUCT_EMPTY",
            tool_index=None,
            tool_description=None,
            field=None,
            value=0,
            message="Library contains zero entries",
        ))
        return [], False

    # UNKNOWN_TYPE_PRESENT — WARN only, does not block iteration
    for i, tool in enumerate(data):
        if not isinstance(tool, dict):
            continue
        t = tool.get("type")
        if isinstance(t, str) and t.strip():
            if t.strip().lower() not in KNOWN_TOOL_TYPES:
                issues.append(ValidationIssue(
                    severity="WARN",
                    rule="UNKNOWN_TYPE_PRESENT",
                    tool_index=i,
                    tool_description=_tool_desc(tool),
                    field="type",
                    value=t,
                    message=(
                        f'Unknown type "{t}" at index {i} — will be included '
                        f"in sync unless filter is updated"
                    ),
                ))

    # Collect sync candidates (skip holders + probes)
    sync_candidates = [t for t in data if isinstance(t, dict) and _is_sync_candidate(t)]

    if len(sync_candidates) == 0:
        issues.append(ValidationIssue(
            severity="FAIL",
            rule="SYNC_CANDIDATES_ZERO",
            tool_index=None,
            tool_description=None,
            field=None,
            value=0,
            message="No syncable tools after filtering — check type values",
        ))
        return sync_candidates, False

    # DUPLICATE_GUID — across all entries (holders + probes included)
    guid_seen: dict[str, int] = {}
    for i, tool in enumerate(data):
        if not isinstance(tool, dict):
            continue
        guid = tool.get("guid")
        if isinstance(guid, str) and guid:
            if guid in guid_seen:
                prev = guid_seen[guid]
                issues.append(ValidationIssue(
                    severity="FAIL",
                    rule="DUPLICATE_GUID",
                    tool_index=i,
                    tool_description=_tool_desc(tool),
                    field="guid",
                    value=guid,
                    message=f'Duplicate guid "{guid}" at indexes {prev} and {i}',
                ))
            else:
                guid_seen[guid] = i

    # DUPLICATE_PRODUCT_ID — sync candidates only
    pid_seen: dict[str, int] = {}
    for i, tool in enumerate(data):
        if not isinstance(tool, dict) or not _is_sync_candidate(tool):
            continue
        pid = tool.get("product-id")
        if isinstance(pid, str) and pid:
            if pid in pid_seen:
                prev = pid_seen[pid]
                issues.append(ValidationIssue(
                    severity="FAIL",
                    rule="DUPLICATE_PRODUCT_ID",
                    tool_index=i,
                    tool_description=_tool_desc(tool),
                    field="product-id",
                    value=pid,
                    message=(
                        f'Duplicate product-id "{pid}" at indexes {prev} '
                        f"and {i} — upsert will collide"
                    ),
                ))
            else:
                pid_seen[pid] = i

    # CROSS_LIBRARY_DUPLICATE — WARN, multi-library runs only
    if cross_library_product_ids is not None:
        for i, tool in enumerate(data):
            if not isinstance(tool, dict) or not _is_sync_candidate(tool):
                continue
            pid = tool.get("product-id")
            if isinstance(pid, str) and pid and pid in cross_library_product_ids:
                other = cross_library_product_ids[pid]
                issues.append(ValidationIssue(
                    severity="WARN",
                    rule="CROSS_LIBRARY_DUPLICATE",
                    tool_index=i,
                    tool_description=_tool_desc(tool),
                    field="product-id",
                    value=pid,
                    message=(
                        f'product-id "{pid}" also exists in "{other}" — '
                        f"check for cross-library collision"
                    ),
                ))

    # If any library-level rule FAILed (DUPLICATE_GUID / DUPLICATE_PRODUCT_ID),
    # we still allow iteration so per-tool checks can surface additional
    # errors. Only the hard structural failures above abort iteration.
    return sync_candidates, True


def _check_required_field(
    tool: dict,
    index: int,
    key: str,
    issues: list[ValidationIssue],
) -> bool:
    val = tool.get(key)
    if not isinstance(val, str) or not val.strip():
        issues.append(ValidationIssue(
            severity="FAIL",
            rule="REQUIRED_FIELD",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field=key,
            value=val,
            message=(
                f"Missing required field '{key}' — "
                f"this tool cannot be deduped in Plex"
            ),
        ))
        return False
    return True


def _check_vendor_rules(
    tool: dict,
    index: int,
    issues: list[ValidationIssue],
    supplier_names: list[str] | None,
    debug_trace: list[str] | None,
) -> None:
    vendor = tool.get("vendor")

    if not isinstance(vendor, str) or not vendor.strip():
        issues.append(ValidationIssue(
            severity="WARN",
            rule="VENDOR_MISSING",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="vendor",
            value=vendor,
            message="Tool has no vendor — supplier linkage will fail on sync",
        ))
        return

    if supplier_names is None:
        return  # API check disabled — not our job to warn

    if not supplier_names:
        return  # API failed or empty — gracefully skip (warning already logged)

    if not _match_vendor(vendor, supplier_names):
        issues.append(ValidationIssue(
            severity="WARN",
            rule="VENDOR_NOT_IN_PLEX",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="vendor",
            value=vendor,
            message=(
                f"Vendor \"{vendor}\" not found in Plex supplier master — "
                f"will fail at sync time"
            ),
        ))
        if debug_trace is not None:
            closest = _closest_supplier_names(vendor, supplier_names)
            debug_trace.append(
                f"[DEBUG] Closest matches to \"{vendor}\": "
                + ", ".join(f'"{n}" ({d})' for n, d in closest)
            )


def _check_geometry_rules(
    tool: dict,
    index: int,
    issues: list[ValidationIssue],
    debug_trace: list[str] | None,
) -> None:
    geom = tool.get("geometry")

    if not isinstance(geom, dict):
        issues.append(ValidationIssue(
            severity="WARN",
            rule="GEOMETRY_MISSING",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="geometry",
            value=None,
            message="Tool has no geometry block",
        ))
        return

    # DC — cutting diameter
    dc = geom.get("DC")
    if dc is None:
        issues.append(ValidationIssue(
            severity="WARN",
            rule="GEOMETRY_DC_MISSING",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="geometry.DC",
            value=None,
            message="Cutting diameter (DC) missing",
        ))
    else:
        try:
            dc_val = float(dc)
        except (TypeError, ValueError):
            dc_val = None
        if dc_val is None:
            issues.append(ValidationIssue(
                severity="FAIL",
                rule="GEOMETRY_DC_NONPOSITIVE",
                tool_index=index,
                tool_description=_tool_desc(tool),
                field="geometry.DC",
                value=dc,
                message=f"Cutting diameter must be a number (got {dc!r})",
            ))
        elif dc_val <= 0:
            issues.append(ValidationIssue(
                severity="FAIL",
                rule="GEOMETRY_DC_NONPOSITIVE",
                tool_index=index,
                tool_description=_tool_desc(tool),
                field="geometry.DC",
                value=dc_val,
                message=f"Cutting diameter must be > 0 (got {dc_val})",
            ))
        elif DC_MIN is not None and DC_MAX is not None:
            if not (DC_MIN <= dc_val <= DC_MAX):
                issues.append(ValidationIssue(
                    severity="WARN",
                    rule="GEOMETRY_DC_RANGE",
                    tool_index=index,
                    tool_description=_tool_desc(tool),
                    field="geometry.DC",
                    value=dc_val,
                    message=(
                        f"Cutting diameter {dc_val} outside expected "
                        f"range [{DC_MIN}, {DC_MAX}]"
                    ),
                ))
        elif debug_trace is not None:
            debug_trace.append(
                "[DEBUG] GEOMETRY_DC_RANGE skipped — DC_MIN/DC_MAX not set"
            )

    # OAL — overall length
    oal = geom.get("OAL")
    if oal is None:
        issues.append(ValidationIssue(
            severity="WARN",
            rule="GEOMETRY_OAL_MISSING",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="geometry.OAL",
            value=None,
            message="Overall length (OAL) missing",
        ))
    else:
        try:
            oal_val = float(oal)
        except (TypeError, ValueError):
            oal_val = None
        if oal_val is not None:
            # OAL < DC is physically implausible; always active when both present
            try:
                dc_val_cmp = float(dc) if dc is not None else None
            except (TypeError, ValueError):
                dc_val_cmp = None
            if dc_val_cmp is not None and dc_val_cmp > 0 and oal_val < dc_val_cmp:
                issues.append(ValidationIssue(
                    severity="WARN",
                    rule="GEOMETRY_OAL_SHORTER_THAN_DC",
                    tool_index=index,
                    tool_description=_tool_desc(tool),
                    field="geometry.OAL",
                    value=oal_val,
                    message=(
                        f"Overall length ({oal_val}) is shorter than "
                        f"cutting diameter ({dc_val_cmp}) — physically implausible"
                    ),
                ))
            if OAL_MIN is not None and OAL_MAX is not None:
                if not (OAL_MIN <= oal_val <= OAL_MAX):
                    issues.append(ValidationIssue(
                        severity="WARN",
                        rule="GEOMETRY_OAL_RANGE",
                        tool_index=index,
                        tool_description=_tool_desc(tool),
                        field="geometry.OAL",
                        value=oal_val,
                        message=(
                            f"Overall length {oal_val} outside expected "
                            f"range [{OAL_MIN}, {OAL_MAX}]"
                        ),
                    ))
            elif debug_trace is not None:
                debug_trace.append(
                    "[DEBUG] GEOMETRY_OAL_RANGE skipped — OAL_MIN/OAL_MAX not set"
                )

    # NOF — number of flutes
    nof = geom.get("NOF")
    if nof is None:
        issues.append(ValidationIssue(
            severity="WARN",
            rule="GEOMETRY_NOF_MISSING",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="geometry.NOF",
            value=None,
            message="Number of flutes (NOF) missing",
        ))
    else:
        try:
            nof_val = float(nof)
        except (TypeError, ValueError):
            nof_val = None
        if nof_val is None:
            issues.append(ValidationIssue(
                severity="FAIL",
                rule="GEOMETRY_NOF_NONPOSITIVE",
                tool_index=index,
                tool_description=_tool_desc(tool),
                field="geometry.NOF",
                value=nof,
                message=f"Number of flutes must be a number (got {nof!r})",
            ))
        elif nof_val <= 0:
            issues.append(ValidationIssue(
                severity="FAIL",
                rule="GEOMETRY_NOF_NONPOSITIVE",
                tool_index=index,
                tool_description=_tool_desc(tool),
                field="geometry.NOF",
                value=nof_val,
                message=f"Number of flutes must be > 0 (got {nof_val})",
            ))
        elif NOF_MIN is not None and NOF_MAX is not None:
            if not (NOF_MIN <= nof_val <= NOF_MAX):
                issues.append(ValidationIssue(
                    severity="WARN",
                    rule="GEOMETRY_NOF_RANGE",
                    tool_index=index,
                    tool_description=_tool_desc(tool),
                    field="geometry.NOF",
                    value=nof_val,
                    message=(
                        f"Number of flutes {nof_val} outside expected "
                        f"range [{NOF_MIN}, {NOF_MAX}]"
                    ),
                ))
        elif debug_trace is not None:
            debug_trace.append(
                "[DEBUG] GEOMETRY_NOF_RANGE skipped — NOF_MIN/NOF_MAX not set"
            )


def _check_postprocess_rules(
    tool: dict,
    index: int,
    issues: list[ValidationIssue],
) -> None:
    pp = tool.get("post-process")
    if not isinstance(pp, dict) or "number" not in pp:
        issues.append(ValidationIssue(
            severity="WARN",
            rule="POSTPROCESS_NUMBER_MISSING",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="post-process.number",
            value=None,
            message="post-process.number missing — no pocket assignment",
        ))
        return

    num = pp.get("number")
    try:
        num_val = float(num)
    except (TypeError, ValueError):
        issues.append(ValidationIssue(
            severity="WARN",
            rule="POSTPROCESS_NUMBER_NONPOSITIVE",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="post-process.number",
            value=num,
            message=f"post-process.number must be a number (got {num!r})",
        ))
        return

    if num_val <= 0:
        issues.append(ValidationIssue(
            severity="WARN",
            rule="POSTPROCESS_NUMBER_NONPOSITIVE",
            tool_index=index,
            tool_description=_tool_desc(tool),
            field="post-process.number",
            value=num_val,
            message=f"post-process.number must be > 0 (got {num_val})",
        ))


def _check_per_tool_rules(
    sync_candidates: list[dict],
    all_tools: list[dict],
    issues: list[ValidationIssue],
    supplier_names: list[str] | None,
    debug_trace: list[str] | None,
) -> None:
    """Run per-tool rules. Uses the original index from ``all_tools`` for reporting."""
    for i, tool in enumerate(all_tools):
        if not isinstance(tool, dict) or not _is_sync_candidate(tool):
            continue

        if debug_trace is not None:
            desc = _tool_desc(tool) or "(no description)"
            debug_trace.append(f'[DEBUG] tool {i} "{desc}"')

        # Required fields
        _check_required_field(tool, i, "guid", issues)
        _check_required_field(tool, i, "type", issues)
        _check_required_field(tool, i, "description", issues)
        _check_required_field(tool, i, "product-id", issues)

        # Vendor
        _check_vendor_rules(tool, i, issues, supplier_names, debug_trace)

        # Geometry
        _check_geometry_rules(tool, i, issues, debug_trace)

        # Post-process
        _check_postprocess_rules(tool, i, issues)


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def validate_library(
    tools: Any,
    library_name: str,
    mode: ValidationMode = ValidationMode.PRODUCTION,
    use_api: bool = False,
    client=None,
    cross_library_product_ids: dict[str, str] | None = None,
) -> ValidationResult:
    """
    Validate a list of Fusion 360 tool objects against the sync rules.

    Parameters
    ----------
    tools
        List of tool dicts from a Fusion JSON library — the unwrapped
        ``data`` array. May be any type; type errors are caught and
        returned as STRUCT_* FAILs.
    library_name
        Short name for the library (used in issue messages + summary).
    mode
        ValidationMode.PRODUCTION / VERBOSE / DEBUG. Currently affects
        only the ``debug_trace`` field and debug-only logging; rule
        evaluation is identical in all modes.
    use_api
        When True, fetches the Plex supplier master and runs
        VENDOR_NOT_IN_PLEX checks. Requires ``client``. Defaults to False
        to keep the loader fast and offline-safe.
    client
        PlexClient instance. Required iff ``use_api=True``.
    cross_library_product_ids
        Optional dict of already-seen product-ids to library names. When
        provided, enables CROSS_LIBRARY_DUPLICATE WARN rule. Used by
        multi-library batch runs.

    Returns
    -------
    ValidationResult
    """
    issues: list[ValidationIssue] = []
    debug_trace: list[str] | None = [] if mode == ValidationMode.DEBUG else None

    # Library-level rules
    sync_candidates, safe_to_iterate = _check_library_rules(
        tools, issues, cross_library_product_ids, debug_trace
    )

    tool_count = len(tools) if isinstance(tools, list) else 0
    sync_candidate_count = len(sync_candidates)

    # Per-tool rules only if library-level checks didn't hard-abort
    if safe_to_iterate:
        supplier_names: list[str] | None = None
        if use_api:
            if client is None:
                log.warning(
                    "use_api=True but no client provided — "
                    "skipping vendor API checks"
                )
                supplier_names = None
            else:
                supplier_names = _get_supplier_names(
                    client, debug=(mode == ValidationMode.DEBUG)
                )

        _check_per_tool_rules(
            sync_candidates,
            tools if isinstance(tools, list) else [],
            issues,
            supplier_names,
            debug_trace,
        )

    passed = not any(i.severity == "FAIL" for i in issues)

    return ValidationResult(
        library_name=library_name,
        passed=passed,
        tool_count=tool_count,
        sync_candidate_count=sync_candidate_count,
        issues=issues,
        debug_trace=debug_trace,
    )


# ─────────────────────────────────────────────
# CLI OUTPUT FORMATTING
# ─────────────────────────────────────────────

def _format_issue(issue: ValidationIssue) -> str:
    desc = issue.tool_description or "(no description)"
    tool_label = (
        f"tool {issue.tool_index} \"{desc}\""
        if issue.tool_index is not None
        else "(library-level)"
    )
    lines = [
        f"  [{issue.severity}] {issue.rule} - {tool_label}",
    ]
    if issue.field:
        lines.append(f"         Field: {issue.field}")
    if issue.value not in (None, ""):
        lines.append(f"         Value: {issue.value!r}")
    lines.append(f"         {issue.message}")
    return "\n".join(lines)


def format_result(
    result: ValidationResult,
    mode: ValidationMode = ValidationMode.PRODUCTION,
) -> str:
    """Human-readable CLI output for a single ValidationResult."""
    if result.passed and not result.warns:
        return (
            f"[PASS] {result.library_name} - "
            f"{result.sync_candidate_count} tools valid, ready to sync"
        )

    header_parts = []
    n_fail = len(result.fails)
    n_warn = len(result.warns)
    if n_fail:
        header_parts.append(f"{n_fail} error{'s' if n_fail != 1 else ''}")
    if n_warn and mode != ValidationMode.PRODUCTION:
        header_parts.append(f"{n_warn} warning{'s' if n_warn != 1 else ''}")

    status = "PASS" if result.passed else "FAIL"
    header = (
        f"[{status}] {result.library_name}"
        + (f" - {'FAILED' if not result.passed else 'passed'} "
           f"({', '.join(header_parts)})" if header_parts else "")
    )
    body_lines: list[str] = [header, ""]

    # Show FAILs always
    for issue in result.fails:
        body_lines.append(_format_issue(issue))
        body_lines.append("")

    # Show WARNs only in verbose/debug
    if mode != ValidationMode.PRODUCTION:
        for issue in result.warns:
            body_lines.append(_format_issue(issue))
            body_lines.append("")

    # Debug trace
    if mode == ValidationMode.DEBUG and result.debug_trace:
        body_lines.append("  Debug trace:")
        for line in result.debug_trace:
            body_lines.append(f"    {line}")

    return "\n".join(body_lines).rstrip() + "\n"


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

def _load_json_file(path: Path) -> list[dict] | None:
    """Load a Fusion JSON file and return the ``data`` array (or raw on error)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
        print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
        return None

    if not isinstance(raw, dict):
        # Pass the raw thing through; the validator will FAIL on STRUCT_*
        return raw  # type: ignore[return-value]

    return raw.get("data")


def _cli_main(argv: list[str] | None = None) -> int:
    # Force stdout to UTF-8 so em-dashes in messages don't blow up the
    # Windows cp1252 console. Matches the pattern in app.py (PR #22).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Validate Fusion 360 tool library JSON file(s) for sync"
    )
    parser.add_argument(
        "--file", "-f",
        help="Path to a single JSON file to validate",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show WARN issues in addition to FAILs",
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Show full field trace and supplier list",
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="Skip live Plex supplier lookup (offline mode)",
    )
    args = parser.parse_args(argv)

    if args.debug:
        mode = ValidationMode.DEBUG
        logging.basicConfig(level=logging.DEBUG)
    elif args.verbose:
        mode = ValidationMode.VERBOSE
        logging.basicConfig(level=logging.INFO)
    else:
        mode = ValidationMode.PRODUCTION
        logging.basicConfig(level=logging.WARNING)

    # File resolution
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"ERROR: File not found: {path}", file=sys.stderr)
            return 2
        files = [path]
    else:
        # Default to all libraries in the ADC CAMTools directory
        try:
            from tool_library_loader import CAM_TOOLS_DIR
        except ImportError:
            print(
                "ERROR: tool_library_loader not importable and no --file given",
                file=sys.stderr,
            )
            return 2
        if not CAM_TOOLS_DIR.exists():
            print(
                f"ERROR: CAMTools directory not found: {CAM_TOOLS_DIR}",
                file=sys.stderr,
            )
            return 2
        files = sorted(CAM_TOOLS_DIR.glob("*.json"))
        if not files:
            print(f"ERROR: No .json files in {CAM_TOOLS_DIR}", file=sys.stderr)
            return 2

    # Optional API client for supplier lookup
    client = None
    use_api = not args.no_api
    if use_api:
        try:
            from plex_api import PlexClient, API_KEY, API_SECRET, TENANT_ID, USE_TEST
            if not API_KEY:
                print(
                    "WARNING: PLEX_API_KEY not set — disabling API vendor checks",
                    file=sys.stderr,
                )
                use_api = False
            else:
                client = PlexClient(
                    api_key=API_KEY,
                    api_secret=API_SECRET,
                    tenant_id=TENANT_ID,
                    use_test=USE_TEST,
                )
        except Exception as e:
            print(
                f"WARNING: Plex client setup failed ({e}) — disabling API checks",
                file=sys.stderr,
            )
            use_api = False

    # Run validation across all files with cross-library tracking
    cross_library: dict[str, str] = {}
    all_results: list[ValidationResult] = []
    for path in files:
        tools = _load_json_file(path)
        result = validate_library(
            tools=tools,
            library_name=path.stem,
            mode=mode,
            use_api=use_api,
            client=client,
            cross_library_product_ids=dict(cross_library) if cross_library else None,
        )
        all_results.append(result)
        print(format_result(result, mode))

        # Update cross-library tracking with this library's product-ids
        if isinstance(tools, list):
            for tool in tools:
                if not isinstance(tool, dict) or not _is_sync_candidate(tool):
                    continue
                pid = tool.get("product-id")
                if isinstance(pid, str) and pid and pid not in cross_library:
                    cross_library[pid] = path.stem

    any_failed = any(not r.passed for r in all_results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(_cli_main())
