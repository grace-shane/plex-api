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

## 3. Discovered Endpoints & Subscription Status

The target architecture requires pushing Fusion 360 data to the Tooling/Workcenter endpoints. Initial discovery revealed that certain API collections require activation by IT.

### ✅ Working Endpoints

| Collection | Endpoint | Purpose |
|---|---|---|
| Master Data | `mdm/v1/parts` | Returns master part records. Confirmed working. |
| Master Data | `mdm/v1/suppliers` | Returns supplier UUIDs (e.g., MSC Industrial). |
| Purchasing | `purchasing/v1/purchase-orders` | Returns full PO headers (e.g., tooling orders from MSC). |
| Production | `production/v1/control/workcenters` | Discovered on Dev Portal. Replaces old 404 manufacturing endpoint. |

### API Product Subscription Model

> [!IMPORTANT]
> Plex requires each Consumer Key to be **explicitly subscribed** to API products in the developer portal before any URI under that product is reachable. An unsubscribed product returns **HTTP 401 `REQUEST_NOT_AUTHENTICATED`** at the gateway, *not* 403 — same wire response as bad credentials, which makes diagnosing this without an access matrix surprisingly hard.
>
> Verified empirically against the Grace `Fusion2Plex` app (April 2026): `tooling/v1/*` returns `404 RESOURCE_NOT_FOUND` (auth ok, just no resource at that path), while unsubscribed products like `mdm/v1/*` return `401 REQUEST_NOT_AUTHENTICATED`. The 401-vs-404 distinction is the only way to tell from outside the portal whether a product is enabled.

#### Current access matrix for the `Fusion2Plex` app

| Path                                  | Status | Subscribed? |
|---------------------------------------|--------|-------------|
| `mdm/v1/tenants`                      | 401    | ❌ Common APIs not approved |
| `mdm/v1/parts`                        | 401    | ❌ Common APIs not approved |
| `mdm/v1/suppliers`                    | 401    | ❌ Common APIs not approved |
| `purchasing/v1/purchase-orders`       | 401    | ❌ Purchasing not approved |
| `production/v1/control/workcenters`   | 401    | ❌ Production Control not approved |
| `manufacturing/v1/operations`         | 404    | ✅ Standalone MES approved |
| `tooling/v1/tools`                    | 404    | ✅ Tooling approved |
| `tooling/v1/tool-assemblies`          | 404    | ✅ Tooling approved |
| `tooling/v1/tool-inventory`           | 404    | ✅ Tooling approved |

**Pending IT action**: ask Courtney to also approve the `Fusion2Plex` app for **Common APIs**, **Purchasing**, and **Production Control** so we can read parts/suppliers, look up POs, and push workcenter docs.

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
