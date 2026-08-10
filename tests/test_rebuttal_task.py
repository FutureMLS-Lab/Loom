"""Auto Rebuttal Factory domain and persistence tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from loom import rebuttal_task as rebuttal


def _pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


@pytest.fixture()
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    registry = tmp_path / "registry.json"
    monkeypatch.setenv("LOOM_REBUTTAL_REGISTRY", str(registry))
    source = tmp_path / "submission-package"
    source.mkdir()
    _pdf(source / "main.pdf")
    _pdf(source / "reviewer-R1-review.pdf")
    (source / "results.json").write_text(
        '{"accuracy": 0.75, "baseline": 0.70}\n',
        encoding="utf-8",
    )
    payload = rebuttal.register_project(str(source), title="Paper response")
    return source, payload["project"]["id"]


def test_register_scans_paper_reviews_and_materials(
    package: tuple[Path, str],
) -> None:
    source, project_id = package
    state = rebuttal.read_state(project_id)
    manifest = state["manifest"]
    assert manifest["ready"]
    assert manifest["paper_pdf"] == str(source / "main.pdf")
    assert manifest["review_pdfs"] == [str(source / "reviewer-R1-review.pdf")]
    assert {item["kind"] for item in manifest["files"]} == {
        "paper_pdf",
        "review_pdf",
        "material",
    }
    assert rebuttal.list_projects()[0]["id"] == project_id
    assert (source / rebuttal.OUTPUT_SUBDIR / rebuttal.MANIFEST_FILE).is_file()


def test_register_rejects_missing_or_invalid_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "LOOM_REBUTTAL_REGISTRY",
        str(tmp_path / "registry.json"),
    )
    with pytest.raises(ValueError, match="input path is required"):
        rebuttal.register_project("")
    with pytest.raises(ValueError, match="not a directory"):
        rebuttal.register_project(str(tmp_path / "missing"))


def test_analyze_reviews_writes_atomic_concern_matrix(
    package: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_id = package
    monkeypatch.setattr(
        rebuttal,
        "_paper_material",
        lambda state: ("Submitted paper text.", []),
    )
    monkeypatch.setattr(
        rebuttal,
        "_review_material",
        lambda state: ("Reviewer says the baseline is incomplete.", []),
    )

    def fake_runner(*args, **kwargs):
        return {
            "ok": True,
            "text": """{
              "reviewers": [{
                "id": "R1",
                "label": "Reviewer R1",
                "summary": "Promising but underspecified.",
                "positive_points": ["Important question"],
                "concerns": [
                  {
                    "id": "R1-W1",
                    "type": "weakness",
                    "verbatim": "The baseline is incomplete.",
                    "summary": "Missing a strong baseline.",
                    "severity": "high",
                    "response_mode": "correct",
                    "evidence_needed": "Controlled baseline result"
                  },
                  {
                    "id": "R1-Q1",
                    "type": "question",
                    "verbatim": "How sensitive is lambda?",
                    "summary": "Clarify lambda sensitivity.",
                    "severity": "medium",
                    "response_mode": "clarify",
                    "evidence_needed": "Ablation"
                  }
                ]
              }]
            }""",
            "cost": 0.2,
        }

    result = rebuttal.analyze_project(project_id, runner=fake_runner)
    assert result["ok"]
    assert [item["id"] for item in result["reviewers"][0]["concerns"]] == [
        "R1-W1",
        "R1-Q1",
    ]
    concern_json = source / rebuttal.OUTPUT_SUBDIR / rebuttal.CONCERNS_FILE
    concern_md = source / rebuttal.OUTPUT_SUBDIR / rebuttal.CONCERN_MATRIX_FILE
    assert concern_json.is_file()
    assert "R1-W1" in concern_md.read_text(encoding="utf-8")


def test_analysis_refuses_image_only_or_empty_pdfs(
    package: tuple[Path, str],
) -> None:
    _, project_id = package
    result = rebuttal.analyze_project(
        project_id,
        runner=lambda *args, **kwargs: pytest.fail("model must not run"),
    )
    assert not result["ok"]
    assert "no extractable text" in result["error"]


def test_draft_validate_edit_and_approve(
    package: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_id = package
    monkeypatch.setattr(
        rebuttal,
        "_paper_material",
        lambda state: ("Submitted paper text.", []),
    )
    reviewers = [
        {
            "id": "R1",
            "label": "Reviewer R1",
            "summary": "",
            "positive_points": ["Important problem"],
            "concerns": [
                {
                    "id": "R1-W1",
                    "type": "weakness",
                    "summary": "Missing baseline",
                    "verbatim": "",
                    "severity": "high",
                    "response_mode": "correct",
                    "evidence_needed": "result",
                }
            ],
        }
    ]
    rebuttal.update_state(
        project_id,
        reviewers=reviewers,
        stage=rebuttal.STAGE_CONCERNS,
    )

    def fake_runner(*args, **kwargs):
        return {
            "ok": True,
            "text": (
                "# Response to Reviewer R1\n\n"
                "Thank you for the careful review and for recognizing the problem.\n\n"
                "### R1-W1: Missing baseline\n\n"
                "**Response.** We agree that this comparison is decisive.\n\n"
                "**Evidence.** The controlled result is 75% versus a 70% baseline.\n\n"
                "**Action/Scope.** If accepted, we will add this comparison to the paper."
            ),
            "cost": 0.1,
        }

    result = rebuttal.draft_project(project_id, runner=fake_runner)
    assert result["ok"]
    rebuttal.update_state(
        project_id,
        responses=result["responses"],
        stage=rebuttal.STAGE_RESPONSES,
    )
    report = rebuttal.validate_project(project_id)
    assert report["ready"], report["errors"]
    rebuttal.update_state(
        project_id,
        validation=report,
        stage=rebuttal.STAGE_VALIDATED,
    )
    approved = rebuttal.approve_project(project_id)
    assert approved["project"]["stage"] == rebuttal.STAGE_APPROVED
    assert approved["project"]["approved_at"]

    edited = rebuttal.response_body(project_id, "R1").replace("75%", "76%")
    payload = rebuttal.save_response(project_id, "R1", edited)
    assert payload["project"]["stage"] == rebuttal.STAGE_RESPONSES
    assert not payload["project"]["validation"]
    assert "76%" in rebuttal.response_body(project_id, "R1")
    assert (
        source
        / rebuttal.OUTPUT_SUBDIR
        / rebuttal.RESPONSES_SUBDIR
        / "response-R1.md"
    ).is_file()


def test_validation_blocks_policy_leaks(
    package: tuple[Path, str],
) -> None:
    _, project_id = package
    reviewer = {
        "id": "R1",
        "label": "R1",
        "concerns": [{"id": "R1-W1", "summary": "Concern"}],
    }
    rebuttal.update_state(project_id, reviewers=[reviewer])
    source = Path(rebuttal.read_state(project_id)["source_path"])
    response_dir = source / rebuttal.OUTPUT_SUBDIR / rebuttal.RESPONSES_SUBDIR
    response_dir.mkdir(parents=True, exist_ok=True)
    path = response_dir / "response-R1.md"
    path.write_text(
        "# Response\n\n"
        "R1-W1\n\n"
        "We revised the manuscript and we will add another figure. "
        "See https://example.com for the private artifact. "
        "This paragraph is deliberately long enough to be substantive.",
        encoding="utf-8",
    )
    rebuttal.update_state(
        project_id,
        responses={
            "R1": {
                "reviewer_id": "R1",
                "path": str(path),
                "filename": path.name,
                "characters": path.stat().st_size,
            }
        },
    )
    report = rebuttal.validate_project(project_id)
    assert not report["ready"]
    errors = "\n".join(report["errors"])
    assert "forbidden URL" in errors
    assert "already revised" in errors
    assert 'If accepted, we will' in errors


def test_delete_forgets_registry_but_preserves_output(
    package: tuple[Path, str],
) -> None:
    source, project_id = package
    assert rebuttal.delete_project(project_id)
    assert not rebuttal.read_state(project_id)
    assert (source / rebuttal.OUTPUT_SUBDIR / rebuttal.STATE_FILE).is_file()


def test_sweep_marks_interrupted_jobs(
    package: tuple[Path, str],
) -> None:
    _, project_id = package
    rebuttal.update_state(project_id, active_job=rebuttal.JOB_DRAFT)
    assert rebuttal.sweep_interrupted_jobs() == 1
    state = rebuttal.read_state(project_id)
    assert state["active_job"] == ""
    assert "interrupted" in state["error"]
