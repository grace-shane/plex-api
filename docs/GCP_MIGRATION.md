# GCP Migration — Datum

**Status:** Planning (2026-04-17). No code changes in the session that wrote this doc.
**Umbrella issue:** [#85](https://github.com/grace-shane/Datum/issues/85)

This document captures the agreed architecture for moving Datum off Supabase +
Autodesk Desktop Connector (ADC) + the locked-down work machine, and onto GCP +
the Autodesk Platform Services (APS) HTTP API. Read this together with
[`BRIEFING.md`](./BRIEFING.md) for project context and
[`validate_library_spec.md`](./validate_library_spec.md) for the pre-sync gate
(the validation engine itself is source-agnostic and survives the migration
unchanged — only the CLI entry point that walks `CAMTools` needs to change).

---

## Why migrate

Three forcing functions collided in April 2026:

1. **Dev machine at Grace is locked down.** New tooling can't be installed,
   long-lived dev servers are awkward, `.env.local` churn is painful. A
   persistent cloud dev environment (`datum-dev`) solves this.
2. **Supabase is a stopgap.** It earned its keep during Phase A, but it adds a
   vendor we don't need once GCP is the deploy surface. Cloud SQL gives us one
   infra control plane.
3. **APS removes the ADC dependency.** Autodesk Platform Services exposes Fusion
   Hub tool libraries over HTTP. That kills the "ADC stall for >25h" failure
   mode in `tool_library_loader.py:34`, the "file locked mid-sync" error path
   in `tool_library_loader.py:104`, and the whole CAMTools network share as a
   moving part. `aps_client.py` already exists in the tree — partial
   implementation from earlier Fusion-cloud work.

---

## Target architecture

```
  Autodesk Hub (APS)
      │  HTTP (OAuth, refresh via Secret Manager)
      ▼
  ┌─────────────────┐         ┌─────────────────────┐
  │  datum-runtime  │ ──────▶ │   Cloud SQL         │
  │  e2-micro       │         │   Postgres          │
  │  always-on      │         │   db-f1-micro       │
  │  us-central1    │         │   libraries / tools │
  │  (sync + API)   │         │   cutting_presets   │
  └─────────────────┘         └─────────────────────┘
      │ Secret Manager: PLEX_API_KEY, PLEX_API_SECRET,
      │                 DB URL, APS client creds
      ▼
  Plex connect.plex.com — identity slice → supply-items

  Cloudflare (datum.graceops.dev) ──▶ Flask on runtime VM ──▶ React UI

  ┌─────────────────┐
  │  datum-dev      │  Cloud Scheduler: start 7am CT / stop 5pm CT (Mon–Fri)
  │  e2-standard-2  │
  │  Ubuntu 22.04   │  SSH target for VS Code Remote / Claude Code
  └─────────────────┘
```

---

## VM topology

| VM | Purpose | Machine type | OS | Runtime model |
|---|---|---|---|---|
| `datum-dev` | Cloud dev environment — replaces the locked-down work machine. SSH target for VS Code Remote / Claude Code. | `e2-standard-2` | Ubuntu 22.04 | Business hours only. Cloud Scheduler start 7am CT / stop 5pm CT, Mon–Fri. Off weekends and evenings. |
| `datum-runtime` | Nightly sync cron + Flask API surface for the React UI | `e2-micro` | Ubuntu 22.04 | Always-on in `us-central1` (free tier) |

### Why split them

`datum-dev` needs enough RAM/CPU to run VS Code Remote, pytest, and Claude Code
comfortably — but only during work hours. Keeping it on 24/7 wastes money and
lets state rot (nightly shutdowns force us to keep env setup scripted).
`datum-runtime` only needs to call APS once a night and serve a light Flask API,
so the free `e2-micro` fits. Keeping them separate means a dev-side crash,
reboot, or upgrade can't take the nightly sync down.

---

## Service mapping

| Today | After migration | Notes |
|---|---|---|
| Supabase (`datum` project, us-east-2) | Cloud SQL `db-f1-micro`, us-central1 | Same Postgres schema and bare table names (`libraries` / `tools` / `cutting_presets`) — Supabase is on its own DB, so no prefix is needed for isolation |
| Autodesk Desktop Connector + CAMTools network share | Autodesk Platform Services (APS) HTTP API | Removes 25h stale-file guard, mid-sync file-lock handling, and per-machine ADC install requirement. `aps_client.py` is already partially wired. |
| Windows Task Scheduler (planned, never built) | Cloud Scheduler → systemd timer on `datum-runtime` (or Cloud Run Job) | Cloud Scheduler also drives the dev VM start/stop |
| `.env.local` loaded by `bootstrap.py` | Secret Manager on both VMs, fallback `.env.local` for local dev | Never commit Secrets; `bootstrap.py` gains a Secret Manager loader path |
| Work machine (locked down) | `datum-dev` VM + Cloudflare DNS | `datum.graceops.dev` serves the React UI over TLS |
| Supabase service-role key (server-side only) | Cloud SQL connection via Cloud SQL Auth Proxy / IAM | Same "never ship to browser" model; Flask holds the connection server-side |
| (none — Phase 5 was never deployed) | Cloudflare in front of Cloud Run or runtime VM | `datum.graceops.dev` |

**Not in scope:** Firebase, Cloud Data Connect, Firestore. Cloud SQL is the only
database. The React UI reads through Flask, not directly.

---

## Data flow (ADC-free)

1. Cloud Scheduler fires nightly at midnight CT → triggers the sync unit on
   `datum-runtime`.
2. `sync.py` authenticates to APS using the OAuth client credentials stored in
   Secret Manager, lists Fusion Hub projects, and downloads tool library JSON
   over HTTP.
3. `validate_library.py` gates each library per
   [`validate_library_spec.md`](./validate_library_spec.md). FAIL aborts that
   library; PASS continues.
4. Upsert into Cloud SQL `libraries` / `tools` / `cutting_presets` via the new
   DB client.
5. `build_supply_item_payload` (issue #3) reads the `tools` table and pushes
   the identity slice (vendor part #, description) to Plex
   `inventory/v1/inventory-definitions/supply-items`.
6. Flask (`app.py`) serves `/api/*` and the React UI from `datum-runtime`.
   Cloudflare terminates TLS at `datum.graceops.dev` and proxies to the VM.

The production write guard (`PLEX_ALLOW_WRITES=1`, PR #17) still applies.
Default OFF in the VM boot env; the systemd sync unit sets it just for the
invocation window.

---

## Credentials — Secret Manager layout

| Secret name | Contents | Consumers |
|---|---|---|
| `plex-api-key` | Datum Consumer Key (rotates every 31 days, next 2026-05-08) | `datum-runtime` (sync), `datum-dev` (optional) |
| `plex-api-secret` | Datum Consumer Secret (currently optional — reserved for future) | same |
| `plex-tenant-id` | Grace tenant UUID (`58f781ba-…`) — not actually secret, but convenient | same |
| `db-url` | Cloud SQL Postgres connection string | `datum-runtime`, `datum-dev` |
| `aps-client-id`, `aps-client-secret` | Autodesk Platform Services app credentials | `datum-runtime` |
| `aps-refresh-token` | APS OAuth refresh token (rotated by the sync runner) | `datum-runtime` |

### IAM split

- `datum-runtime` service account — `Secret Accessor` on all of the above,
  `Cloud SQL Client` on the runtime DB.
- `datum-dev` service account — `Secret Accessor` on everything except
  `aps-refresh-token` (the runner owns token rotation; dev shouldn't contend).
  `Cloud SQL Client` on the runtime DB for read/write access during dev.

### `bootstrap.py` behavior

Add a `USE_SECRET_MANAGER=1` path that pulls secrets at process start via
`google-cloud-secret-manager`. `setdefault` semantics are preserved — a real
shell env var still wins (lesson from BRIEFING.md History §4, the stale
`PLEX_API_KEY` Windows env var that shadowed `.env.local`). Local dev falls
back to `.env.local` exactly as today.

---

## Affected code (change-surface map)

**No edits in the planning session. This is the enumeration that future
implementation PRs will work through.**

### ADC / local-filesystem removal

| File | Change | Reason |
|---|---|---|
| [`tool_library_loader.py`](../tool_library_loader.py) | Replace with an APS-backed loader or refactor to a source-agnostic interface with an APS adapter. The 25h stale-file guard becomes an "APS response freshness" check or is retired entirely. | Core ADC reader: `_DC_REL_PATH = DC\Fusion\XWERKS\Assets\CAMTools`, `load_library`, `load_all_libraries`, `_check_file_age`, `report_library_contents`. Every consumer path flows through here. |
| [`sync.py`](../sync.py) | Delete the "local ADC fallback" branch (~lines 265–420). APS becomes the only source. `--local-adc` flag becomes dead code. | File header currently reads "APS cloud-first, local ADC fallback" — the fallback is the thing we're removing. |
| [`app.py`](../app.py) | `/api/fusion/validate` GET currently walks `CAM_TOOLS_DIR`; switch to APS. `/api/aps/*` OAuth routes stay (they were built for this). `/api/fusion/libraries` GET likewise. | Flask endpoints that back the React library browser. |
| [`validate_library.py`](../validate_library.py) | CLI default resolves a CAMTools dir; switch to APS listing, or require an explicit `--file` / `--hub-project`. Engine itself is unchanged — the spec stays valid. | `CAM_TOOLS_DIR` references around line 996. |
| [`aps_client.py`](../aps_client.py) | Audit for completeness against the new required scope. Add refresh-token rotation writing back to Secret Manager. | Already partially implemented — reused, not rewritten. |
| [`tests/test_tool_library_loader.py`](../tests/test_tool_library_loader.py), [`tests/test_sync.py`](../tests/test_sync.py), [`tests/test_validate_library.py`](../tests/test_validate_library.py), [`tests/test_app_routes.py`](../tests/test_app_routes.py) | Replace filesystem fixtures with APS-response fixtures (mocked HTTP). | Follow the production code. |

### Supabase → Cloud SQL

| File | Change | Reason |
|---|---|---|
| [`supabase_client.py`](../supabase_client.py) | Replace with `db_client.py` (psycopg / SQLAlchemy against Cloud SQL). Preserve the public surface so call sites change by import only. | Single point of change if the adapter is clean. |
| [`sync_supabase.py`](../sync_supabase.py) | Rename → `sync_db.py` (or keep name, just swap client). Switch to new client. | |
| [`sync_tool_inventory.py`](../sync_tool_inventory.py), [`populate_supply_items.py`](../populate_supply_items.py), [`ingest_reference.py`](../ingest_reference.py), [`enrich.py`](../enrich.py), [`scripts/load_sample.py`](../scripts/load_sample.py) | Swap `from supabase_client import …` for new DB client import. | All currently depend on `supabase_client`. |
| [`app.py`](../app.py) | Swap Supabase reads for DB client reads on every Flask route that hits the DB. | React UI back-end. |
| [`tests/test_supabase_client.py`](../tests/test_supabase_client.py), [`tests/conftest.py`](../tests/conftest.py), [`tests/test_sync_supabase.py`](../tests/test_sync_supabase.py), [`tests/test_sync_tool_inventory.py`](../tests/test_sync_tool_inventory.py), [`tests/test_populate_supply_items.py`](../tests/test_populate_supply_items.py), [`tests/test_ingest_reference.py`](../tests/test_ingest_reference.py), [`tests/test_enrich.py`](../tests/test_enrich.py), [`tests/test_sync.py`](../tests/test_sync.py) | Point fixtures at a local Postgres (docker) or SQLAlchemy fake; drop the Supabase REST mocks. | Follow the production code. |

### Credentials / secrets

| File | Change | Reason |
|---|---|---|
| [`bootstrap.py`](../bootstrap.py) | Add Secret Manager loader path behind `USE_SECRET_MANAGER=1`. Keep `.env.local` fallback. Preserve `setdefault` semantics (shell env wins — see BRIEFING History §4). | Entry point for every credential read. |
| [`plex_api.py`](../plex_api.py) | No change — reads env vars which `bootstrap.py` populates. | Transparent to the API layer. |

### Docs needing follow-up edits (not in this doc)

- `CLAUDE.md` entry #7 (Supabase staging layer) — repoint at Cloud SQL
- `README.md` — status table, architecture diagram, "Why the pivot" paragraph
- `docs/BRIEFING.md` — "Current situation" block, architecture diagram, Notion link to schema page
- `docs/validate_library_spec.md` — any language mentioning "ADC share" or the network-share GET path

---

## Migration sequence (suggested)

1. **Provision GCP** — project, `datum-dev`, `datum-runtime`, Cloud SQL,
   Secret Manager entries. No application code yet.
2. **Apply schema to Cloud SQL** with bare table names (`libraries` / `tools`
   / `cutting_presets`) — matches the current Supabase schema post-PR #34.
3. **`bootstrap.py` Secret Manager path** — additive change, can land before
   anything else is wired up; it's a no-op until `USE_SECRET_MANAGER=1` is set.
4. **`db_client.py`** — new module, drop-in for `supabase_client`. Land behind
   a feature flag (`USE_CLOUD_SQL=1`), dual-read/dual-write if useful, then flip.
5. **APS-only loader** — replace/refactor `tool_library_loader.py`, gut the
   local-ADC branch in `sync.py`, update Flask routes. Tests follow.
6. **Cloud Scheduler wiring** — nightly sync cron + dev VM start/stop schedules.
7. **Cloudflare DNS** — `datum.graceops.dev` → runtime VM (or Cloud Run if we
   promote the Flask app off the VM; defer that decision).
8. **Decom** — remove Supabase project, strip ADC references from CLAUDE.md,
   BRIEFING, README, validate_library_spec.

---

## Open questions / risks

- **Cold Cloud SQL on the nightly cron.** `db-f1-micro` + one-shot nightly
  writes may hit cold-start latency. Acceptable for a midnight job; revisit if
  it ever matters for interactive UI reads.
- **APS rate limits + OAuth refresh.** Need to confirm refresh-token lifetime
  and build rotation into `aps_client.py`. Token write-back to Secret Manager
  needs its own IAM grant.
- **Cloud Run vs runtime VM for Flask.** Either works. The VM is simpler given
  we already have one; Cloud Run is cheaper at idle and scales to zero. Defer
  the decision until the migration is otherwise done.
- **`datum-dev` state management.** Business-hours-only means no long-running
  background processes on it. Fine for editor + pytest + Claude Code; document
  so we don't get surprised.
- **Secret Manager IAM per service account.** `datum-dev` should not have
  write access to production credentials; scope narrowly.
- **Production write guard on the runtime VM.** `PLEX_ALLOW_WRITES` should
  default OFF at boot and be set only by the systemd unit that invokes the
  nightly sync. Never in the VM's shell profile.
- **APS token vs Consumer Key lifetime.** Plex Consumer Key rotates every 31
  days; APS tokens rotate on their own cycle. Two independent rotation alarms;
  document both in the runbook.
