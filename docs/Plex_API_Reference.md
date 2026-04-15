# Grace Engineering: Plex Connect REST API Reference

## 1. Overview

This reference document synthesizes the discoveries from preliminary API testing and aligns them with the **Fusion 360 Tool Library Synchronization** architectural goals. It serves as the master guide for developers interacting with the Grace Engineering Plex instance via the `connect.plex.com` REST API gateway.

*Note: Grace Engineering runs Plex Classic, MES+ enabled, supporting Prime Archery and Montana Rifle Company.*

> **Companion: Postman collections.** Every endpoint documented in
> §3 below has a matching request in the **Plex API — Datum** Postman
> collection (see [`Postman_Collections.md`](./Postman_Collections.md)
> for the full catalog and naming convention). Postman is the
> recommended way to explore endpoints by hand; this file is the
> authoritative reference for what each endpoint actually returns.

---

## 2. Authentication & Headers

All Plex APIs are routed through the developer portal. There is no session token or OAuth flow; a static subscription key is passed via request headers.

- **Developer Portal**: `https://developers.plex.com/`
- **Rate Limit**: 200 API calls per minute across all endpoints.
- **Base URL**: `https://connect.plex.com` (Production) / `https://test.connect.plex.com` (Test)

**Required Header:**

```http
X-Plex-Connect-Api-Key: <your_consumer_key>
```

> [!WARNING]
> The API key **must** be in the Request Headers. Placing it as a URL parameter will result in a 401 Unauthorized error.

---

## 3. Verified Endpoints & Access Matrix

> [!IMPORTANT]
> All values below were verified empirically against `connect.plex.com`
> (production) on the Grace tenant
> (`58f781ba-1691-4f32-b1db-381cdb21300c`). Reproduce by running the
> diagnostic at `/api/diagnostics/tenant` from the local UI, or by
> running the Postman `[AUTH] List All Tenants — Auth Canary` request.
>
> **Verification history:**
>
> - **2026-04-07** — first full sweep with the `Fusion2Plex` Consumer
>   Key. Discovered that tools live at `inventory/v1/inventory-definitions/supply-items`
>   (not `tooling/v1/tools` as earlier docs claimed).
> - **2026-04-09** — re-verified with the rotated `Datum` Consumer Key
>   after the project rename. 23-request connectivity sweep + 6-request
>   Get-by-ID chain test. Captured full field schemas + discovered that
>   **supply-items have no foreign key to suppliers, parts, locations,
>   or any other resource** (see §3.5 below). Also discovered the
>   `scheduling/v1/jobs` endpoint (new — not in any earlier doc).

### URL pattern convention

Plex uses two URL shapes for read endpoints:

1. **Master data — flat**: `<namespace>/v1/<resource>`
   Example: `mdm/v1/parts`, `mdm/v1/suppliers`, `mdm/v1/operations`
2. **Definitions — nested**: `<namespace>/v1/<namespace>-definitions/<resource>`
   Example: `production/v1/production-definitions/workcenters`,
   `inventory/v1/inventory-definitions/supply-items`,
   `inventory/v1/inventory-definitions/locations`
3. **Flat with sub-namespace** (new 2026-04-09): `<namespace>/v1/<resource>`
   — the `scheduling/v1/jobs` endpoint uses the first pattern but lives
   under a namespace that wasn't previously catalogued.

Both patterns are used in production. The bare `<namespace>/v1` root
typically returns 404 (no resource at the root); the actual data lives
one level deeper.

### Verified working endpoints

Record counts are as of **2026-04-09** unless noted. Schemas captured
2026-04-09 by the Get-by-ID chain test.

