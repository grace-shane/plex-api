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
