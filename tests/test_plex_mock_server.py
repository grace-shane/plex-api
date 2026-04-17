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


class TestMalformedSnapshot:
    def test_malformed_json_raises_value_error_with_path(self, tmp_path: Path):
        d = tmp_path / "snapshots"
        d.mkdir()
        (d / "supply_items_list.json").write_text("not json at all")
        (d / "workcenters_list.json").write_text("[]")
        with pytest.raises(ValueError) as excinfo:
            create_app(snapshots_dir=d, db_path=tmp_path / "c.db", run_id="r1")
        assert "supply_items_list.json" in str(excinfo.value)


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

    def test_post_409_does_not_capture(self, client):
        payload = {"supplyItemNumber": "ABC-1", "description": "dup"}
        rv = client.post("/inventory/v1/inventory-definitions/supply-items", json=payload)
        assert rv.status_code == 409
        store = client.application.config["PLEX_MOCK_STORE"]
        rows = store.query(run_id=client.application.config["PLEX_MOCK_RUN_ID"])
        assert len(rows) == 0


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
