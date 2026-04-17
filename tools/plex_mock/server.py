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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in snapshot {path}: {exc}") from exc


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

    # The mock is stateless: these dicts are loaded once at app creation
    # and never mutated. Task 6 POST/PUT/PATCH handlers capture request
    # bodies to the SQLite store and return Plex-shape responses with
    # synthetic UUIDs, but they do NOT add/modify entries here. A GET of
    # a synthetic id from an earlier POST therefore intentionally 404s —
    # the mock doesn't simulate Plex's inventory state, just its wire shape.
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

    @app.post("/inventory/v1/inventory-definitions/supply-items")
    def supply_items_post():
        from flask import request
        payload = request.get_json(silent=True) or {}
        # Dedup by supplyItemNumber against the snapshot — Plex returns 409.
        # Guard before capturing so failed requests aren't stored; matches
        # the 404 ordering in supply_items_put and workcenter_write.
        sin = payload.get("supplyItemNumber")
        if sin and any(rec.get("supplyItemNumber") == sin for rec in supply_items):
            return jsonify({"error": "duplicate supplyItemNumber", "supplyItemNumber": sin}), 409
        store: CaptureStore = app.config["PLEX_MOCK_STORE"]
        store.append(
            method="POST",
            path=request.path,
            body=payload,
            run_id=app.config["PLEX_MOCK_RUN_ID"],
        )
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
    # threaded=True so the sync can issue concurrent POSTs against the mock
    # without Werkzeug's default single-threaded server serialising them.
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
