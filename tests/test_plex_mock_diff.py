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

    def test_checked_counter_reflects_rows(self, store: CaptureStore, expected: dict):
        body = {
            "category": "Tools & Inserts", "description": "x",
            "group": "Machining - End Mills", "inventoryUnit": "Ea",
            "supplyItemNumber": "ABC-1", "type": "SUPPLY",
        }
        store.append(method="POST", path="/inventory/v1/inventory-definitions/supply-items", body=body, run_id="r1")
        store.append(method="POST", path="/inventory/v1/inventory-definitions/supply-items", body=body, run_id="r1")
        result = diff_run(store=store, run_id="r1", expected=expected)
        assert result.checked == 2
        assert result.ok is True

    def test_empty_run_returns_ok_with_zero_checked(self, store: CaptureStore, expected: dict):
        result = diff_run(store=store, run_id="nope", expected=expected)
        assert result.ok is True
        assert result.checked == 0
