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
