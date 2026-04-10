"""
tool_library_loader.py
Fusion 360 Tool Library JSON Loader
Grace Engineering — plex-api project
======================================
Reads all .json tool library files from the Autodesk Desktop Connector
local sync path. Files are the absolute Source of Truth for Plex tooling.

Requirements:
- CAMTools directory must be flat (no subdirectories).
- All Fusion 360 tool library exports must be .json files in that directory.
- Autodesk Desktop Connector must be running and synced prior to script execution.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# Resolve path using standard Windows environment variables.
# %USERPROFILE% = C:\Users\<username>  |  %LOCALAPPDATA%, %APPDATA% also available.
# This avoids hardcoding a username and survives profile/machine changes.
_USERPROFILE  = os.environ.get("USERPROFILE", "")
_DC_REL_PATH  = r"DC\Fusion\XWERKS\Assets\CAMTools"
CAM_TOOLS_DIR = Path(_USERPROFILE) / _DC_REL_PATH

# Maximum age of JSON files before the loader aborts.
# ADC sync is expected to keep files current. If files are older than this,
# assume ADC is stalled or the machine was offline and bail out safely.
MAX_FILE_AGE_HOURS = 25

# ─────────────────────────────────────────────
# LOGGER
# ─────────────────────────────────────────────
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# FILE AGE CHECK
# ─────────────────────────────────────────────
def _check_file_age(path: Path, max_age_hours: int = MAX_FILE_AGE_HOURS) -> bool:
    """
    Returns True if the file was modified within the allowed window.
    Logs a warning and returns False if the file is stale.
    ADC sync failure is silent — stale files look valid without this guard.
    """
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    age   = datetime.now() - mtime
    if age > timedelta(hours=max_age_hours):
        log.warning(
            "STALE FILE — %s last modified %s (%.1f hours ago). "
            "ADC sync may be stalled. Aborting load to prevent pushing stale data.",
            path.name,
            mtime.strftime("%Y-%m-%d %H:%M:%S"),
            age.total_seconds() / 3600,
        )
        return False
    return True


# ─────────────────────────────────────────────
# SINGLE FILE LOADER
# ─────────────────────────────────────────────
def load_library(path: Path, validate: bool = False) -> list[dict] | None:
    """
    Load a single Fusion 360 tool library JSON file.
    Returns the list of tool/holder objects from the root "data" array,
    or None on failure (stale, locked, malformed, or validation failure).

    Handles:
    - File age guard (ADC stall detection)
    - PermissionError (ADC mid-sync file lock)
    - JSON decode errors (incomplete sync / corrupt file)
    - Schema validation via ``validate_library`` (when ``validate=True``)

    Parameters
    ----------
    path
        Path to a .json tool library file.
    validate
        When True, runs ``validate_library.validate_library()`` in PRODUCTION
        mode with ``use_api=False``. A failing validation returns None so the
        sync layer can abort cleanly. Default is False to preserve the
        existing offline diagnostic behaviour; sync callers should pass True.
    """
    if not _check_file_age(path):
        return None  # stale — caller decides whether to abort or skip

    if path.stat().st_size == 0:
        log.warning("EMPTY FILE — %s is 0 bytes. Skipping.", path.name)
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

    except PermissionError:
        log.error(
            "LOCKED — %s is held by another process (ADC sync in progress?). "
            "Skipping this library.",
            path.name,
        )
        return None

    except (json.JSONDecodeError, OSError) as e:
        log.error(
            "MALFORMED JSON — %s failed to parse: %s. "
            "File may be mid-write by ADC.",
            path.name,
            e,
        )
        return None

    tools = raw.get("data")
    if not isinstance(tools, list):
        log.error(
            "UNEXPECTED SCHEMA — %s: root 'data' key missing or not a list.",
            path.name,
        )
        return None

    if validate:
        # Imported lazily so that importing tool_library_loader does not
        # drag in validate_library for every caller that only wants a
        # raw JSON load.
        from validate_library import validate_library as _validate, ValidationMode

        result = _validate(
            tools=tools,
            library_name=path.stem,
            mode=ValidationMode.PRODUCTION,
            use_api=False,
        )
        if not result.passed:
            log.error("Validation failed for %s — sync aborted", path.name)
            log.error(result.summary())
            for issue in result.fails:
                log.error("  %s: %s", issue.rule, issue.message)
            return None

    log.info("Loaded %s — %d entries", path.name, len(tools))
    return tools


# ─────────────────────────────────────────────
# DIRECTORY LOADER
# ─────────────────────────────────────────────
def load_all_libraries(
    directory: Path = CAM_TOOLS_DIR,
    abort_on_stale: bool = True,
    validate: bool = False,
) -> dict[str, list[dict]]:
    """
    Glob all .json files in the flat CAMTools directory and load each one.

    Parameters
    ----------
    directory      : Path to the CAMTools folder. Defaults to ADC sync path.
    abort_on_stale : If True (default), abort the entire run when any file is
                     stale. Prevents partial pushes where some libraries are
                     current and others are not.
                     Set False to skip stale files and continue with valid ones.
    validate       : If True, each library is passed through validate_library
                     and libraries that fail are treated the same as stale.
                     Default False; sync callers should pass True.

    Returns
    -------
    dict keyed by library filename (stem), value is list of tool dicts.
    Empty dict on hard failure (directory missing, all files stale/locked).
    """
    if not directory.exists():
        log.critical(
            "CAMTools directory not found: %s — "
            "Is Autodesk Desktop Connector running?",
            directory,
        )
        return {}

    json_files = sorted(directory.glob("*.json"))

    if not json_files:
        log.warning("No .json files found in %s", directory)
        return {}

    log.info("Found %d tool library file(s) in %s", len(json_files), directory)

    libraries: dict[str, list[dict]] = {}

    for path in json_files:
        tools = load_library(path, validate=validate)

        if tools is None:
            if abort_on_stale:
                log.critical(
                    "Aborting full sync — %s could not be loaded. "
                    "Fix ADC sync or file issue before retrying.",
                    path.name,
                )
                return {}
            else:
                log.warning("Skipping %s and continuing.", path.name)
                continue

        libraries[path.stem] = tools

    return libraries


# ─────────────────────────────────────────────
# QUICK DIAGNOSTIC
# ─────────────────────────────────────────────
def report_library_contents(libraries: dict[str, list[dict]]) -> None:
    """
    Prints a summary of loaded libraries: file name, count, and type breakdown.
    Useful for verifying load before any API push.
    """
    for name, tools in libraries.items():
        type_counts: dict[str, int] = {}
        for t in tools:
            tool_type = t.get("type", "unknown")
            type_counts[tool_type] = type_counts.get(tool_type, 0) + 1

        breakdown = ", ".join(
            f"{count} {kind}" for kind, count in sorted(type_counts.items())
        )
        print(f"  {name}: {len(tools)} entries — {breakdown}")


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print(f"CAMTools path: {CAM_TOOLS_DIR}")
    print(f"Path exists:   {CAM_TOOLS_DIR.exists()}\n")

    libs = load_all_libraries(abort_on_stale=True)

    if libs:
        print(f"\nLoaded {len(libs)} library file(s):")
        report_library_contents(libs)
    else:
        print("No libraries loaded — check logs above.")
