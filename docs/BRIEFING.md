# Grace Engineering — Datum: Claude Code Briefing

This is the primary context document for AI-assisted development sessions.
Read this first, then read `plex_api.py`, `tool_library_loader.py`, and
`docs/validate_library_spec.md` (the pre-sync validation gate design, #25).

> **File layout note.** As of 2026-04-08, all long-form docs live under
> `docs/`. This file is `docs/BRIEFING.md`, not `./BRIEFING.md`. Siblings:
> `docs/Plex_API_Reference.md`, `docs/Fusion360_Tool_Library_Reference.md`,
> `docs/validate_library_spec.md`, `docs/Postman_Collections.md`.
> `README.md`, `CLAUDE.md`, and `TODO.md` are still at the repo root. See
> PR #24 for the move.

> **Read the "History of incorrect hypotheses" section at the bottom of this
> file before changing anything credential- or tenant-related.** It documents
> four wrong turns this project took that all came down to one root cause
> (see History §1). Do not repeat them.

---

## What this project is

Nightly automation that syncs Autodesk Fusion 360 tool library data into
Rockwell Automation Plex Smart Manufacturing (ERP). Fusion 360 JSON files
on a local network share are the absolute source of truth. The script reads
them and pushes tooling data to Plex via REST API every night at midnight.

**Project name: Datum.** Named for the machining reference point — the fixed datum everything is measured from. Fusion 360 is the datum; Plex and Supabase stay in sync with it.

---

## Repo: https://github.com/grace-shane/datum

Forked from just-shane/plex-api. Grace Engineering's working copy.

Renamed from `plex-api` → `datum` on 2026-04-09.

---

## Notion pages

Live project state and decision log live in Notion, outside the repo.
The repo has the "what" (code, specs, CI); Notion has the "where are we
right now" and the running conversation about trade-offs.

| Page | URL | Purpose |
|---|---|---|
| Grace Engineering | https://www.notion.so/33c3160a3abf813f9db6c5f68bef8bf2 | Parent — all Grace work lives under this page |
| Datum | https://www.notion.so/Grace-Engineering-Fusion2Plex-33c3160a3abf81f1aac0e58101952be5 | **Read this at the start of every session.** Current State block = exactly where to pick up. |

### Session protocol

- **Start of session:** read the Datum Notion page. The Current
  State block at the top tells you phase, next action, and test count
  without having to diff the repo.
- **End of session:** update the Current State block (phase, next
  action, test count) and append one line to the Decision Log describing
  what changed and why.

---

## Current situation (April 2026)

- **App**: `Datum` in the Plex Developer Portal
- **Environment**: `https://connect.plex.com` — **PRODUCTION**, real Grace data
- **Tenant**: `58f781ba-1691-4f32-b1db-381cdb21300c` (`Grace`) — verified
  empirically by `GET /mdm/v1/tenants`
- **Credentials**: Consumer Key + (optional) Secret in `.env.local`,
  loaded by `bootstrap.py` at startup. Gitignored.
- **Key expires every 31 days** — see issue #12 for rotation cadence
- **Reads work** — `mdm/v1/tenants`, `mdm/v1/parts`, `mdm/v1/suppliers`,
  `purchasing/v1/purchase-orders` all return 200
- **Writes are blocked** at the proxy by default (PR #17 production guard).
  To enable: set `PLEX_ALLOW_WRITES=1` in the environment and restart
- **There is NO test environment for this app.** The Datum Consumer
  Key only authenticates against `connect.plex.com`, not `test.connect.plex.com`.
  Every action you take is against real production data.

---

## Auth — header model

```
X-Plex-Connect-Api-Key:    <key>      # required — identifies the app
X-Plex-Connect-Tenant-Id:  <uuid>     # required — selects the tenant
X-Plex-Connect-Api-Secret: <secret>   # OPTIONAL — Plex authenticates on
                                       # the key alone for this app
```

The Insomnia Generate Code output for a working request shows only the
key + tenant headers. The secret may be needed in some configurations
(future-proof, harmless to send), but is not currently required.

Credentials are loaded from `.env.local` via `bootstrap.py`.
**Never hardcode credentials. Never commit credentials.**

### Tenants

| Name              | Tenant ID                              | Status                              |
|-------------------|----------------------------------------|-------------------------------------|
| **Grace Eng.**    | `58f781ba-1691-4f32-b1db-381cdb21300c` | **CURRENT** — verified live, prod   |
| Grace (stale)     | `a6af9c99-bce5-4938-a007-364dc5603d08` | Dead. Was in earlier docs. Wrong.   |
| G5                | `b406c8c4-cef0-4d62-862c-1758b702cd02` | Another company. Old test app only. |

Tenant IDs are not secrets — they are committed as defaults in
`plex_api.py` (`GRACE_TENANT_ID`) and `plex_diagnostics.py`
(`KNOWN_TENANTS`).

---

## Architecture

```
Fusion 360 .json (network share, via Autodesk Desktop Connector)
  └── tool_library_loader.py    reads + validates JSON, stale-file guard
  └── validate_library.py       pre-sync validation gate (spec only, #25)
  └── transform layer           build_supply_item_payload (in progress, #3)
  └── plex_api.py / PlexClient  pushes to Plex REST API
        ├── inventory/v1/inventory-definitions/supply-items   cutting tools (category="Tools & Inserts")
        ├── mdm/v1/suppliers                                  resolve vendor UUIDs
        └── production/v1/production-definitions/workcenters  machine setup docs (per-id write shape TBD, #6)
```

### Industry hierarchy (Plex data model)

1. Purchased consumables — cutting tools as bought parts (end mills, drills, etc.)
2. Tool assemblies — consumable + holder paired together
3. Routings / operations — assemblies mapped to machining ops
4. Jobs — ops executed on the shop floor
5. Manufactured parts — end product, with full tool traceability

---

## Plex API access matrix — Datum on production

Verified empirically against `connect.plex.com` with the Grace tenant.

### URL pattern convention

Plex uses two URL shapes for read endpoints:

- **Master data, flat**: `<namespace>/v1/<resource>`
  → `mdm/v1/parts`, `mdm/v1/suppliers`, `mdm/v1/operations`
- **Definitions, nested**: `<namespace>/v1/<namespace>-definitions/<resource>`
  → `production/v1/production-definitions/workcenters`
  → `inventory/v1/inventory-definitions/supply-items`

### Verified working endpoints

Record counts are as of **2026-04-09** unless noted. For the full schema
of every resource + cross-reference discussion, see
[`docs/Plex_API_Reference.md`](./Plex_API_Reference.md) §3.

| Path | Records | What it is |
|---|---:|---|
| `mdm/v1/tenants` | 1 | Grace tenant only. Auth canary. |
| `mdm/v1/parts` | 16,921 | +8 since 2026-04-07. **Finished products + raw materials only.** Tools are NOT here. |
| `mdm/v1/parts/{id}` | — | Per-id verified 2026-04-09. Same fields as list. |
| `mdm/v1/suppliers` | 1,575 | Supplier master. Has `parentSupplierId` self-FK. Mixed material + carrier types. |
| `mdm/v1/suppliers/{id}` | — | Per-id verified 2026-04-09. |
| `mdm/v1/customers` | 109 | 35-field schema. FKs to employees, contacts, suppliers. |
| `mdm/v1/customers/{id}` | — | Per-id verified 2026-04-09. |
| `mdm/v1/contacts` | 299 | |
| `mdm/v1/buildings` | 4 | Provides `buildingCode`/`buildingId` referenced by workcenters. |
| `mdm/v1/employees` | 641 | UUIDs here appear as `createdById`/`modifiedById` across every resource. |
| `mdm/v1/operations` | 122 | Process steps. Minimal schema (4 fields). No FK to tools/parts/routings — see Gotchas. |
| `mdm/v1/operations/{id}` | — | Per-id verified 2026-04-09. |
| `purchasing/v1/purchase-orders` | — | 44.2 MB unfiltered. `?updatedAfter` filter confirmed silent no-op 2026-04-09. |
| `production/v1/production-definitions/workcenters` | 143 | Includes 21 MILLs. **Codes 879/880 = Brother Speedio FTP IPs.** ⚠️ Primary key is `workcenterId`, not `id`. |
| `production/v1/production-definitions/workcenters/{id}` | — | Per-id verified 2026-04-09. |
| `inventory/v1/inventory-definitions/supply-items` | 2,516 | **WHERE TOOLS LIVE.** Filter `category="Tools & Inserts"` for the 1,109 cutting tools. **⚠️ No supplier FK, no cross-references of any kind — identity-only. See §3.5 of Plex_API_Reference.md.** |
| `inventory/v1/inventory-definitions/supply-items/{id}` | — | Per-id verified 2026-04-09. Same 7 fields, no hidden detail. |
| `inventory/v1/inventory-definitions/locations` | 1,270 | Inventory location master. Not referenced from supply-item. |
| `scheduling/v1/jobs` | TBD | **NEW — discovered 2026-04-09.** Returns 200 but ~15.8s response time (large body). Schema TBD. Potentially relevant to #5 if jobs carry tool references. |

### Where tooling data actually lives

Cutting tools and inserts are **`inventory/v1/inventory-definitions/supply-items`**
records with `category="Tools & Inserts"` and `group="Machining"`. There are
already 1,109 tools/inserts tracked in Plex Grace (verified 2026-04-09).
The schema is just 7 fields:

  - `category` (e.g. "Tools & Inserts")
  - `description` (free-text, human-readable)
  - `group` (e.g. "Machining", "Tool Room")
  - `id` (UUID — Plex primary key)
  - `inventoryUnit` (e.g. "Ea")
  - `supplyItemNumber` (**legacy: free-text, not vendor part numbers**)
  - `type` (e.g. "SUPPLY")

**⚠️ CRITICAL: supply-items have NO cross-references to any other resource (verified 2026-04-09).** This is identity-only — Plex stores no link from a tool to:

- its vendor (no `supplierId`)
- its physical location (no `locationId`)
- the part it helps produce (no `partId`)
- the machine it belongs to (no `workcenterId`)
- the operation it performs (no `operationId`)

**Implication for the Datum architecture:** vendor/supplier data for tools MUST live in Supabase as the source of truth. The Fusion JSON carries `vendor` and `product-id` → those get written to the `tools` table in Supabase → and `build_supply_item_payload()` (issue #3) constructs the Plex POST body using only the 7 identity fields listed above. Plex never learns who the vendor is, because Plex doesn't model that relationship for tools.

This kills the "use PO lines as a back-channel for the vendor link" hypothesis that was implicit earlier — `purchasing/v1/purchase-orders-lines` returned 404 on 2026-04-09.

The Fusion sync will write to `inventory/v1/inventory-definitions/supply-items`, not to `mdm/v1/parts` (which is for finished products).

**Sample existing `supplyItemNumber` values captured 2026-04-09** (confirming the legacy free-text nature of these records):

- `"Insert  HM90 AXCR 150508 IC28"` (description, not a part number)
- `"Screw Indexable Face Mill F75"`
- `"Tap #8-32 H3 Spiral Point"`

Fusion writes will use clean vendor part numbers like `"990910"`, so expect ~100% INSERTs with zero collisions on first sync.

### Workcenter ↔ machine mapping

The 21 MILL workcenter records map directly to physical machines via
`workcenterCode` (which equals the machine number / DNC IP last octet):

| Brother Speedio | FTP IP | Plex workcenterCode | Plex workcenterId |
|---|---|---|---|
| 879 | 192.168.25.79 | `879` | `0b6cf62b-2809-4d3d-ab24-369cd0171f62` |
| 880 | 192.168.25.80 | `880` | `8e262d5a-3ce8-4597-8726-d2b979b1b6b7` |

Full mill list: 814, 825, 827, 830, 834-841, 845, 848, 851, 865, 873,
879, 880, DEFLECT.

### How to read 401 vs 404 from Plex

- **401 `REQUEST_NOT_AUTHENTICATED`** — bad credentials OR you're hitting
  a recognized namespace your app isn't subscribed to. Same wire response.
- **404 `RESOURCE_NOT_FOUND`** — Plex's gateway has no route at that path.
  Could mean unknown URL OR subscribed-but-no-resource. Same wire response.
- **The only way to tell apart cleanly** is to compare across many endpoints
  with the same auth, AND ideally compare against a known-good client
  (Insomnia → Generate Code) for ground truth.

### Filter behavior — most query params are silently ignored

Empirically verified: Plex's gateway accepts unknown query parameters
without complaint and just returns the unfiltered set. The only filter
we've seen actually work on `mdm/v1/parts` is `?status=Active` (reduces
19.6 MB → 7.8 MB). The `typeName`, `type`, `category`, `limit` parameters
all return the full unfiltered response. Always assume `limit` does
nothing and use real filters or accept the full DB pull.

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
| geometry.DC            | Cutting diameter                    |                                    |
| geometry.OAL           | Overall length                      |                                    |
| geometry.NOF           | Number of flutes                    |                                    |
| holder (object)        | Assembly component / BOM link       |                                    |

Tool type distribution in active library:
- flat end mill: 12  |  holder: 6  |  bull nose end mill: 4  |  drill: 2
- face mill: 1  |  form mill: 1  |  slot mill: 1  |  probe: 1

Sync filter: include only `type != "holder" AND type != "probe"`

---

## What's built

### plex_api.py
- `PlexClient` base class with throttling (200 calls/min rate limit)
- Constructor takes `api_key`, `api_secret`, `tenant_id`, `use_test`
- All four config values read from environment variables via `bootstrap.py`
  (`PLEX_API_KEY`, `PLEX_API_SECRET`, `PLEX_TENANT_ID`, `PLEX_USE_TEST`)
- `TENANT_ID` defaults to `GRACE_TENANT_ID` (production Grace)
- `USE_TEST` defaults to `False` (production is the only environment we have)
- `get()` returns parsed JSON or None (legacy)
- `get_envelope()` returns a structured envelope so callers can see HTTP errors
- Extraction helpers: `extract_purchase_orders`, `extract_parts`, `extract_workcenters`
- `discover_all()` endpoint probe utility

### plex_diagnostics.py
- `list_tenants(client)` — GET /mdm/v1/tenants
- `get_tenant(client, id)` — GET /mdm/v1/tenants/{id}
- `tenant_whoami(client, configured_id)` — composite check that compares
  visible tenants against `KNOWN_TENANTS` and returns a structured report
  with `match` enum (`grace`, `g5`, `auth_failed`, `request_failed`,
  `no_data`, `configured`, `other`). Run this first to verify tenant routing.

### tool_library_loader.py
- `load_library(path)` — loads single .json, returns data array
- `load_all_libraries(directory)` — globs all .json files in CAMTools dir
- Stale file guard — aborts if files older than 25h (ADC sync stall detection)
- `PermissionError` and `JSONDecodeError` handling (ADC mid-sync file locks)
- `report_library_contents()` — diagnostic summary

### bootstrap.py
- Loads `.env.local` (gitignored) into `os.environ` via `setdefault`
  semantics — real shell env vars always win
- Imported at the very top of `plex_api.py` so credential reads happen
  AFTER the file is loaded
- Tested in `tests/test_bootstrap.py` (16 tests)

### app.py + templates/static
- Flask endpoint tester UI at http://localhost:5000
- Left rail: Diagnostics (run first), Plex presets, Extractors, Fusion local
- Top: method selector + URL bar + query params + Send (Ctrl/Cmd+Enter)
- Tabbed response pane (Body / Headers / Raw), copy and clear, history
- Env-chip in header shows TEST (amber) or **PROD (red)**, plus
  **READ ONLY** / **WRITES ON** sub-pill
- `/api/plex/raw` proxy lets the UI hit any Plex endpoint via PlexClient
  without exposing credentials to the browser
- **Production write guard** in proxy refuses POST/PUT/PATCH/DELETE
  against `connect.plex.com` unless `PLEX_ALLOW_WRITES=1` is set
- `/api/diagnostics/tenant` runs `tenant_whoami`
- `/api/config` exposes non-secret config including `is_production` and
  `writes_allowed`

### Tests
- `pytest` suite in `tests/`. CI on PRs to `master` via
  `.github/workflows/test.yml`. Branch protection on master requires the
  `pytest` check to pass before merge. Auto-merge enabled.
- Currently 156 tests, all green.

---

## Immediate TODO (in priority order)

All items below are mirrored as GitHub Issues — see
https://github.com/grace-shane/datum/issues for live status.

1. ~~Fix PlexClient constructor — add api_secret, include header~~ DONE
2. ~~Find the real Plex tooling endpoint~~ DONE — it's
   `inventory/v1/inventory-definitions/supply-items` with
   `category="Tools & Inserts"`. 1,109 records already exist.
3. ~~Read baseline tooling inventory from supply-items~~ DONE (PR #21,
   issue #2 closed). `extract_supply_items(client)` in plex_api.py
   returns the filtered list and writes a CSV snapshot. Verified
   live: 1,109 records, 30 KB response, 1.4s round trip.
4. **`validate_library.py` pre-sync validation gate — issue #25.**
   Implement the full spec at `docs/validate_library_spec.md`: three
   entry points (CLI / programmatic / Flask), library-level + per-tool
   rule tables, cached supplier lookup for vendor validation, integration
   hook in `tool_library_loader.load_library()` that aborts the sync on
   FAIL. **Gates all write-side work below** — must land before #3 or
   #7 can safely touch production.
5. `build_supply_item_payload(fusion_tool: dict) -> dict` — issue #3.
   Maps Fusion tool to a supply-item POST body with
   `category="Tools & Inserts"`, `group="Machining"`,
   `supplyItemNumber=<vendor part-id>`, `description=<fusion description>`.
   Runs validate_library gate first.
6. Match-and-upsert logic by `supplyItemNumber` — issue #3.
   Read existing supply-items via extract_supply_items(), match by
   vendor part number, decide POST (new) vs PUT (update existing).
7. Workcenter doc push — issue #6. Use the verified path
   `production/v1/production-definitions/workcenters/{id}` and the
   workcenterCode → Brother Speedio mapping (codes 879, 880).
   We have READ-only verified; write endpoint shape still TBD.
8. Core sync logic — upsert with `supplyItemNumber` dedup — issue #7.
   Dry-run by default. Real writes require `PLEX_ALLOW_WRITES=1`.
   Calls validate_library gate before every run.
9. Error handling + logging to network share text file — issue #8.

### Architectural decisions still pending (issues #4 and #5)

- **#4 — Tool Assemblies**: Plex's supply-item schema is identity-only
  (no holder linkage). Four options listed in the issue body —
  descope / encode in description / CSV upload / ask Plex for a
  different product. Needs the user's call before any code work.
- **#5 — Routing/Operation linkage**: `mdm/v1/operations` exists but
  has no FK to tools. Same kind of decision needed as #4.

---

## Gotchas — read before touching anything

- **EVERY READ HITS PRODUCTION DATA.** There is no test environment for the
  Datum app. Be conscious of rate limits (200/min) and response sizes
  (`mdm/v1/parts` is 19.6 MB unfiltered).
- **Writes are blocked at the proxy by default** (PR #17). To enable:
  `PLEX_ALLOW_WRITES=1` env var. Unset it as soon as you're done.
- **`mdm/v1/parts` and `purchasing/v1/purchase-orders` IGNORE the `limit`
  query param** — empirically verified. `?limit=1` returns the entire
  database (19.6 MB and 44 MB respectively). Always include a real filter
  like `status=Active` and a date range.
- **`PLEX_API_KEY` / `PLEX_API_SECRET` come from `.env.local`** via
  `bootstrap.py`. A real shell env var with the same name will OVERRIDE
  `.env.local` via `setdefault` semantics — clear stale shell vars if you
  have them. (See History §1 for the painful version of this lesson.)
- **The previously hardcoded API key (`k3SmLW3y…`) is dead.** It's in git
  history but no longer authenticates anywhere.
- **Plex returns 401 `REQUEST_NOT_AUTHENTICATED` for both bad credentials
  AND endpoints under unsubscribed API products.** The only way to tell
  them apart is to compare across multiple endpoints AND against a
  known-good client like Insomnia. See History §2.
- **`l` (lowercase L) and `I` (uppercase i) are visually identical in many
  fonts.** When reading credentials from images, treat them as ambiguous.
  Always paste credentials as text, never read them from a screenshot.
  See History §1.
- **Visible categories in the dev portal ≠ URL prefixes.** "Common APIs,
  Platform APIs, Standalone MES, IIoT" don't 1:1 map to `mdm/`, `purchasing/`,
  `tooling/` etc. The mapping is opaque.
- supplierId in responses is a UUID, not a supplier code (MSC != "MSC001")
- URL-encode spaces in filter strings (`MRO SUPPLIES` -> `MRO%20SUPPLIES`)
- API key must be in header — URL parameter returns 401
- PowerShell: use `Invoke-RestMethod`, not `curl` (alias doesn't pass headers)
- Fusion Tool objects from CAM API are copies, not references
- ADC stale file guard will abort sync if network share files are > 25h old
- `BROTHER SPEEDIO ALUMINUM.json` is committed to repo for reference only —
  sync script must always read from network share, not this file

---

## DNC / machine connections (for future NC program push work)

| Machine              | Protocol       | Address                     |
|----------------------|----------------|-----------------------------|
| Brother Speedio 879  | FTP            | 192.168.25.79               |
| Brother Speedio 880  | FTP            | 192.168.25.80               |
| Citizen / Tsugami    | RS-232 → TCP   | Moxa NPort 5150/5250        |
| Haas VMCs            | Ethernet       | Sigma 5 native              |

---

## History of incorrect hypotheses

This is a postmortem of four wrong turns this project took, written here
so the next agent (or future-me) doesn't repeat them. All four trace back
to one root cause: I misread an API key from a screenshot.

### §1 — The I-vs-l misread (root cause of everything below)

When the user shared a screenshot of the Fusion2Plex Consumer Key from the
Plex Developer Portal, I read the 9th character as `I` (uppercase i) when
it was actually `l` (lowercase L). In most fonts these are visually
indistinguishable. I wrote `AEiK3tYoIfA15wt3x3t0qmILFGAG2NkK` into
`.env.local` instead of the correct `AEiK3tYolfA15wt3x3t0qmILFGAG2NkK`.

Plex's gateway is case-sensitive on the key value, so it returned 401
`REQUEST_NOT_AUTHENTICATED` for everything. That's an entirely generic
"bad credentials" response. From the outside, it looked exactly like a
subscription problem or a tenant scoping problem.

**Lesson**: never read credentials from images. Always have the user paste
the value as text, or use Insomnia "Generate Code" output as ground truth.

### §2 — The "tenant routing" / "subscription" / "more subscription" cycle

Driven by the 401s from §1, I cycled through three wrong hypotheses about
why endpoints were failing:

- **Hypothesis A** (initial): "Tooling endpoints return 403 because IT
  hasn't enabled the Tooling API collection in the dev portal" — sourced
  from the original `Plex_API_Reference.md` written by the previous
  developer. **Plausible but unverified.**
- **Hypothesis B** (my correction in PR #16): "Actually it's tenant
  scoping, not subscription. The 403s will resolve once Courtney completes
  tenant routing." — based on a misread of BRIEFING. **Wrong.**
- **Hypothesis C** (my second correction): "Actually the Plex_API_Reference
  was right, it IS per-product subscription. The Datum app needs more
  product approvals." — based on testing with the wrong key. **Also wrong.**

The actual answer was: **the key value was wrong.** Once the right key
was loaded, every endpoint that was supposedly "blocked" started returning
200. There was no subscription problem and no tenant routing problem.
The whole investigation was an artifact of one character.

**Lesson**: when you have a confusing 401 that resists every hypothesis,
the most likely explanation is that the credential value is wrong, even
if you "verified" it. Verify against a known-good client first.

### §3 — Tooling/manufacturing/production-control 404s

After fixing the key, the working endpoints (`mdm/`, `purchasing/`) all
returned 200. But `tooling/v1/tools`, `manufacturing/v1/operations`, and
`production/v1/control/workcenters` returned 404 `RESOURCE_NOT_FOUND`.

These exact paths were in the original `Plex_API_Reference.md` and worked
for the previous developer with their old credentials on the test
environment. They don't work for the Datum app on production.

There are three possible explanations and we don't yet know which:
- The URL patterns are different in this product set
- Those endpoints aren't included in the Fusion2Plex app's product subscriptions
- The previous developer was on a fundamentally different Plex deployment

**Status**: unresolved. The user will need to share a working Insomnia
URL for one of those endpoints to make progress. Issues #4, #5, #6
remain blocked on this.

### §4 — The stale shell env var

While debugging §1, I wasted ~45 minutes because the user's shell had a
DIFFERENT, also-invalid `PLEX_API_KEY` set as a User-level Windows
environment variable in `HKCU\Environment`. Even when `.env.local` had the
correct value, `bootstrap.setdefault()` correctly refused to override the
shell value, and Flask kept using the wrong key.

The user's stale value was `uP4G8xgHdkoCFcJ00LPgfB5KYILsfdt6` — origin
unknown. Probably set via `setx` or System Properties at some earlier
point in the project's life.

**Lesson**: the very first thing `tenant_whoami` should do is print which
key value (first 8 chars + length + first-source — env var or .env.local)
is being used. We should also probably make `bootstrap.py` log when
`.env.local` is being shadowed by an existing env var.

---

## Session log

Reverse chronological. Each entry: what was the goal, what landed, what's left.

### 2026-04-09 — Postman buildout + connectivity sweep + supply-item cross-ref finding

**Goal:** Build out the Postman collections to full known scope, then actually run a connectivity sweep to stop hedging about "verified vs unverified" and get ground truth on every endpoint.

**Done:**

- **Postman collections expanded** (PR #38): Plex collection 12 → 33 requests + `[SCHED] List Jobs` + 2 new `[PROBE]` entries = 36 total. Fusion collection 10 → 14 requests. Organized via `[NS]` name prefixes (Postman MCP minimal tier has no folder creation). New `docs/Postman_Collections.md` as the day-to-day reference.
- **Connectivity sweep** (23 requests, 2026-04-09): 18/23 returned 200, 5/23 returned 404, **zero 401s**. Clean ground truth on the full subscription scope.
- **Get-by-ID chain test** (6 requests): all 6 per-id endpoints work. **Every per-id view returns exactly the same fields as the list view** — no hidden detail on any resource.
- **Fresh record counts captured** for every list endpoint (see §3 table above).
- **Full field schemas captured** for every resource (see Plex_API_Reference.md §3).
- **New endpoint discovered:** `scheduling/v1/jobs` returns 200 (15.8s response — large body, schema TBD). Potentially relevant to issue #5.
- **Critical architectural finding:** `inventory/v1/inventory-definitions/supply-items` has **NO cross-references to any other resource**. Supply-items are identity-only — Plex does not model tool→vendor, tool→location, tool→part, tool→workcenter, or tool→operation. This resolves the question the user asked about "how do we get the supplier from a supply-item": **you can't, not from Plex alone.** Vendor data has to live in Supabase as the source of truth. (Also killed the "use PO lines as a back-channel" hypothesis — `purchasing/v1/purchase-orders-lines` returns 404.)
- **Filter no-op confirmed on POs:** unfiltered and `?updatedAfter=2025-01-01` both returned byte-identical 44.2 MB responses. The filter is silently ignored (same behavior as `?limit=N`).
- **Postman descriptions updated** for all 23 sweep endpoints + the 6 per-id endpoints + the 5 `[PROBE]` entries. Historical dates preserved (2026-04-07 initial / 2026-04-09 re-verification).

**Key facts for the next session:**

- The legacy `PLEX_API_KEY=uP4G...` stale shell env var is **still set** in `HKCU\Environment`. It shadows `.env.local` due to `bootstrap.setdefault()` semantics. User cannot permanently unset it in this environment — every session must `unset PLEX_API_KEY && export PLEX_API_KEY='<current>'` before running anything that hits Plex. Document this as a project foot-gun (it's already in History §4 but the env var never got cleaned up).
- This worktree (`charming-hamilton`) does **not** have a `.env.local`. Per the `Bootstrap.py worktree foot-gun` memory, every worktree needs its own until issue #36 lands.
- The `scheduling/v1/jobs` endpoint is the highest-value follow-up — if its records carry tool references, we get the operation→tool mapping that issue #5 is blocked on without needing the `manufacturing/v1/routings` endpoint to ever become available.

**What's left:**

1. Deep-dive `scheduling/v1/jobs` — pull once, sample shape, document fields. Look specifically for `toolId`, `supplyItemId`, `workcenterId`, `operationId` references.
2. Issue #3 — `build_supply_item_payload` reading from Supabase `tools` table, now with full confidence that Plex never needs to know about vendors.
3. Issue #5 / #4 — architectural decisions remain blocked on product questions (not code questions).
4. Clean up the stale shell `PLEX_API_KEY=uP4G...` when the user gets admin access.

### 2026-04-09 — project rename + key rotation

**Goal:** Give the project a real name before it grows further.

**Done:**
- Repo renamed `grace-shane/plex-api` → `grace-shane/datum` (GitHub preserves old URL redirects)
- Plex Developer Portal app renamed `Fusion2Plex` → `Datum`
- New Consumer Key issued and loaded into `.env.local`
- All docs updated: README, CLAUDE.md, TODO.md, docs/BRIEFING.md
- Issue #12 (key rotation) closed

**Next session** (unchanged priority order):
1. Issue #25 — implement `validate_library.py` per `docs/validate_library_spec.md`
2. Issue #3 — `build_supply_item_payload` + match-and-upsert
3. Architectural decisions on #4, #5
4. Issue #6 — workcenter write support

### 2026-04-08 — docs reorg + validate_library spec + drift cleanup

**Started with:**
- All long-form docs (BRIEFING, Plex_API_Reference, Fusion360_Tool_Library_Reference) sitting in the repo root alongside source code
- No design spec for the pre-sync validation gate — the need for one was implicit in #3 and #7 but nothing was written down
- Content drift across docs: architecture diagram in BRIEFING still showed discredited endpoints (`mdm/v1/parts`, `tooling/v1/tool-assemblies`, `production/v1/control/workcenters`), test count frozen at "119+", `docs/Plex_API_Reference.md` Section 4 Target State still pointed at `tooling/v1/tool-assemblies`, line 5 referenced `plexonline.com` (classic UI, not the REST gateway), TODO.md Phase 3 item #1 still `[ ]` despite PR #21 having closed #2
- User had untracked `data/` (Fusion API reference PDFs, ~10 MB) and `outputs/` (CSV extractor snapshot, 154 KB) in the main workspace
- A fresh `docs/validate_library_spec.md` (455 lines) written locally but not yet committed

**Ended with:**
- `docs/` folder created. `BRIEFING.md`, `Plex_API_Reference.md`, `Fusion360_Tool_Library_Reference.md` all moved. Git detected them as 100% renames, so history is preserved — `git log --follow docs/BRIEFING.md` still works.
- `docs/validate_library_spec.md` committed — full design spec for the `validate_library.py` pre-sync validation gate. Three entry points (CLI, programmatic hook in `tool_library_loader`, Flask `/api/fusion/validate`), full library-level + per-tool rule tables, supplier lookup strategy with closest-3 edit-distance hint in debug mode, integration hooks.
- **GitHub issue #25 opened** — `feat: implement validate_library.py pre-sync validation gate`. Blocks #3 and #7. Spec backfilled with the real issue number (was `#XX`).
- `.gitignore` additions: `data/`, `outputs/`, `.claude/worktrees/`
- All 6 drift items fixed (test count, architecture diagram, plexonline, Target State rewrite, TODO checkbox, spec issue number)
- README.md + CLAUDE.md link paths updated to the new `./docs/` prefix
- 156 tests still green — no code changes this session, docs-only

**Pull requests merged this session** (newest first):
- #26 docs: fix stale content drift in BRIEFING, Plex_API_Reference, TODO, spec
- #24 docs: move long-form docs into `docs/`, add validate_library spec, gitignore large dirs

**GitHub issues opened:**
- **#25** feat: implement `validate_library.py` pre-sync validation gate — blocks #3 and #7

**What's left to do next session** (in order):
1. **Issue #25** — implement `validate_library.py` per `docs/validate_library_spec.md`. This is now the highest-priority item since it gates the upsert work. Expect: new module + CLI + Flask routes + loader hook + ~30 pytest cases covering every Rule ID.
2. **Issue #3** — `build_supply_item_payload(fusion_tool)` + match-and-upsert logic, with the validate_library gate called first.
3. **Architectural decisions on #4, #5** — still blocked on a product question, not a code question.
4. **Issue #6** — workcenter doc write support (carefully, with `PLEX_ALLOW_WRITES=1` set deliberately).
5. **Issue #12** — key rotation deadline 2026-05-08.

**Lessons** (follow-ups to "History of incorrect hypotheses" if anything goes sideways the same way):

6. **Worktree gotcha — the painful one this session.** I burned ~30 minutes and a lot of tokens looking for a `docs/` folder the user said they'd added. I kept running `ls` and `git status` from a worktree at `.claude/worktrees/naughty-khayyam/`, not the main workspace at `C:/projects/plex-api/`. Worktrees share the `.git` directory (via `.git` file pointer) but have independent working trees — any new files the user creates in the main workspace are invisible to worktree `ls`. **Rule: when the user says "I added X locally" or "I moved stuff around", the first command is `cd "C:/projects/plex-api" && git status` in the main workspace, not the worktree.** Don't trust the worktree's view of the filesystem for anything the user did in File Explorer.
7. **Git rename detection is automatic.** The user moved files with File Explorer before I got there. Git saw them as deletes + untracked adds. Running `git rm` on the old paths and `git add` on the new paths in the **same commit** lets git's diff-rename detection catch them as 100% renames, preserving history. No special `git mv` step is needed — git is smart about this at commit time, not at stage time. The PR showed them as `rename BRIEFING.md => docs/BRIEFING.md (100%)` without any extra ceremony.
8. **Open issues before writing specs that reference them.** The validate_library spec had `#XX` placeholders for the implementation issue. Cleaner workflow: open the issue first, get the real number, then write the spec with the real number baked in. Otherwise you end up with a two-step commit (add spec with `#XX`, then a follow-up PR to backfill `#25`).
9. **Always re-run `git status` from the correct cwd after a worktree operation.** The shell in the Claude harness runs each Bash command with the cwd reset to the worktree root — which means `cd` inside a Bash call is ephemeral. Chain commands with `&&` when the later ones need to see the earlier `cd` effect. Every `Bash(cd X && git foo)` reminds you of this.

---

### 2026-04-07 — full project bootstrap + Phase 3 read side

**Started with:**
- Hardcoded API key in `plex_api.py` (still in git history)
- Old "gradient/glass dashboard" UI
- TODO.md as the only project tracker
- No tests, no CI, no .env.local concept
- BRIEFING claiming tenant routing was the IT blocker

**Ended with:**
- 11 PRs merged, all via auto-merge after CI passes
- 156 pytest tests, all green, branch protection enforces them on master
- `.env.local` loader (`bootstrap.py`) + dev override (`run_dev.py`)
- Production write guard (`/api/plex/raw` refuses POST/PUT/PATCH/DELETE
  unless `PLEX_ALLOW_WRITES=1`)
- Verified working credentials (`Fusion2Plex` Consumer Key) on
  production with the real Grace tenant `58f781ba-...`
- **Issue #2 closed** — `extract_supply_items()` returns 1,109
  cutting tools and inserts from
  `inventory/v1/inventory-definitions/supply-items` in 1.4s
- Brother Speedio mapping verified — workcenters 879/880 = FTP IPs
  192.168.25.79/.80
- BRIEFING + Plex_API_Reference + TODO all rewritten to match
  empirical reality (with the "History of incorrect hypotheses"
  postmortem above documenting four wrong turns)

**Pull requests merged this session** (newest first):
- #22 fix: stdout UTF-8 reconfigure + ASCII arrows
- #21 feat: extract_supply_items + Fusion testing-harness endpoints (closes #2)
- #20 docs: Plex tooling lives in inventory/v1/inventory-definitions/supply-items
- #19 feat: run_dev.py local launcher
- #18 feat: migrate to PROD Plex environment + verified Grace tenant
- #17 feat: production write guard at the proxy
- #16 docs: correct subscription-not-tenant hypothesis (later corrected by #20)
- #15 fix: surface HTTP errors instead of swallowing them as None
- #14 feat: .env.local loader + Claude Preview launch config
- #13 Endpoint tester UI, tenant diagnostics, env-var credentials, GH issue tracking

**What's left to do tomorrow** (in order):
1. **Issue #3** — `build_supply_item_payload(fusion_tool)` writing to
   `inventory/v1/inventory-definitions/supply-items`. We have the verified
   read path and 1,109 records to learn the schema from.
2. **Architectural decision on issues #4 and #5** — descope or pivot.
   Both are blocked on a real product question, not a code question.
3. **Issue #6** — probe write support on workcenters (carefully, with
   `PLEX_ALLOW_WRITES=1` enabled deliberately).
4. **Issue #12** — key rotation deadline 2026-05-08.

**Lessons** (additions to "History of incorrect hypotheses" if any
session goes sideways the same way again):
1. Never read credentials from images. Always have the user paste
   them as text or via Insomnia "Generate Code" output.
2. Status codes from Plex are misleading on their own. 401 means
   "bad creds OR unsubscribed product"; 404 means "wrong URL OR
   unsubscribed namespace". Compare across endpoints to disambiguate.
3. Plex's URL convention is `<namespace>/v1/<namespace>-definitions/<resource>`
   for definition data — not the bare `<namespace>/v1/<resource>` we
   kept guessing. Tools live at `inventory/v1/inventory-definitions/supply-items`,
   not `tooling/v1/tools` or `mdm/v1/parts`.
4. Server-side filters on Plex endpoints are mostly silently ignored.
   `?limit=1` on `mdm/v1/parts` returns 19.6 MB. Filter client-side.
5. pytest's `capsys` uses UTF-8, so stdout encoding bugs only show
   up under live Flask. Add `sys.stdout.reconfigure(encoding="utf-8")`
   at the top of any process whose stdout might end up captured by
   Flask request handlers on Windows.
