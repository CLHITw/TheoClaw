"""Reads API keys from .env at the project root into the environment.

Variables that are already set win over the file, so a key set in the shell for
one session is not overridden. The file is git-ignored; .env.example shows the form.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..common.paths import ENV_FILE

_loaded: set[str] = set()


def load_env(path: Path | str = ENV_FILE) -> list[str]:
    """Sets KEY=VALUE lines from the file that are not set yet; returns their names."""
    p = Path(path)
    if str(p) in _loaded or not p.exists():
        return []
    _loaded.add(str(p))
    added = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value
            added.append(key)
    return added
