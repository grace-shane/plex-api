# NEXT_SESSION.md — prompts for the next Datum Claude session on `datum-dev`

This file holds canned prompts to paste into a fresh Claude Code session
running on the `datum-dev` GCP VM. The VM already has all repo plugins
installed; it just needs a `git pull` on `master` before the session
starts.

Read these in order:

- [`BRIEFING.md`](./BRIEFING.md) — overall project context
- [`GCP_MIGRATION.md`](./GCP_MIGRATION.md) — what's already provisioned
- [`REORG_AND_STACK.md`](./REORG_AND_STACK.md) — the pending stack swap

## Prompt 1 — Cloud Scheduler start/stop for `datum-dev`

```
Read docs/GCP_MIGRATION.md, then set up Cloud Scheduler to start
datum-dev each weekday morning (07:00 America/Chicago) and stop it each
evening (19:00 America/Chicago). Use the HTTP target against
compute.googleapis.com with OAuth and the runtime service account.

Add a new idempotent script scripts/gcp/08-scheduler.sh that creates
both jobs and the minimal IAM bindings needed for the SA to
start/stop the instance. Document the expected monthly-cost delta
(baseline ~$50/mo 24/7 → ~$15/mo weekday-only) in a short section at
the bottom of docs/GCP_MIGRATION.md.

Open a PR on grace-shane/Datum with --repo grace-shane/Datum (do not
rely on gh's default remote — it picks upstream, which is wrong).
```

## Prompt 2 — Populate Supabase slots + migrate DB to Cloud SQL

```
Phase 2 of docs/REORG_AND_STACK.md: move the staging DB from Supabase
to the Cloud SQL instance datum-db.

Before any migration work, add two Secret Manager slots for the
existing Supabase project (we still need to read from it to dump):
supabase-url and supabase-service-role-key. Update
scripts/gcp/env.sh SECRETS array and re-run scripts/gcp/05-secrets.sh
plus scripts/gcp/10-populate-secrets.sh.

Then: pg_dump from Supabase (Shane has full admin there), restore
into datum-db, swap the app's DB layer to SQLAlchemy + psycopg3 as
specified in REORG_AND_STACK.md Phase 2. Keep Supabase reads working
behind a feature flag for one deploy cycle so we can roll back.

Write a plan before touching code. Confirm with Shane before running
pg_dump — it's a one-way step in the sense that it locks in a
cutover moment.
```

## Prompt 3 — General session kickoff (if doing neither of the above)

```
Read CLAUDE.md and follow its reading order. Then check Notion's
Current State block to see what's actually next. If nothing's
pressing, look at TODO.md for the next unblocked GitHub issue.
```

## Gotchas this VM will hit

- `gh` auto-picks the `upstream` remote (old `just-shane/plex-api` fork).
  Always pass `--repo grace-shane/Datum`.
- The `datum-runtime` VM holds `aps-refresh-token`; `datum-dev` does not
  (by IAM policy in `05-secrets.sh`). Don't try to read that secret from
  this machine.
- Plex writes stay gated behind `PLEX_ALLOW_WRITES=1`. The GCP move did
  not change that contract.
