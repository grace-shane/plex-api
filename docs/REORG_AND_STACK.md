# Reorg + Stack Update — Datum

**Status:** Planning (2026-04-17). No code changes in the session that wrote this doc.
**Trigger:** Grace Engineering has provided Shane company-supplied GCP access and
budget for Datum. That funds the [GCP migration epic #85](https://github.com/grace-shane/Datum/issues/85)
and opens room for stack changes that wouldn't have been justifiable on a
zero-budget project.
**Relationship to #85:** This plan executes *before* the GCP migration. The
repo ships to Cloud SQL + Cloud Run / VMs easier if it's organized and the DB
layer is already vendor-neutral. See the sequencing block at the bottom.

---

## Scope boundaries (read first)

These are explicit limits, not stretch goals. Written up front because
"everyone asks when you have a UI" and scope creep is the fastest way to
wreck a cleanup PR series.

| Boundary | Meaning |
|---|---|
| **React UI is debug + show-and-tell only** | `datum.graceops.dev` is not a product Shane actively develops. Other Grace engineers use it and that's valuable, but feature requests land in a user-goals conversation before any code. No speculative features. |
| **No mobile support** | Not now, not as part of this reorg, not as a stretch goal. No PWA, no mobile-first refactors, no React Native. If the UI renders acceptably on a tablet, that's a bonus, not a requirement. |
| **Plex writes stay last** | Nothing in this plan changes the "DB first, Plex last, can't dry-run prod" sequencing. The reorg and stack update are strictly below the Plex write layer. |
| **No new features masquerading as cleanup** | Organize moves files. Stack updates change imports. Neither adds behavior. New features get their own issues and PRs. |
| **Don't touch the Flask endpoint-tester scope** | `app.py` + `templates/` + `static/` is Shane's personal Plex-API poking tool. It's not user-facing. Retain it through the reorg — Shane uses it to sanity-check Plex responses. React UI is the user-facing surface. |

If any PR in this series starts drifting past these boundaries, pause and
split the work instead of letting it grow.

---

## Why now, why this order

Three reasons to organize before migrating, not after:

1. **Vendor-neutral DB layer is the single highest-leverage stack change** —
   and it's also the natural prerequisite for swapping Supabase → Cloud SQL.
   Doing it after migration means a second round of rewrites. Doing it before
   means Cloud SQL is a connection-string flip.
2. **15 flat `.py` files at the repo root is the visible symptom of "we didn't
   know what we were building yet."** That excuse is gone. We know what we're
   building. The layout should reflect it.
3. **Mixing a reorg PR with a migration PR makes every diff ambiguous** — is
   this a rename, a rewrite, a behavior change? Separating them keeps review
   tractable.

Stack updates that *don't* unblock Cloud SQL (FastAPI, httpx, uv) are
secondary. They're in §3 but flagged as "weigh against whether it unblocks
anything," not mandatory.

---

## Current state

```
datum/
├── 15 top-level *.py files    ← the main symptom
├── tests/                      flat, 17 test files
├── scripts/load_sample.py      single script, no organization needed
├── db/migrations/              SQL migrations
├── web/                        React UI (product surface)
├── templates/, static/         legacy Flask endpoint-tester UI
├── docs/                       documentation
├── .github/workflows/          CI
├── pyproject.toml              Python packaging
├── requirements.txt, requirements-dev.txt   pinned deps
└── README.md, CLAUDE.md, TODO.md
```

Pain points that motivate the reorg:

- Four sync-adjacent entrypoints (`sync.py`, `sync_supabase.py`,
  `sync_tool_inventory.py`, `populate_supply_items.py`) with overlapping
  concerns — hard to tell which one is the real nightly path without
  reading each
- `supabase_client.py` is the direct blocker for Cloud SQL migration
- No `datum/` package — imports are all top-level, which means worktree
  discovery and cloud packaging both hit edge cases
- Tests mirror the flat layout, which means `test_sync_supabase.py` +
  `test_sync.py` + `test_sync_tool_inventory.py` live side by side with
  no obvious relationship
- The React UI sits in `web/` with no statement about whether it's part
  of the Python project (it isn't) or a peer (it is) — affects how
  Cloudflare, CI, and dependency management read the repo

---

## Phase 1: Organize

One PR series, three or four PRs, each one mechanical. Goal: every file
in `*.py` at the repo root gets a home.

### Target Python package layout

```
datum/                           # Python package (importable as `datum.*`)
├── __init__.py
├── bootstrap.py                 # credential loader (moved from root)
├── plex/
│   ├── __init__.py
│   ├── client.py                # from plex_api.py
│   ├── diagnostics.py           # plex_diagnostics.py
│   └── extractors.py            # extract_* helpers split from plex_api.py
├── fusion/
│   ├── __init__.py
│   ├── aps.py                   # aps_client.py (primary source)
│   └── adc_loader.py            # tool_library_loader.py (fallback, slated
│                                #   for deletion under #85)
├── db/
│   ├── __init__.py
│   ├── client.py                # supabase_client.py → becomes SQLAlchemy
│   │                            #   in Phase 2
│   └── ingest.py                # ingest_reference.py
├── sync/
│   ├── __init__.py
│   ├── runner.py                # sync.py — the nightly CLI entry point
│   ├── staging.py               # sync_supabase.py (writes to DB staging)
│   ├── inventory.py             # sync_tool_inventory.py (Plex qty pull)
│   ├── supply_items.py          # populate_supply_items.py
│   ├── payload.py               # build_supply_item_payload (new home
│   │                            #   for issue #3 work)
│   └── enrich.py                # enrich.py
├── validate/
│   ├── __init__.py
│   └── library.py               # validate_library.py
└── web/                         # Flask API only — React UI stays separate
    ├── __init__.py
    ├── app.py                   # from top-level app.py
    ├── templates/               # Flask endpoint-tester (retained)
    ├── static/                  # Flask endpoint-tester assets (retained)
    └── routes/
        ├── plex.py              # /api/plex/*
        ├── fusion.py            # /api/fusion/*, /api/aps/*
        └── diagnostics.py       # /api/diagnostics/*
```

Top-level after reorg:

```
/
├── datum/                  # Python package (above)
├── web/                    # React UI (unchanged — peer to datum/,
│                           #   NOT absorbed into the Python package)
├── tests/                  # mirror datum/ structure
├── db/migrations/          # SQL migrations (unchanged location)
├── scripts/                # one-off CLI scripts
├── docs/
├── .github/workflows/
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── README.md, CLAUDE.md, TODO.md
```

**Key decision:** `web/` (React) is a peer to `datum/` (Python), not a
subdirectory of it. Different language, different toolchain, different
deploy (Cloudflare Workers vs runtime VM). Monorepo layout, not nested.

### File-move table

| From | To | Notes |
|---|---|---|
| `plex_api.py` | `datum/plex/client.py` | Split `extract_*` helpers into `datum/plex/extractors.py` |
| `plex_diagnostics.py` | `datum/plex/diagnostics.py` | |
| `aps_client.py` | `datum/fusion/aps.py` | |
| `tool_library_loader.py` | `datum/fusion/adc_loader.py` | Renamed to make its "fallback path" status visible |
| `supabase_client.py` | `datum/db/client.py` | Becomes SQLAlchemy in Phase 2 |
| `ingest_reference.py` | `datum/db/ingest.py` | |
| `sync.py` | `datum/sync/runner.py` | The nightly CLI entry point |
| `sync_supabase.py` | `datum/sync/staging.py` | |
| `sync_tool_inventory.py` | `datum/sync/inventory.py` | |
| `populate_supply_items.py` | `datum/sync/supply_items.py` | |
| `enrich.py` | `datum/sync/enrich.py` | |
| `validate_library.py` | `datum/validate/library.py` | Spec doc stays in `docs/` |
| `bootstrap.py` | `datum/bootstrap.py` | |
| `app.py` | `datum/web/app.py` | Split route handlers into `datum/web/routes/*.py` |
| `templates/` | `datum/web/templates/` | Flask tester — retain |
| `static/` | `datum/web/static/` | Flask tester — retain |
| `run_dev.py` | stays at root | Dev launcher — convenient at the top level |
| `scripts/load_sample.py` | unchanged | |
| `web/` (React) | unchanged | Peer, not absorbed |

`pyproject.toml` gets a `packages = ["datum"]` entry (or the src-layout
equivalent) so `pip install -e .` picks it up.

### Suggested PR breakdown

1. **PR A — add `datum/` package skeleton, move leaf modules** (`bootstrap`,
   `plex`, `fusion`, `validate`). Update imports. Green CI.
2. **PR B — move sync layer** (`sync/*`). Update all imports. Green CI.
3. **PR C — move Flask app** (`datum/web/`). Split route handlers. React UI
   untouched. Green CI.
4. **PR D — mirror-structure test reorg** — move `tests/test_*.py` into
   `tests/plex/`, `tests/fusion/`, etc. Optional; low value if the flat
   layout is readable.

Each PR is ~15–30 file moves + import-path updates. Git catches renames
automatically (see BRIEFING session log 2026-04-08, lesson #7), so history
is preserved.

---

## Phase 2: Stack updates

### Primary: SQLAlchemy 2.0 + psycopg3 (unblocks Cloud SQL)

Replace the Supabase Python client with SQLAlchemy 2.0 over psycopg3.

**What changes:**

- `datum/db/client.py` gains a SQLAlchemy `Engine` and session factory.
- `datum/db/models.py` (new) — SQLAlchemy declarative models for
  `libraries`, `tools`, `cutting_presets`, `plex_supply_items`.
- Supabase-client calls (`client.table("tools").upsert(...)`) become
  SQLAlchemy `session.merge(...)` or `insert(...).on_conflict_do_update(...)`.
- Connection string moves from `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`
  to a standard `DATABASE_URL` env var (psycopg3 parses it directly).
  `.env.local` gains `DATABASE_URL` — Supabase exposes a direct Postgres
  connection that works with psycopg3.
- Tests swap Supabase-REST mocks for an in-process SQLite-or-Postgres
  fixture. `pytest-postgresql` or `sqlalchemy-utils` create/drop.

**Why this unblocks Cloud SQL:** after the swap, pointing `DATABASE_URL`
at Cloud SQL is a connection-string flip. No application code changes.
The migration PR becomes infra + secret rotation, not a rewrite.

### Secondary (pick-and-choose, not mandatory)

| Change | Verdict | Reason |
|---|---|---|
| `ruff` for lint + format | **Do it** | Single tool replaces black + flake8 + isort. Cheap to adopt, fast, widely used. |
| `uv` for dep resolution | **Probably** | Pins `requirements.txt` stay, but `uv pip install` is dramatically faster. Low risk, no lock-in. |
| Type-check with `mypy` / `pyright` | **Skip for now** | Codebase is small and well-tested (262 tests). The ROI shows up at 50k+ LOC, not 5k. Revisit if the reorg surfaces unclear interfaces. |
| Flask → FastAPI | **Skip** | Flask is stable, the production write guard is non-trivial to port, and the React UI doesn't need async. Swap later if there's a real pain point. |
| `requests` → `httpx` | **Skip** | Plex client is throttled at 200/min and synchronous is fine. `httpx` buys nothing concrete. |
| Structured logging (`structlog` or plain `logging` JSON) | **Do it with GCP migration** | GCP Cloud Logging parses structured JSON natively. Align with the `datum-runtime` deploy, not this phase. |
| `pytest-postgresql` for DB tests | **Do it, with SQLAlchemy** | Pairs with the primary stack change. |

### Stack change file surface

| File | Change |
|---|---|
| `datum/db/client.py` | SQLAlchemy `Engine` + `sessionmaker` replaces Supabase client |
| `datum/db/models.py` | New — declarative models for all 4 tables |
| `datum/sync/staging.py`, `datum/sync/inventory.py`, `datum/sync/supply_items.py`, `datum/sync/enrich.py`, `datum/db/ingest.py` | Swap Supabase API calls for SQLAlchemy session ops |
| `datum/web/routes/*.py` | Swap Supabase reads for SQLAlchemy query objects |
| `requirements.txt` | Drop `supabase`, add `sqlalchemy>=2`, `psycopg[binary]>=3`, `alembic` (optional — for migrations going forward) |
| `pyproject.toml` | Add `[tool.ruff]` config |
| `tests/conftest.py` | Swap Supabase REST mocks for a `pytest-postgresql` fixture or SQLAlchemy in-memory SQLite |
| All test files that mock Supabase | Update fixtures |

---

## Phase 3: React UI — lock the scope

No code changes in this phase — just a docs pass that makes the scope
boundaries visible on the UI itself and in the repo.

- Add a "scope" section to `README.md` under the UI section: "debug +
  show-and-tell; no mobile; feature requests need a documented use case."
- Add a small footer to the React UI (`web/src/components/Footer.tsx`
  or similar) that links to the scope statement. Makes the boundary
  visible where the users actually are.
- `web/README.md` (if it doesn't exist) — one-page statement of what
  the UI is for, who owns it (Shane), and what the contribution bar is.
- No mobile-related dependencies in `web/package.json`. No PWA manifest.
  No responsive-design retrofit.

Cost: one PR, maybe 20 LOC + two doc paragraphs. Pays for itself the
first time someone asks "why doesn't this work on my phone."

---

## Sequencing

Suggested order, with rough effort estimates:

1. **Reorg PRs A → D** (Phase 1) — ~4 PRs, ~1 day each if done in one
   pass. Tests should stay green throughout — these are pure moves.
2. **Stack update: SQLAlchemy + psycopg3** (Phase 2 primary) — ~1 week.
   Biggest risk is test fixture rewrites. Land behind a feature flag
   (`DATUM_USE_SQLALCHEMY=1`) so Supabase client stays in place as the
   fallback during bring-up.
3. **Stack update: ruff + uv** (Phase 2 secondary) — ~half a day total.
   Low risk, immediate payoff.
4. **UI scope doc pass** (Phase 3) — ~1 PR, under an hour.
5. **Now ready for GCP migration (#85)** — Cloud SQL cutover is a
   connection string flip, APS was already primary, Cloudflare DNS
   already points at Workers.

Everything below #5 (Phase 5 deploy items, etc.) is already done.

---

## Open questions

- **Should the DB schema move from raw SQL in `db/migrations/` to
  Alembic?** Alembic is nicer for collaborative schema changes but you're
  the only dev touching it. Weigh against: raw SQL is simpler to read,
  Cloud SQL accepts both, Alembic adds a dependency. Default: **stay
  with raw SQL until there are 2+ devs.**
- **Should `run_dev.py` stay at the repo root or move under `datum/`?**
  Root is friendlier for `py run_dev.py` muscle memory. `datum/` is more
  correct. Default: **leave at root**, it's a dev-only file.
- **Do we write `web/README.md` now or when other engineers ask to
  contribute?** Writing it now is cheap and prevents the "everyone asks"
  drift. Default: **now, alongside Phase 3**.
- **Structured logging in Phase 2 or Phase 6 (#85)?** Doing it now makes
  the GCP cutover cleaner but couples two unrelated changes. Default:
  **defer to Phase 6**, keep this plan focused.
- **Do we keep `supabase_client.py` side-by-side during SQLAlchemy bring-up
  for a dual-write period, or cut over in one commit?** Dual-write is
  safer but adds temporary complexity. Given the Supabase DB is
  single-tenant and low-volume, a single-commit cutover is probably fine,
  but the feature-flag approach gives you an escape hatch. Default:
  **feature-flag, flip when tests pass.**
