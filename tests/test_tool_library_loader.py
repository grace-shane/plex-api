"""
Tests for tool_library_loader — JSON parsing, schema validation,
stale-file guard, and directory glob.

All tests use tmp_path so we don't touch the real CAMTools directory.
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tool_library_loader import (
    load_library,
    load_all_libraries,
    report_library_contents,
    _check_file_age,
    MAX_FILE_AGE_HOURS,
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
SAMPLE_LIBRARY = {
    "data": [
        {"guid": "tool-1", "type": "flat end mill", "description": "5/8 SQ"},
        {"guid": "tool-2", "type": "drill", "description": "1/4 drill"},
        {"guid": "tool-3", "type": "holder", "description": "BT30"},
    ]
}


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


# ─────────────────────────────────────────────
# load_library — happy path
# ─────────────────────────────────────────────
class TestLoadLibraryHappyPath:
    def test_loads_valid_library(self, tmp_path):
        f = tmp_path / "lib.json"
        write_json(f, SAMPLE_LIBRARY)
        tools = load_library(f)
        assert tools is not None
        assert len(tools) == 3
        assert tools[0]["guid"] == "tool-1"

    def test_empty_data_array_is_valid(self, tmp_path):
        f = tmp_path / "lib.json"
        write_json(f, {"data": []})
        tools = load_library(f)
        assert tools == []


# ─────────────────────────────────────────────
# load_library — error handling
# ─────────────────────────────────────────────
class TestLoadLibraryErrors:
    def test_returns_none_for_malformed_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not valid json", encoding="utf-8")
        assert load_library(f) is None

    def test_returns_none_for_missing_data_key(self, tmp_path):
        f = tmp_path / "lib.json"
        write_json(f, {"tools": [{"guid": "x"}]})  # wrong root key
        assert load_library(f) is None

    def test_returns_none_when_data_is_not_a_list(self, tmp_path):
        f = tmp_path / "lib.json"
        write_json(f, {"data": "not a list"})
        assert load_library(f) is None

    def test_returns_none_for_stale_file(self, tmp_path):
        f = tmp_path / "stale.json"
        write_json(f, SAMPLE_LIBRARY)
        # Backdate the mtime to 100 hours ago — well past the 25h limit.
        old = time.time() - (100 * 3600)
        os.utime(f, (old, old))
        assert load_library(f) is None


# ─────────────────────────────────────────────
# _check_file_age
# ─────────────────────────────────────────────
class TestFileAgeCheck:
    def test_recent_file_passes(self, tmp_path):
        f = tmp_path / "fresh.json"
        f.write_text("{}", encoding="utf-8")
        assert _check_file_age(f) is True

    def test_stale_file_fails(self, tmp_path):
        f = tmp_path / "stale.json"
        f.write_text("{}", encoding="utf-8")
        old = time.time() - ((MAX_FILE_AGE_HOURS + 5) * 3600)
        os.utime(f, (old, old))
        assert _check_file_age(f) is False

    def test_custom_max_age_window(self, tmp_path):
        f = tmp_path / "f.json"
        f.write_text("{}", encoding="utf-8")
        old = time.time() - (3 * 3600)  # 3 hours old
        os.utime(f, (old, old))
        assert _check_file_age(f, max_age_hours=5) is True
        assert _check_file_age(f, max_age_hours=1) is False


# ─────────────────────────────────────────────
# load_all_libraries
# ─────────────────────────────────────────────
class TestLoadAllLibraries:
    def test_returns_empty_for_missing_directory(self, tmp_path):
        missing = tmp_path / "nope"
        result = load_all_libraries(missing)
        assert result == {}

    def test_loads_multiple_files(self, tmp_path):
        write_json(tmp_path / "a.json", SAMPLE_LIBRARY)
        write_json(tmp_path / "b.json", {"data": [{"guid": "z", "type": "drill"}]})
        result = load_all_libraries(tmp_path)
        assert set(result.keys()) == {"a", "b"}
        assert len(result["a"]) == 3
        assert len(result["b"]) == 1

    def test_returns_empty_when_no_json_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hi", encoding="utf-8")
        result = load_all_libraries(tmp_path)
        assert result == {}

    def test_abort_on_stale_aborts_full_run(self, tmp_path):
        # Two files, one fresh, one stale → with abort_on_stale=True (default),
        # the entire load should return {}.
        write_json(tmp_path / "fresh.json", SAMPLE_LIBRARY)
        stale = tmp_path / "stale.json"
        write_json(stale, SAMPLE_LIBRARY)
        old = time.time() - (100 * 3600)
        os.utime(stale, (old, old))

        result = load_all_libraries(tmp_path, abort_on_stale=True)
        assert result == {}

    def test_skip_stale_continues_with_fresh(self, tmp_path):
        write_json(tmp_path / "fresh.json", SAMPLE_LIBRARY)
        stale = tmp_path / "stale.json"
        write_json(stale, SAMPLE_LIBRARY)
        old = time.time() - (100 * 3600)
        os.utime(stale, (old, old))

        result = load_all_libraries(tmp_path, abort_on_stale=False)
        assert "fresh" in result
        assert "stale" not in result


# ─────────────────────────────────────────────
# report_library_contents — smoke test
# ─────────────────────────────────────────────
class TestReportLibraryContents:
    def test_runs_without_error(self, capsys):
        libs = {"sample": SAMPLE_LIBRARY["data"]}
        report_library_contents(libs)
        captured = capsys.readouterr()
        # Should print library name + per-type counts
        assert "sample" in captured.out
        assert "flat end mill" in captured.out
        assert "drill" in captured.out
        assert "holder" in captured.out

    def test_handles_empty_library(self, capsys):
        report_library_contents({})
        captured = capsys.readouterr()
        # No exception, no output for an empty dict
        assert captured.out == ""
