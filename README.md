# Datum — Fusion 360 → Plex tooling sync for Grace Engineering

Nightly automation that syncs Autodesk Fusion 360 tool library data into Rockwell Automation Plex
Manufacturing Cloud (ERP). Fusion 360 JSON files on a local network share are the absolute source
of truth. As of the April 2026 architecture pivot, Fusion data lands first in a Supabase
database (enriched source of truth — geometry, holder pairings, pocket assignments) and then an
identity slice (vendor part number + description) is pushed on to Plex's `supply-items` endpoint.
The React UI reads from Supabase; Plex gets only what its schema can accept.

## Status

| | |
|---|---|
| **Plex environment** | `connect.plex.com` (production) — there is no test environment for this app |
| **Plex app** | `Datum` Consumer Key, expires every 31 days (next rotation: 2026-05-08, issue #12) |
| **Plex tenant** | `58f781ba-1691-4f32-b1db-381cdb21300c` (Grace Engineering) |
| **Tooling endpoint** | `inventory/v1/inventory-definitions/supply-items` filtered to `category="Tools & Inserts"` (1,109 records) |
| **Workcenters** | `production/v1/production-definitions/workcenters` (143 records, including 21 mills mapping directly to Brother Speedio FTP IPs) |
| **Supabase** | dedicated `datum` project (us-east-2), 3 tables — `libraries`, `tools`, `cutting_presets` |
| **Phase** | **Phase B complete** — `validate_library.py` pre-sync gate landed (#25). Phase A-Python (Supabase upsert layer) is next. |
| **Tests** | 215 pytest tests, all green. CI on PRs to master via GitHub Actions. Branch protection requires the check to pass. |

## Architecture

```
Fusion 360 JSON (network share, via Autodesk Desktop Connector)
        │
        ▼
  validate_library.py          ← pre-sync gate: abort if library is invalid (#25)
        │
        ▼
  sync_supabase.py             ← upsert full tool records into Supabase  [Phase A-Python]
        │
        ├──▶  Supabase (bulletforge)   ← enriched source of truth
        │           │
        │           └──▶  React UI     ← tool library browser  [Phase D+]
        │
        └──▶  sync_plex.py             ← identity slice only → supply-items  [Phase C]
```

Why the pivot: Plex's `supply-items` schema is identity-only — vendor part number and description,
nothing else. Geometry, holder pairings, and pocket assignments have no home in Plex. Supabase
holds the full record; Plex gets the slice it can accept.

The original plan to write to `mdm/v1/parts` and `tooling/v1/tool-assemblies` was incorrect — see
[BRIEFING.md "History of incorrect hypotheses"](./docs/BRIEFING.md) for the postmortem.

## Quick start (local development)

1. **Clone and create your `.env.local`**

   ```powershell
   git clone https://github.com/grace-shane/datum.git
   cd datum
   copy .env.example .env.local
   # Edit .env.local with your Datum Consumer Key + Secret
   ```

   `.env.local` is gitignored. Get the Consumer Key from
   [developers.plex.com](https://developers.plex.com/) → My Apps → Datum.

2. **Install dependencies**

   ```powershell
   py -m pip install -r requirements-dev.txt
   ```

3. **Run the local endpoint tester**

   ```powershell
   py run_dev.py
   ```

   Opens on http://localhost:5000. The left rail has buttons for:
   - **Diagnostics** — `tenant_whoami` (run this first to verify connection)
   - **Plex presets** — verified Plex API URLs as one-click hits
   - **Extractors** — `extract_supply_items` (1,109 cutting tools), `extract_parts`, `extract_purchase_orders`, etc.
   - **Fusion 360 local** — `tools_stats` and `consumables_only` for verifying the local Fusion library load

   `run_dev.py` overrides shell environment variables with `.env.local` (the opposite of
   `bootstrap.py`'s production-safe `setdefault` semantics), so a stale system env var won't
   silently shadow your real key.

4. **Run tests**

   ```powershell
   py -m pytest
   ```

5. **Validate a Fusion library before syncing**

   ```powershell
   # Production mode — PASS/FAIL only, exit code 0 or 1
   py validate_library.py --file "BROTHER SPEEDIO ALUMINUM.json" --no-api

   # Verbose — shows WARN issues too
   py validate_library.py --file "BROTHER SPEEDIO ALUMINUM.json" --no-api --verbose

   # With live Plex supplier lookup for VENDOR_NOT_IN_PLEX checks
   py validate_library.py --file "BROTHER SPEEDIO ALUMINUM.json" --verbose
   ```

   The validator catches duplicate product-ids, missing required fields, non-positive geometry,
   unknown tool types, and vendors that won't resolve to a Plex supplier. The sync layer gates on
   a PASS; FAILs abort the sync before anything touches Supabase or Plex. Full rule table in
   [`docs/validate_library_spec.md`](./docs/validate_library_spec.md).

## Production safety

This codebase reads from real Grace Engineering production data on every API call. Two guard rails
protect against accidental writes:

- **`PlexClient.get_envelope()`** returns structured success/error envelopes so HTTP failures
  are visible (PR #15 fixed an earlier "swallow on error" bug).
- **`/api/plex/raw` proxy refuses POST/PUT/PATCH/DELETE** when running against
  `connect.plex.com` unless `PLEX_ALLOW_WRITES=1` is set in the environment (PR #17). Read-only
  is always allowed. To enable writes:

   ```powershell
   $env:PLEX_ALLOW_WRITES = "1"
   py run_dev.py
   ```

  The UI shows a red `WRITES ON` chip when the guard is disabled. Rotate the env var off as soon
  as you're done.

## Key references

- [`docs/BRIEFING.md`](./docs/BRIEFING.md) — primary context document for AI-assisted dev sessions and the
  source of truth for current status, current credentials, gotchas, and project history
- [`docs/Plex_API_Reference.md`](./docs/Plex_API_Reference.md) — verified endpoint access matrix and URL
  pattern conventions
- [`docs/Fusion360_Tool_Library_Reference.md`](./docs/Fusion360_Tool_Library_Reference.md) — Fusion JSON
  schema and field-to-Plex mapping
- [`docs/validate_library_spec.md`](./docs/validate_library_spec.md) — design spec for the pre-sync
  validation gate; implemented as `validate_library.py` (#25)
- [`TODO.md`](./TODO.md) — project roadmap mirrored to GitHub Issues
- [GitHub Issues](https://github.com/grace-shane/datum/issues) — live status of every phase work
  item with dependencies and blockers
- [Plex Manufacturing Cloud API docs](https://www.rockwellautomation.com/en-us/support/plex-manufacturing-cloud/api.html)

## Contributing workflow

1. Branch from `master`
2. Push to a `claude/<short-name>` branch (or any branch — naming is convention, not enforced)
3. Open a PR to `master`
4. CI runs `pytest` automatically
5. Branch protection blocks merge until the check is green
6. Use `gh pr merge --auto --squash` to enable auto-merge — it lands the PR the moment CI passes

## License

Internal Grace Engineering project. Forked from
[`just-shane/plex-api`](https://github.com/just-shane/plex-api).
