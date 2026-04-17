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
    checked: int = 0

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
        result.checked += 1
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
        if result.checked == 0:
            print(f"plex-mock diff: CLEAN but ZERO rows checked (run_id={args.run_id}) — is the run_id correct?", file=sys.stderr)
            return 3
        print(f"plex-mock diff: CLEAN (run_id={args.run_id}, {result.checked} supply-items POSTs checked)")
        return 0
    print(f"plex-mock diff: DRIFT (run_id={args.run_id}, {result.checked} checked, {len(result.issues)} issues)")
    for issue in result.issues:
        print(f"  {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
