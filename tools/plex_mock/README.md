# Plex-Mimic Mock

Local HTTP server mirroring the Plex REST surface for write-pipeline
validation. Tracked in [#92](https://github.com/grace-shane/Datum/issues/92);
blocks [#3](https://github.com/grace-shane/Datum/issues/3) and
[#6](https://github.com/grace-shane/Datum/issues/6).

## Quick start

```bash
# Refresh snapshots from real Plex (read-only; safe to re-run)
python -m tools.plex_mock.capture_snapshots

# Start the mock on localhost:8080
python -m tools.plex_mock.server --run-id $(date +%Y%m%d-%H%M%S)

# In another shell: point the sync at it
PLEX_BASE_URL=http://127.0.0.1:8080 \
PLEX_ALLOW_WRITES=1 \
  datum-sync

# After the run: diff captures against the expected payload shape
python -m tools.plex_mock.diff \
  --run-id <run-id from first command> \
  --db tools/plex_mock/captures.db \
  --expected tests/fixtures/plex_mock/expected_supply_items.json
```

## What it serves

| Endpoint | Behavior |
|---|---|
| `GET  /healthz` | liveness probe, returns `{"ok": true}` |
| `GET  /inventory/v1/inventory-definitions/supply-items` | serves `snapshots/supply_items_list.json` |
| `GET  /inventory/v1/inventory-definitions/supply-items/{id}` | one record from the snapshot; 404 if unknown |
| `POST /inventory/v1/inventory-definitions/supply-items` | captures body, returns 201 with synthetic UUID; 409 if `supplyItemNumber` collides with snapshot |
| `PUT  /inventory/v1/inventory-definitions/supply-items/{id}` | captures body, merges over snapshot record, returns 200; 404 if unknown |
| `GET  /production/v1/production-definitions/workcenters` | serves `snapshots/workcenters_list.json` |
| `GET  /production/v1/production-definitions/workcenters/{id}` | one record; 404 if unknown |
| `PUT/PATCH /production/v1/production-definitions/workcenters/{id}` | captures body, returns merged record (the #6 probe path) |

Every write lands in `captures.db` keyed by `run_id` for later diffing.

## Validation-window protocol

Before we flip `PLEX_ALLOW_WRITES=1` against real `connect.plex.com`:

1. Three consecutive `datum-sync` runs against the mock produce identical capture sets (same count, same payload shapes).
2. `datum-plex-mock-diff` reports CLEAN against `expected_supply_items.json` for all three runs.
3. Rehearsal notes in `tools/plex_mock/REHEARSAL_NOTES.md` document at least one full mock-sync cycle end-to-end.
4. Only then: PR that enables writes to real Plex, and only with explicit Shane approval in the PR description.

The mock is the validation surface. `test.connect.plex.com` (`PLEX_USE_TEST=1`) is not — the Datum Consumer Key only authenticates against production (see `docs/BRIEFING.md`).

## Deploy on `datum-runtime`

See `tools/plex_mock/systemd/datum-plex-mock.service`. Copy into
`/etc/systemd/system/`, `systemctl daemon-reload && systemctl enable --now datum-plex-mock`.
Bound to `127.0.0.1:8080` — no external exposure, no TLS needed.