| Status | Path | Records | Schema / Notes |
|---|---|---:|---|
| **200** | `mdm/v1/tenants` | 1 | Single tenant: Grace. Auth canary — run first in any session. |
| **200** | `mdm/v1/parts` | **16,921** | +8 since 2026-04-07. 19.6 MB unfiltered. Tools are **NOT** here. Fields: `buildingCode, createdById, createdDate, description, group, id, leadTimeDays, modifiedById, modifiedDate, name, note, number, productType, revision, source, status, type`. `type` ∈ {`Finished Good`, `Raw Material`, `Sub Assembly`}. |
| **200** | `mdm/v1/parts?status=Active` | — | 7.8 MB — only verified working filter. All other query params silently ignored. |
| **200** | `mdm/v1/parts/{id}` | — | Same 17 fields as list view — no hidden detail. |
| **200** | `mdm/v1/suppliers` | **1,575** | 709 KB. Fields: `category, code, contactNote, createdById, createdDate, id, language, modifiedById, modifiedDate, name, note, oldCode, parentSupplierId, status, type, webAddress`. `parentSupplierId` is a self-referential FK. First record is a `Carrier` — list mixes material suppliers, carriers, etc. |
| **200** | `mdm/v1/suppliers/{id}` | — | Same 16 fields as list view. |
| **200** | `mdm/v1/customers` | **109** | 96 KB. 35 fields. FKs to employees (`assignedToId`, `assignedTo2Id`, `assignedTo3Id`), contacts (`contactResourceId`), suppliers (`defaultCarrierIds` array, `supplierCode`). |
| **200** | `mdm/v1/customers/{id}` | — | Same 35 fields as list view. |
| **200** | `mdm/v1/contacts` | **299** | 202 KB. |
| **200** | `mdm/v1/buildings` | **4** | 1.2 KB. Referenced from workcenters via `buildingCode`/`buildingId`. |
| **200** | `mdm/v1/employees` | **641** | 272 KB. UUIDs appear as `createdById`/`modifiedById` across essentially every other resource. |
| **200** | `mdm/v1/operations` | **122** | Minimal 4-field schema: `code, id, inventoryType, type`. **No FK to tools, parts, or routings** — the reason issue #5 is blocked. |
| **200** | `mdm/v1/operations/{id}` | — | Same 4 fields as list view. |
| **200** | `inventory/v1/inventory-definitions/supply-items` | **2,516** | 614 KB. Full unfiltered. |
| **200** | `inventory/v1/inventory-definitions/supply-items?category=Tools%20%26%20Inserts` | **1,109** | **TOOLS LIVE HERE.** Fields: `category, description, group, id, inventoryUnit, supplyItemNumber, type`. **No supplier FK. No cross-references of any kind.** See §3.5. |
| **200** | `inventory/v1/inventory-definitions/supply-items/{id}` | — | Same 7 fields as list view. |
| **200** | `inventory/v1/inventory-definitions/locations` | **1,270** | 279 KB. Not cross-referenced from supply-item. |
| **200** | `production/v1/production-definitions/workcenters` | **143** | 21 MILLs. ⚠️ **Primary key is `workcenterId`, not `id`.** Fields: `buildingCode, buildingId, ipAddress, name, plcName, productionLineId, tankSilo, workcenterCode, workcenterGroup, workcenterId, workcenterType`. |
| **200** | `production/v1/production-definitions/workcenters/{id}` | — | Same 11 fields as list view. |
| **200** | `purchasing/v1/purchase-orders` | — | **44.2 MB** unfiltered. Full PO history. `?updatedAfter=` filter confirmed as a silent no-op on 2026-04-09 (byte-identical response). |
| **200** | `inventory/v1-beta1/inventory-history/item-adjustments?ItemId=<uuid>&StartDate=<ISO>&EndDate=<ISO>` | varies | **Supply-item adjustment log.** 31/1,109 tools have non-empty history (2026-04-15). Fields: `adjustmentDate, itemId, itemNo, location, locationId, quantity, transactionType`. Summing `quantity` (already signed) gives running balance. **Dates MUST be full ISO with `Z`** (plain YYYY-MM-DD → 400 ARGUMENT_INVALID). See §3.6. |
| **200** | `inventory/v1/inventory-tracking/containers` | **10,676** | On-hand for parts (RAW/WIP/FG). Fields include `quantity, partId, partNo, location, locationId, serialNo, lotId, inventoryType`. Disjoint from supply-items (tools). |
| **200** | `inventory/v1/inventory-history/container-adjustments?BeginDate=<ISO>&EndDate=<ISO>` | **6,298** | Per-container adjustment log. Fields: `adjustmentCode, adjustmentDate, location, partId, partNumber, quantity, serialNo, ...`. |
| **200** | `scheduling/v1/jobs` | TBD | **NEW — discovered 2026-04-09.** Returns 200 but **15.8s response time**, so the body is large. Schema, record count, and whether it carries tool/operation/workcenter FKs all TBD. Worth a deep-dive as follow-up to issue #5 (routing/operation linkage) — if jobs link to tools, we get the missing operation→tool mapping for free. |

