"""
sync_supabase.py
Fusion 360 JSON → Supabase ingest
Grace Engineering — Datum project
=============================================================
Reads Fusion 360 tool-library JSON files, applies the eight
normalization rules documented in the Supabase Schema Design
(Notion · 2026-04-08), and upserts the three core tables
(``libraries``, ``tools``, ``cutting_presets``) in the dedicated
``datum`` Supabase project.

Pipeline
--------
1. Load a library (filename → list of raw tool dicts) with
   ``tool_library_loader.load_library``.
2. Filter out holders and probes (Rule 6).
3. For each remaining tool, build a normalized row:
   - Unit convert inches → mm on all FLOAT geometry (Rule 1).
   - Strip leading/trailing whitespace on ``product_id``; preserve
     internal characters (Rule 2).
   - Carry JSON nulls through as SQL NULL (Rule 5).
   - Carry ``shaft.segments`` as JSONB passthrough, NULL if absent
     (Rule 7).
   - Use ``.get("comment")`` for post-process comment (Rule 8).
4. Upsert the library row on ``library_name``, capture its id.
5. Upsert all tool rows on ``fusion_guid`` in one batch, capture ids
   keyed by fusion_guid.
6. For each tool, flush its existing presets (DELETE WHERE tool_id),
   then bulk-insert the freshly normalized preset rows. This is a
   cleaner model than trying to upsert per-preset when the vendor
   doesn't provide a stable preset identity.

The module is pure data — it does not touch Plex. Downstream,
``build_supply_item_payload`` (#3) will read normalized rows from
the ``tools`` table and push them to Plex.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from supabase_client import SupabaseClient

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
INCHES_TO_MM = 25.4

EXCLUDED_TYPES = frozenset({"holder", "probe"})

# Geometry fields that are dimensional (convert inches → mm) vs dimensionless
# (counts, flags, angles — carry as-is).
GEOMETRY_LENGTH_FIELDS = {
    "DC": "geo_dc",
    "OAL": "geo_oal",
    "LCF": "geo_lcf",
    "LB": "geo_lb",
    "SFDM": "geo_sfdm",
    "RE": "geo_re",
    "tip-diameter": "geo_tip_diameter",
    "tip-length": "geo_tip_length",
    "tip-offset": "geo_tip_offset",
    "assemblyGaugeLength": "geo_assembly_gauge_length",
    "shoulder-diameter": "geo_shoulder_diameter",
    "shoulder-length": "geo_shoulder_length",
}

# Dimensionless geometry fields (counts, angles, booleans, etc.) — never
# scaled by unit conversion.
GEOMETRY_DIMENSIONLESS_FIELDS = {
    "NOF": "geo_nof",
    "SIG": "geo_sig",          # point angle in degrees
    "NT": "geo_nt",
    "TA": "geo_ta",            # taper angle in degrees
    "TA2": "geo_ta2",
    "TP": "geo_tp",
    "thread-profile-angle": "geo_thread_profile_angle",
}

GEOMETRY_BOOL_FIELDS = {
    "HAND": "geo_hand",
    "CSP": "geo_csp",
}

# Post-process field map (int/bool/text, never unit-scaled).
POST_PROCESS_INT_FIELDS = {
    "number": "pp_number",
    "turret": "pp_turret",
    "diameter-offset": "pp_diameter_offset",
    "length-offset": "pp_length_offset",
}

POST_PROCESS_BOOL_FIELDS = {
    "live": "pp_live",
    "break-control": "pp_break_control",
    "manual-tool-change": "pp_manual_tool_change",
}

# Preset FLOAT fields — all nullable, carry JSON null through unchanged.
# Keys are Fusion JSON field names, values are Supabase column names.
PRESET_FLOAT_FIELDS = {
    "v_c": "v_c",
    "v_f": "v_f",
    "f_z": "f_z",
    "f_n": "f_n",
    "n": "n",
    "n_ramp": "n_ramp",
    "ramp-angle": "ramp_angle",
    "v_f_plunge": "v_f_plunge",
    "v_f_ramp": "v_f_ramp",
    "v_f_leadIn": "v_f_lead_in",
    "v_f_leadOut": "v_f_lead_out",
    "v_f_retract": "v_f_retract",
    "v_f_transition": "v_f_transition",
}

PRESET_BOOL_FIELDS = {
    "use-feed-per-revolution": "use_feed_per_revolution",
    "use-stepdown": "use_stepdown",
    "use-stepover": "use_stepover",
}


# ─────────────────────────────────────────────
# Normalization primitives
# ─────────────────────────────────────────────
def normalize_product_id(raw: Any) -> str | None:
    """
    Rule 2 — strip leading/trailing whitespace only. Never strip
    internal characters. Sandvik ships ``"RA216.33-0845-CK04P 1640"``
    with a real internal space that must be preserved.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    stripped = raw.strip()
    return stripped or None


