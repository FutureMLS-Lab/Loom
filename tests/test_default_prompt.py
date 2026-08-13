"""The default prompt and project memory reach every task prompt."""

from __future__ import annotations

import json
from pathlib import Path

import loom.web as web
from loom.paths import default_prompt_path


def make_task(tmp_path: Path, slug: str = "t1") -> None:
    task = tmp_path / ".RUD" / slug
    (task / "work").mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({
        "slug": slug, "title": "T", "general_goal": "G", "agent": "claude",
    }))


def test_default_prompt_is_always_injected(tmp_path):
    make_task(tmp_path)
    prompt = web._build_claude_prompt(tmp_path, "t1")
    assert "Default prompt (always active" in prompt
    assert "Simplicity first" in prompt          # content, not just the header
    assert "Project memory" in prompt            # protocol present even when empty


def test_project_memory_is_injected_and_tail_capped(tmp_path):
    make_task(tmp_path)
    memory = tmp_path / ".RUD" / "MEMORY.md"
    filler = "\n".join(f"- [old] lesson {i}" for i in range(400))
    memory.write_text(filler + "\n- [recent] never trust the cache\n")
    prompt = web._build_claude_prompt(tmp_path, "t1")
    # The newest lesson survives the tail cap; the oldest may not.
    assert "never trust the cache" in prompt
    assert "lesson 0\n" not in prompt


def test_default_prompt_is_not_a_picker_option(tmp_path):
    options = web._available_skill_options(default_prompt_path())
    paths = {o["path"] for o in options}
    assert str(default_prompt_path().resolve()) not in paths
