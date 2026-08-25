"""Tiny helpers shared by web.py and its split-off feature modules."""

from __future__ import annotations

import re
from pathlib import Path

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,80}$")


def _path_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False
