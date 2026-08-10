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
    monkeypatch.setenv(
        "LOOM_REBUTTAL_ROOT",
        str(tmp_path / "studios"),
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


def test_analyze_job_chains_automatic_draft(
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
            "cost": 0.1,
        },
    )
    launched = []
    monkeypatch.setattr(
        web,
        "_ar_run_async",
        lambda fn, *args: launched.append((fn, args)),
    )
    rebuttal.update_state(
        project,
        active_job=rebuttal.JOB_ANALYZE,
        auto_draft=True,
    )

    web._rebuttal_analyze_job(project, "claude-test")

    state = rebuttal.read_state(project)
    assert state["active_job"] == rebuttal.JOB_DRAFT
    assert launched == [
        (web._rebuttal_draft_job, (project, "claude-test"))
    ]
    assert any("automatically starting" in line for line in state["logs"])


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


def test_policy_job_updates_studio_stage_and_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "LOOM_REBUTTAL_REGISTRY",
        str(tmp_path / "registry.json"),
    )
    monkeypatch.setenv(
        "LOOM_REBUTTAL_ROOT",
        str(tmp_path / "studios"),
    )
    studio_id = rebuttal.register_studio(
        "WACV",
        2027,
        "https://wacv.test/cfp",
    )["studio"]["id"]
    monkeypatch.setattr(
        web.rebuttal,
        "discover_studio_policy",
        lambda studio_id, model, on_line: {
            "ok": True,
            "policy": {
                **rebuttal.DEFAULT_POLICY,
                "character_limit": 5_000,
            },
            "policy_evidence": {
                "character_limit": {
                    "source_url": "https://wacv.test/cfp",
                    "quote": "5,000 characters",
                    "confidence": "high",
                }
            },
            "strategy": {"summary": "Answer point by point."},
            "unknowns": [],
            "sources": [{"url": "https://wacv.test/cfp", "ok": True}],
            "cost": 0.15,
        },
    )
    rebuttal.update_studio(
        studio_id,
        active_job=rebuttal.JOB_POLICY,
        stage=rebuttal.STUDIO_STAGE_POLICY_DRAFT,
    )

    web._rebuttal_policy_job(studio_id, "claude-test")

    state = rebuttal.read_studio(studio_id)
    assert state["active_job"] == ""
    assert state["stage"] == rebuttal.STUDIO_STAGE_AWAIT_POLICY_REVIEW
    assert state["policy"]["character_limit"] == 5_000
    assert state["sources"][0]["ok"]
    assert state["cost_usd"] == 0.15
