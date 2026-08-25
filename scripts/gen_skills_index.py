#!/usr/bin/env python3
"""Regenerate the skills list inside loom/skills/DEFAULT_PROMPT.md.

The default prompt is the one text every agent always receives, so the
map of available skills lives right there - between the SKILLS markers,
rendered from the same catalogs the runtime uses (the AR pipeline's
skill_catalog and the picker's option scan), never hand-kept. A test
compares the section against a fresh render; when a skill is added or
its description changes, run:

    python3 scripts/gen_skills_index.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from loom import ar_task as ar  # noqa: E402
from loom.paths import default_prompt_path  # noqa: E402
from loom.rud_task import bundled_skills_path  # noqa: E402
from loom.web import _available_skill_options, _skill_summary  # noqa: E402

BEGIN = "<!-- SKILLS:BEGIN generated - edit skills, then run scripts/gen_skills_index.py -->"
END = "<!-- SKILLS:END -->"


def _rel(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def render_section() -> str:
    lines: list[str] = ["", "Pick-and-read (also selectable at task creation):"]
    for option in _available_skill_options(bundled_skills_path()):
        summary = _skill_summary(Path(option["path"]))
        lines.append(f"- {option['label']} - {summary}")
        lines.append(f"    {_rel(option['path'])}")
    lines.append("")
    lines.append(
        "Paper Factory (AR) skills - the pipeline injects these itself; listed "
        "so you know the machinery:"
    )
    for entry in ar.skill_catalog():
        lines.append(
            f"- {entry['name']} ({entry['role']}) - {entry['description']} "
            f"[{entry['injection']}]"
        )
        lines.append(f"    {_rel(entry['path'])}")
    lines.append("")
    return "\n".join(lines)


def render_document() -> str:
    doc = default_prompt_path().read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(BEGIN) + r".*?" + re.escape(END), flags=re.DOTALL
    )
    if not pattern.search(doc):
        raise SystemExit(
            f"markers not found in {default_prompt_path()} - refusing to guess"
        )
    return pattern.sub(BEGIN + render_section() + END, doc)


if __name__ == "__main__":
    default_prompt_path().write_text(render_document(), encoding="utf-8")
    print(f"updated {default_prompt_path()}")
