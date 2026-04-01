# Project Roadmap: Fusion 360 to Plex Sync

This document outlines the step-by-step implementation plan for the Autodesk Fusion 360 tool library to Plex Manufacturing Cloud synchronization project.

## Phase 1: API Discovery & Authentication

- [x] Set up Postman and discover relevant Plex API endpoints.
- [x] Obtain API authentication credentials (Client ID/Secret or API Key) for the Plex environment.
- [x] Successfully authenticate via a test script (`plex_api.py`).
- [ ] **ACTION ITEM**: Regenerate API Key in the Developer Portal (Previous key was exposed in `.docx` git history).

## Phase 2: Local Data Reading & Parsing

- [ ] Identify the permanent network share path for the Fusion 360 tool library JSON files.
- [ ] Write a script to consistently read the JSON files from the network share.
- [x] Parse the Fusion 360 JSON schema to identify key tooling attributes (Completed in `Fusion360_Tool_Library_Reference.md`).

## Phase 3: Plex API Implementation

- [ ] Implement API call to retrieve current tooling inventory from Plex (master list).
- [ ] Implement API call to update/create tooling inventory in Plex.
- [ ] Implement API call to update tooling within the specific Workcenter Document (`production/v1/control/workcenters`).
- [ ] **BLOCKED**: Waiting on IT (Courtney) to enable Tooling & Manufacturing APIs in the Developer Portal.

## Phase 4: Data Mapping & Sync Logic

- [x] Create a mapping definition between Fusion 360 data structures and Plex API payload requirements (Completed in `Fusion360_Tool_Library_Reference.md`).
- [ ] Implement the core synchronization logic:
  - Compare local JSON state vs Plex state (or simply execute full overwrites for simplicity).
  - Loop through tools and push updates to the master inventory list.
  - Push updates to the workcenter documents.
- [ ] Add basic error handling and logging (e.g., logging successful syncs or failed API calls to a text file on the network share).

## Phase 5: Automation & Deployment

- [ ] Finalize the synchronization script.
- [ ] Deploy the script to a server or always-on PC with access to the network share.
- [ ] Schedule the script to run daily at midnight (e.g., using Windows Task Scheduler).
