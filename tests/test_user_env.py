"""~/.loom/env: per-host LOOM_* settings every `loom` command loads first."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from loom import user_env


def test_parse_reads_loom_settings_and_skips_the_rest() -> None:
    text = """
# a comment
LOOM_CURSOR_DEFAULT_MODEL=gpt-5.6-sol-max-fast
export LOOM_AUTO_ROTATE_BUDGET_LIMIT=0
LOOM_TURN_TOKEN_BUDGET = 0   # off: logs print "tokens" too
LOOM_QUOTED="has # hash"
PATH=/evil
loom_lowercase=1
NOT A LINE
LOOM_EMPTY=
"""
    assert user_env.parse_env_text(text) == {
        "LOOM_CURSOR_DEFAULT_MODEL": "gpt-5.6-sol-max-fast",
        "LOOM_AUTO_ROTATE_BUDGET_LIMIT": "0",
        "LOOM_TURN_TOKEN_BUDGET": "0",
        "LOOM_QUOTED": "has # hash",
        "LOOM_EMPTY": "",
    }


def test_the_real_environment_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "env"
    env.write_text("LOOM_A_SETTING=from-file\nLOOM_B_SETTING=from-file\n")
    monkeypatch.setenv("LOOM_A_SETTING", "from-shell")
    monkeypatch.delenv("LOOM_B_SETTING", raising=False)
    assert user_env.load_user_env(env) == ["LOOM_B_SETTING"]
    assert os.environ["LOOM_A_SETTING"] == "from-shell"
    assert os.environ["LOOM_B_SETTING"] == "from-file"
    monkeypatch.delenv("LOOM_B_SETTING")


def test_a_missing_file_changes_nothing(tmp_path: Path) -> None:
    assert user_env.load_user_env(tmp_path / "absent") == []


def test_settings_reach_import_time_defaults(tmp_path: Path) -> None:
    """The default model is fixed when rud_task is imported, so the file must
    be loaded before that - which is what importing loom.cli guarantees."""
    home = tmp_path / "home"
    (home / ".loom").mkdir(parents=True)
    (home / ".loom" / "env").write_text(
        "LOOM_CURSOR_DEFAULT_MODEL=gpt-5.6-sol-max-fast\n"
        "LOOM_AUTO_ROTATE_BUDGET_LIMIT=3\n"
        "LOOM_TURN_TOKEN_BUDGET=2000000\n"
        "LOOM_CONTEXT_PERCENT_BUDGET=80\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("LOOM_")}
    env["HOME"] = str(home)
    probe = (
        "import loom.cli\n"
        "from loom import rud_task, usage_budget\n"
        "print(rud_task.CURSOR_DEFAULT_MODEL, usage_budget.auto_rotate_limit(),"
        " usage_budget.turn_token_budget(), usage_budget.context_percent_budget())\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["gpt-5.6-sol-max-fast", "3", "2000000", "80.0"]
