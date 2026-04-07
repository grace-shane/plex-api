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

### Current access matrix

| Status | Path                                    | Notes                                                |
|--------|------------------------------------------|------------------------------------------------------|
| **200**| `mdm/v1/tenants`                         | Returns tenant list (62 B). Used by `tenant_whoami`. |
| **200**| `mdm/v1/parts?limit=1`                   | **19.6 MB** — `limit` IGNORED. Filter or pay the bill. |
| **200**| `mdm/v1/suppliers?limit=1`               | 708 KB — same no-pagination behaviour.               |
| **200**| `purchasing/v1/purchase-orders?limit=1`  | **44 MB** — full PO history.                         |
| 404    | `tooling/v1/tools`                       | Path doesn't exist on this app's product set.        |
| 404    | `tooling/v1/tool-assemblies`             | Same.                                                |
| 404    | `tooling/v1/tool-inventory`              | Same.                                                |
| 404    | `manufacturing/v1/operations`            | Same.                                                |
| 404    | `production/v1/control/workcenters`      | Same. Issues #4, #5, #6 are blocked on finding the right URLs. |

### Reading Plex's status codes

- **200** — success.
- **401 `REQUEST_NOT_AUTHENTICATED`** — bad credentials OR a recognized
  namespace your app isn't subscribed to. Same wire response, indistinguishable
  from outside.
- **404 `RESOURCE_NOT_FOUND`** — Plex's gateway has no route at that path.
  Could mean unknown URL OR subscribed-but-no-resource. Same wire response.
- **403** — **never observed in practice on this app**, despite earlier docs
  claiming we were getting 403 from `tooling/v1/*`. Treat any 403 as
  unexpected.

The 401-vs-404 distinction is **not** a clean signal. The only reliable way
to disambiguate is to compare against a known-good client (Insomnia "Generate
Code" output is the gold standard).

### No server-side pagination

`mdm/v1/parts` and `purchasing/v1/purchase-orders` **silently ignore** the
`limit` query parameter. We learned this empirically — `?limit=1` returned
19.6 MB and 44 MB respectively. Always use a real filter (`status=Active`,
date range, etc.) before calling these endpoints.

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
