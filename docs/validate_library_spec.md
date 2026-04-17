# `validate_library.py` — Full Design Spec

**Project:** Fusion 360 → Plex tooling sync — Grace Engineering
**Repo:** https://github.com/grace-shane/Datum
**Status:** Implemented — landed in [PR #28](https://github.com/grace-shane/Datum/pull/28) (2026-04-08), closing issue [#25](https://github.com/grace-shane/Datum/issues/25). This document is retained as the design reference.

---

## Purpose

Pre-sync validation gate for Fusion 360 tool library JSON files. Runs before
any data touches Plex. Three entry points share one validation engine. A FAIL
aborts the sync. WARNs are surfaced in verbose/debug modes and the Flask UI.

---

## File Location

```
plex-api/
  validate_library.py      ← new file
  tool_library_loader.py   ← calls validate_library as pre-sync gate
  app.py                   ← adds /api/fusion/validate endpoint
```

---

## Output Modes

| Mode | Trigger | Shows |
|---|---|---|
| Production | default / no flags | PASS or FAIL + failing rules only |
| Verbose | `--verbose` / `-v` | PASS / FAIL + WARN + failing rules |
| Debug | `--debug` / `-d` | Everything — every field checked, full supplier list on vendor lookup |

The Flask endpoint always behaves as **verbose** since a human is reading it.

---

## Entry Points

### 1 — CLI

```bash
# Production default — PASS/FAIL only
python validate_library.py

# Specific file
python validate_library.py --file "BROTHER SPEEDIO ALUMINUM.json"

# Verbose — adds WARNs
python validate_library.py --verbose

# Debug — full field trace + supplier list
python validate_library.py --debug

# Skip the live Plex supplier lookup (offline mode)
python validate_library.py --no-api
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | PASS |
| `1` | FAIL |
| `2` | Script / environment error (missing file, no API creds, etc.) |

---

### 2 — Programmatic (called from `tool_library_loader.py`)

```python
from validate_library import validate_library, ValidationMode

result = validate_library(
    tools=raw_tool_list,        # list[dict] already loaded by load_library()
    library_name="BROTHER SPEEDIO ALUMINUM",
    mode=ValidationMode.PRODUCTION,
    use_api=False,              # False to skip supplier lookup
)

if not result.passed:
    log.error("Validation failed — aborting sync")
    log.error(result.summary())
    return None                 # tool_library_loader returns None, sync aborts
```

`tool_library_loader.py` calls this **after** `load_library()` succeeds but
**before** returning tools to the sync layer. Stale/locked file errors are
still caught by the existing loader guards — validation only runs on
successfully parsed data.

`use_api=False` is the default in the loader to keep it fast and offline-safe.
API vendor validation is an explicit opt-in from the CLI or Flask.

---

### 3 — Flask Endpoint

```
GET  /api/fusion/validate
POST /api/fusion/validate
```

- **GET** — validates live files from the ADC network share
- **POST** — validates an uploaded JSON file without touching the share
  (same multipart upload shape as `/api/fusion/libraries`)

Always runs in verbose mode. No `--debug` toggle from the UI in the initial
implementation (can be added later as a query param).

**Response shape:**

```json
{
  "library_name": "BROTHER SPEEDIO ALUMINUM",
  "passed": false,
  "tool_count": 28,
  "sync_candidate_count": 21,
  "issues": [
    {
      "severity": "FAIL",
      "rule": "REQUIRED_FIELD",
      "tool_index": 4,
      "tool_description": "5/8x4x1-3/4 in SQ. END",
      "field": "product-id",
      "message": "Missing required field 'product-id' — this tool cannot be deduped in Plex"
    },
    {
      "severity": "WARN",
      "rule": "VENDOR_NOT_IN_PLEX",
      "tool_index": 7,
      "tool_description": "1/4 BALL END MILL",
      "field": "vendor",
      "value": "GARR TOOL",
      "message": "Vendor 'GARR TOOL' not found in mdm/v1/suppliers — will fail on sync"
    }
  ],
  "debug_trace": null
}
```

`debug_trace` is `null` unless `debug=True` is passed programmatically or a
future `?debug=1` query param is supported.

---

## Core Data Structures

### `ValidationMode` enum

```python
class ValidationMode(Enum):
    PRODUCTION = "production"   # PASS/FAIL only
    VERBOSE    = "verbose"      # + WARNs
    DEBUG      = "debug"        # + field trace
```

### `ValidationIssue` dataclass

```python
@dataclass
class ValidationIssue:
    severity: Literal["FAIL", "WARN"]
    rule: str           # machine-readable rule ID (see Rule Table)
    tool_index: int | None
    tool_description: str | None
    field: str | None
    value: Any
    message: str        # human-readable
```

### `ValidationResult` dataclass

```python
@dataclass
class ValidationResult:
    library_name: str
    passed: bool
    tool_count: int
    sync_candidate_count: int   # count after filtering holders + probes
    issues: list[ValidationIssue]
    debug_trace: list[str] | None

    def summary(self) -> str: ...     # single-line human-readable string
    def to_dict(self) -> dict: ...    # Flask JSON response
```

---

## Constants Block

Define at the top of `validate_library.py`:

```python
# ── Known tool types ─────────────────────────────────────────────────────────
KNOWN_TOOL_TYPES = {
    "flat end mill", "bull nose end mill", "drill",
    "face mill", "form mill", "slot mill",
    "holder", "probe"
}

# Types excluded from sync — identity only, not purchasable consumables
NON_SYNC_TYPES = {"holder", "probe"}

# ── Geometry bounds ───────────────────────────────────────────────────────────
# TODO (issue #XX): confirm real shop floor bounds with Shane before enabling
# range WARN rules. The nonpositive FAIL rules (DC <= 0, NOF <= 0) are always
# active regardless of these values.
DC_MIN  = None   # cutting diameter min, inches
DC_MAX  = None   # cutting diameter max, inches
OAL_MIN = None   # overall length min, inches
OAL_MAX = None   # overall length max, inches
NOF_MIN = None   # number of flutes min
NOF_MAX = None   # number of flutes max
```

When a bound is `None`, the corresponding range check is skipped entirely.
In debug mode, skipped checks are logged:
```
[DEBUG] GEOMETRY_DC_RANGE skipped — DC_MIN/DC_MAX not set
```

---

## Rule Table

Rules run in this order. **Library-level rules run first.** If any library-level
rule FAILs, per-tool rules are skipped — there is nothing safe to iterate.

---

### Library-Level Rules

| Rule ID | Severity | Condition | Message |
|---|---|---|---|
| `STRUCT_ROOT_KEY` | FAIL | `"data"` key missing from root | Root `"data"` key missing — not a valid Fusion tool library |
| `STRUCT_DATA_LIST` | FAIL | `data` is not a list | Root `"data"` is not a list |
| `STRUCT_EMPTY` | FAIL | `data` list is empty | Library contains zero entries |
| `SYNC_CANDIDATES_ZERO` | FAIL | After filtering `NON_SYNC_TYPES`, zero tools remain | No syncable tools after filtering — check type values |
| `DUPLICATE_GUID` | FAIL | Two entries share the same `guid` | Duplicate guid `{guid}` at indexes {i} and {j} |
| `DUPLICATE_PRODUCT_ID` | FAIL | Two sync-candidate entries share `product-id` | Duplicate product-id `{id}` at indexes {i} and {j} — upsert will collide |
| `CROSS_LIBRARY_DUPLICATE` | WARN | `product-id` already seen in a previously validated library (multi-library runs only) | product-id `{id}` also exists in `{other_library}` — check for cross-library collision |
| `UNKNOWN_TYPE_PRESENT` | WARN | A `type` value is not in `KNOWN_TOOL_TYPES` | Unknown type `"{type}"` at index {i} — will be included in sync unless filter is updated |

---

### Per-Tool Rules

Runs on sync candidates only (entries where `type` is not in `NON_SYNC_TYPES`).
Holders and probes are silently skipped.

#### Required Field Rules

| Rule ID | Severity | Field | Condition |
|---|---|---|---|
| `REQUIRED_FIELD` | FAIL | `guid` | missing or empty string |
| `REQUIRED_FIELD` | FAIL | `type` | missing or empty string |
| `REQUIRED_FIELD` | FAIL | `description` | missing or empty string |
| `REQUIRED_FIELD` | FAIL | `product-id` | missing or empty string |

#### Vendor Rules

| Rule ID | Severity | Condition | Message |
|---|---|---|---|
| `VENDOR_MISSING` | WARN | `vendor` key missing or empty string | Tool has no vendor — supplier linkage will fail on sync |
| `VENDOR_NOT_IN_PLEX` | WARN | vendor present but not matched in `mdm/v1/suppliers` (only when `use_api=True`) | Vendor `"{vendor}"` not found in Plex supplier master — will fail at sync time |

In debug mode, `VENDOR_NOT_IN_PLEX` additionally logs:
- The full supplier name list it matched against
- The 3 closest names by edit distance (to catch `"GARR TOOL"` vs `"Garr Tool"`,
  trailing spaces, abbreviation differences, etc.)

#### Geometry Rules

All geometry lives under `tool["geometry"]`. If `geometry` is absent entirely
on a sync candidate, that is its own WARN before any field-level checks run.

| Rule ID | Severity | Field | Condition | Note |
|---|---|---|---|---|
| `GEOMETRY_MISSING` | WARN | `geometry` | key absent on sync candidate | Logged once per tool; field checks below are skipped |
| `GEOMETRY_DC_MISSING` | WARN | `geometry.DC` | key absent | |
| `GEOMETRY_DC_NONPOSITIVE` | FAIL | `geometry.DC` | `<= 0` | Hard rule — always active |
| `GEOMETRY_DC_RANGE` | WARN | `geometry.DC` | outside `[DC_MIN, DC_MAX]` | Skipped when either bound is `None` |
| `GEOMETRY_OAL_MISSING` | WARN | `geometry.OAL` | key absent | |
| `GEOMETRY_OAL_SHORTER_THAN_DC` | WARN | `geometry.OAL` vs `geometry.DC` | `OAL < DC` | Physically implausible — always active when both fields present |
| `GEOMETRY_OAL_RANGE` | WARN | `geometry.OAL` | outside `[OAL_MIN, OAL_MAX]` | Skipped when either bound is `None` |
| `GEOMETRY_NOF_MISSING` | WARN | `geometry.NOF` | key absent | |
| `GEOMETRY_NOF_NONPOSITIVE` | FAIL | `geometry.NOF` | `<= 0` | Hard rule — always active |
| `GEOMETRY_NOF_RANGE` | WARN | `geometry.NOF` | outside `[NOF_MIN, NOF_MAX]` | Skipped when either bound is `None` |

#### Post-Process Rules

| Rule ID | Severity | Field | Condition |
|---|---|---|---|
| `POSTPROCESS_NUMBER_MISSING` | WARN | `post-process.number` | `post-process` object absent or `number` key absent |
| `POSTPROCESS_NUMBER_NONPOSITIVE` | WARN | `post-process.number` | `<= 0` |

---

## Supplier Lookup

Implemented as a module-level cached function — hits the API once per process
run regardless of how many libraries are validated.

```python
_supplier_cache: list[str] | None = None

def _get_supplier_names(client: PlexClient, debug: bool = False) -> list[str]:
    """
    Fetch supplier names from mdm/v1/suppliers.
    Cached after first call. Returns empty list on API failure (non-fatal —
    VENDOR_NOT_IN_PLEX checks are skipped if the supplier list cannot be loaded).
    """
```

**Matching strategy:**
1. Case-insensitive exact match
2. If no match and debug mode: log the 3 closest names by edit distance

API failure during supplier fetch is non-fatal. Log a warning that vendor
checks were skipped and continue. Never abort the validation run because
the supplier endpoint was unreachable.

---

## CLI Output Examples

### Production — PASS

```
✓ BROTHER SPEEDIO ALUMINUM — 21 tools valid, ready to sync
```

### Production — FAIL

```
✗ BROTHER SPEEDIO ALUMINUM — FAILED (2 errors)

  [FAIL] REQUIRED_FIELD — tool 4 "5/8x4x1-3/4 in SQ. END"
         Field: product-id
         Missing required field 'product-id' — this tool cannot be deduped in Plex

  [FAIL] GEOMETRY_DC_NONPOSITIVE — tool 11 "1/4 BALL END MILL"
         Field: geometry.DC
         Cutting diameter must be > 0 (got 0.0)
```

### Verbose — FAIL with WARNs

```
✗ BROTHER SPEEDIO ALUMINUM — FAILED (2 errors, 1 warning)

  [FAIL] REQUIRED_FIELD — tool 4 "5/8x4x1-3/4 in SQ. END"
         Field: product-id
         Missing required field 'product-id' — this tool cannot be deduped in Plex

  [FAIL] GEOMETRY_DC_NONPOSITIVE — tool 11 "1/4 BALL END MILL"
         Field: geometry.DC
         Cutting diameter must be > 0 (got 0.0)

  [WARN] VENDOR_NOT_IN_PLEX — tool 7 "1/4 BALL END MILL"
         Field: vendor
         Value: "GARR TOOL"
         Vendor not found in Plex supplier master — will fail at sync time
```

### Debug — adds full field trace per tool (truncated)

```
  [DEBUG] tool 0 "5/8x4x1-3/4 in SQ. END"
          guid .................. OK  (a3f1...)
          type .................. OK  (flat end mill)
          description ........... OK
          product-id ............ OK  (990910)
          vendor ................ OK  — matched "Harvey Tool" in supplier master
          geometry.DC ........... OK  (0.625) — range check skipped (bounds not set)
          geometry.OAL .......... OK  (4.0)
          geometry.NOF .......... OK  (4)
          post-process.number ... OK  (1)
```

In debug mode, vendor mismatch additionally prints:

```
  [DEBUG] Supplier master (47 records):
          Closest matches to "GARR TOOL":
            1. "Garr Tool Co."       (edit distance 5)
            2. "GARR TOOLING INC"    (edit distance 7)
            3. "GARR"                (edit distance 9)
```

---

## Integration Into `tool_library_loader.py`

Add a single call in `load_library()` after successful JSON parse, before
`return tools`:

```python
# After: tools = raw.get("data") passes all existing checks
# Before: return tools

from validate_library import validate_library, ValidationMode

validation = validate_library(
    tools=tools,
    library_name=path.stem,
    mode=ValidationMode.PRODUCTION,
    use_api=False,   # keep loader fast and offline-safe
)
if not validation.passed:
    log.error("Validation failed for %s — sync aborted", path.name)
    log.error(validation.summary())
    return None
```

---

## Integration Into `app.py`

Add two routes:

```python
@app.route('/api/fusion/validate', methods=['GET', 'POST'])
def api_fusion_validate():
    """
    GET  — validate live files from ADC share (same source as /api/fusion/libraries)
    POST — validate uploaded JSON file(s) without touching the share

    Always runs in VERBOSE mode (human is reading the response).
    Returns ValidationResult.to_dict() per library.
    """
```

---

## GitHub Issues to Open

| Issue | Title |
|---|---|
| #XX | `validate_library.py` — implement core engine + CLI |
| #XX | Geometry bounds — confirm DC / OAL / NOF ranges, enable range WARN rules |
| #XX | Vendor fuzzy matching — promote near-miss debug output to verbose mode |

---

## Open Decisions

| # | Decision | Status |
|---|---|---|
| 1 | Geometry bounds (DC / OAL / NOF) | **Blocked on Shane** — constants stubbed as `None` |
| 2 | Fuzzy vendor matching in verbose vs debug only | Debug only for now; revisit after first real sync run |
| 3 | `?debug=1` query param on Flask endpoint | Deferred — not in initial implementation |
