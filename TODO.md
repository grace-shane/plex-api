# Project Roadmap: Fusion 360 to Plex Sync

This document outlines the step-by-step implementation plan for the Autodesk Fusion 360 tool library to Plex Manufacturing Cloud synchronization project.

> **Live tracking:** All unchecked items below are mirrored as GitHub Issues.
> See <https://github.com/grace-shane/plex-api/issues> for current status, comments, and blockers.

## Phase 1: API Discovery & Authentication

- [x] Set up Postman and discover relevant Plex API endpoints.
- [x] Obtain API authentication credentials (Client ID/Secret or API Key) for the Plex environment.
- [x] Successfully authenticate via a test script (`plex_api.py`).
- [x] **ACTION ITEM**: Regenerate API Key in the Developer Portal (Previous key was exposed in `.docx` git history).

## Phase 2: Local Data Reading & Parsing

- [x] Identify the permanent network share path for the Fusion 360 tool library JSON files.
- [x] Write a script to consistently read the JSON files from the network share (Fusion files are the absolute Source of Truth).
- [x] Parse the Fusion 360 JSON schema to identify key tooling attributes (Completed in `Fusion360_Tool_Library_Reference.md`).

## Phase 3: Plex API Source-of-Truth Implementation

- [ ] Implement API call to retrieve current tooling inventory — `inventory/v1/inventory-definitions/supply-items` returns 2,516 records, of which 1,109 are `category="Tools & Inserts"`. Filter client-side. → [#2](https://github.com/grace-shane/plex-api/issues/2)
- [ ] Implement API call to upsert supply-items — `build_supply_item_payload(fusion_tool)` writes to `inventory/v1/inventory-definitions/supply-items` with `supplyItemNumber=<vendor part-id>`. Drafting can begin against the verified read path. → [#3](https://github.com/grace-shane/plex-api/issues/3)
- [ ] Implement Tool Assembly handling — Plex's supply-item schema is identity-only (no holder linkage). Tool assemblies as a separate concept may not exist in this app's API surface. **Investigate or descope.** → [#4](https://github.com/grace-shane/plex-api/issues/4)
- [ ] Implement API call to link tools to Routings/Operations — `mdm/v1/operations` exposes only `code, id, inventoryType, type` with no FK to tools. **Linkage may not be possible via API**; may require CSV upload or different approach. → [#5](https://github.com/grace-shane/plex-api/issues/5)
- [ ] Implement API call to update tooling within the specific Workcenter Document — verified read path is `production/v1/production-definitions/workcenters/{id}`. We have the workcenterCode → Brother Speedio mapping (879, 880). Write shape TBD. → [#6](https://github.com/grace-shane/plex-api/issues/6)
- [x] **IT blocker resolved.** The Fusion2Plex app on production with the Grace tenant authenticates correctly. The earlier "tenant routing" / "subscription approvals" investigation was a red herring caused by a credential typo. See BRIEFING.md "History of incorrect hypotheses" for the postmortem. → [#1](https://github.com/grace-shane/plex-api/issues/1)

## Phase 4: Data Mapping & Sync Logic

- [x] Create a mapping definition between Fusion 360 data structures and Plex API payload requirements (Completed in `Fusion360_Tool_Library_Reference.md`).
- [ ] Implement the core synchronization logic: → [#7](https://github.com/grace-shane/plex-api/issues/7)
  - Utilize the Fusion JSON file output as the explicit Source of Truth relative to Plex.
  - Push updates for purchased consumables to the master inventory list.
  - Link those consumables into Tool Assemblies.
  - Ensure those assemblies dynamically flow down to the Routing and then the Job when run in the shop, linking tools directly to manufactured parts.
  - Push final setups to the workcenter documents.
- [ ] Add basic error handling and logging (e.g., logging successful syncs or failed API calls to a text file on the network share). → [#8](https://github.com/grace-shane/plex-api/issues/8)

## Phase 5: Automation & Deployment

- [ ] Finalize the synchronization script. → [#9](https://github.com/grace-shane/plex-api/issues/9)
- [ ] Deploy the script to a server or always-on PC with access to the network share. → [#10](https://github.com/grace-shane/plex-api/issues/10)
- [ ] Schedule the script to run daily at midnight (e.g., using Windows Task Scheduler). → [#11](https://github.com/grace-shane/plex-api/issues/11)
- [ ] Rotate the Plex API key before production (previous key is still in git history). → [#12](https://github.com/grace-shane/plex-api/issues/12)