### Probed — returned 404 (not subscribed or doesn't exist)

All of the following were probed on 2026-04-09 and returned `404 RESOURCE_NOT_FOUND`. Kept here so future sessions know they've been checked and don't waste a cycle re-testing them blindly. Re-probe periodically to detect subscription changes.

| Path | First checked | Notes |
|---|---|---|
| `tooling/v1/tools` | 2026-04-07 (re-check 2026-04-09) | In original pre-Datum docs. Blocks #4. |
| `tooling/v1/tool-assemblies` | 2026-04-07 (re-check 2026-04-09) | Blocks #4. |
| `tooling/v1/assemblies` | 2026-04-09 | Alternate spelling, also 404. |
| `manufacturing/v1/routings` | 2026-04-07 (re-check 2026-04-09) | Blocks #5. |
| `quality/v1/inspections` | 2026-04-09 | Speculative probe. |
| `sales/v1/sales-orders` | 2026-04-09 | Speculative probe. |
| `inventory/v1/on-hand` | 2026-04-09 | Would have given tool stock levels. |
| `inventory/v1/containers` | 2026-04-09 | |
| `inventory/v1/inventory-definitions/container-types` | 2026-04-09 | |
| `mdm/v1/parts-buckets` | 2026-04-09 | |
| `production/v1/production-definitions/assets` | 2026-04-09 | |
| `production/v1/production-definitions/assemblies` | 2026-04-09 | |
| `purchasing/v1/purchase-orders-lines` | 2026-04-09 | Would have given supply-item → PO → supplier linkage. |

### §3.5 — Supply-item cross-references: the critical finding

**The `inventory/v1/inventory-definitions/supply-items` resource is identity-only.** Its 7 fields are:

- `category` (string, e.g. `"Tools & Inserts"`)
- `description` (free-text, human-readable)
- `group` (string, e.g. `"Machining"`)
- `id` (UUID — Plex primary key)
- `inventoryUnit` (string, e.g. `"Ea"`)
- `supplyItemNumber` (string — see below)
- `type` (string, e.g. `"SUPPLY"`)

**There is no field on this resource that references another resource.** Specifically:

- No `supplierId` or `preferredSupplierId` — **you cannot derive the vendor for a tool from Plex alone.**
- No `locationId` or `warehouseId` — you cannot ask "where is this tool right now?" via this endpoint.
- No `partId` — supply-items are not linked to `mdm/v1/parts`.
- No `workcenterId` — supply-items are not assigned to machines.
- No `operationId` — supply-items are not linked to operations.

