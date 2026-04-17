"""
One-off: hit real connect.plex.com and persist GET responses for the two
endpoints the mock needs to serve. Commit the output files.

Run with credentials loaded the usual way (.env.local + bootstrap.py):

    python -m tools.plex_mock.capture_snapshots

Refresh when the Plex shape changes. This script only GETs — safe to
run any time without the PLEX_ALLOW_WRITES guard.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from plex_api import API_KEY, API_SECRET, TENANT_ID, USE_TEST, PlexClient


SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


def capture(client: PlexClient, collection: str, version: str, resource: str, outfile: str) -> int:
    env = client.get_envelope(collection, version, resource)
    if not env["ok"]:
        print(f"  FAILED {collection}/{version}/{resource}: HTTP {env['status']}", file=sys.stderr)
        return 1
    data = env["body"]
    out = SNAPSHOTS_DIR / outfile
    out.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    count = len(data) if isinstance(data, list) else 1
    print(f"  wrote {out.relative_to(Path.cwd())} ({count} records, {out.stat().st_size} bytes)")
    return 0


def main() -> int:
    if not API_KEY:
        print("PLEX_API_KEY is not set; can't capture snapshots.", file=sys.stderr)
        return 2
    client = PlexClient(API_KEY, API_SECRET, TENANT_ID, use_test=USE_TEST)
    rc = 0
    rc |= capture(client, "inventory", "v1", "inventory-definitions/supply-items",
                  "supply_items_list.json")
    rc |= capture(client, "production", "v1", "production-definitions/workcenters",
                  "workcenters_list.json")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
