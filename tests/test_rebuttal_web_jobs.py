"""Web background jobs for Auto Rebuttal Factory."""

from __future__ import annotations

import json
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


def test_live_agent_watcher_ingests_completion_marker(
    project: str,
) -> None:
    state = rebuttal.read_state(project)
    source = Path(state["source_path"])
    out = source / rebuttal.OUTPUT_SUBDIR
    reviewer = {
        "id": "R1",
        "label": "R1",
        "concerns": [
            {
                "id": "R1-W1",
                "type": "weakness",
                "summary": "Concern",
                "severity": "high",
                "response_mode": "clarify",
                "evidence_needed": "result",
            }
        ],
    }
    (out / rebuttal.CONCERNS_FILE).write_text(
        json.dumps({"reviewers": [reviewer]}),
        encoding="utf-8",
    )
    response_dir = out / rebuttal.RESPONSES_SUBDIR
    response_dir.mkdir(exist_ok=True)
    response_dir.joinpath("response-R1.md").write_text(
        "# Response to R1\n\n"
        "Thank you for the careful review.\n\n"
        "### R1-W1\n\n"
        "The direct evidence resolves this concern under the submitted scope, "
        "and the response states the exact boundary without overclaiming.",
        encoding="utf-8",
    )
    (out / rebuttal.AGENT_COMPLETE_FILE).write_text(
        json.dumps(
            {
                "status": "complete",
                "reviewers": ["R1"],
                "summary": "Done.",
            }
        ),
        encoding="utf-8",
    )
    rebuttal.update_state(
        project,
        execution_mode="tmux",
        tmux_target="loom-rebuttal-test:0.0",
        agent_status="running",
    )

    web._rebuttal_watch_agent(project)

    state = rebuttal.read_state(project)
    assert state["agent_status"] == "complete"
    assert state["stage"] == rebuttal.STAGE_RESPONSES
    assert state["responses"]["R1"]["characters"] > 100
    assert state["agent_summary"] == "Done."


def test_delivery_watcher_hands_marker_to_strict_preflight(
    project: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = rebuttal.read_state(project)
    source = Path(state["source_path"])
    attempt = source / rebuttal.OUTPUT_SUBDIR / "delivery" / "attempts" / "run-1"
    attempt.mkdir(parents=True)
    marker = attempt / web.delivery.DELIVERY_COMPLETE_FILE
    marker.write_text('{"status":"complete"}', encoding="utf-8")
    rebuttal.update_state(
        project,
        stage=rebuttal.STAGE_DELIVERY_AGENT,
        delivery={
            "run_id": "run-1",
            "phase": "agent_running",
            "agent_status": "running",
            "marker_path": str(marker),
            "tmux_target": "loom-rebuttal-delivery-test:0.0",
        },
    )
    observed: dict[str, str] = {}

    def fake_ingest(project_id: str) -> dict:
        current = rebuttal.read_state(project_id)
        observed["stage"] = str(current["stage"])
        observed["phase"] = str(current["delivery"]["phase"])
        current["stage"] = rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL
        current["delivery"]["phase"] = "awaiting_final_approval"
        current["delivery"]["agent_status"] = "complete"
        rebuttal.write_state(project_id, current)
        return {"ok": True}

    monkeypatch.setattr(web.delivery, "ingest_delivery_completion", fake_ingest)

    web._rebuttal_watch_delivery_agent(project)

    assert observed == {
        "stage": rebuttal.STAGE_DELIVERY_VALIDATING,
        "phase": "validating",
    }
    final = rebuttal.read_state(project)
    assert final["stage"] == rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL
    assert final["delivery"]["agent_status"] == "complete"
