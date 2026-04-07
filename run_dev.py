"""
run_dev.py
Local development launcher for app.py.
======================================

Forces .env.local values to OVERRIDE shell environment variables, then
runs app.py as if it were the main entry point.

Why this exists
---------------
bootstrap.py uses os.environ.setdefault() so that real shell env vars
always win over .env.local. That's correct for production deployment,
where credentials should come from the host's secure environment, not
a file. But it's wrong for local dev where:

  - A stale shell env var (e.g. an old credential set via setx in the
    Windows registry years ago) silently shadows .env.local
  - Debugging "why isn't it working" wastes hours

This launcher forces the override for local dev only. Production
deployments still use `py app.py` directly, which respects
bootstrap.setdefault() and lets the host shell env take precedence.

Usage
-----
    py run_dev.py

Or via Claude Preview — .claude/launch.json points here.
"""
import os
import sys
from pathlib import Path

# Force stdout to UTF-8 before importing app — same reason as in app.py:
# Windows cp1252 console can't encode em-dashes / arrows / etc., and a
# print() failure mid-Flask-request turns into a 500.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.local"


def force_override_from_env_local(path: Path | str | None = None) -> int:
    """
    Read .env.local and write each KEY=VALUE pair into os.environ via
    direct assignment (NOT setdefault). Existing shell env vars with
    the same name are OVERRIDDEN.

    Parameters
    ----------
    path : Path | str | None
        Override the file path. Defaults to ``<project_root>/.env.local``.

    Returns
    -------
    int
        The number of os.environ keys that were either added or
        actually changed (entries already at the desired value count
        as zero).
    """
    if path is None:
        path = DEFAULT_ENV_FILE
    else:
        path = Path(path)

    if not path.exists():
        return 0

    changed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Strip matched surrounding quotes (' or ")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        if not key:
            continue

        # Direct assignment — OVERRIDE the shell value if it exists
        if os.environ.get(key) != value:
            os.environ[key] = value
            changed += 1

    return changed


def main() -> None:
    n = force_override_from_env_local()
    if n:
        print(
            f"[run_dev] Loaded {n} env var(s) from .env.local "
            f"(overriding any shell-level values)"
        )
    elif not DEFAULT_ENV_FILE.exists():
        print(
            f"[run_dev] WARNING: {DEFAULT_ENV_FILE.name} not found. "
            f"Falling back to shell env vars only."
        )

    # Re-execute app.py as __main__ so its existing startup banner +
    # app.run() block fires correctly. Using runpy keeps the executed
    # module's __name__ == '__main__'.
    import runpy
    runpy.run_path(str(PROJECT_ROOT / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