def normalize_preset_guid(raw: Any) -> str | None:
    """
    Rule 3 — strip surrounding curly braces from Sandvik preset GUIDs:
    ``"{6a2d224-...}"`` → ``"6a2d224-..."``. Leave everything else
    alone.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    s = raw.strip()
    if len(s) >= 2 and s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return s or None


def unit_scale(value: Any, is_inches: bool) -> float | None:
    """
    Rule 1 — multiply dimensional values by 25.4 when the library
    declares ``unit == "inches"``. Pass JSON nulls through unchanged.
    Booleans and non-numeric strings return None (not a dimensional
    value).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int in Python — reject explicitly.
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if is_inches:
        return as_float * INCHES_TO_MM
    return as_float


def _maybe_float(value: Any) -> float | None:
    """Coerce to float or return None (for dimensionless geometry + presets)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _maybe_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    return value


# ─────────────────────────────────────────────
# Tool row builder
# ─────────────────────────────────────────────
def build_tool_row(tool: dict) -> dict:
    """
    Map one raw Fusion tool dict to a ``tools`` row dict.
    Does NOT include ``library_id`` — caller fills that in after the
    library row has been upserted and has a real id.

    Applies Rules 1, 2, 7, 8. Rules 5 and 6 are applied at the batch
    level (see ``sync_library``).
    """
    unit_raw = tool.get("unit")
    is_inches = isinstance(unit_raw, str) and unit_raw.lower() == "inches"

    row: dict[str, Any] = {
        "fusion_guid": _maybe_str(tool.get("guid")),
        "vendor": _maybe_str(tool.get("vendor")) or "",
        "product_id": normalize_product_id(tool.get("product-id")) or "",
        "description": _maybe_str(tool.get("description")) or "",
        "type": _maybe_str(tool.get("type")) or "",
        "bmc": _maybe_str(tool.get("BMC")),
        "grade": _maybe_str(tool.get("GRADE")),
        # reference_guid is observed as integer 0 in Harvey/Helical — store as string
        "reference_guid": (
            str(tool["reference_guid"]) if "reference_guid" in tool else None
        ),
        "unit_original": _maybe_str(unit_raw),
        "product_link": _maybe_str(tool.get("product-link")),
        "tapered_type": _maybe_str(tool.get("tapered-type")),
    }

    # Geometry — length fields go through unit_scale; dimensionless pass through.
    geometry = tool.get("geometry") or {}
    for fusion_key, col in GEOMETRY_LENGTH_FIELDS.items():
        row[col] = unit_scale(geometry.get(fusion_key), is_inches)
    for fusion_key, col in GEOMETRY_DIMENSIONLESS_FIELDS.items():
        row[col] = _maybe_float(geometry.get(fusion_key))
    for fusion_key, col in GEOMETRY_BOOL_FIELDS.items():
        row[col] = _maybe_bool(geometry.get(fusion_key))

    # Post-process — Rule 8: use .get("comment"), not direct key access.
    pp = tool.get("post-process") or {}
    for fusion_key, col in POST_PROCESS_INT_FIELDS.items():
        row[col] = _maybe_int(pp.get(fusion_key))
    for fusion_key, col in POST_PROCESS_BOOL_FIELDS.items():
        row[col] = _maybe_bool(pp.get(fusion_key))
    row["pp_comment"] = _maybe_str(pp.get("comment"))

    # Rule 7 — shaft.segments as JSONB passthrough, NULL if absent. Do not error.
    shaft = tool.get("shaft")
    if isinstance(shaft, dict) and "segments" in shaft:
        row["shaft_segments"] = shaft["segments"]
    else:
        row["shaft_segments"] = None

    return row


# ─────────────────────────────────────────────
# Preset row builder
# ─────────────────────────────────────────────
def build_preset_rows(tool: dict, tool_id: str) -> list[dict]:
    """
    Map ``tool.start-values.presets`` → list of preset row dicts.
    ``tool_id`` is the Supabase UUID of the parent tool row.

    Applies Rules 3 (brace strip) and 5 (JSON nulls).
    """
    start_values = tool.get("start-values") or {}
    presets = start_values.get("presets") or []
    if not isinstance(presets, list):
        return []

    rows: list[dict] = []
    for raw in presets:
        if not isinstance(raw, dict):
            continue
        material = raw.get("material") or {}
        if not isinstance(material, dict):
            material = {}

        # Preset GUID can appear under either 'guid' or 'presetGuid' across vendors.
        preset_guid = raw.get("presetGuid") or raw.get("guid")

        row: dict[str, Any] = {
            "tool_id": tool_id,
            "preset_guid": normalize_preset_guid(preset_guid),
            "name": _maybe_str(raw.get("name")),
            "description": _maybe_str(raw.get("description")),
            "material_category": _maybe_str(material.get("category")),
            "material_query": _maybe_str(material.get("query")),
            "material_use_hardness": _maybe_bool(material.get("useHardness")),
            "tool_coolant": _maybe_str(raw.get("tool-coolant")),
        }

        for fusion_key, col in PRESET_FLOAT_FIELDS.items():
            # Rule 5 — preserve explicit JSON null, do not substitute 0.
            if fusion_key in raw:
                row[col] = _maybe_float(raw.get(fusion_key))
            else:
                row[col] = None

        for fusion_key, col in PRESET_BOOL_FIELDS.items():
            if fusion_key in raw:
                row[col] = _maybe_bool(raw.get(fusion_key))
            else:
                row[col] = None

        rows.append(row)

    return rows


# ─────────────────────────────────────────────
# File hashing
# ─────────────────────────────────────────────
def hash_file(path: Path) -> str:
    """SHA-256 of file contents, used for change detection on libraries."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────
