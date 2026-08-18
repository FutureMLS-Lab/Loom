from __future__ import annotations

import subprocess
from pathlib import Path

from loom.rud_task import (
    create_task,
    list_worktree_candidates,
    prepare_task_worktree_from,
)
from loom.web_projects import WebProjectRegistry


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    (path / "README.md").write_text("test\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def test_project_code_root_defaults_to_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = WebProjectRegistry(tmp_path / "registry.json")
    pid = registry.ensure_project(project)
    assert registry.get_code_root_pattern(pid) == "."
    assert registry.get_code_root(pid) == project.resolve()


def test_nested_code_root_is_persisted_and_resolved(tmp_path: Path) -> None:
    project = tmp_path / "project"
    code = project / "src" / "code"
    code.mkdir(parents=True)
    registry = WebProjectRegistry(tmp_path / "registry.json")
    pid = registry.ensure_project(project)
    ok, error = registry.set_code_root_pattern(pid, "src/code")
    assert ok, error
    assert registry.get_code_root_pattern(pid) == "src/code"
    assert registry.get_code_root(pid) == code.resolve()

    reloaded = WebProjectRegistry(tmp_path / "registry.json")
    assert reloaded.get_code_root(pid) == code.resolve()


def test_code_root_rejects_escape_and_missing_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = WebProjectRegistry(tmp_path / "registry.json")
    pid = registry.ensure_project(project)
    assert registry.set_code_root_pattern(pid, "../outside")[0] is False
    assert registry.set_code_root_pattern(pid, "/tmp")[0] is False
    assert registry.set_code_root_pattern(pid, "src/missing")[0] is False


def test_nested_code_root_is_preferred_worktree_candidate(tmp_path: Path) -> None:
    project = tmp_path / "project"
    code = project / "src" / "code"
    _git_init(code)
    candidates = list_worktree_candidates(project, [code])
    assert candidates[0] == {
        "path": str(code.resolve()),
        "name": "code",
        "kind": "preferred",
    }


def test_task_worktree_can_be_created_from_nested_code_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    code = project / "src" / "code"
    _git_init(code)
    meta = create_task(
        project,
        "Nested task",
        "test nested code root",
        auto_worktree=False,
    )
    worktree, branch, error = prepare_task_worktree_from(project, meta.slug, code)
    assert worktree is not None, error
    assert worktree == (project / ".RUD" / meta.slug / "work" / "code").resolve()
    assert branch == "loom/nested-task"
