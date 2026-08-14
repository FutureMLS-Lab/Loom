"""Auto Rebuttal Factory domain and persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from loom import rebuttal_task as rebuttal


def _pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


def _rebuttal_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LOOM_REBUTTAL_REGISTRY",
        str(tmp_path / "registry.json"),
    )
    monkeypatch.setenv(
        "LOOM_REBUTTAL_ROOT",
        str(tmp_path / "studios"),
    )


@pytest.fixture()
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    _rebuttal_env(tmp_path, monkeypatch)
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


def test_register_conference_studio_and_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rebuttal_env(tmp_path, monkeypatch)
    payload = rebuttal.register_studio(
        "NeurIPS",
        2027,
        "https://neurips.test/call-for-papers",
    )
    studio = payload["studio"]
    assert studio["id"] == "neurips-2027"
    assert studio["stage"] == rebuttal.STUDIO_STAGE_POLICY_INPUT
    assert studio["papers"] == []
    listed = rebuttal.list_studios()
    assert listed[0]["title"] == "NeurIPS 2027"
    assert not listed[0]["policy_approved"]


def test_policy_fetch_rejects_private_urls() -> None:
    with pytest.raises(ValueError, match="public"):
        rebuttal._public_url("http://127.0.0.1/private-policy")
    with pytest.raises(ValueError, match="public"):
        rebuttal._public_url("http://localhost/rebuttal")


def test_policy_discovery_preserves_quotes_and_generates_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rebuttal_env(tmp_path, monkeypatch)
    studio_id = rebuttal.register_studio(
        "NeurIPS",
        2027,
        "https://neurips.test/cfp",
    )["studio"]["id"]

    def fake_fetcher(url: str):
        return {
            "url": url,
            "ok": True,
            "title": "NeurIPS 2027 CFP",
            "text": (
                "Author responses are limited to 10,000 characters. "
                "The submitted PDF cannot be revised during rebuttal."
            ),
            "links": [],
            "content_type": "text/html",
        }

    def fake_runner(*args, **kwargs):
        return {
            "ok": True,
            "text": """{
              "official_policy": {
                "platform": {
                  "value": "OpenReview",
                  "source_url": "https://neurips.test/cfp",
                  "quote": "Author responses",
                  "confidence": "high"
                },
                "character_limit": {
                  "value": 10000,
                  "source_url": "https://neurips.test/cfp",
                  "quote": "limited to 10,000 characters",
                  "confidence": "high"
                },
                "manuscript_frozen": {
                  "value": true,
                  "source_url": "https://neurips.test/cfp",
                  "quote": "submitted PDF cannot be revised",
                  "confidence": "high"
                }
              },
              "strategy": {
                "summary": "Reply point by point.",
                "response_structure": ["Thank the reviewer", "Answer W/Q items"],
                "priorities": ["AC blockers first"],
                "warnings": ["Keep 500 characters spare"]
              },
              "unknowns": ["Whether links are permitted"]
            }""",
            "cost": 0.12,
        }

    result = rebuttal.discover_studio_policy(
        studio_id,
        runner=fake_runner,
        fetcher=fake_fetcher,
    )
    assert result["ok"]
    assert result["policy"]["character_limit"] == 10_000
    assert result["policy"]["manuscript_frozen"]
    assert (
        result["policy_evidence"]["character_limit"]["source_url"]
        == "https://neurips.test/cfp"
    )
    assert result["strategy"]["priorities"] == ["AC blockers first"]
    assert result["unknowns"] == ["Whether links are permitted"]
    studio_dir = rebuttal.studio_path(studio_id).parent
    assert (studio_dir / rebuttal.POLICY_SOURCES_FILE).is_file()
    assert (studio_dir / rebuttal.POLICY_FILE).is_file()
    assert (studio_dir / rebuttal.STRATEGY_FILE).is_file()
    policy_markdown = (studio_dir / rebuttal.POLICY_MARKDOWN_FILE).read_text(
        encoding="utf-8"
    )
    strategy_markdown = (studio_dir / rebuttal.STRATEGY_FILE).read_text(
        encoding="utf-8"
    )
    assert "官方硬规则" in policy_markdown
    assert "每份回复字符上限" in policy_markdown
    assert "Rebuttal 接收策略" in strategy_markdown


def test_policy_approval_gates_paper_creation_and_inherits_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rebuttal_env(tmp_path, monkeypatch)
    studio_id = rebuttal.register_studio(
        "ICLR",
        2027,
        "https://iclr.test/cfp",
    )["studio"]["id"]
    source = tmp_path / "paper-package"
    source.mkdir()
    _pdf(source / "main.pdf")
    _pdf(source / "review.pdf")
    with pytest.raises(ValueError, match="approve"):
        rebuttal.register_paper_for_studio(studio_id, str(source))

    state = rebuttal.read_studio(studio_id)
    state["sources"] = [{"url": "https://iclr.test/cfp", "ok": True}]
    state["policy"] = rebuttal.normalize_policy(
        {
            **rebuttal.DEFAULT_POLICY,
            "character_limit": 8_000,
            "allow_links": True,
        }
    )
    state["stage"] = rebuttal.STUDIO_STAGE_AWAIT_POLICY_REVIEW
    rebuttal.write_studio(studio_id, state)
    approved = rebuttal.approve_studio_policy(studio_id)
    assert approved["studio"]["stage"] == rebuttal.STUDIO_STAGE_ACTIVE

    paper = rebuttal.register_paper_for_studio(
        studio_id,
        str(source),
        title="Paper A",
    )["project"]
    assert paper["studio_id"] == studio_id
    assert paper["policy"]["character_limit"] == 8_000
    assert paper["policy"]["allow_links"]
    assert rebuttal.studio_payload(studio_id)["studio"]["papers"][0]["id"] == paper["id"]

    rebuttal.save_studio_policy(
        studio_id,
        {
            **state["policy"],
            "character_limit": 7_000,
            "allow_links": False,
        },
    )
    rebuttal.approve_studio_policy(studio_id)
    inherited = rebuttal.read_state(paper["id"])
    assert inherited["policy"]["character_limit"] == 7_000
    assert not inherited["policy"]["allow_links"]
    with pytest.raises(ValueError, match="every Paper"):
        rebuttal.delete_studio(studio_id)


def test_validate_edit_and_approve(
    package: tuple[Path, str],
) -> None:
    source, project_id = package
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

    response_dir = source / rebuttal.OUTPUT_SUBDIR / rebuttal.RESPONSES_SUBDIR
    response_dir.mkdir(parents=True, exist_ok=True)
    body = (
        "# Response to Reviewer R1\n\n"
        "Thank you for the careful review and for recognizing the problem.\n\n"
        "### R1-W1: Missing baseline\n\n"
        "**Response.** We agree that this comparison is decisive.\n\n"
        "**Evidence.** The controlled result is 75% versus a 70% baseline.\n\n"
        "**Action/Scope.** If accepted, we will add this comparison to the paper.\n"
    )
    response_path = response_dir / "response-R1.md"
    response_path.write_text(body, encoding="utf-8")
    rebuttal.update_state(
        project_id,
        responses={
            "R1": {
                "reviewer_id": "R1",
                "path": str(response_path),
                "filename": "response-R1.md",
                "characters": len(body),
            }
        },
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


def test_prepare_and_ingest_live_agent_outputs(
    package: tuple[Path, str],
) -> None:
    source, project_id = package
    instructions = rebuttal.prepare_agent_instructions(project_id)
    text = instructions.read_text(encoding="utf-8")
    assert "Auto Rebuttal Agent Task" in text
    assert str(source) in text
    assert rebuttal.AGENT_COMPLETE_FILE in text

    out = source / rebuttal.OUTPUT_SUBDIR
    reviewer = {
        "id": "R1",
        "label": "Reviewer R1",
        "summary": "One concern.",
        "positive_points": [],
        "concerns": [
            {
                "id": "R1-W1",
                "type": "weakness",
                "summary": "Missing baseline",
                "verbatim": "Missing baseline.",
                "severity": "high",
                "response_mode": "correct",
                "evidence_needed": "baseline result",
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
        "# Response to Reviewer R1\n\n"
        "Thank you for the careful review.\n\n"
        "### R1-W1: Missing baseline\n\n"
        "We agree. The controlled baseline evidence directly resolves this "
        "concern and will be explained with its exact protocol.",
        encoding="utf-8",
    )
    (out / rebuttal.AGENT_COMPLETE_FILE).write_text(
        json.dumps(
            {
                "status": "complete",
                "reviewers": ["R1"],
                "summary": "Drafted one response.",
            }
        ),
        encoding="utf-8",
    )

    result = rebuttal.ingest_agent_outputs(project_id)
    assert result["ok"]
    assert result["reviewers"][0]["concerns"][0]["id"] == "R1-W1"
    assert result["responses"]["R1"]["characters"] > 100
    assert result["summary"] == "Drafted one response."


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
    rebuttal.update_state(project_id, active_job=rebuttal.JOB_POLICY)
    assert rebuttal.sweep_interrupted_jobs() == 1
    state = rebuttal.read_state(project_id)
    assert state["active_job"] == ""
    assert "interrupted" in state["error"]