# Top-level ingest
# ─────────────────────────────────────────────
def _pick_vendor(tools: list[dict]) -> str | None:
    """
    Rule 4 — preserve raw vendor casing. Most libraries are single-vendor,
    so we take the first tool's vendor string as-is. Job-specific libraries
    (e.g. BROTHER SPEEDIO ALUMINUM) may be mixed; that's fine — the
    library-level ``vendor`` is a hint, the per-tool ``vendor`` column
    is the source of truth.
    """
    for t in tools:
        v = t.get("vendor")
        if isinstance(v, str) and v.strip():
            return v
    return None


def _pick_unit_original(tools: list[dict]) -> str | None:
    """First declared unit wins for the library metadata."""
    for t in tools:
        u = t.get("unit")
        if isinstance(u, str) and u.strip():
            return u
    return None


def sync_library(
    library_name: str,
    tools: list[dict],
    *,
    client: SupabaseClient,
    file_path: str | None = None,
    file_hash: str | None = None,
) -> dict[str, int]:
    """
    Upsert one library worth of Fusion tools into Supabase.

    Parameters
    ----------
    library_name : str
        Filename stem or other unique name. UPSERT key on libraries.
    tools : list[dict]
        Raw ``data`` array from a Fusion JSON file. Holders/probes are
        filtered out inside this function (Rule 6).
    client : SupabaseClient
        Configured Supabase client.
    file_path : str | None
        Full on-disk path. Stored for audit; not required.
    file_hash : str | None
        SHA-256 of the source file. Stored on the library row so future
        runs can skip unchanged files.

    Returns
    -------
    dict
        ``{"tools": <count>, "presets": <count>}``.
    """
    # Rule 6 — sync filter.
    filtered = [t for t in tools if t.get("type") not in EXCLUDED_TYPES]

    vendor = _pick_vendor(filtered)
    unit_original = _pick_unit_original(filtered)

    # ── 1. Library row upsert ──────────────────────────────────────
    library_row = {
        "library_name": library_name,
        "vendor": vendor,
        "file_path": file_path,
        "file_hash": file_hash,
        "tool_count": len(filtered),
        "unit_original": unit_original,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    lib_result = client.upsert(
        "libraries",
        library_row,
        on_conflict="library_name",
    )
    if not lib_result:
        raise RuntimeError(f"Library upsert returned no rows for {library_name!r}")
    library_id = lib_result[0]["id"]
    log.info(
        "Library upserted: %s → id=%s (%d tools after filter)",
        library_name,
        library_id,
        len(filtered),
    )

    # ── 2. Tool rows upsert ────────────────────────────────────────
    tool_rows: list[dict] = []
    for raw in filtered:
        row = build_tool_row(raw)
        if not row.get("fusion_guid"):
            log.warning(
                "Skipping tool with no guid in %s: %s",
                library_name,
                row.get("product_id") or row.get("description") or "<unknown>",
            )
            continue
        row["library_id"] = library_id
        tool_rows.append(row)

    if not tool_rows:
        log.info("No tool rows to upsert for %s", library_name)
        return {"tools": 0, "presets": 0}

    tools_result = client.upsert(
        "tools",
        tool_rows,
        on_conflict="fusion_guid",
    )
    # Build a guid → db id lookup for preset parenting.
    guid_to_id = {r["fusion_guid"]: r["id"] for r in tools_result}
    log.info("Tools upserted: %d rows for %s", len(tools_result), library_name)

    # ── 3. Presets: flush + bulk insert per tool ───────────────────
    total_presets = 0
    for raw in filtered:
        guid = raw.get("guid")
        if guid not in guid_to_id:
            continue
        tool_id = guid_to_id[guid]
        # Flush existing presets for this tool so a re-sync never double-inserts.
        client.delete(
            "cutting_presets",
            filters={"tool_id": f"eq.{tool_id}"},
        )
        preset_rows = build_preset_rows(raw, tool_id=tool_id)
        if preset_rows:
            client.insert("cutting_presets", preset_rows)
            total_presets += len(preset_rows)

    log.info("Presets inserted: %d rows for %s", total_presets, library_name)
    return {"tools": len(tools_result), "presets": total_presets}


def sync_library_file(
    path: Path,
    *,
    client: SupabaseClient,
    library_name: str | None = None,
) -> dict[str, int]:
    """
    Convenience — load a single ``.json`` file from disk, apply the
    stale-file guard via ``tool_library_loader.load_library``, and
    sync it into Supabase.
    """
    from tool_library_loader import load_library

    tools = load_library(path)
    if tools is None:
        raise RuntimeError(f"load_library returned None for {path}")

    name = library_name or path.stem
    file_hash = hash_file(path)
    return sync_library(
        name,
        tools,
        client=client,
        file_path=str(path),
        file_hash=file_hash,
    )
