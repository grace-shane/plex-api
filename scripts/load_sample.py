"""
scripts/load_sample.py
Smoke test — ingest BROTHER SPEEDIO ALUMINUM.json into Supabase
================================================================
Loads the committed sample Fusion library file into the Datum
``libraries``/``tools``/``cutting_presets`` tables and prints a
row-count report.

Run from the repo root::

    py scripts/load_sample.py

Expected output with a fresh database (28 total entries in the sample,
minus 6 holders + 1 probe = 21 tools, ~25 presets)::

    Library upserted: BROTHER SPEEDIO ALUMINUM → id=...
    Tools upserted:   21
    Presets inserted: 25

Re-running the script should be idempotent — tool counts stay the
same, presets are flushed and re-inserted. Requires SUPABASE_URL
and SUPABASE_SERVICE_ROLE_KEY in .env.local (or the shell env).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make the repo root importable when running ``py scripts/load_sample.py``.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supabase_client import SupabaseClient, SupabaseConfigError  # noqa: E402
from sync_supabase import hash_file, sync_library  # noqa: E402


SAMPLE_FILE = ROOT / "BROTHER SPEEDIO ALUMINUM.json"
LIBRARY_NAME = "BROTHER SPEEDIO ALUMINUM"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not SAMPLE_FILE.exists():
        print(f"ERROR: sample file not found at {SAMPLE_FILE}", file=sys.stderr)
        return 2

    # Load tools from disk without going through the stale-file guard —
    # the committed sample is always older than 25h, but we still want to
    # exercise the ingest pipeline against it.
    import json

    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    tools = raw.get("data", [])
    print(f"Loaded {len(tools)} entries from {SAMPLE_FILE.name}")

    try:
        client = SupabaseClient()
    except SupabaseConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            "\nAdd these to .env.local:\n"
            "  SUPABASE_URL=https://<your-datum-project-ref>.supabase.co\n"
            "  SUPABASE_SERVICE_ROLE_KEY=<service role JWT>\n",
            file=sys.stderr,
        )
        return 3

    file_hash = hash_file(SAMPLE_FILE)
    print(f"File hash (sha256): {file_hash[:16]}...")

    result = sync_library(
        LIBRARY_NAME,
        tools,
        client=client,
        file_path=str(SAMPLE_FILE),
        file_hash=file_hash,
    )

    print()
    print("=" * 56)
    print(f"  Tools upserted:    {result['tools']:4d}")
    print(f"  Presets inserted:  {result['presets']:4d}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
