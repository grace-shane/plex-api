"""
Tests for run_dev.py — local dev launcher with force-override semantics.

The whole point of run_dev.py is the OPPOSITE of bootstrap.py:
bootstrap uses setdefault (real shell wins), run_dev uses direct
assignment (file wins). These tests pin down that contract.
"""
import os

import pytest

from run_dev import force_override_from_env_local


# ─────────────────────────────────────────────
# Missing file is a no-op
# ─────────────────────────────────────────────
class TestMissingFile:
    def test_missing_file_returns_zero(self, tmp_path):
        missing = tmp_path / "does-not-exist.env"
        assert force_override_from_env_local(missing) == 0

    def test_missing_file_does_not_raise(self, tmp_path):
        nowhere = tmp_path / "nope" / "alsonope" / ".env.local"
        force_override_from_env_local(nowhere)  # no exception


# ─────────────────────────────────────────────
# Override behavior — the whole point
# ─────────────────────────────────────────────
class TestOverrideSemantics:
    def test_overrides_existing_env_var(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=from-file\n")
        monkeypatch.setenv("FOO", "from-shell")

        changed = force_override_from_env_local(f)

        assert changed == 1
        assert os.environ["FOO"] == "from-file"

    def test_sets_var_when_unset(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=from-file\n")
        monkeypatch.delenv("FOO", raising=False)

        changed = force_override_from_env_local(f)

        assert changed == 1
        assert os.environ["FOO"] == "from-file"

    def test_no_change_count_when_already_correct(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=already-correct\n")
        monkeypatch.setenv("FOO", "already-correct")

        changed = force_override_from_env_local(f)

        # The shell already has the right value — counts as zero changes
        assert changed == 0
        assert os.environ["FOO"] == "already-correct"

    def test_partial_override_multiple_vars(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO=new-foo\nBAR=new-bar\nBAZ=new-baz\n")
        monkeypatch.setenv("FOO", "old-foo")  # will be overridden
        monkeypatch.setenv("BAR", "new-bar")  # already correct
        monkeypatch.delenv("BAZ", raising=False)  # unset

        changed = force_override_from_env_local(f)

        # FOO: changed, BAR: no-op, BAZ: added → 2 changes
        assert changed == 2
        assert os.environ["FOO"] == "new-foo"
        assert os.environ["BAR"] == "new-bar"
        assert os.environ["BAZ"] == "new-baz"


# ─────────────────────────────────────────────
# Parsing — comments, blanks, quotes
# ─────────────────────────────────────────────
class TestParsing:
    def test_skips_comments(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("# comment\nFOO=bar\n# another\n")
        monkeypatch.delenv("FOO", raising=False)

        changed = force_override_from_env_local(f)

        assert changed == 1
        assert os.environ["FOO"] == "bar"

    def test_skips_blank_lines(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("\n\nFOO=bar\n\n\n")
        monkeypatch.delenv("FOO", raising=False)

        changed = force_override_from_env_local(f)
        assert changed == 1

    def test_skips_lines_without_equals(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("not-a-pair\nFOO=bar\n")
        monkeypatch.delenv("FOO", raising=False)

        changed = force_override_from_env_local(f)
        assert changed == 1

    def test_strips_double_quotes(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text('FOO="bar baz"\n')
        monkeypatch.delenv("FOO", raising=False)

        force_override_from_env_local(f)
        assert os.environ["FOO"] == "bar baz"

    def test_strips_single_quotes(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("FOO='bar baz'\n")
        monkeypatch.delenv("FOO", raising=False)

        force_override_from_env_local(f)
        assert os.environ["FOO"] == "bar baz"

    def test_handles_value_with_equals(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("URL=https://example.com/?a=1&b=2\n")
        monkeypatch.delenv("URL", raising=False)

        force_override_from_env_local(f)
        assert os.environ["URL"] == "https://example.com/?a=1&b=2"


# ─────────────────────────────────────────────
# Contract: run_dev opposite of bootstrap
# ─────────────────────────────────────────────
class TestRunDevVsBootstrap:
    def test_run_dev_overrides_where_bootstrap_would_not(self, tmp_path, monkeypatch):
        """
        Pin down the differing semantics. With the same .env.local content
        and pre-existing shell env, bootstrap.setdefault keeps the shell
        value while run_dev.force_override replaces it.
        """
        f = tmp_path / ".env"
        f.write_text("CRED=from-file\n")
        monkeypatch.setenv("CRED", "from-shell")

        # bootstrap.load_env_local is the SAFE path: shell wins
        from bootstrap import load_env_local
        load_env_local(f)
        assert os.environ["CRED"] == "from-shell"

        # run_dev.force_override is the DEV path: file wins
        force_override_from_env_local(f)
        assert os.environ["CRED"] == "from-file"
