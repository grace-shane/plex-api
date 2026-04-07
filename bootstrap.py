"""
bootstrap.py
.env.local loader
==================
Optional dotenv-style loader for credentials and other environment
configuration. Imported at the very top of plex_api.py so that
PLEX_API_KEY / PLEX_API_SECRET can come from a gitignored .env.local
file in the project root, instead of requiring the user to set them
in every shell.

Behavior
--------
- If .env.local exists in the project root, parse KEY=VALUE pairs
  and inject them into os.environ via setdefault — meaning any
  variable already set in the real environment WINS, never overridden.
- Lines starting with # are comments. Blank lines are ignored.
- Surrounding single or double quotes on values are stripped.
- Missing file is a no-op (no error).

Why setdefault, not direct assignment
-------------------------------------
A real shell environment variable should always override .env.local —
that lets CI, production deployments, and ad-hoc shell exports take
precedence over local dev defaults without anyone having to remember
to delete the file.
"""
import os
from pathlib import Path

# Project root = directory containing this file (bootstrap.py lives at the root)
_PROJECT_ROOT = Path(__file__).resolve().parent


def load_env_local(path: Path | str | None = None) -> int:
    """
    Load KEY=VALUE pairs from a .env.local file into os.environ via setdefault.

    Parameters
    ----------
    path : Path | str | None
        Override the file path. Defaults to ``<project_root>/.env.local``.

    Returns
    -------
    int
        Number of variables actually injected into os.environ
        (i.e. that were not already present).
    """
    if path is None:
        path = _PROJECT_ROOT / ".env.local"
    else:
        path = Path(path)

    if not path.exists():
        return 0

    injected = 0
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

        if key and key not in os.environ:
            os.environ[key] = value
            injected += 1

    return injected


# Auto-load on import — no-op if .env.local does not exist.
load_env_local()
