# Grace Engineering — Plex API: Claude Code Briefing

This is the primary context document for AI-assisted development sessions.
Read this first, then read plex_api.py and tool_library_loader.py.

---

## What this project is

Nightly automation that syncs Autodesk Fusion 360 tool library data into
Rockwell Automation Plex Smart Manufacturing (ERP). Fusion 360 JSON files
on a local network share are the absolute source of truth. The script reads
them and pushes tooling data to Plex via REST API every night at midnight.

---

## Repo: https://github.com/grace-shane/plex-api

Forked from just-shane/plex-api. Grace Engineering's working copy.

---

## Current situation

- Connected and authenticating successfully — but to the WRONG tenant (G5)
- G5 is real production data belonging to another company — READ ONLY, no writes
- IT (Courtney) is resolving tenant access for Grace Engineering
- No new credentials needed — switching tenants = enabling one header
- Use https://test.connect.plex.com (test. prefix) for all development

---

## Auth — three headers required
X-Plex-Connect-Api-Key:    <key>      # identifies the app
X-Plex-Connect-Api-Secret: <secret>   # second factor, same credential
X-Plex-Connect-Tenant-Id:  <uuid>     # tenant routing — omit = defaults to G5

Keys and secrets are managed here in Claude Code via environment variables.
Never hardcode credentials. Never commit credentials.

### Tenants

| Name            | Tenant ID                              | Status                        |
|-----------------|----------------------------------------|-------------------------------|
| Grace Eng.      | a6af9c99-bce5-4938-a007-364dc5603d08  | Target — waiting on IT        |
| G5              | b406c8c4-cef0-4d62-862c-1758b702cd02  | Currently connected — READ ONLY |

---

## Architecture

Fusion 360 .json (network share, via ADC)
└── tool_library_loader.py   reads + validates JSON, stale-file guard
└── transform layer  (build_part_payload, build_assembly_payload)
└── plex_api.py / PlexClient   pushes to Plex REST API
├── mdm/v1/parts                (consumable tools)
├── mdm/v1/suppliers            (resolve vendor UUIDs)
├── tooling/v1/tool-assemblies  (BLOCKED — see below)
└── production/v1/control/workcenters

### Industry hierarchy (Plex data model)

1. Purchased consumables — cutting tools as bought parts (end mills, drills, etc.)
2. Tool assemblies — consumable + holder paired together
3. Routings / operations — assemblies mapped to machining ops
4. Jobs — ops executed on the shop floor
5. Manufactured parts — end product, with full tool traceability

---

## Plex API endpoints

### Working (test environment)

| Endpoint                               | Notes                                          |
|----------------------------------------|------------------------------------------------|
| GET mdm/v1/tenants                     | Returns tenants for credential. Currently G5.  |
| GET mdm/v1/parts                       | NO pagination — always filter status=Active    |
| GET mdm/v1/suppliers                   | Returns UUIDs, not supplier codes              |
| GET purchasing/v1/purchase-orders      | URL-encode spaces in filter values             |
| GET production/v1/control/workcenters  | Target for pocket/turret assignment pushes     |

### 403 responses — suspected tenant routing, not subscription

- tooling/v1/tools
- tooling/v1/tool-assemblies
- tooling/v1/tool-inventory

Working hypothesis: these 403s will resolve once IT completes the tenant
routing change for Grace Engineering. Cannot verify until tenant access lands,
since G5 is another company's data and we have no authority to test writes
there. The tenant change is the **only** open IT blocker.

---

## Fusion 360 JSON schema (key fields)

Source file: BROTHER SPEEDIO ALUMINUM.json (28 entries, root "data" array)

| Field                  | Maps to Plex                        | Notes                              |
|------------------------|-------------------------------------|------------------------------------|
| guid                   | External reference key              | Use for dedup on re-sync           |
| type                   | Item sub-category                   | Filter out "holder" and "probe"    |
| description            | Part description                    |                                    |
| product-id             | Part number                         | Vendor part number, key for PO link|
| vendor                 | Supplier (resolve to UUID first)    |                                    |
| post-process.number    | Pocket / turret number              | Critical for workcenter doc update |
| geometry.DC            | Cutting diameter                    | Blocked endpoint                   |
| geometry.OAL           | Overall length                      | Blocked endpoint                   |
| geometry.NOF           | Number of flutes                    | Blocked endpoint                   |
| holder (object)        | Assembly component / BOM link       | Blocked endpoint                   |

Tool type distribution in active library:
- flat end mill: 12  |  holder: 6  |  bull nose end mill: 4  |  drill: 2
- face mill: 1  |  form mill: 1  |  slot mill: 1  |  probe: 1

Sync filter: include only type != "holder" AND type != "probe"

---

## What's built

### plex_api.py
- PlexClient base class with throttling (200 calls/min rate limit)
- get() and get_paginated() methods
- Extraction functions: extract_purchase_orders, extract_parts, extract_workcenters
- discover_all() endpoint probe utility
- **NEEDS UPDATE**: PlexClient constructor is missing api_secret parameter
  and X-Plex-Connect-Api-Secret header — fix this before any further work

### tool_library_loader.py
- load_library(path) — loads single .json, returns data array
- load_all_libraries(directory) — globs all .json files in CAMTools dir
- Stale file guard — aborts if files older than 25h (ADC sync stall detection)
- PermissionError and JSONDecodeError handling (ADC mid-sync file locks)
- report_library_contents() — diagnostic summary

---

## Immediate TODO (in priority order)

1. Fix PlexClient constructor — add api_secret, include header
2. build_part_payload(tool: dict) -> dict
   Maps Fusion tool object to mdm/v1/parts POST body
3. resolve_supplier_uuid(vendor_name: str) -> str
   Looks up supplier UUID from mdm/v1/suppliers — safe to test on G5 (read-only)
4. build_assembly_payload(tool: dict, holder: dict) -> dict
   Stub only — tooling endpoints blocked, but payload shape can be drafted
5. Core sync logic — upsert with guid-based dedup
6. Error handling + logging to network share text file

---

## Gotchas — read before touching anything

- **G5 is production data. Read only. No writes, no mutations.**
- PlexClient missing api_secret — fix before running anything
- mdm/v1/parts has NO server-side pagination — unfiltered = entire DB pulled
- supplierId in responses is a UUID, not a supplier code (MSC != "MSC001")
- URL-encode spaces in filter strings (MRO SUPPLIES -> MRO%20SUPPLIES)
- API key must be in header — URL parameter returns 401
- PowerShell: use Invoke-RestMethod, not curl (alias doesn't pass headers)
- Tooling 403s look like 404s — it's a subscription issue, not missing endpoints
- Fusion Tool objects from CAM API are copies, not references
- ADC stale file guard will abort sync if network share files are > 25h old
- BROTHER SPEEDIO ALUMINUM.json is committed to repo for reference only —
  sync script must always read from network share, not this file

---

## DNC / machine connections (for future NC program push work)

| Machine              | Protocol       | Address                     |
|----------------------|----------------|-----------------------------|
| Brother Speedio 879  | FTP            | 192.168.25.79               |
| Brother Speedio 880  | FTP            | 192.168.25.80               |
| Citizen / Tsugami    | RS-232 → TCP   | Moxa NPort 5150/5250        |
| Haas VMCs            | Ethernet       | Sigma 5 native              |

