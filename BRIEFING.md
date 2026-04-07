# Grace Engineering — Plex API: Claude Code Briefing

This is the primary context document for AI-assisted development sessions.
Read this first, then read plex_api.py and tool_library_loader.py.

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

---

## Repo: https://github.com/grace-shane/plex-api

Forked from just-shane/plex-api. Grace Engineering's working copy.

---

## Current situation (April 2026)

- **App**: `Fusion2Plex` in the Plex Developer Portal
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
- **There is NO test environment for this app.** The Fusion2Plex Consumer
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
  └── transform layer           build_part_payload, build_assembly_payload
  └── plex_api.py / PlexClient  pushes to Plex REST API
        ├── mdm/v1/parts                consumable tools
        ├── mdm/v1/suppliers            resolve vendor UUIDs
        ├── tooling/v1/tool-assemblies  see History §3 below
        └── production/v1/control/workcenters  see History §3 below
```

### Industry hierarchy (Plex data model)

1. Purchased consumables — cutting tools as bought parts (end mills, drills, etc.)
2. Tool assemblies — consumable + holder paired together
3. Routings / operations — assemblies mapped to machining ops
4. Jobs — ops executed on the shop floor
5. Manufactured parts — end product, with full tool traceability

---

## Plex API access matrix — Fusion2Plex on production

Verified empirically against `connect.plex.com` with the Grace tenant.

| Status | Path                                  | Notes                                       |
|--------|---------------------------------------|---------------------------------------------|
| **200**| `mdm/v1/tenants`                      | 62 B — tenant list                          |
| **200**| `mdm/v1/parts?limit=1`                | **19.6 MB** — `limit` IGNORED, full DB dump |
| **200**| `mdm/v1/suppliers?limit=1`            | 708 KB — same, no server-side pagination    |
| **200**| `purchasing/v1/purchase-orders?limit=1` | **44 MB** — full PO history                |
| 404    | `production/v1/control/workcenters`   | Path doesn't exist on this app — see History §3 |
| 404    | `tooling/v1/tools`                    | Path doesn't exist — see History §3         |
| 404    | `tooling/v1/tool-assemblies`          | Path doesn't exist — see History §3         |
| 404    | `tooling/v1/tool-inventory`           | Path doesn't exist — see History §3         |
| 404    | `manufacturing/v1/operations`         | Path doesn't exist — see History §3         |

**The 404 endpoints either use a different URL pattern in this product
set, or aren't available to the Fusion2Plex app at all.** The user will
need to share working URLs from Insomnia for those endpoints to make
progress on issues #4, #5, #6.

### How to read 401 vs 404 from Plex

- **401 `REQUEST_NOT_AUTHENTICATED`** — bad credentials OR you're hitting
  a recognized namespace your app isn't subscribed to. Same wire response.
- **404 `RESOURCE_NOT_FOUND`** — Plex's gateway has no route at that path.
  Could mean unknown URL OR subscribed-but-no-resource. Same wire response.
- **The only way to tell apart cleanly** is to compare across many endpoints
  with the same auth, AND ideally compare against a known-good client
  (Insomnia → Generate Code) for ground truth.

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
- Currently 119+ tests, all green.

---

## Immediate TODO (in priority order)

All items below are mirrored as GitHub Issues — see
https://github.com/grace-shane/plex-api/issues for live status.

1. ~~Fix PlexClient constructor — add api_secret, include header~~ DONE
2. Read baseline tooling inventory from `mdm/v1/parts` — issue #2.
   **Endpoint works** but `limit` is ignored (full DB pull is 19.6 MB).
   Need to figure out the right filter parameter (`status=Active`,
   maybe `type=...`) to get just consumable cutting tools.
3. `build_part_payload(tool: dict) -> dict` — issue #3.
   Maps Fusion tool object to `mdm/v1/parts` POST body. Drafting can
   start now since we can read existing parts to learn the schema.
4. `resolve_supplier_uuid(vendor_name: str) -> str` — issue #3.
   Looks up supplier UUID from `mdm/v1/suppliers` (works on PROD now).
5. `build_assembly_payload(tool: dict, holder: dict) -> dict` — issue #4.
   `tooling/v1/tool-assemblies` returns 404 on PROD — need working URL
   pattern from Insomnia.
6. Core sync logic — upsert with guid-based dedup — issue #7.
   Dry-run by default. Real writes require `PLEX_ALLOW_WRITES=1`.
7. Error handling + logging to network share text file — issue #8.

---

## Gotchas — read before touching anything

- **EVERY READ HITS PRODUCTION DATA.** There is no test environment for the
  Fusion2Plex app. Be conscious of rate limits (200/min) and response sizes
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
  was right, it IS per-product subscription. The Fusion2Plex app needs more
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
environment. They don't work for the Fusion2Plex app on production.

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
