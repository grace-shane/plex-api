# Postman Collections — Datum

This document is the authoritative reference for the two Postman collections
that back the Datum project. It lives next to `BRIEFING.md` and
`Plex_API_Reference.md` because the collections are the day-to-day
exploration tool — when you need to poke at a Plex endpoint or the local
Flask harness, the collections are where you start.

> **Read order.** If you have not yet read `docs/BRIEFING.md` and
> `docs/Plex_API_Reference.md`, read those first. This document assumes
> you understand the Datum project, the Plex auth model, and the
> "verified vs probe" distinction. The collections inherit those rules.

---

## 1. Where the collections live

Both collections live in Shane's Grace Engineering Postman workspace.

| Field | Value |
|---|---|
| Workspace name | (Grace Engineering — Datum workspace) |
| Workspace ID | `154e8d9a-cde9-4036-8e07-6913e468ab05` |
| Owner | `shanewaid@graceeng.com` (Shane's Grace Postman account, owner ID `53648712`) |

### Collections

| Name | Collection ID | UID (MCP form) |
|---|---|---|
| **Plex API — Datum** | `75b28dc4-9c73-4e27-90d0-1539777f52ea` | `53648712-75b28dc4-9c73-4e27-90d0-1539777f52ea` |
| **Fusion 360 Tool Libraries — Datum** | `8a9b5ce6-f541-4301-b15d-fd95970df0e8` | `53648712-8a9b5ce6-f541-4301-b15d-fd95970df0e8` |

The bare collection ID (no owner prefix) is the form most Postman MCP
endpoints want. The UID form (with the `53648712-` prefix) is what
`getCollection`, `getCollections`, etc. return as a stable handle.

### Environment

| Field | Value |
|---|---|
| Name | `Plex — Grace Engineering (Production)` |
| Variables | `api_key`, `api_secret` (secret type), `tenant_id`, `base_url` |

The Fusion collection doesn't strictly need this environment because it
runs against the local Flask app, but having it active is harmless.

---

## 2. Auth model

Plex auth lives entirely at the collection level. Every request in the
**Plex API — Datum** collection inherits a pre-request script that injects
three headers from the active environment:

```javascript
pm.request.headers.add({ key: 'X-Plex-Connect-Api-Key',    value: pm.environment.get('api_key') });
pm.request.headers.add({ key: 'X-Plex-Connect-Api-Secret', value: pm.environment.get('api_secret') });
pm.request.headers.add({ key: 'X-Plex-Connect-Tenant-Id',  value: pm.environment.get('tenant_id') });
```

You should never have to set these headers manually. If a Plex request
returns 401 `REQUEST_NOT_AUTHENTICATED`, check that:

1. The `Plex — Grace Engineering (Production)` environment is **active**
   (top-right environment selector in Postman).
2. `api_key` is the current Datum Consumer Key from the Plex Developer
   Portal — keys rotate every 31 days (see issue #12).
3. You haven't recently regenerated the key in the portal.

The Fusion collection has no auth — it's all local Flask, no credentials.

---

## 3. Naming convention

Both collections use a `[NS]` prefix on every request name to group them
visually in the Postman sidebar. This is a workaround for the fact that
the Postman MCP minimal tool surface doesn't expose folder creation, so
we can't use real folders. Sort the request list alphabetically in
Postman to see the groups together.

### Plex — Datum

| Prefix | Meaning | Folder analogue |
|---|---|---|
| `[AUTH]` | Auth canary + tenant lookups | Run **first** in any session |
| `[MDM]` | Master Data Management — parts, suppliers, customers, contacts, buildings, employees, operations | Verified namespace |
| `[INV]` | Inventory — supply-items (where TOOLS live) and locations | Verified namespace |
| `[PROD]` | Production — workcenters, including the Brother Speedio per-id reads | Verified namespace |
| `[PURCH]` | Purchasing — purchase orders | Verified namespace |
| `[WRITE]` | Mutating requests — POST/PUT/DELETE templates | **Production data — see §6** |
| `[PROBE]` | Unverified namespaces (`tooling/`, `manufacturing/`, `quality/`, `sales/`) | Run to detect subscription gaps |

### Fusion — Datum

| Prefix | Meaning |
|---|---|
| `[SRV]` | Server-level Flask endpoints — config, tenant diagnostic |
| `[LIB]` | Fusion library reads — list, upload, stats, consumables |
| `[VAL]` | Pre-sync validation gate variants |
| `[PROXY]` | Raw Plex proxy through the local Flask app |

---

## 4. Plex API — Datum — full endpoint catalog

All paths are relative to `{{base_url}}` which resolves to
`https://connect.plex.com` from the environment.

### `[AUTH]` — Auth & Diagnostics

| Request | Method | Path | Status |
|---|---|---|---|
| List All Tenants — Auth Canary | GET | `/mdm/v1/tenants` | **Verified** — must return 1 record (Grace) |
| Get Tenant by ID | GET | `/mdm/v1/tenants/{tenant_id_grace}` | **Verified** |

The auth canary has a Postman test script that asserts:

- Status 200
- Response is an array of length 1
- The Grace tenant UUID `58f781ba-1691-4f32-b1db-381cdb21300c` matches

If those tests fail, your auth is broken — **stop and fix the credential
before running anything else**. See `docs/BRIEFING.md` History §1 for why
this matters.

### `[MDM]` — Master Data

| Request | Method | Path | Verified | Notes |
|---|---|---|---|---|
| List Parts — Unfiltered | GET | `/mdm/v1/parts` | ✅ 16,913 records | **19.6 MB unfiltered.** Tools are NOT here. |
| List Parts — Active only | GET | `/mdm/v1/parts?status=Active` | ✅ | Only filter that actually works on this endpoint. 19.6 MB → 7.8 MB. |
| Get Part by ID | GET | `/mdm/v1/parts/:partId` | ✅ | Same fields as list view. |
| List Suppliers | GET | `/mdm/v1/suppliers` | ✅ ~708 KB | `supplierId` is a UUID, not a code. Cached by `validate_library --use-api` for VENDOR_NOT_IN_PLEX. |
| Get Supplier by ID | GET | `/mdm/v1/suppliers/:supplierId` | ⚠️ Pattern unverified | List view IS verified. |
| List Customers | GET | `/mdm/v1/customers` | ✅ ~96 KB | |
| Get Customer by ID | GET | `/mdm/v1/customers/:customerId` | ⚠️ Pattern unverified | |
| List Contacts | GET | `/mdm/v1/contacts` | ✅ ~202 KB | |
| List Buildings | GET | `/mdm/v1/buildings` | ✅ ~1.2 KB | Provides the `buildingCode`/`buildingId` from workcenters. |
| List Employees | GET | `/mdm/v1/employees` | ✅ ~272 KB | |
| List Operations | GET | `/mdm/v1/operations` | ✅ 122 records | Minimal schema — no FK to tools/parts/routings. |
| Get Operation by ID | GET | `/mdm/v1/operations/:operationId` | ✅ | Same fields as list view. |

### `[INV]` — Inventory

| Request | Method | Path | Verified | Notes |
|---|---|---|---|---|
| List Supply Items — All | GET | `/inventory/v1/inventory-definitions/supply-items` | ✅ 2,516 records | Full unfiltered, ~614 KB. |
| List Supply Items — Tools & Inserts | GET | `/inventory/v1/inventory-definitions/supply-items?category=Tools%20%26%20Inserts` | ✅ 1,109 after client filter | **Target endpoint for the Fusion sync.** Has a test script asserting array shape and `category="Tools & Inserts"`. |
| Get Supply Item by ID | GET | `/inventory/v1/inventory-definitions/supply-items/:supplyItemId` | ⚠️ Pattern unverified | |
| List Inventory Locations | GET | `/inventory/v1/inventory-definitions/locations` | ✅ ~279 KB | |

### `[PROD]` — Production

| Request | Method | Path | Verified | Notes |
|---|---|---|---|---|
| List Workcenters | GET | `/production/v1/production-definitions/workcenters` | ✅ 143 records | Includes 21 MILLs. Test script logs the count. |
| Get Workcenter by ID — generic | GET | `/production/v1/production-definitions/workcenters/:workcenterId` | ✅ | |
| Get Workcenter — Brother Speedio 879 | GET | `/production/v1/production-definitions/workcenters/0b6cf62b-2809-4d3d-ab24-369cd0171f62` | ✅ | workcenterCode `879`, FTP `192.168.25.79`. |
| Get Workcenter — Brother Speedio 880 | GET | `/production/v1/production-definitions/workcenters/8e262d5a-3ce8-4597-8726-d2b979b1b6b7` | ✅ | workcenterCode `880`, FTP `192.168.25.80`. |

### `[PURCH]` — Purchasing

| Request | Method | Path | Verified | Notes |
|---|---|---|---|---|
| List Purchase Orders — Unfiltered | GET | `/purchasing/v1/purchase-orders` | ✅ | **44 MB unfiltered. Be careful.** |
| List Purchase Orders — Filtered (template) | GET | `/purchasing/v1/purchase-orders?updatedAfter=...&supplier=...` | ⚠️ Filter effectiveness unverified | Use as a probe template. |

### `[WRITE]` — Mutating requests

| Request | Method | Path | Status | Notes |
|---|---|---|---|---|
| POST Supply Item — Create New | POST | `/inventory/v1/inventory-definitions/supply-items` | **Live writes blocked at proxy** | Body uses `inventoryUnit: "Ea"` and `type: "SUPPLY"` (both confirmed from live production data). Issue #3. |
| PUT Supply Item — Update Existing | PUT | `/inventory/v1/inventory-definitions/supply-items/{supply_item_id}` | **Live writes blocked at proxy** | Same body shape as POST. Issue #3. |
| DELETE Supply Item by ID | DELETE | `/inventory/v1/inventory-definitions/supply-items/:supplyItemId` | **Destructive** | For test cleanup only — Fusion sync should never call this. |
| PUT Workcenter Doc — issue #6 | PUT | `/production/v1/production-definitions/workcenters/:workcenterId` | **Write shape UNVERIFIED** | Placeholder body — do not run against production until issue #6 is closed. |

> ⚠️ **Postman bypasses the local production write guard.** The Flask
> proxy at `/api/plex/raw` refuses POST/PUT/PATCH/DELETE against
> `connect.plex.com` unless `PLEX_ALLOW_WRITES=1` is set in the shell.
> **Postman talks directly to Plex** and has no such guard. Sending a
> request from the `[WRITE]` group **will hit production**. See §6 for the
> safe write workflow, and use the `[PROXY]` requests in the Fusion
> collection if you want the guard to apply.

> ℹ️ **About the `inventoryUnit` and `type` field values.** When the
> Plex POST/PUT supply-item write shape was first added to the
> collection (PR pending in issue #3), `inventoryUnit` was set to `"Ea"`
> and `type` was set to `"SUPPLY"`. Both values were confirmed by
> reading existing rows from `[INV] List Supply Items — Tools & Inserts`.
> A separate observation: existing Plex `supplyItemNumber` values are
> mostly free-text descriptions, **not** vendor part numbers. Expect the
> first sync run to be mostly INSERTs, not UPDATEs.

### `[PROBE]` — Unverified namespaces

| Request | Method | Path | Last Status |
|---|---|---|---|
| tooling/v1/tools | GET | `/tooling/v1/tools` | 404 (2026-04-07) |
| tooling/v1/tool-assemblies | GET | `/tooling/v1/tool-assemblies` | 404 (2026-04-07) |
| manufacturing/v1/routings | GET | `/manufacturing/v1/routings` | 404 (2026-04-07) |
| quality/v1/inspections | GET | `/quality/v1/inspections` | Never tested |
| sales/v1/sales-orders | GET | `/sales/v1/sales-orders` | Never tested |

The `tooling/v1/*` and `manufacturing/v1/*` paths were in the original
pre-Datum API reference and worked for the previous developer on a
different Plex deployment, but the Datum app subscription returns 404 for
all of them. They're kept here so that if the subscription set ever
changes, we can rerun the probes and detect it. See `docs/BRIEFING.md`
History §3.

---

## 5. Fusion 360 Tool Libraries — Datum — full endpoint catalog

All paths are relative to `{{base_url}}` which is set as a **collection
variable** to `http://localhost:5000`. The Flask app must be running:

```powershell
py run_dev.py
```

ADC (Autodesk Desktop Connector) must also be running and synced for any
endpoint that touches the network share.

### `[SRV]` — Server-level

| Request | Method | Path | What it does |
|---|---|---|---|
| Get Server Config | GET | `/api/config` | Returns base URL, environment, `is_production`, `writes_allowed`, tenant ID, key/secret presence. |
| Tenant Diagnostic (via Flask) | GET | `/api/diagnostics/tenant` | Runs `tenant_whoami()` end-to-end through the Flask app. The most thorough auth canary. |

### `[LIB]` — Fusion library reads

| Request | Method | Path | What it does |
|---|---|---|---|
| Get All Libraries | GET | `/api/fusion/libraries` | List all libraries from the ADC share. |
| Upload Library (File) | POST | `/api/fusion/libraries` | Upload a `.json` file (no ADC required). |
| Get Tool Library Stats | GET | `/api/fusion/tools/stats` | Type and vendor distribution across all loaded libraries. |
| Get Consumable Tools (sync candidates) | GET | `/api/fusion/tools/consumable` | Filtered list — excludes holders and probes. **This is the input to `build_supply_item_payload()` (issue #3).** Test asserts no holders or probes in the result. |

> ⚠️ **Known route divergence.** The Postman URLs above were captured
> from an earlier app version. The current Flask routes in `app.py` are
> `/api/fusion/tools` (GET/POST), `/api/fusion/tools/stats`, and
> `/api/fusion/tools/consumables` (plural). If a `[LIB]` request returns
> 404, the route was probably renamed and the collection is stale.
> **Verify against `app.py` before assuming a backend bug.**

### `[VAL]` — Pre-sync validation gate

These hit `/api/fusion/validate` (per `app.py:395`) — the entry point
described in `docs/validate_library_spec.md` (issue #25).

| Request | Method | Query / Body | When to use |
|---|---|---|---|
| Validate Library — Live ADC (default) | GET | `?abort_on_stale=true` | The default sweep — validates every `*.json` in the ADC `CAMTools` directory. |
| Validate Library — Single File (live ADC) | GET | `?file=BROTHER%20SPEEDIO%20ALUMINUM.json` | Iterating on one library without running the full sweep. |
| Validate Library — With Live Plex Supplier Lookup | GET | `?use_api=1` | Most thorough — also resolves vendors against `mdm/v1/suppliers`. Catches typos like `"HARVEY TOOL"` vs `"HARVEY TOOLS"`. **Use this before any actual sync push.** |
| Validate Library — Upload (POST, no ADC) | POST | multipart/form-data | Validate uploaded files without touching the share. Useful when ADC is down or you want to inspect a candidate library before saving it. |

All four return the same `ValidationResult` shape. See
`docs/validate_library_spec.md` for the full rule table and the
`debug_trace` field semantics.

### `[PROXY]` — Raw Plex Proxy

| Request | Method | Path | Notes |
|---|---|---|---|
| Raw Plex Proxy — GET | GET | `/api/plex/raw?path={{plex_path}}` | Always allowed regardless of `PLEX_ALLOW_WRITES`. |
| Raw Plex Proxy — POST | POST | `/api/plex/raw?path={{plex_path}}` | **Blocked by write guard unless `PLEX_ALLOW_WRITES=1`.** |
| Raw Plex Proxy — PUT | PUT | `/api/plex/raw?path={{plex_path}}` | **Blocked by write guard unless `PLEX_ALLOW_WRITES=1`.** |
| Raw Plex Proxy — DELETE | DELETE | `/api/plex/raw?path={{plex_path}}` | **Blocked by write guard unless `PLEX_ALLOW_WRITES=1`.** |

The `plex_path` collection variable defaults to `mdm/v1/tenants` so a
proxy GET out of the box returns the same payload as the Plex collection's
auth canary. Override it per call.

**Use the proxy variants in preference to the direct Plex collection's
`[WRITE]` requests when the production write guard matters.**

---

## 6. Safe write workflow

If you need to actually run a write against Plex:

1. **Run the matching read first.** Use `[INV] Get Supply Item by ID` (or
   the equivalent for whatever you're modifying) to confirm current state
   and capture the UUID.
2. **Set the write guard env var:**
   ```powershell
   $env:PLEX_ALLOW_WRITES = "1"
   py run_dev.py
   ```
   This enables the proxy to forward mutating methods. The Flask UI
   header chip will switch from **READ ONLY** to **WRITES ON** so you
   can see at a glance what mode the server is in.
3. **Decide which path you're sending through:**
   - **Through the proxy (`[PROXY]` requests in Fusion collection):** the
     guard is enforced, so this is the safest option. Use this for all
     normal write testing.
   - **Direct to Plex (`[WRITE]` requests in Plex collection):** bypasses
     the guard. Only use when you specifically need to test the wire
     payload without Flask in the middle.
4. **Send the request.** Watch the response carefully.
5. **Re-run the matching read** to confirm the change took effect.
6. **Unset the guard immediately when you're done:**
   ```powershell
   Remove-Item Env:PLEX_ALLOW_WRITES
   ```
   Or just close the shell. **Do not leave `PLEX_ALLOW_WRITES=1`
   sticking around.**

---

## 7. Adding new requests

When the Datum project discovers a new endpoint or needs a new template,
add it to the appropriate collection following these conventions:

1. **Pick the right collection.** Plex namespaces go in `Plex API — Datum`.
   Anything that hits the local Flask app goes in `Fusion 360 Tool
   Libraries — Datum`.
2. **Use the `[NS]` naming prefix.** Pick from §3 above. If a new
   namespace appears (e.g. `quality/v1/*` starts working), add a new
   prefix and document it in this file.
3. **Use `{{base_url}}` in the URL.** Don't hardcode hosts.
4. **Mark verification status in the description.** Use `**Verified.**`,
   `**UNVERIFIED.**`, `**Returns 404 as of YYYY-MM-DD.**` etc. so the
   next reader knows what to trust.
5. **For writes, default to a placeholder body** with `REPLACE-ME-*`
   sentinel values. Never commit a body containing real product data.
6. **For reads with known response sizes, mention the byte / record
   count** in the description. The `[MDM] List Parts — Unfiltered` row
   above is a good template — knowing it's 19.6 MB up front saves
   someone an unintended download.
7. **Add a Postman test script** if there's a useful invariant to
   assert (e.g. "supplyItemNumber field present", "category equals
   'Tools & Inserts'"). Several existing requests already have these —
   look at `[INV] List Supply Items — Tools & Inserts` and `[AUTH] List
   All Tenants — Auth Canary` for the pattern.

### Tooling — how to add via the Postman MCP

Both collections are managed via the Postman MCP server (`createCollectionRequest`,
`updateCollectionRequest`). Folder creation is **not available on the
minimal MCP tier** — that's why we use the `[NS]` prefix convention
instead of real folders. If the MCP tier is upgraded, the prefix
convention can be replaced with real folders via `createCollectionFolder`.

To add a new request from a Claude Code session:

```
mcp__<postman-mcp>__createCollectionRequest(
  collectionId="75b28dc4-9c73-4e27-90d0-1539777f52ea",
  name="[INV] My New Endpoint",
  method="GET",
  url="{{base_url}}/inventory/v1/inventory-definitions/foo",
  description="..."
)
```

Use the bare collection ID (no `53648712-` prefix) for `createCollectionRequest`,
but the prefixed UID for `getCollection`. (Yes, this is inconsistent —
it's a Postman API quirk, not ours.)

---

## 8. Update protocol

Some changes invalidate parts of these collections. When any of the
following happens, update the collection AND this document in the same
PR:

| Trigger | What to update |
|---|---|
| Plex Datum Consumer Key rotates (~31 days) | Environment `api_key` value (Postman UI). No code change. |
| New Plex namespace verified working | Move from `[PROBE]` to its real namespace prefix; update `docs/Plex_API_Reference.md` access matrix. |
| New Plex namespace probed and confirmed not subscribed | Add to `[PROBE]` group with the date in the description. |
| Brother Speedio FTP IP changes | Update collection variables `workcenter_id_speedio_879` / `workcenter_id_speedio_880` AND `docs/BRIEFING.md` machine table. |
| `app.py` route renamed | Update the matching `[LIB]` / `[VAL]` / `[PROXY]` request URL. The current Postman URLs may already be stale — see the warning under §5 `[LIB]`. |
| New `[WRITE]` shape verified | Replace the `_TBD` / `REPLACE-ME` sentinel values with the verified body and mark `**Verified.**` in the description. |

---

## 9. References

- `docs/BRIEFING.md` — primary project context
- `docs/Plex_API_Reference.md` — verified endpoint matrix and 401-vs-404 reading guide
- `docs/Fusion360_Tool_Library_Reference.md` — Fusion JSON schema
- `docs/validate_library_spec.md` — pre-sync validation gate spec
- `app.py` — local Flask routes that the Fusion collection hits
- `plex_api.py` — `PlexClient` and the extraction helpers
- GitHub issue #3 — supply-item upsert (drives the `[WRITE]` requests)
- GitHub issue #6 — workcenter doc push (drives the `[WRITE] PUT Workcenter Doc` placeholder)
- GitHub issue #12 — key rotation cadence
- GitHub issue #25 — `validate_library.py` implementation (drives the `[VAL]` requests)
