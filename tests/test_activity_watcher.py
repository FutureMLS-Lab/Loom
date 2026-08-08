"""Turning an agent's stop hook into "this task finished"."""

from __future__ import annotations

from loom.web import AgentActivityWatcher


class FakeRegistry:
    def __init__(self, projects):
        self._projects = projects

    def list_projects(self):
        return self._projects


def test_pane_tag_identifies_the_task_directly():
    """The tag Loom stamps on the pane needs no filesystem lookup."""
    watcher = AgentActivityWatcher(FakeRegistry([]))
    assert watcher.report_finished("", "abc123/my-task") == ("abc123", "my-task")

    snap = watcher.snapshot()
    entry = snap["tasks"]["abc123/my-task"]
    assert entry["finished_at"] > 0
    assert entry["working"] is False


def test_ack_clears_the_ring():
    watcher = AgentActivityWatcher(FakeRegistry([]))
    watcher.report_finished("", "abc123/my-task")
    watcher.ack("abc123", "my-task")
    assert watcher.snapshot()["tasks"]["abc123/my-task"]["finished_at"] == 0


def test_garbage_tags_are_ignored():
    watcher = AgentActivityWatcher(FakeRegistry([]))
    for bad in ("", "no-slash", "/", "abc/"):
        assert watcher.report_finished("", bad) is None


def test_falls_back_to_the_directory_for_panes_loom_did_not_start(tmp_path):
    project = tmp_path / "proj"
    task = project / ".RUD" / "some-task"
    (task / "work").mkdir(parents=True)
    (task / "task.json").write_text('{"slug": "some-task", "title": "t"}')

    watcher = AgentActivityWatcher(
        FakeRegistry([{"id": "pid1", "path": str(project)}])
    )
    # A worktree sits below the task directory; the deeper match still resolves
    # to the task that owns it.
    assert watcher.report_finished(str(task / "work"), "") == ("pid1", "some-task")


def test_a_directory_outside_every_task_reports_nothing(tmp_path):
    project = tmp_path / "proj"
    (project / ".RUD").mkdir(parents=True)
    watcher = AgentActivityWatcher(
        FakeRegistry([{"id": "pid1", "path": str(project)}])
    )
    # The repository root is what a stop event actually carries, and it maps to
    # no single task - guessing one would ring the wrong thing.
    assert watcher.report_finished(str(project), "") is None
