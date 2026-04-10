# Plex Classic Web Services — Access Request

**From:** Shane Waid, Grace Engineering
**Date:** April 10, 2026
**Project:** Datum — Fusion 360 Tool Library Sync
**Repo:** https://github.com/grace-shane/datum

---

## What we're building

Datum is an internal automation that syncs our Autodesk Fusion 360 CAM
tool library data into Plex. Fusion 360 JSON files on our network share
are the source of truth for cutting tools — the script reads them and
pushes tooling data to Plex nightly so tool information stays current
across programming, purchasing, and the shop floor.

## What works today

We have a working integration with the **Plex Connect REST API**
(`connect.plex.com`) using a Consumer Key from the Developer Portal.
The Datum app can:

- Authenticate against Grace Engineering's production tenant
- Read supply items, parts, suppliers, workcenters, operations, jobs,
  and 10+ other endpoints
- Write to `inventory/v1/inventory-definitions/supply-items` (our tool
  master list — 1,109 existing records)

The tool identity sync (name, vendor part number, description, category)
is ready to go live via the REST API.

## What we can't do with the REST API

After a thorough investigation of every available REST endpoint (36
requests across 8 namespace groups, verified April 9-10, 2026), we've
confirmed that the Connect REST API **does not expose**:

| Capability | REST API status | Why we need it |
|---|---|---|
| **Part Operations** | `mdm/v1/operations` has 4 fields, no FK to parts or tools | Link tools to the operations they perform |
| **Tool-to-Operation assignments** | No endpoint exists | Operators need to see which tools are required for each op |
| **Routing / operation sequences** | `manufacturing/v1/routings` returns 404 | Define the order of operations on a part |
| **DCS / Document attachments** | `documents/v1/*` and `dcs/v1/*` return 404 | Attach tool setup sheets to Part Operations |
| **Workcenter documents** | `workcenters/{id}/documents` returns 404 | Push tool lists to machine setup docs |
| **Supply item cross-references** | `supply-items` has 7 identity fields only — no supplier FK, no location, no operation link | Connect tools to vendors, locations, machines |

These relationships **do exist in Plex** — we can see them in the
Classic UI at `plexonline.com` (Control Panel, Part Operation
Attachments, Workcenter views). They're just not available through the
Connect REST API.

## What we're requesting: Classic Web Services access

The **Plex Web Services** endpoint at
`plexonline.com/Modules/Xmla/XmlDataSource.asmx` can access the full
Classic schema via Data Sources. This would let Datum:

1. **Read Part Operations** — which operations run on which parts, at
   which workcenters
2. **Assign tools to operations** — so the shop floor sees the right
   tools for each job
3. **Upload setup sheet attachments** via the DCS (Document Control
   System) — the "Part Operation Attachments" screen that's currently
   empty for our milling operations
4. **Push tool lists to workcenter documents** — so machine operators
   on the Brother Speedios (879, 880) have current tool data

### What we found so far (April 10, 2026)

We tested the Classic Web Services endpoint from multiple angles:

1. **Unauthenticated GET** to
   `https://www.plexonline.com/Modules/Xmla/XmlDataSource.asmx?WSDL`
   — returned the Plex login page (IAM Login button only, no
   username/password form). Confirms the endpoint path exists and
   Plex Classic now authenticates through Rockwell IAM.

2. **Authenticated GET** (logged into Plex via IAM in the same browser
   session, then navigated to the WSDL URL in the same tab) — returned
   a **system error page**: *"A system error has occurred on this page.
   Plex personnel have been automatically notified and are working on
   the problem."* The Plex header bar rendered (session is valid), but
   the ASMX endpoint itself threw a server-side exception.

3. **Session-prefixed URL** — Classic Plex URLs include a per-login
   session GUID (e.g. `plexonline.com/0daa8ab4-4c2e-.../Modules/...`).
   We tried `plexonline.com/{session-guid}/Modules/Xmla/XmlDataSource.asmx?WSDL`
   but navigating outside the Classic UI window forces a re-login, which
   generates a new session GUID. The ASMX URL was stripped during the
   redirect and never reached.

4. **Classic UI navigation** — The Plex Classic window locks out the
   address bar (kiosk-style). There is no way to navigate to the ASMX
   endpoint from within the Classic session.

**Conclusion:** The ASMX endpoint exists but is non-functional for
Grace Engineering's authenticated user. This is either a subscription
issue, a deprecation, or a configuration that needs Plex support to
enable.

### What we need

| Item | Details |
|---|---|
| **Is Classic Web Services available to us?** | The ASMX endpoint at `plexonline.com/Modules/Xmla/XmlDataSource.asmx` returns a system error when accessed by an authenticated Grace Engineering user. Is this feature enabled for our subscription? If not, what does it take to enable it? |
| **Correct endpoint URL** | If the ASMX path has moved during the IAM migration, what is the current URL for programmatic Data Source access? |
| **Programmatic auth method** | How does a script (not a browser) authenticate to Classic Web Services now that IAM SSO is required? Is there an OAuth2 client credentials flow, an API key, or a service account token? This is separate from the Developer Portal Consumer Key we already use for the REST API at `connect.plex.com`. |
| **Company Code** | Grace Engineering's numeric Company Code in Classic Plex (not the tenant UUID `58f781ba-...` used by the REST API). This may be required as a parameter in SOAP calls. |
| **Data Source inventory** | If Web Services is available (or can be enabled), we need a list of Data Sources related to: Part Operations, Tool Assignments, Workcenter Assignments, and DCS/Attachments. If custom Data Sources need to be created, we can specify the exact fields we need. |

### What we will NOT do

- We will not modify any existing Part, Operation, or Workcenter records
  without explicit approval
- All writes will go through a dry-run validation step first
- The integration already has a production write guard that blocks
  mutations by default (`PLEX_ALLOW_WRITES` must be explicitly enabled)
- Credentials will be stored in environment variables, never committed
  to source control

## Architecture overview

```
Fusion 360 JSON (network share, nightly)
        |
        v
  validate_library.py       <-- pre-sync validation gate
        |
        v
  sync_supabase.py          <-- full record upsert (geometry, vendor, presets)
        |
        |---> Supabase (datum)           <-- enriched tool database + React UI
        |
        |---> Plex REST API              <-- tool identity (supply-items)
        |     connect.plex.com               WORKS TODAY
        |
        |---> Plex Classic Web Services  <-- tool assignments, attachments, routing
              plexonline.com                 NEED ACCESS
```

## Contact

Shane Waid
shanewaid@graceeng.com
Grace Engineering — CNC Programming
