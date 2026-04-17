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