**Implication for Datum sync architecture:** vendor/supplier data for tools MUST live in Supabase as the source of truth. The Fusion JSON carries `vendor` and `product-id`, those get written to the `tools` table in Supabase, and when `build_supply_item_payload()` (issue #3) constructs the Plex POST body it uses only the 7 identity fields. Plex never learns who the vendor is, because Plex doesn't model that relationship for tools.

This finding also kills the hypothesis that PO lines could be used as a back-channel for the vendor link — `purchasing/v1/purchase-orders-lines` returned 404 on 2026-04-09.

**Sample `supplyItemNumber` values captured 2026-04-09** (confirming the
"legacy free-text descriptions, not vendor part numbers" observation
from the 2026-04-08 Decision Log):

- `"Insert  HM90 AXCR 150508 IC28"`
- `"Screw Indexable Face Mill F75"`
- `"Tap #8-32 H3 Spiral Point"`

Fusion will insert clean vendor part numbers like `"990910"`, so expect essentially zero collision with existing Plex records on first sync.

### §3.6 — Supply-item `item-adjustments` and the `transactionType` sign table

Endpoint: `GET inventory/v1-beta1/inventory-history/item-adjustments`
Required params: `ItemId` (supply-item UUID), `StartDate`, `EndDate` (full ISO with `Z`).

**Key finding (probed 2026-04-15 across all 1,109 `category="Tools & Inserts"` supply-items):** the `quantity` field is delivered **pre-signed** — positive for additions, negative for removals. You do NOT need to apply sign based on `transactionType`. Sum `quantity` directly to get the running balance.

The enumerated `transactionType` values across 2,005 real records:

| transactionType | records | qty_min | qty_max | quantity sign | interpretation |
|---|---:|---:|---:|---|---|
| `PO Receipt` | 1,479 | 1.0 | 100.0 | always `+` | vendor received into stock |
| `Checkout` | 326 | -75.0 | -1.0 | always `-` | pulled from crib to production |
| `Correction` | 125 | -6433.0 | 78.0 | either | manual count adjustment, signed |
| `Check In` | 74 | 1.0 | 103.0 | always `+` | returned to crib / physical recount up |
| `null` | 1 | 19.0 | 19.0 | — | one record with missing `transactionType`; treat as data-quality issue, still sum the qty |

**Implementation rule:** `running_balance = sum(r.quantity for r in records)`. No sign flip, no lookup table. If future records introduce a new `transactionType`, the pre-signed `quantity` contract should still hold — but the sync script should log any unknown `transactionType` values it encounters as a warning for review.

Of Grace's 1,109 tools, **31 (2.8%) have non-empty adjustment history.** The remaining 1,078 have never been tracked in Plex inventory at all — a data-quality finding, not an API limitation. Datum distinguishes this in `tools.qty_tracked`: TRUE = ≥1 record, FALSE = linked but Plex has no history (display as "not tracked"), NULL = not yet checked by sync.

### Where tooling data actually lives

**Cutting tools and inserts are `inventory/v1/inventory-definitions/supply-items`
records** with `category="Tools & Inserts"`. This is NOT what the original
`Plex_API_Reference.md` claimed — that file referenced `tooling/v1/tools` and
`mdm/v1/parts`, neither of which works for tooling on this app.

Verified empirically: 1,109 tools/inserts already exist in Plex Grace, mostly
in `group="Machining"` (1,039) and `group="Tool Room"` (104). The supply-item
schema is minimal — it tracks vendor part number identity, not geometry, so
the Fusion 360 sync will:

1. Read existing tools via `GET inventory/v1/inventory-definitions/supply-items`
2. Filter client-side or via query string to `category=Tools & Inserts`
3. Match by `supplyItemNumber` (vendor part number, e.g. Harvey Tool's `990910`)
4. Create new supply-items for Fusion tools that don't exist
5. Update existing ones

Geometry (DC, OAL, NOF, holder details) stays in Fusion as the source of
truth — Plex stores only the identity, description, and group/category.

### Workcenter ↔ machine mapping (verified)

The 21 MILL workcenter records map directly to physical Brother Speedio
machines via the `workcenterCode` field (which equals the machine number /
DNC IP last octet):

- Workcenter `879` → Brother Speedio 879 → FTP `192.168.25.79`
- Workcenter `880` → Brother Speedio 880 → FTP `192.168.25.80`

The full mill list: 814, 825, 827, 830, 834, 835, 836, 837, 839, 840, 841,
845, 848, 851, 865, 873, 879, 880, DEFLECT.

### Reading Plex's status codes

- **200** — success.
- **401 `REQUEST_NOT_AUTHENTICATED`** — bad credentials OR a recognized
  namespace your app isn't subscribed to. Same wire response, indistinguishable
  from outside.
- **404 `RESOURCE_NOT_FOUND`** — Plex's gateway has no route at that path.
  Could mean unknown URL OR subscribed-but-no-resource. Same wire response.
- **400** — Plex recognizes the path but the request is malformed (often
  treats a string as a UUID parameter and fails to parse).
- **403** — **never observed in practice on this app**.

The 401-vs-404 distinction is **not** a clean signal on its own. The only
reliable way to disambiguate is to compare against a known-good client
(Insomnia "Generate Code" output is the gold standard).

### No server-side pagination

`mdm/v1/parts` and `purchasing/v1/purchase-orders` **silently ignore** the
`limit` query parameter. We learned this empirically — `?limit=1` returned
19.6 MB and 44 MB respectively. The only filter we've verified actually
works is `?status=Active` on `mdm/v1/parts` (reduces 19.6 MB → 7.8 MB).
The `typeName` filter is also silently ignored. **Always assume `limit`
does nothing and use real filters or accept the full DB pull.**

---

## 4. Current Tooling Data Flow (Fusion 360 to Plex)

Data flows from Fusion 360 to Plex via the REST API. The `tooling/v1/*` path namespace referenced in earlier drafts of this document does NOT exist on the Fusion2Plex app — see Section 3 and [`BRIEFING.md` History §3](./BRIEFING.md) for the postmortem.

1. **REST API Automation (Target State)**
   - A scheduled script parses the network share Fusion 360 tool library JSON files.
   - Extracts `product-id`, `vendor`, `description`, and `geometry`.
   - Pre-sync validation gate runs via `validate_library.py` (spec only, see [`validate_library_spec.md`](./validate_library_spec.md), implementation issue #25).
   - Pushes payloads to `inventory/v1/inventory-definitions/supply-items` with `category="Tools & Inserts"`, `group="Machining"`, and `supplyItemNumber=<vendor part-id>` as the dedup key. Read path verified (1,109 records); write logic in progress (issue #3).
   - Pushes payloads to `production/v1/production-definitions/workcenters/{id}` utilizing `post-process.number` for turret/pocket placement. Read path verified; write shape TBD (issue #6).

2. **CSV Upload System (Historical Fallback)**
   - Prior to API access being verified, engineering used bulk CSV uploads.
   - Sequence: **Tool Assembly Upload** ➔ **Tool Inventory Upload** ➔ **Tool BOM Upload** ➔ **Routing Upload**.
   - The supply-items REST path above is the target state and supersedes this workflow once issues #3, #6, and #7 land.

---

## 5. Machine Integration (DNC Overview)

Outside of the Plex database, NC programs and tool alignments require pushing to physical machines on the floor:

- **Brother Speedio (879/880)**: Native FTP integration (`192.168.25.79`, `192.168.25.80`). Scripts can push programs directly via standard FTP.
- **Citizen / Tsugami**: Connected via Moxa NPort 5150/5250 converting RS-232 to TCP/IP.
- **Haas VMCs**: Native Ethernet on Sigma 5 boards.

*Plex DCS acts as the source-of-truth for NC programs natively; DNC protocols transfer them to machines just-in-time.*

---

## 6. Known Issues & Development Gotchas

- **Supplier UUIDs**: The `supplierId` in API responses is a UUID, NOT the supplier code (i.e. MSC is not `MSC001`). You must query the MDM endpoint to resolve vendor names to their internal UUIDs.
- **PO Filters**: Filtering by `type` strings containing spaces (`MRO SUPPLIES`) requires proper URL encoding (`%20`). Undetected encoding issues will result in zero-record responses rather than explicit HTTP errors.
- **PowerShell Curl**: Do not use the alias `curl` in PowerShell scripts. Use `Invoke-RestMethod` to guarantee proper header passage and JSON native ingestion.
