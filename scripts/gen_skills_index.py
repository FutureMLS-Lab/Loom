#!/usr/bin/env python3
"""Regenerate loom/skills/SKILLS.md - the one-file map of every skill.

The index is generated, not hand-kept: it reads the same catalogs the
runtime uses (the AR pipeline's skill_catalog and the picker's option
scan), so it cannot silently disagree with what agents actually receive.
A test compares the file against a fresh render; when a skill is added
or its description changes, run:

    python3 scripts/gen_skills_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from loom import ar_task as ar  # noqa: E402
from loom.paths import default_prompt_path  # noqa: E402
from loom.rud_task import bundled_skills_path  # noqa: E402
from loom.web import _available_skill_options, _skill_summary  # noqa: E402

INDEX_PATH = REPO / "loom" / "skills" / "SKILLS.md"


def _rel(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def render() -> str:
    lines: list[str] = [
        "# Every Loom skill, on one page",
        "",
        "<!-- GENERATED - edit the skills, then run scripts/gen_skills_index.py -->",
        "",
        "A skill is a markdown file; injection is text. Three tiers decide who",
        "reads what, and when:",
        "",
        "1. **Always on** - in every prompt, nobody chooses it.",
        "2. **Human-picked** - the task creator selects; full text is injected,",
        "   and every task prompt also carries this tier as an on-demand menu",
        "   (name + pitch + path) so agents can read unselected ones anyway.",
        "3. **Pipeline-injected** - the Paper Factory hands each AR role its",
        "   methodology itself; these never appear in the picker.",
        "",
        "## Always on",
        "",
    ]
    dp = default_prompt_path()
    lines.append(
        f"- **DEFAULT_PROMPT** — {_skill_summary(dp) or 'working style + project memory protocol'}"
    )
    lines.append(f"    `{_rel(dp)}`")
    lines += ["", "## Human-picked (the task picker / the skill shelf)", ""]
    for option in _available_skill_options(bundled_skills_path()):
        summary = _skill_summary(Path(option["path"]))
        lines.append(f"- **{option['label']}** — {summary}")
        lines.append(f"    `{_rel(option['path'])}`")
    lines += ["", "## Pipeline-injected (AR / Paper Factory)", ""]
    role_order: dict[str, list[dict[str, str]]] = {}
    for entry in ar.skill_catalog():
        role_order.setdefault(entry["role"], []).append(entry)
    for role, entries in role_order.items():
        lines.append(f"### {role}")
        lines.append("")
        for entry in entries:
            lines.append(f"- **{entry['name']}** — {entry['description']}")
            lines.append(f"    {entry['injection']}")
            lines.append(f"    `{_rel(entry['path'])}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    INDEX_PATH.write_text(render(), encoding="utf-8")
    print(f"wrote {INDEX_PATH}")
