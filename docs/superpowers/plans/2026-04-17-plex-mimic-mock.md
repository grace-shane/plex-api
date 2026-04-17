# Plex-Mimic Mock HTTP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a local HTTP server that mimics the Plex REST surface (supply-items + workcenters) so `datum-sync` can dress-rehearse writes without touching `connect.plex.com`. Blocks issues [#3](https://github.com/grace-shane/Datum/issues/3) and [#6](https://github.com/grace-shane/Datum/issues/6); tracked in [#92](https://github.com/grace-shane/Datum/issues/92).

**Architecture:** Flask app deployed as a systemd unit on `datum-runtime`, bound to `127.0.0.1:8080`. GET handlers serve canned snapshots captured once from real Plex; POST/PUT/PATCH handlers log the full request to SQLite and return Plex-shape responses with synthetic UUIDs. `plex_api.py` gets a `PLEX_BASE_URL` env override so the sync points at the mock with no code branches. A diff CLI reports payload drift between a mock run's captures and an expected-payload fixture.

**Tech Stack:** Flask (already in `app.py`), SQLite (stdlib), pytest + monkeypatch (existing test conventions), systemd on Ubuntu 24.04 (`datum-runtime`).

---

## File Structure

**Create:**
- `tools/__init__.py` — empty package marker
- `tools/plex_mock/__init__.py` — package marker + version constant
- `tools/plex_mock/server.py` — Flask app, route handlers
- `tools/plex_mock/store.py` — SQLite capture store (create/append/query)
- `tools/plex_mock/snapshots/README.md` — how to refresh
- `tools/plex_mock/snapshots/supply_items_list.json` — canned GET response (committed)
- `tools/plex_mock/snapshots/workcenters_list.json` — canned GET response (committed)
- `tools/plex_mock/capture_snapshots.py` — one-off CLI that hits real Plex and writes the snapshot files
- `tools/plex_mock/diff.py` — CLI that compares captures vs expected fixture
- `tools/plex_mock/systemd/datum-plex-mock.service` — systemd unit (deployed, not auto-installed)
- `tools/plex_mock/README.md` — how to run, how to deploy, validation-window protocol
- `tests/test_plex_mock_store.py`
- `tests/test_plex_mock_server.py`
- `tests/test_plex_mock_diff.py`
- `tests/fixtures/plex_mock/expected_supply_items.json` — reference payload shape for the diff CLI

**Modify:**
- `plex_api.py:49-63` — add `PLEX_BASE_URL` override; extend `PlexClient.__init__` with an optional `base_url` arg
- `tests/test_plex_api.py:66-80` — new tests covering the override
- `pyproject.toml` — add three console scripts (`datum-plex-mock-serve`, `datum-plex-mock-snapshot`, `datum-plex-mock-diff`)
- `docs/Plex_API_Reference.md` — one-paragraph section on `PLEX_BASE_URL` + the mock
- `.gitignore` — ignore `tools/plex_mock/captures/` and `tools/plex_mock/*.db`

**Don't touch:** `bootstrap.py` (already reads env via `setdefault`; no change needed for `PLEX_BASE_URL` to flow through).

---

## Task 1: `PLEX_BASE_URL` override in `plex_api.py` (TDD)

Smallest, safest chunk. Additive, no behavior change when unset. Can land immediately, independent of the rest.

**Files:**
- Modify: `plex_api.py:49-53` (module-level constants), `plex_api.py:61-63` (client constructor)
- Modify: `tests/test_plex_api.py` — add tests to `TestPlexClientEnvironment` and `TestModuleDefaults`

- [ ] **Step 1.1: Write failing tests for the override**

Append to `tests/test_plex_api.py`, inside class `TestPlexClientEnvironment`:

```python
    def test_explicit_base_url_arg_wins(self):
        c = PlexClient(api_key="k", base_url="http://localhost:8080")
        assert c.base == "http://localhost:8080"

    def test_explicit_base_url_arg_wins_even_over_use_test(self):
        c = PlexClient(api_key="k", use_test=True, base_url="http://localhost:8080")
        assert c.base == "http://localhost:8080"
```

Append to class `TestModuleDefaults`:

```python
    def test_override_url_empty_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("PLEX_BASE_URL", raising=False)
        importlib.reload(plex_api)
        assert plex_api.OVERRIDE_URL == ""
        importlib.reload(plex_api)

    def test_override_url_set_from_env(self, monkeypatch):
        monkeypatch.setenv("PLEX_BASE_URL", "http://localhost:8080")
        importlib.reload(plex_api)
        assert plex_api.OVERRIDE_URL == "http://localhost:8080"
        importlib.reload(plex_api)

    def test_client_uses_override_url_when_env_set(self, monkeypatch):
        monkeypatch.setenv("PLEX_BASE_URL", "http://localhost:8080")
        importlib.reload(plex_api)
        c = plex_api.PlexClient(api_key="k")
        assert c.base == "http://localhost:8080"
        importlib.reload(plex_api)

    def test_client_override_url_wins_over_use_test(self, monkeypatch):
        monkeypatch.setenv("PLEX_BASE_URL", "http://localhost:8080")
        importlib.reload(plex_api)
        c = plex_api.PlexClient(api_key="k", use_test=True)
        assert c.base == "http://localhost:8080"
        importlib.reload(plex_api)

    def test_client_unchanged_when_override_unset(self, monkeypatch):
        monkeypatch.delenv("PLEX_BASE_URL", raising=False)
        importlib.reload(plex_api)
        c = plex_api.PlexClient(api_key="k")
        assert c.base == plex_api.BASE_URL
        importlib.reload(plex_api)
```

- [ ] **Step 1.2: Run the new tests; expect failures**

Run: `python -m pytest tests/test_plex_api.py::TestPlexClientEnvironment::test_explicit_base_url_arg_wins tests/test_plex_api.py::TestModuleDefaults::test_override_url_empty_when_env_unset -v`

