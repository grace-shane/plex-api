"""
Tests for bootstrap.py — .env.local loader.

Verifies the contract:
  - missing file is a no-op
  - KEY=VALUE pairs are parsed and injected via setdefault
  - existing env vars are NEVER overridden
  - blank lines and # comments are skipped
  - matched surrounding quotes (single or double) are stripped
  - returns the count of injected variables
"""
import os

import pytest

from bootstrap import load_env_local


# ─────────────────────────────────────────────
# Missing file behavior
# ─────────────────────────────────────────────
class TestMissingFile:
    def test_missing_file_is_noop(self, tmp_path):
        missing = tmp_path / "does-not-exist.env"
        result = load_env_local(missing)
        assert result == 0

    def test_missing_file_does_not_raise(self, tmp_path):
        # Should not raise even if directory itself does not exist
        nowhere = tmp_path / "nope" / "alsonope" / ".env.local"
        load_env_local(nowhere)  # no exception


# ─────────────────────────────────────────────
# Basic parsing
# ─────────────────────────────────────────────
class TestBasicParsing:
    def test_simple_key_value(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=bar\n")
        monkeypatch.delenv("FOO", raising=False)
        injected = load_env_local(f)
        assert injected == 1
        assert os.environ["FOO"] == "bar"

    def test_multiple_pairs(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=bar\nBAZ=qux\nHELLO=world\n")
        for k in ("FOO", "BAZ", "HELLO"):
            monkeypatch.delenv(k, raising=False)
        injected = load_env_local(f)
        assert injected == 3
        assert os.environ["FOO"] == "bar"
        assert os.environ["BAZ"] == "qux"
        assert os.environ["HELLO"] == "world"

    def test_value_can_contain_equals(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("URL=https://example.com/?a=1&b=2\n")
        monkeypatch.delenv("URL", raising=False)
        load_env_local(f)
        assert os.environ["URL"] == "https://example.com/?a=1&b=2"


# ─────────────────────────────────────────────
# Comments and blank lines
# ─────────────────────────────────────────────
class TestCommentsAndBlanks:
    def test_skips_comments(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("# this is a comment\nFOO=bar\n# another comment\n")
        monkeypatch.delenv("FOO", raising=False)
        injected = load_env_local(f)
        assert injected == 1
        assert os.environ["FOO"] == "bar"

    def test_skips_blank_lines(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("\n\nFOO=bar\n\n\nBAZ=qux\n")
        for k in ("FOO", "BAZ"):
            monkeypatch.delenv(k, raising=False)
        injected = load_env_local(f)
        assert injected == 2

    def test_skips_lines_without_equals(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("not-a-pair\nFOO=bar\nalso-not-a-pair\n")
        monkeypatch.delenv("FOO", raising=False)
        injected = load_env_local(f)
        assert injected == 1


# ─────────────────────────────────────────────
# Quote stripping
# ─────────────────────────────────────────────
class TestQuoteStripping:
    def test_strips_double_quotes(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text('FOO="bar baz"\n')
        monkeypatch.delenv("FOO", raising=False)
        load_env_local(f)
        assert os.environ["FOO"] == "bar baz"

    def test_strips_single_quotes(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO='bar baz'\n")
        monkeypatch.delenv("FOO", raising=False)
        load_env_local(f)
        assert os.environ["FOO"] == "bar baz"

    def test_does_not_strip_mismatched_quotes(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=\"bar'\n")
        monkeypatch.delenv("FOO", raising=False)
        load_env_local(f)
        assert os.environ["FOO"] == "\"bar'"

    def test_preserves_internal_quotes(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text('FOO=bar"baz\n')
        monkeypatch.delenv("FOO", raising=False)
        load_env_local(f)
        assert os.environ["FOO"] == 'bar"baz'


# ─────────────────────────────────────────────
# setdefault semantics — real env always wins
# ─────────────────────────────────────────────
class TestSetdefaultBehavior:
    def test_existing_env_var_is_not_overridden(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=from-file\n")
        monkeypatch.setenv("FOO", "from-shell")
        injected = load_env_local(f)
        # Was already set, so injected count is 0
        assert injected == 0
        assert os.environ["FOO"] == "from-shell"

    def test_partial_override_only_sets_missing(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=from-file\nBAZ=from-file\n")
        monkeypatch.setenv("FOO", "from-shell")
        monkeypatch.delenv("BAZ", raising=False)
        injected = load_env_local(f)
        assert injected == 1
        assert os.environ["FOO"] == "from-shell"
        assert os.environ["BAZ"] == "from-file"


# ─────────────────────────────────────────────
# Whitespace handling
# ─────────────────────────────────────────────
class TestWhitespace:
    def test_strips_whitespace_around_key_and_value(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("  FOO  =  bar  \n")
        monkeypatch.delenv("FOO", raising=False)
        load_env_local(f)
        assert os.environ["FOO"] == "bar"

    def test_handles_crlf_line_endings(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_bytes(b"FOO=bar\r\nBAZ=qux\r\n")
        monkeypatch.delenv("FOO", raising=False)
        monkeypatch.delenv("BAZ", raising=False)
        injected = load_env_local(f)
        assert injected == 2
        assert os.environ["FOO"] == "bar"
        assert os.environ["BAZ"] == "qux"
