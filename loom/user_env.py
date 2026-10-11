"""Per-host Loom settings, kept in ``~/.loom/env``.

Loom's knobs are LOOM_* environment variables (the default Cursor model, the
usage-budget guards, ...). Passing them on the launch command is easy to lose:
a restart from another shell quietly drops them. So every ``loom`` command
first loads ``~/.loom/env`` - ``KEY=VALUE`` lines, ``#`` comments, an optional
``export`` - and the real environment still wins over the file.

Only LOOM_* names are read, so the file cannot reach PATH or anything else
outside Loom. It must load before any module that reads a setting when it is
imported, which is why this module imports nothing from Loom.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^LOOM_[A-Z0-9_]+$")


def user_env_path() -> Path:
    override = os.environ.get("LOOM_HOME", "").strip()
    home = Path(override).expanduser() if override else Path.home() / ".loom"
    return home / "env"


def parse_env_text(text: str) -> dict[str, str]:
    """``KEY=VALUE`` lines to a dict; anything else is skipped, not fatal."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def load_user_env(path: Path | None = None) -> list[str]:
    """Apply the file to ``os.environ``; returns the names it set."""
    try:
        text = (path or user_env_path()).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    applied: list[str] = []
    for key, value in parse_env_text(text).items():
        if key in os.environ:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied
