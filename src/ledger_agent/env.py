"""Minimal ``.env`` loading.

The repository ships a ``.env.example``, so a reader who copies it to ``.env`` should
find that things work. Ten lines of parsing is cheaper than a dependency, and cheaper
still than the confusion of a sample file nothing reads.

Real environment variables always win — sourcing a file must never silently override
a key the caller deliberately exported.
"""

from __future__ import annotations

import os
from pathlib import Path

# The package lives at <repo>/src/ledger_agent/, so the root is three levels up.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Load ``KEY=value`` pairs from ``path`` into the environment.

    A missing file is not an error: the variables may well be exported already, and
    the callers check for what they actually need.
    """
    env_path = path or REPO_ROOT / ".env"
    if not env_path.is_file():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
