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
- Constructor takes api_key, api_secret, tenant_id, use_test
- Sets X-Plex-Connect-Api-Key, X-Plex-Connect-Api-Secret, and
  X-Plex-Connect-Tenant-Id headers
- Credentials read from PLEX_API_KEY / PLEX_API_SECRET env vars
- get() and get_paginated() methods
- Extraction functions: extract_purchase_orders, extract_parts, extract_workcenters
- discover_all() endpoint probe utility

### plex_diagnostics.py
- list_tenants(client) — GET /mdm/v1/tenants
- get_tenant(client, id) — GET /mdm/v1/tenants/{id}
- tenant_whoami(client, configured_id) — composite check that compares
  visible tenants against the known Grace and G5 UUIDs and returns a
  structured report. Run this first to verify tenant routing.

### tool_library_loader.py
- load_library(path) — loads single .json, returns data array
- load_all_libraries(directory) — globs all .json files in CAMTools dir
- Stale file guard — aborts if files older than 25h (ADC sync stall detection)
- PermissionError and JSONDecodeError handling (ADC mid-sync file locks)
- report_library_contents() — diagnostic summary

### app.py + templates/static
- Flask endpoint tester UI at http://localhost:5000
- Left rail: Diagnostics (run first), Plex presets, Extractors, Fusion local
- Top: method selector + URL bar + query params + Send (Ctrl/Cmd+Enter)
- Tabbed response pane (Body / Headers / Raw), copy and clear, history
- /api/plex/raw proxy lets the UI hit any Plex endpoint via PlexClient
  without exposing credentials to the browser
- /api/diagnostics/tenant runs tenant_whoami from plex_diagnostics

---

## Immediate TODO (in priority order)

All items below are mirrored as GitHub Issues — see
https://github.com/grace-shane/plex-api/issues for live status.

1. ~~Fix PlexClient constructor — add api_secret, include header~~ DONE
2. Read baseline tooling inventory from mdm/v1/parts — issue #2 (unblocked,
   read-only — can start today on G5)
3. build_part_payload(tool: dict) -> dict — issue #3
   Maps Fusion tool object to mdm/v1/parts POST body
4. resolve_supplier_uuid(vendor_name: str) -> str — issue #3
   Looks up supplier UUID from mdm/v1/suppliers (safe to test on G5 read)
5. build_assembly_payload(tool: dict, holder: dict) -> dict — issue #4
   Draft only — endpoints currently 403 (suspected tenant scoping)
6. Core sync logic — upsert with guid-based dedup — issue #7
7. Error handling + logging to network share text file — issue #8

---

## Gotchas — read before touching anything

- **G5 is production data. Read only. No writes, no mutations.**
- PLEX_API_KEY and PLEX_API_SECRET must be set in the environment before
  running plex_api.py or app.py — both will hard-fail with a clear message
  if they are missing
- The previously hardcoded API key (k3SmLW3y…) is still in git history on
  master and must be rotated before production deployment — see issue #12
- mdm/v1/parts has NO server-side pagination — unfiltered = entire DB pulled
- supplierId in responses is a UUID, not a supplier code (MSC != "MSC001")
- URL-encode spaces in filter strings (MRO SUPPLIES -> MRO%20SUPPLIES)
- API key must be in header — URL parameter returns 401
- PowerShell: use Invoke-RestMethod, not curl (alias doesn't pass headers)
- Tooling 403s on tooling/v1/* are SUSPECTED to be tenant scoping, not API
  collection subscription. Working hypothesis only — cannot verify until
  tenant routing lands. See issue #1.
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