Expected: both fail with `AttributeError: module 'plex_api' has no attribute 'OVERRIDE_URL'` / `TypeError: __init__() got an unexpected keyword argument 'base_url'`.

- [ ] **Step 1.3: Add the module-level constant**

In `plex_api.py`, replace lines 49-53:

```python
BASE_URL = "https://connect.plex.com"
TEST_URL = "https://test.connect.plex.com"
USE_TEST = os.environ.get("PLEX_USE_TEST", "").strip().lower() in (
    "1", "true", "yes", "on", "enabled",
)
```

with:

```python
BASE_URL = "https://connect.plex.com"
TEST_URL = "https://test.connect.plex.com"
# PLEX_BASE_URL — explicit override for the Plex base URL (e.g. the local
# mock at tools/plex_mock/server.py running on localhost:8080). Empty
# string means "no override"; BASE_URL / TEST_URL selection applies.
# Used by the write-validation workflow in issue #92 so the sync can
# dress-rehearse against a fake-Plex without touching connect.plex.com.
OVERRIDE_URL = os.environ.get("PLEX_BASE_URL", "").strip()
USE_TEST = os.environ.get("PLEX_USE_TEST", "").strip().lower() in (
    "1", "true", "yes", "on", "enabled",
)
```

- [ ] **Step 1.4: Extend the client constructor**

In `plex_api.py:61-63`, replace:

```python
class PlexClient:
    def __init__(self, api_key, api_secret="", tenant_id="", use_test=False):
        self.base = TEST_URL if use_test else BASE_URL
```

with:

```python
class PlexClient:
    def __init__(self, api_key, api_secret="", tenant_id="", use_test=False, base_url=None):
        # Resolution order:
        #   1. explicit base_url kwarg (tests, ad-hoc scripts)
        #   2. PLEX_BASE_URL env var (deployment-time override — the mock)
        #   3. TEST_URL if use_test else BASE_URL (original behavior)
        if base_url:
            self.base = base_url
        elif OVERRIDE_URL:
            self.base = OVERRIDE_URL
        else:
            self.base = TEST_URL if use_test else BASE_URL
```

- [ ] **Step 1.5: Run the tests; expect all green**

Run: `python -m pytest tests/test_plex_api.py -v`

Expected: all tests pass, including the new 7.

- [ ] **Step 1.6: Commit**

```bash
git add plex_api.py tests/test_plex_api.py
git commit -m "feat(plex-api): PLEX_BASE_URL override + base_url client kwarg (#92)"
```

---

## Task 2: `tools/plex_mock/` package scaffold

Lay down the directory skeleton and `.gitignore` rules so later tasks can drop files in without restructuring.

**Files:**
- Create: `tools/__init__.py`, `tools/plex_mock/__init__.py`, `tools/plex_mock/README.md`, `tools/plex_mock/snapshots/README.md`
- Modify: `.gitignore`

- [ ] **Step 2.1: Create the package markers**

```bash
mkdir -p tools/plex_mock/snapshots tools/plex_mock/systemd
```

Create `tools/__init__.py` with:

```python
"""Internal tooling for the Datum project (not packaged for distribution)."""
```

Create `tools/plex_mock/__init__.py` with:

```python
"""
Local mock HTTP server mirroring the Plex REST surface for write-pipeline
validation. See tools/plex_mock/README.md and issue #92.
"""
__version__ = "0.1.0"
```

- [ ] **Step 2.2: Stub the READMEs**

Create `tools/plex_mock/README.md` with (placeholder — filled out in Task 9):

```markdown
# Plex-Mimic Mock

Local HTTP server mimicking the Plex REST surface. See issue #92 and
`docs/superpowers/plans/2026-04-17-plex-mimic-mock.md` for the full plan.

Full usage + validation-window protocol lands in Task 9 of the plan.
```

Create `tools/plex_mock/snapshots/README.md` with:

```markdown
# Canned GET snapshots

JSON responses captured from real `connect.plex.com` so the mock can
serve realistic GETs without a live-Plex dependency. Refresh via
`python -m tools.plex_mock.capture_snapshots` when Plex shapes change.

Files here are committed. Ad-hoc mock captures (POSTs the sync sent)
live in `tools/plex_mock/captures/` which is gitignored.
```

- [ ] **Step 2.3: Update `.gitignore`**

Append to `.gitignore`:

```
# Plex mock — ephemeral capture data (POSTs the sync sent against the mock)
tools/plex_mock/captures/
tools/plex_mock/*.db
tools/plex_mock/*.db-journal
```

- [ ] **Step 2.4: Commit**

```bash
git add tools/ .gitignore
git commit -m "feat(plex-mock): package scaffold for Plex-mimic mock (#92)"
```

---

## Task 3: SQLite capture store (TDD)

Pure-Python module, no Flask dep. Append-only store of every POST/PUT/PATCH the mock sees, queryable by the diff CLI.

**Files:**
- Create: `tools/plex_mock/store.py`
- Create: `tests/test_plex_mock_store.py`

- [ ] **Step 3.1: Write the failing tests**

Create `tests/test_plex_mock_store.py`:

