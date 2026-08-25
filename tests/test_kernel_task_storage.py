from __future__ import annotations

import json
from pathlib import Path

import loom.web_kernel as web
from loom.rud_task import create_task


def _task(tmp_path: Path, slug_title: str = "Kernel Storage"):
    return create_task(
        tmp_path,
        slug_title,
        "test kernel storage",
        kind="kernel",
        auto_worktree=False,
    )


def test_legacy_run_and_docs_migrate_to_task_tree(tmp_path: Path) -> None:
    meta = _task(tmp_path)
    task = tmp_path / ".RUD" / meta.slug
    (task / "INSTRUCTION.md").write_text("brief")
    (task / "EVALUATION.md").write_text("rubric")
    (task / "WIKI.md").write_text("knowledge")

    legacy = tmp_path / ".RUD" / "kernel-runs"
    legacy.mkdir()
    record = {
        "id": "run123",
        "state": "finished",
        "slug": meta.slug,
        "plugin": "torch.linear",
        "config": {"plugin": "torch.linear", "n_agents": 2},
    }
    (legacy / "run123.json").write_text(json.dumps(record))
    (legacy / "run123.log").write_text("launcher output")

    records = web._kernel_list_records(tmp_path, meta.slug)
    assert [r["id"] for r in records] == ["run123"]
    kernel = task / "kernel"
    assert (kernel / "INSTRUCTION.md").read_text() == "brief"
    assert (kernel / "EVALUATION.md").read_text() == "rubric"
    assert (kernel / "WIKI.md").read_text() == "knowledge"
    assert (kernel / "runs" / "run123" / "run.json").is_file()
    assert (kernel / "runs" / "run123" / "launcher.log").read_text() == "launcher output"
    assert (kernel / "contract" / "plugin.py").is_file()
    assert not (legacy / "run123.json").exists()


def test_submission_mirror_is_deduplicated(
    tmp_path: Path, monkeypatch
) -> None:
    meta = _task(tmp_path, "Mirror Test")
    rec = {
        "id": "run456",
        "state": "running",
        "slug": meta.slug,
        "run_id": "remote-run",
        "plugin": "torch.linear",
        "config": {
            "plugin": "torch.linear",
            "target": "cutedsl",
            "n_agents": 1,
        },
    }
    web._kernel_write_record(tmp_path, rec)
    web._initialize_kernel_run_artifacts(tmp_path, rec)

    def fake_helper(root, args, timeout=600, cluster=""):
        if args[0] == "job-source":
            return True, {"ok": True, "source": "def prepare(inputs):\n    return lambda: None\n"}
        return False, {"error": "not available"}

    monkeypatch.setattr(web, "_run_kernel_helper", fake_helper)
    monkeypatch.setattr(web, "_maybe_mirror_kernel_agent_logs", lambda *args: None)
    status = {
        "agents": [{"index": "1", "running": True}],
        "submissions": [{
            "job_id": "job1",
            "agent_index": 1,
            "state": "completed",
            "correct": True,
            "speedup": 1.25,
            "candidate_us": 8.0,
            "baseline_us": 10.0,
        }],
    }
    web._kernel_merge_submissions(tmp_path, rec, status)
    web._kernel_merge_submissions(tmp_path, rec, status)

    agent = (
        tmp_path / ".RUD" / meta.slug / "kernel" / "runs" / "run456"
        / "agents" / "agent-1"
    )
    sources = list((agent / "attempts").glob("*.py"))
    results = list((agent / "attempts").glob("*.json"))
    assert len(sources) == 1
    assert len(results) == 1
    assert (agent / "latest.py").is_file()
    wiki = (tmp_path / ".RUD" / meta.slug / "kernel" / "WIKI.md").read_text()
    assert wiki.count("kernel-submission:job1") == 1
    assert status["submissions"][0]["local_source_path"] == str(sources[0])


def test_judged_winner_archives_and_promotes(tmp_path: Path, monkeypatch) -> None:
    meta = _task(tmp_path, "Winner Test")
    worktree = tmp_path / "repo"
    worktree.mkdir()
    monkeypatch.setattr(web, "task_worktree_path", lambda root, slug: worktree)

    exported = web._export_judged_kernel(
        tmp_path,
        meta.slug,
        "run789",
        "job789",
        2.5,
        "def prepare(inputs):\n    return lambda: None\n",
        "demo.kernel",
    )
    assert Path(exported) == worktree / "demo_kernel_candidate.py"
    winner = (
        tmp_path / ".RUD" / meta.slug / "kernel" / "winners"
        / "job789" / "kernel.py"
    )
    assert winner.is_file()
    metadata = json.loads((winner.parent / "metadata.json").read_text())
    assert metadata["speedup"] == 2.5
