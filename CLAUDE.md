# Claude memory file

This is the entry point for Claude Code (or any AI agent) working on this
repository. **Read these files in this order before doing anything**:

1. **[`docs/BRIEFING.md`](./docs/BRIEFING.md)** — primary context document. Project
   purpose, current credentials, current Plex environment, verified
   endpoint matrix, gotchas, immediate TODO, "History of incorrect
   hypotheses" postmortem, and a session log of what's been done. **This
   is the most important file in the repo for AI context.**

2. **[`docs/Plex_API_Reference.md`](./docs/Plex_API_Reference.md)** — verified URL
   patterns, the 401-vs-404 reading guide, and the no-pagination gotcha.
   Read this before writing any new Plex API call.

3. **[`docs/Fusion360_Tool_Library_Reference.md`](./docs/Fusion360_Tool_Library_Reference.md)**
   — Fusion JSON schema and field-to-Plex mapping. Read this before
   writing anything that consumes the local Fusion library files.

4. **[`TODO.md`](./TODO.md)** — project roadmap, links to GitHub Issues
   for live status.

5. **Datum Notion page** — https://www.notion.so/Grace-Engineering-Fusion2Plex-33c3160a3abf81f1aac0e58101952be5
   — **read at the start of every session.** Current State block tells
   you phase, next action, and test count. End each session by updating
   that block + appending one line to the Decision Log. See the
   "Notion pages" section in `docs/BRIEFING.md` for details.

6. **Supabase staging layer** — Fusion JSON is ingested into the
   `libraries`, `tools`, and `cutting_presets` tables in the dedicated
   `datum` Supabase project (us-east-2) before anything pushes to Plex.
   Schema spec: [Notion · Supabase Schema Design](https://www.notion.so/33c3160a3abf814c885cc174cda76d17).
   Code: `supabase_client.py`, `sync_supabase.py`, `scripts/load_sample.py`.
   Credentials: `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` in `.env.local`.
   Issue #31. Downstream (`build_supply_item_payload`, #3) reads from
   the `tools` table, not raw JSON.

## Hard rules

- **Never read credentials from images.** Always have the user paste them
  as text or via Insomnia "Generate Code" output. We learned this the
  hard way (see BRIEFING.md "History of incorrect hypotheses §1").
- **Never hardcode credentials.** They live in `.env.local` (gitignored),
  loaded by `bootstrap.py`. Production deploy uses real shell env vars.
- **Never bypass the production write guard.** Mutating HTTP methods on
  `connect.plex.com` are refused at `/api/plex/raw` unless
  `PLEX_ALLOW_WRITES=1` is explicitly set in the environment.
- **Always run `pytest` before committing.** Branch protection on master
  requires the `pytest` GitHub Actions check to pass before any merge.
- **Use the `claude/<short-name>` branch naming convention** for new
  branches off master, then auto-merge with `gh pr merge --auto --squash`.
- **Never ship the Supabase service role key to a browser.** It bypasses
  RLS. Server-side ingest scripts only.

## Quick commands

```powershell
# Run the local endpoint tester (overrides shell env from .env.local)
py run_dev.py

# Run tests
py -m pytest

# Open a PR with auto-merge
gh pr create --base master --head claude/my-branch --title "..." --body "..."
gh pr merge <number> --auto --squash
```

## Things this repo does NOT have

- A test environment for the Datum Plex app — production is the
  only environment we have credentials for. Be cautious.
- A scheduled deploy yet (Phase 5 work, issues #9-#11)
- A CI badge or release versioning yet
- Any tooling-API endpoints — Plex's tool data lives under
  `inventory/v1/inventory-definitions/supply-items`, NOT
  `tooling/v1/*` or `mdm/v1/parts`. See BRIEFING.md.

## When in doubt

- The repo is small and the context fits in one read of BRIEFING.md +
  Plex_API_Reference.md. Read them; don't guess.
- Claude Code has a built-in `tenant_whoami` diagnostic at
  `/api/diagnostics/tenant` — run that first whenever the connection
  state is unclear.
- Open a PR. CI is fast (~10s) and branch protection guarantees you
  can't break master.