```python
"""Tests for the Plex-mock SQLite capture store."""
import json
import sqlite3
from pathlib import Path

import pytest

from tools.plex_mock.store import CaptureStore


@pytest.fixture
def store(tmp_path: Path) -> CaptureStore:
    return CaptureStore(tmp_path / "captures.db")


class TestCaptureStoreInit:
    def test_creates_db_file_on_open(self, tmp_path: Path):
        db = tmp_path / "captures.db"
        assert not db.exists()
        CaptureStore(db)
        assert db.exists()

    def test_creates_table_schema(self, store: CaptureStore):
        with sqlite3.connect(store.path) as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(captures)")}
        assert {"id", "ts", "method", "path", "body_json", "run_id"} <= cols


class TestCaptureStoreAppend:
    def test_append_returns_integer_id(self, store: CaptureStore):
        rid = store.append(method="POST", path="/foo", body={"a": 1}, run_id="r1")
        assert isinstance(rid, int)
        assert rid >= 1

    def test_append_persists_row(self, store: CaptureStore):
        store.append(method="POST", path="/foo", body={"a": 1}, run_id="r1")
        rows = store.query(run_id="r1")
        assert len(rows) == 1
        assert rows[0]["method"] == "POST"
        assert rows[0]["path"] == "/foo"
        assert rows[0]["body"] == {"a": 1}
        assert rows[0]["run_id"] == "r1"

    def test_append_stores_body_as_json(self, store: CaptureStore):
        payload = {"nested": {"k": [1, 2, 3]}}
        store.append(method="PUT", path="/x", body=payload, run_id="r1")
        with sqlite3.connect(store.path) as con:
            raw = con.execute("SELECT body_json FROM captures").fetchone()[0]
        assert json.loads(raw) == payload

    def test_append_handles_null_body(self, store: CaptureStore):
        store.append(method="PATCH", path="/x", body=None, run_id="r1")
        rows = store.query(run_id="r1")
        assert rows[0]["body"] is None


class TestCaptureStoreQuery:
    def test_query_filters_by_run_id(self, store: CaptureStore):
        store.append(method="POST", path="/a", body={}, run_id="r1")
        store.append(method="POST", path="/b", body={}, run_id="r2")
        assert len(store.query(run_id="r1")) == 1
        assert len(store.query(run_id="r2")) == 1

    def test_query_filters_by_method(self, store: CaptureStore):
        store.append(method="POST", path="/a", body={}, run_id="r1")
        store.append(method="PUT", path="/a", body={}, run_id="r1")
        assert len(store.query(run_id="r1", method="POST")) == 1
        assert len(store.query(run_id="r1", method="PUT")) == 1

    def test_query_orders_by_id_ascending(self, store: CaptureStore):
        store.append(method="POST", path="/a", body={"n": 1}, run_id="r1")
        store.append(method="POST", path="/b", body={"n": 2}, run_id="r1")
        rows = store.query(run_id="r1")
        assert [r["body"]["n"] for r in rows] == [1, 2]

    def test_query_empty_when_no_match(self, store: CaptureStore):
        assert store.query(run_id="nope") == []
```

- [ ] **Step 3.2: Run tests; expect import failure**

Run: `python -m pytest tests/test_plex_mock_store.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'tools.plex_mock.store'`.

- [ ] **Step 3.3: Implement the store**

Create `tools/plex_mock/store.py`:

```python
"""
SQLite-backed capture store for the Plex-mimic mock.

Every POST/PUT/PATCH the mock server sees is appended here so the
diff CLI (#92) can report what the sync *would have* sent to real
Plex, and three-runs-in-a-row idempotency checks can compare run sets.

Append-only by design — no update/delete path. Gitignored; survives
mock restarts.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT    NOT NULL,
  method    TEXT    NOT NULL,
  path      TEXT    NOT NULL,
  body_json TEXT,
  run_id    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS captures_run_id_idx ON captures(run_id);
CREATE INDEX IF NOT EXISTS captures_run_method_idx ON captures(run_id, method);
"""


class CaptureStore:
    """Thin wrapper around a SQLite file used as an append-only capture log."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.executescript(SCHEMA)

    def append(
        self,
        *,
        method: str,
        path: str,
        body: Any,
        run_id: str,
    ) -> int:
        """Record one captured request. Returns the rowid."""
        ts = datetime.now(timezone.utc).isoformat()
        body_json = json.dumps(body) if body is not None else None
        with sqlite3.connect(self.path) as con:
            cur = con.execute(
                "INSERT INTO captures (ts, method, path, body_json, run_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, method, path, body_json, run_id),
            )
            return cur.lastrowid

    def query(
        self,
        *,
        run_id: str,
        method: str | None = None,
    ) -> list[dict]:
        """Return all captures for a run, oldest first. Optional method filter."""
        sql = "SELECT id, ts, method, path, body_json, run_id FROM captures WHERE run_id = ?"
        args: list[Any] = [run_id]
        if method is not None:
            sql += " AND method = ?"
            args.append(method)
        sql += " ORDER BY id ASC"
        with sqlite3.connect(self.path) as con:
            rows = con.execute(sql, args).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "method": r[2],
                "path": r[3],
                "body": json.loads(r[4]) if r[4] is not None else None,
                "run_id": r[5],
            }
            for r in rows
        ]
```

- [ ] **Step 3.4: Run tests; expect all green**

Run: `python -m pytest tests/test_plex_mock_store.py -v`

