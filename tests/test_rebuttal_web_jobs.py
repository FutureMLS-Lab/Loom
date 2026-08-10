"""Web background jobs for Auto Rebuttal Factory."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from loom import rebuttal_task as rebuttal
from loom import web


def _pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(
        "LOOM_REBUTTAL_REGISTRY",
        str(tmp_path / "registry.json"),
    )
    source = tmp_path / "package"
    source.mkdir()
    _pdf(source / "paper.pdf")
    _pdf(source / "review.pdf")
    return rebuttal.register_project(str(source))["project"]["id"]


def test_analyze_job_updates_stage_cost_and_logs(
    project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer = {
        "id": "R1",
        "label": "R1",
        "concerns": [{"id": "R1-W1", "summary": "Concern"}],
    }
    monkeypatch.setattr(
        web.rebuttal,
        "analyze_project",
        lambda project_id, model, on_line: {
            "ok": True,
            "reviewers": [reviewer],
            "cost": 0.4,
        },
    )
    rebuttal.update_state(project, active_job=rebuttal.JOB_ANALYZE)

    web._rebuttal_analyze_job(project, "claude-test")

    state = rebuttal.read_state(project)
    assert state["active_job"] == ""
    assert state["stage"] == rebuttal.STAGE_CONCERNS
    assert state["reviewers"] == [reviewer]
    assert state["cost_usd"] == 0.4
    assert any("extracted 1 concern" in line for line in state["logs"])


def test_draft_job_keeps_partial_responses_on_failure(
    project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = {
        "R1": {
            "reviewer_id": "R1",
            "path": "/tmp/response-R1.md",
            "characters": 100,
        }
    }
    monkeypatch.setattr(
        web.rebuttal,
        "draft_project",
        lambda project_id, model, on_line: {
            "ok": False,
            "error": "R2 model failed",
            "responses": partial,
            "cost": 0.2,
        },
    )
    rebuttal.update_state(
        project,
        active_job=rebuttal.JOB_DRAFT,
        reviewers=[{"id": "R1", "concerns": []}, {"id": "R2", "concerns": []}],
    )

    web._rebuttal_draft_job(project, "claude-test")

    state = rebuttal.read_state(project)
    assert state["active_job"] == ""
    assert state["error"] == "R2 model failed"
    assert state["responses"] == partial
    assert state["cost_usd"] == 0.2
