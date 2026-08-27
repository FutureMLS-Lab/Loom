"""The route split relocated handler methods into module functions.

A call site left as ``self._helper(...)`` while ``_helper`` became a module
function crashes only when that route is hit in production (the Download PDF
button died this way). This test catches the whole class statically.
"""

import re
from pathlib import Path

import pytest

ROUTE_FILES = sorted(
    (Path(__file__).resolve().parents[1] / "loom").glob("routes_*.py")
)


@pytest.mark.parametrize("path", ROUTE_FILES, ids=lambda p: p.name)
def test_no_self_calls_to_module_functions(path):
    text = path.read_text(encoding="utf-8")
    module_fns = set(re.findall(r"^def (_\w+)\(self", text, re.M))
    stale = [
        f"{path.name}:{text[: m.start()].count(chr(10)) + 1}: self.{m.group(1)}("
        for m in re.finditer(r"self\.(_\w+)\(", text)
        if m.group(1) in module_fns
    ]
    assert not stale, (
        "these call module functions as if they were still handler methods: "
        + ", ".join(stale)
    )