Expected: all 10 tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add tools/plex_mock/store.py tests/test_plex_mock_store.py
git commit -m "feat(plex-mock): SQLite capture store (#92)"
```

---

## Task 4: Snapshot capture script

One-off CLI that hits real Plex and writes the GET snapshots we'll serve from the mock. Read-only against live Plex — safe.

**Files:**
- Create: `tools/plex_mock/capture_snapshots.py`
- Will produce: `tools/plex_mock/snapshots/supply_items_list.json`, `tools/plex_mock/snapshots/workcenters_list.json`

No unit tests in this task — it's an I/O-bound one-off. Tests for the snapshot-serving path live in Task 5.

- [ ] **Step 4.1: Implement the capture CLI**

Create `tools/plex_mock/capture_snapshots.py`:

```python
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
```

- [ ] **Step 4.2: Sanity-run the script locally**

Run: `python -m tools.plex_mock.capture_snapshots`

Expected (with live creds in `.env.local`): two files written under `tools/plex_mock/snapshots/`, roughly 30 KB and ~10 KB respectively, printed confirmation lines.

Expected (no creds): exit code 2 and error message about `PLEX_API_KEY`.

- [ ] **Step 4.3: Review the captured files**

Run: `wc -l tools/plex_mock/snapshots/*.json`

Open each file and eyeball: the arrays should have the expected record counts (supply-items ~2,500; workcenters ~143 per `docs/BRIEFING.md`).

- [ ] **Step 4.4: Commit the script + captured snapshots**

```bash
git add tools/plex_mock/capture_snapshots.py \
        tools/plex_mock/snapshots/supply_items_list.json \
        tools/plex_mock/snapshots/workcenters_list.json
git commit -m "feat(plex-mock): snapshot capture CLI + initial snapshots (#92)"
```

*If credentials aren't available in the execution environment, commit just the script and flag to Shane that the snapshots need to be captured on a VM that has live-Plex creds. Task 5 can proceed with stub snapshots in the meantime.*

---

## Task 5: Flask mock server — GET handlers (TDD)

GET routes serve the captured snapshots. Tests use Flask's test client against fixture JSON; no real HTTP server started.

**Files:**
- Create: `tools/plex_mock/server.py`
- Create: `tests/test_plex_mock_server.py`

- [ ] **Step 5.1: Write failing tests**

Create `tests/test_plex_mock_server.py`:

```python
"""Tests for the Plex-mock Flask server."""
import json
from pathlib import Path

import pytest

from tools.plex_mock.server import create_app


@pytest.fixture
def snapshots_dir(tmp_path: Path) -> Path:
    d = tmp_path / "snapshots"
    d.mkdir()
    supply = [
        {"id": "11111111-1111-1111-1111-111111111111", "supplyItemNumber": "ABC-1",
         "description": "Test tool", "category": "Tools & Inserts",
         "group": "Machining - End Mills", "inventoryUnit": "Ea", "type": "SUPPLY"},
        {"id": "22222222-2222-2222-2222-222222222222", "supplyItemNumber": "ABC-2",
         "description": "Test tool 2", "category": "Tools & Inserts",
         "group": "Machining - Drills", "inventoryUnit": "Ea", "type": "SUPPLY"},
    ]
    workcenters = [
        {"workcenterId": "0b6cf62b-2809-4d3d-ab24-369cd0171f62",
         "workcenterCode": "879", "name": "Brother Speedio 879",
         "workcenterGroup": "MILLS"},
    ]
    (d / "supply_items_list.json").write_text(json.dumps(supply))
    (d / "workcenters_list.json").write_text(json.dumps(workcenters))
    return d


@pytest.fixture
def client(tmp_path: Path, snapshots_dir: Path):
    app = create_app(snapshots_dir=snapshots_dir, db_path=tmp_path / "captures.db", run_id="test-run")
    return app.test_client()


class TestSupplyItemsGetList:
    def test_returns_200(self, client):
        rv = client.get("/inventory/v1/inventory-definitions/supply-items")
        assert rv.status_code == 200

    def test_returns_snapshot_body(self, client):
        rv = client.get("/inventory/v1/inventory-definitions/supply-items")
        body = rv.get_json()
        assert isinstance(body, list)
        assert len(body) == 2
        assert body[0]["supplyItemNumber"] == "ABC-1"


class TestSupplyItemsGetById:
    def test_returns_200_when_found(self, client):
        rv = client.get("/inventory/v1/inventory-definitions/supply-items/11111111-1111-1111-1111-111111111111")
        assert rv.status_code == 200
        assert rv.get_json()["supplyItemNumber"] == "ABC-1"

    def test_returns_404_when_unknown(self, client):
        rv = client.get("/inventory/v1/inventory-definitions/supply-items/does-not-exist")
        assert rv.status_code == 404


class TestWorkcentersGet:
    def test_returns_200_list(self, client):
        rv = client.get("/production/v1/production-definitions/workcenters")
        assert rv.status_code == 200
        assert len(rv.get_json()) == 1

    def test_returns_200_by_id(self, client):
        rv = client.get("/production/v1/production-definitions/workcenters/0b6cf62b-2809-4d3d-ab24-369cd0171f62")
        assert rv.status_code == 200
        assert rv.get_json()["workcenterCode"] == "879"

    def test_returns_404_for_unknown_workcenter(self, client):
        rv = client.get("/production/v1/production-definitions/workcenters/nope")
        assert rv.status_code == 404


class TestHealth:
    def test_health_endpoint(self, client):
        rv = client.get("/healthz")
        assert rv.status_code == 200
        assert rv.get_json() == {"ok": True}
```

- [ ] **Step 5.2: Run tests; expect import failure**

Run: `python -m pytest tests/test_plex_mock_server.py -v`

Expected: `ModuleNotFoundError: No module named 'tools.plex_mock.server'`.

- [ ] **Step 5.3: Implement `create_app` with GET routes**

Create `tools/plex_mock/server.py`:

```python
"""
Flask app mimicking the Plex REST endpoints the sync writes to.
GETs serve canned snapshots from disk; POST/PUT/PATCH handlers land
in Task 6 (this file grows, the tests drive the shape).

Bound to 127.0.0.1 by the systemd unit — never expose publicly.
Issue: #92.
"""
from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, abort, jsonify

from tools.plex_mock.store import CaptureStore


def _load_snapshot(snapshots_dir: Path, name: str) -> list[dict]:
    path = snapshots_dir / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def create_app(
    *,
    snapshots_dir: Path,
    db_path: Path,
    run_id: str,
) -> Flask:
    app = Flask(__name__)
    app.config["PLEX_MOCK_SNAPSHOTS_DIR"] = snapshots_dir
    app.config["PLEX_MOCK_STORE"] = CaptureStore(db_path)
    app.config["PLEX_MOCK_RUN_ID"] = run_id

    supply_items = _load_snapshot(snapshots_dir, "supply_items_list.json")
    workcenters = _load_snapshot(snapshots_dir, "workcenters_list.json")
    supply_by_id = {rec["id"]: rec for rec in supply_items}
    workcenter_by_id = {rec["workcenterId"]: rec for rec in workcenters}

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.get("/inventory/v1/inventory-definitions/supply-items")
    def supply_items_list():
        return jsonify(supply_items)

    @app.get("/inventory/v1/inventory-definitions/supply-items/<item_id>")
    def supply_items_get(item_id: str):
        rec = supply_by_id.get(item_id)
        if rec is None:
            abort(404)
        return jsonify(rec)

    @app.get("/production/v1/production-definitions/workcenters")
    def workcenters_list():
        return jsonify(workcenters)

    @app.get("/production/v1/production-definitions/workcenters/<wc_id>")
    def workcenter_get(wc_id: str):
        rec = workcenter_by_id.get(wc_id)
        if rec is None:
            abort(404)
        return jsonify(rec)

    return app


def main() -> int:
    """Console-script entry (datum-plex-mock-serve)."""
    import argparse
    import uuid

    ap = argparse.ArgumentParser(description="Plex-mimic mock server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--snapshots", default=Path(__file__).parent / "snapshots")
    ap.add_argument("--db", default=Path(__file__).parent / "captures.db")
    ap.add_argument("--run-id", default=None, help="Override run_id (default: random uuid4)")
    args = ap.parse_args()

    app = create_app(
        snapshots_dir=Path(args.snapshots),
        db_path=Path(args.db),
        run_id=args.run_id or str(uuid.uuid4()),
    )
    print(f"plex-mock serving on http://{args.host}:{args.port} run_id={app.config['PLEX_MOCK_RUN_ID']}")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5.4: Run tests; expect all green**

Run: `python -m pytest tests/test_plex_mock_server.py -v`

Expected: all 8 tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add tools/plex_mock/server.py tests/test_plex_mock_server.py
git commit -m "feat(plex-mock): Flask server + GET snapshot handlers (#92)"
```

---

## Task 6: POST/PUT/PATCH capture handlers (TDD)

Writes to the mock are captured to SQLite and return a Plex-shape response with a synthetic UUID. No state mutation between requests — every POST "succeeds" with a fresh UUID; every PUT/PATCH echoes the body back with `id` preserved if present.

**Files:**
- Modify: `tools/plex_mock/server.py` — add write handlers
- Modify: `tests/test_plex_mock_server.py` — add write-handler tests

- [ ] **Step 6.1: Write failing tests**

Append to `tests/test_plex_mock_server.py`:

```python
import uuid


class TestSupplyItemsPost:
    def test_post_returns_201_with_synthetic_id(self, client):
        payload = {"supplyItemNumber": "NEW-1", "description": "New tool",
                   "category": "Tools & Inserts", "group": "Machining - End Mills",
                   "inventoryUnit": "Ea", "type": "SUPPLY"}
        rv = client.post("/inventory/v1/inventory-definitions/supply-items", json=payload)
        assert rv.status_code == 201
        body = rv.get_json()
        assert "id" in body
        uuid.UUID(body["id"])  # valid uuid4
        assert body["supplyItemNumber"] == "NEW-1"

    def test_post_echoes_payload_fields(self, client):
        payload = {"supplyItemNumber": "NEW-2", "description": "x",
                   "group": "Machining - Drills", "inventoryUnit": "Ea",
                   "category": "Tools & Inserts", "type": "SUPPLY"}
        rv = client.post("/inventory/v1/inventory-definitions/supply-items", json=payload)
        body = rv.get_json()
        for k, v in payload.items():
            assert body[k] == v

    def test_post_persists_to_capture_store(self, client):
        from tools.plex_mock.store import CaptureStore
        payload = {"supplyItemNumber": "NEW-3"}
        client.post("/inventory/v1/inventory-definitions/supply-items", json=payload)
        store: CaptureStore = client.application.config["PLEX_MOCK_STORE"]
        rows = store.query(run_id=client.application.config["PLEX_MOCK_RUN_ID"])
        assert len(rows) == 1
        assert rows[0]["method"] == "POST"
        assert rows[0]["path"].endswith("/supply-items")
        assert rows[0]["body"]["supplyItemNumber"] == "NEW-3"

    def test_post_409_on_duplicate_supply_item_number(self, client):
        # Snapshot already has "ABC-1" — mock should treat that as a conflict
        payload = {"supplyItemNumber": "ABC-1", "description": "dup"}
        rv = client.post("/inventory/v1/inventory-definitions/supply-items", json=payload)
        assert rv.status_code == 409


class TestSupplyItemsPut:
    def test_put_200_and_captured(self, client):
        payload = {"description": "updated description"}
        rv = client.put(
            "/inventory/v1/inventory-definitions/supply-items/11111111-1111-1111-1111-111111111111",
            json=payload,
        )
        assert rv.status_code == 200
        assert rv.get_json()["description"] == "updated description"

        store = client.application.config["PLEX_MOCK_STORE"]
        rows = store.query(run_id=client.application.config["PLEX_MOCK_RUN_ID"], method="PUT")
        assert len(rows) == 1

    def test_put_404_on_unknown_id(self, client):
        rv = client.put(
            "/inventory/v1/inventory-definitions/supply-items/not-a-real-id",
            json={"description": "x"},
        )
        assert rv.status_code == 404


class TestWorkcenterWrites:
    def test_put_workcenter_captured(self, client):
        # #6 probe — we don't yet know the body shape, just confirm the mock
        # records whatever we send it.
        payload = {"unknownFieldForProbe": True}
        rv = client.put(
            "/production/v1/production-definitions/workcenters/0b6cf62b-2809-4d3d-ab24-369cd0171f62",
            json=payload,
        )
        assert rv.status_code == 200
        store = client.application.config["PLEX_MOCK_STORE"]
        rows = store.query(run_id=client.application.config["PLEX_MOCK_RUN_ID"], method="PUT")
        assert any(r["body"].get("unknownFieldForProbe") is True for r in rows)

    def test_patch_workcenter_captured(self, client):
        rv = client.patch(
            "/production/v1/production-definitions/workcenters/0b6cf62b-2809-4d3d-ab24-369cd0171f62",
            json={"note": "patched"},
        )
        assert rv.status_code == 200
        store = client.application.config["PLEX_MOCK_STORE"]
        rows = store.query(run_id=client.application.config["PLEX_MOCK_RUN_ID"], method="PATCH")
        assert len(rows) == 1
```

- [ ] **Step 6.2: Run tests; expect failures**

Run: `python -m pytest tests/test_plex_mock_server.py -v`

Expected: 8 new tests fail with 405 (Method Not Allowed) or similar — the Flask app doesn't register POST/PUT/PATCH routes yet.

- [ ] **Step 6.3: Implement the write handlers**

In `tools/plex_mock/server.py`, inside `create_app()` just before `return app`, add:

```python
    @app.post("/inventory/v1/inventory-definitions/supply-items")
    def supply_items_post():
        from flask import request
        payload = request.get_json(silent=True) or {}
        store: CaptureStore = app.config["PLEX_MOCK_STORE"]
        store.append(
            method="POST",
            path=request.path,
            body=payload,
            run_id=app.config["PLEX_MOCK_RUN_ID"],
        )
        # Dedup by supplyItemNumber against the snapshot — Plex returns 409
        sin = payload.get("supplyItemNumber")
        if sin and any(rec.get("supplyItemNumber") == sin for rec in supply_items):
            return jsonify({"error": "duplicate supplyItemNumber", "supplyItemNumber": sin}), 409
        import uuid as _uuid
        resp = dict(payload)
        resp["id"] = str(_uuid.uuid4())
        return jsonify(resp), 201

    @app.put("/inventory/v1/inventory-definitions/supply-items/<item_id>")
    def supply_items_put(item_id: str):
        from flask import request
        if item_id not in supply_by_id:
            abort(404)
        payload = request.get_json(silent=True) or {}
        store: CaptureStore = app.config["PLEX_MOCK_STORE"]
        store.append(
            method="PUT",
            path=request.path,
            body=payload,
            run_id=app.config["PLEX_MOCK_RUN_ID"],
        )
        merged = {**supply_by_id[item_id], **payload, "id": item_id}
        return jsonify(merged), 200

    @app.route(
        "/production/v1/production-definitions/workcenters/<wc_id>",
        methods=["PUT", "PATCH"],
    )
    def workcenter_write(wc_id: str):
        from flask import request
        if wc_id not in workcenter_by_id:
            abort(404)
        payload = request.get_json(silent=True) or {}
        store: CaptureStore = app.config["PLEX_MOCK_STORE"]
        store.append(
            method=request.method,
            path=request.path,
            body=payload,
            run_id=app.config["PLEX_MOCK_RUN_ID"],
        )
        merged = {**workcenter_by_id[wc_id], **payload, "workcenterId": wc_id}
        return jsonify(merged), 200
```

- [ ] **Step 6.4: Run the full test file; expect all green**

Run: `python -m pytest tests/test_plex_mock_server.py -v`

Expected: 16 tests pass (8 from Task 5 + 8 new).

- [ ] **Step 6.5: Commit**

```bash
git add tools/plex_mock/server.py tests/test_plex_mock_server.py
git commit -m "feat(plex-mock): POST/PUT/PATCH capture handlers (#92)"
```

---

## Task 7: End-to-end rehearsal — `datum-sync` against the mock

Run the real sync binary with `PLEX_BASE_URL=http://localhost:8080` + `PLEX_ALLOW_WRITES=1` and confirm captures land. No new code — this is a validation step that writes nothing but a log file.

- [ ] **Step 7.1: Start the mock locally**

```bash
python -m tools.plex_mock.server --run-id rehearsal-1 --db /tmp/plex-mock-rehearsal.db &
sleep 2
curl -sf http://127.0.0.1:8080/healthz | python -m json.tool
```

Expected: `{"ok": true}`.

- [ ] **Step 7.2: Run a dry-run sync pointed at the mock**

```bash
PLEX_BASE_URL=http://127.0.0.1:8080 \
  datum-sync --dry-run 2>&1 | tail -30
```

(`datum-sync` is the console script registered at `pyproject.toml:21` — `datum-sync = "sync:cli"`.)

Expected: sync reaches the Plex-read phase, receives the snapshot, exits cleanly. No captures yet because `--dry-run`.

- [ ] **Step 7.3: Run a real (guarded) sync against the mock**

```bash
PLEX_BASE_URL=http://127.0.0.1:8080 \
PLEX_ALLOW_WRITES=1 \
  datum-sync 2>&1 | tail -30
```

Expected: sync completes; mock captures N POSTs in `/tmp/plex-mock-rehearsal.db`.

- [ ] **Step 7.4: Inspect the captures**

```bash
sqlite3 /tmp/plex-mock-rehearsal.db \
  "SELECT method, path, substr(body_json, 1, 80) FROM captures WHERE run_id='rehearsal-1' LIMIT 5"
```

Expected: rows showing the POST method, supply-items path, and the first 80 chars of each payload.

- [ ] **Step 7.5: Stop the mock + document what worked**

```bash
kill %1
```

Write findings to `tools/plex_mock/REHEARSAL_NOTES.md` (gitignored or committed, as preferred) covering:
- Actual N of captures vs expected N (rows in `plex_supply_items WHERE plex_id IS NULL`)
- Any errors in the sync log
- Any unexpected payload shapes

- [ ] **Step 7.6: Commit the rehearsal doc if valuable**

```bash
git add tools/plex_mock/REHEARSAL_NOTES.md
git commit -m "docs(plex-mock): record first rehearsal findings (#92)"
```

---

## Task 8: Diff CLI (TDD)

Compares a run's captures against an expected-payload fixture. Flags drift: missing fields, extra fields, type mismatches, count mismatches.

**Files:**
- Create: `tools/plex_mock/diff.py`
- Create: `tests/test_plex_mock_diff.py`
- Create: `tests/fixtures/plex_mock/expected_supply_items.json`

- [ ] **Step 8.1: Write the expected-payload fixture**

Create `tests/fixtures/plex_mock/expected_supply_items.json`:

```json
{
  "supply_items_post_shape": {
    "required_fields": [
      "category",
      "description",
      "group",
      "inventoryUnit",
      "supplyItemNumber",
      "type"
    ],
    "forbidden_fields": [
      "id",
      "posted_to_plex_at"
    ],
    "field_types": {
      "category": "str",
      "description": "str",
      "group": "str",
      "inventoryUnit": "str",
      "supplyItemNumber": "str",
      "type": "str"
    }
  }
}
```

- [ ] **Step 8.2: Write failing tests**

Create `tests/test_plex_mock_diff.py`:

```python
"""Tests for the Plex-mock diff CLI."""
import json
from pathlib import Path

import pytest

from tools.plex_mock.diff import diff_run, DiffResult
from tools.plex_mock.store import CaptureStore


FIXTURE = Path(__file__).parent / "fixtures" / "plex_mock" / "expected_supply_items.json"


@pytest.fixture
def store(tmp_path: Path) -> CaptureStore:
    return CaptureStore(tmp_path / "captures.db")


@pytest.fixture
def expected() -> dict:
    return json.loads(FIXTURE.read_text())


class TestDiffRun:
    def test_clean_run_returns_no_issues(self, store: CaptureStore, expected: dict):
        store.append(
            method="POST",
            path="/inventory/v1/inventory-definitions/supply-items",
            body={
                "category": "Tools & Inserts", "description": "x",
                "group": "Machining - End Mills", "inventoryUnit": "Ea",
                "supplyItemNumber": "ABC-1", "type": "SUPPLY",
            },
            run_id="r1",
        )
        result = diff_run(store=store, run_id="r1", expected=expected)
        assert isinstance(result, DiffResult)
        assert result.issues == []
        assert result.ok is True

    def test_missing_required_field_flagged(self, store: CaptureStore, expected: dict):
        store.append(
            method="POST",
            path="/inventory/v1/inventory-definitions/supply-items",
            body={"supplyItemNumber": "ABC-1"},  # missing everything else
            run_id="r1",
        )
        result = diff_run(store=store, run_id="r1", expected=expected)
        assert result.ok is False
        msgs = " ".join(result.issues)
        assert "missing" in msgs.lower()
        assert "category" in msgs

    def test_forbidden_field_flagged(self, store: CaptureStore, expected: dict):
        store.append(
            method="POST",
            path="/inventory/v1/inventory-definitions/supply-items",
            body={
                "category": "Tools & Inserts", "description": "x",
                "group": "Machining - End Mills", "inventoryUnit": "Ea",
                "supplyItemNumber": "ABC-1", "type": "SUPPLY",
                "id": "client-should-not-send-this",
            },
            run_id="r1",
        )
        result = diff_run(store=store, run_id="r1", expected=expected)
        assert result.ok is False
        assert any("forbidden" in m.lower() and "id" in m for m in result.issues)

    def test_wrong_field_type_flagged(self, store: CaptureStore, expected: dict):
        store.append(
            method="POST",
            path="/inventory/v1/inventory-definitions/supply-items",
            body={
                "category": "Tools & Inserts", "description": 42,  # should be str
                "group": "Machining - End Mills", "inventoryUnit": "Ea",
                "supplyItemNumber": "ABC-1", "type": "SUPPLY",
            },
            run_id="r1",
        )
        result = diff_run(store=store, run_id="r1", expected=expected)
        assert result.ok is False
        assert any("description" in m and "str" in m for m in result.issues)
```

- [ ] **Step 8.3: Run tests; expect import failure**

Run: `python -m pytest tests/test_plex_mock_diff.py -v`

Expected: `ModuleNotFoundError: No module named 'tools.plex_mock.diff'`.

- [ ] **Step 8.4: Implement the diff module**

Create `tools/plex_mock/diff.py`:

```python
"""
Diff captured Plex-mock POSTs against an expected-payload fixture.

Checks each supply-items POST for:
  - required fields present
  - forbidden fields absent (things the client shouldn't send)
  - field types match the fixture

Exit code 0 on clean, 1 on drift. Usage:

    python -m tools.plex_mock.diff --run-id <run> --db <path> --expected <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tools.plex_mock.store import CaptureStore


TYPE_MAP = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}


@dataclass
class DiffResult:
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _check_supply_item_post(body: dict, shape: dict, row_id: int) -> list[str]:
    issues: list[str] = []
    for f in shape["required_fields"]:
        if f not in body:
            issues.append(f"row {row_id}: missing required field '{f}'")
    for f in shape["forbidden_fields"]:
        if f in body:
            issues.append(f"row {row_id}: forbidden field '{f}' present")
    for f, t in shape["field_types"].items():
        if f in body:
            expected_t = TYPE_MAP.get(t)
            if expected_t and not isinstance(body[f], expected_t):
                actual = type(body[f]).__name__
                issues.append(f"row {row_id}: field '{f}' expected {t}, got {actual}")
    return issues


def diff_run(*, store: CaptureStore, run_id: str, expected: dict) -> DiffResult:
    result = DiffResult()
    shape = expected.get("supply_items_post_shape")
    if not shape:
        result.issues.append("fixture missing 'supply_items_post_shape'")
        return result

    for row in store.query(run_id=run_id, method="POST"):
        if not row["path"].endswith("/supply-items"):
            continue
        body = row["body"] or {}
        result.issues.extend(_check_supply_item_post(body, shape, row["id"]))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Plex-mock capture diff")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--expected", required=True, type=Path)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2
    if not args.expected.exists():
        print(f"Expected fixture not found: {args.expected}", file=sys.stderr)
        return 2

    store = CaptureStore(args.db)
    expected = json.loads(args.expected.read_text())
    result = diff_run(store=store, run_id=args.run_id, expected=expected)
    if result.ok:
        print(f"plex-mock diff: CLEAN (run_id={args.run_id})")
        return 0
    print(f"plex-mock diff: DRIFT (run_id={args.run_id}, {len(result.issues)} issues)")
    for issue in result.issues:
        print(f"  {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8.5: Run tests; expect all green**

Run: `python -m pytest tests/test_plex_mock_diff.py -v`

Expected: all 4 tests pass.

- [ ] **Step 8.6: Commit**

```bash
git add tools/plex_mock/diff.py tests/test_plex_mock_diff.py \
        tests/fixtures/plex_mock/expected_supply_items.json
git commit -m "feat(plex-mock): capture-diff CLI with payload-shape fixture (#92)"
```

---

## Task 9: Console scripts, docs, final README

Wire the three CLIs into `pyproject.toml` and flesh out the user-facing docs.

**Files:**
- Modify: `pyproject.toml` — three new console scripts
- Modify: `tools/plex_mock/README.md` — replace stub with full usage
- Modify: `docs/Plex_API_Reference.md` — add `PLEX_BASE_URL` paragraph

- [ ] **Step 9.1: Add console scripts to `pyproject.toml`**

The `[project.scripts]` table exists at `pyproject.toml:20` alongside `datum-sync`, `datum-sync-inventory`, and `datum-populate-supply-items`. Append three new entries in the same block:

```toml
datum-plex-mock-serve    = "tools.plex_mock.server:main"
datum-plex-mock-snapshot = "tools.plex_mock.capture_snapshots:main"
datum-plex-mock-diff     = "tools.plex_mock.diff:main"
```

- [ ] **Step 9.2: Replace the `tools/plex_mock/README.md` stub**

Replace the entire file with (note: outer fence uses four backticks because the README embeds a bash block):

````markdown
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
````

- [ ] **Step 9.3: Update `docs/Plex_API_Reference.md`**

Find the section on URL routing / environments and append:

```markdown
### `PLEX_BASE_URL` override

`plex_api.py` honors a `PLEX_BASE_URL` environment variable that overrides
both `BASE_URL` and `PLEX_USE_TEST`. Used by the write-validation
workflow in [#92](https://github.com/grace-shane/Datum/issues/92) to
point `datum-sync` at the local Plex-mimic mock
(`tools/plex_mock/server.py`) instead of `connect.plex.com`. Unset in
normal production operation.

Resolution order (first match wins):

1. Explicit `base_url=` kwarg to `PlexClient()` — tests and ad-hoc scripts
2. `PLEX_BASE_URL` env var — deployment-time override (the mock)
3. `PLEX_USE_TEST=1` → `test.connect.plex.com`
4. Default → `connect.plex.com`
```

- [ ] **Step 9.4: Verify pyproject console scripts install cleanly**

Run: `pip install -e . && datum-plex-mock-serve --help`

Expected: argparse help for the mock server CLI.

- [ ] **Step 9.5: Commit**

```bash
git add pyproject.toml tools/plex_mock/README.md docs/Plex_API_Reference.md
git commit -m "docs(plex-mock): console scripts, README, PLEX_BASE_URL reference (#92)"
```

---

## Task 10: systemd unit + deploy to `datum-runtime`

Persistent mock service on the runtime VM. Localhost-bound, free-tier friendly.

**Files:**
- Create: `tools/plex_mock/systemd/datum-plex-mock.service`

- [ ] **Step 10.1: Write the unit file**

Create `tools/plex_mock/systemd/datum-plex-mock.service`:

```ini
[Unit]
Description=Datum Plex-Mimic Mock HTTP Server
After=network.target
Documentation=https://github.com/grace-shane/Datum/issues/92

[Service]
Type=simple
User=datum
Group=datum
WorkingDirectory=/opt/datum
EnvironmentFile=/opt/datum/.env.local
ExecStart=/opt/datum/.venv/bin/datum-plex-mock-serve \
  --host 127.0.0.1 \
  --port 8080 \
  --snapshots /opt/datum/tools/plex_mock/snapshots \
  --db /var/lib/datum/plex-mock-captures.db
Restart=on-failure
RestartSec=5
# Hardening — mock has no reason to touch anything outside its data dir
ReadWritePaths=/var/lib/datum
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 10.2: Document deploy steps in the unit-file directory**

Create `tools/plex_mock/systemd/README.md` (outer fence uses four backticks because the README embeds a bash block):

````markdown
# Deploy `datum-plex-mock` on `datum-runtime`

Assumes the Datum repo is at `/opt/datum` and a virtualenv at
`/opt/datum/.venv` with `pip install -e .` having registered
`datum-plex-mock-serve`.

```bash
# SSH in via IAP
gcloud compute ssh datum-runtime --zone=us-central1-a --tunnel-through-iap \
  --project=$PROJECT_ID

# On the VM:
sudo mkdir -p /var/lib/datum
sudo chown datum:datum /var/lib/datum
sudo cp /opt/datum/tools/plex_mock/systemd/datum-plex-mock.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now datum-plex-mock
sudo systemctl status datum-plex-mock
curl -sf http://127.0.0.1:8080/healthz
```

Troubleshooting:
- Logs: `journalctl -u datum-plex-mock -f`
- Stop: `sudo systemctl stop datum-plex-mock`
- Test snapshot refresh from the VM: `cd /opt/datum && /opt/datum/.venv/bin/datum-plex-mock-snapshot`
````

- [ ] **Step 10.3: Commit**

```bash
git add tools/plex_mock/systemd/
git commit -m "feat(plex-mock): systemd unit + datum-runtime deploy doc (#92)"
```

- [ ] **Step 10.4: Open the deploy PR**

Deploy to `datum-runtime` happens **after PR merge** — it's an out-of-repo step that Shane runs manually. PR description should include the deploy checklist verbatim from Step 10.2 so Shane can cross-check.

---

## Out-of-scope follow-ups (tracked separately)

- Pre-commit hook or CI check that runs `datum-plex-mock-diff` against a golden capture fixture every PR — cheap regression net once we have the tooling.
- Capture-replay feature: re-drive historical mock captures against a new code path to detect payload-shape drift.
- Multi-run comparison (N runs vs N runs): the current diff is fixture-vs-run; a runs-vs-runs variant would catch nondeterminism in payload generation.
- Extend the mock surface if #4 / #5 ever unblock (Tool Assemblies, Routings).

Do not roll these into #92 — each earns its own issue.
