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
            assert cur.lastrowid is not None  # INSERT always yields a rowid
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
