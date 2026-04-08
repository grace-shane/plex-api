# Grace Engineering: Plex Connect REST API Reference

## 1. Overview

This reference document synthesizes the discoveries from preliminary API testing and aligns them with the **Fusion 360 Tool Library Synchronization** architectural goals. It serves as the master guide for developers interacting with the Grace Engineering Plex instance (`plexonline.com`).

*Note: Grace Engineering runs Plex Classic, MES+ enabled, supporting Prime Archery and Montana Rifle Company.*

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
> (production) on **2026-04-07** with the `Fusion2Plex` Consumer Key on the
> Grace tenant (`58f781ba-1691-4f32-b1db-381cdb21300c`). Reproduce by
> running the diagnostic at `/api/diagnostics/tenant` from the local UI.

### URL pattern convention

Plex uses two URL shapes for read endpoints:

1. **Master data — flat**: `<namespace>/v1/<resource>`
   Example: `mdm/v1/parts`, `mdm/v1/suppliers`, `mdm/v1/operations`
2. **Definitions — nested**: `<namespace>/v1/<namespace>-definitions/<resource>`
   Example: `production/v1/production-definitions/workcenters`,
   `inventory/v1/inventory-definitions/supply-items`,
   `inventory/v1/inventory-definitions/locations`

Both patterns are used in production. The bare `<namespace>/v1` root
typically returns 404 (no resource at the root); the actual data lives
one level deeper.

### Verified working endpoints

| Status | Path | Records | Notes |
|---|---|---|---|
| **200** | `mdm/v1/tenants` | 1 | Single tenant: Grace |
| **200** | `mdm/v1/parts` | 16,913 | Finished products + raw materials. **No tools here** — the `type` field has only `Finished Good`, `Raw Material`, `Sub Assembly` |
| **200** | `mdm/v1/parts/{id}` | — | Per-record GET works. Same fields as the list view (no hidden detail). |
| **200** | `mdm/v1/suppliers` | — | 708 KB |
| **200** | `mdm/v1/customers` | — | 96 KB |
| **200** | `mdm/v1/contacts` | — | 202 KB |
| **200** | `mdm/v1/buildings` | — | 1.2 KB |
| **200** | `mdm/v1/employees` | — | 272 KB |
| **200** | `mdm/v1/operations` | 122 | Minimal: `code, id, inventoryType, type`. No FK to tools/parts/routings. |
| **200** | `mdm/v1/operations/{id}` | — | Per-record GET works. Same fields as list. |
| **200** | `purchasing/v1/purchase-orders` | — | 44 MB unfiltered, full PO history |
| **200** | `production/v1/production-definitions/workcenters` | 143 | All workcenters including the 21 MILLs (codes 879, 880 = Brother Speedio FTP IPs) |
| **200** | `production/v1/production-definitions/workcenters/{id}` | — | Fields: `buildingCode, buildingId, ipAddress, name, plcName, productionLineId, tankSilo, workcenterCode, workcenterGroup, workcenterId, workcenterType` |
| **200** | `inventory/v1/inventory-definitions/supply-items` | 2,516 | **TOOLS LIVE HERE.** Filter to `category="Tools & Inserts"` for the 1,109 cutting tools and inserts. Schema: `category, description, group, id, inventoryUnit, supplyItemNumber, type` |
| **200** | `inventory/v1/inventory-definitions/locations` | — | 279 KB |

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

While waiting for the Tooling APIs to be activated, data can be managed in two ways:

1. **REST API Automation (Target State)**
   - A scheduled script parses the network share `BROTHER SPEEDIO ALUMINUM.json` library.
   - Extracts `product-id`, `vendor`, and geometry.
   - Pushes payloads to `tooling/v1/tool-assemblies` to update the master inventory list.
   - Pushes payload to `production/v1/control/workcenters` utilizing the `post-process.number` to ensure correct turret/pocket placement.

2. **CSV Upload System (Interim State)**
   - Without API access, engineering relies on bulk CSV uploads.
   - Sequence: **Tool Assembly Upload** ➔ **Tool Inventory Upload** ➔ **Tool BOM Upload** ➔ **Routing Upload**.
   - Ensure the *Tool Assembly Type* picklist exists in Plex before attempting uploads.

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
