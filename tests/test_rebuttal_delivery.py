"""Delivery harness tests for WACV-style rebuttal artifacts."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from loom import rebuttal_delivery as delivery
from loom import rebuttal_task as rebuttal


def _pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


@pytest.fixture()
def approved_wacv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str]:
    monkeypatch.setenv("LOOM_REBUTTAL_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setenv("LOOM_REBUTTAL_ROOT", str(tmp_path / "studios"))
    studio_id = rebuttal.register_studio(
        "WACV",
        2027,
        "https://wacv.test/author-guide",
    )["studio"]["id"]
    studio = rebuttal.read_studio(studio_id)
    studio["sources"] = [{"url": "https://wacv.test/author-guide", "ok": True}]
    studio["policy"] = rebuttal.normalize_policy(
        {
            **rebuttal.DEFAULT_POLICY,
            "manuscript_frozen": False,
            "allow_revised_pdf": True,
            "allow_attachments": True,
            "submission_instructions": (
                "Submit a revised paper and a one page rebuttal using the "
                "official template as a revision of the same OpenReview paper."
            ),
        }
    )
    studio["stage"] = rebuttal.STUDIO_STAGE_AWAIT_POLICY_REVIEW
    rebuttal.write_studio(studio_id, studio)
    rebuttal.approve_studio_policy(studio_id)

    source = tmp_path / "paper-2237"
    (source / "latex").mkdir(parents=True)
    (source / "review-rebuttal").mkdir()
    _pdf(source / "paper.pdf")
    _pdf(source / "review.pdf")
    (source / "latex" / "main.tex").write_text(
        "\\documentclass[10pt,twocolumn,letterpaper]{article}\n"
        "\\usepackage[review,algorithms]{wacv}\n"
        "\\def\\wacvPaperID{2237}\n"
        "\\begin{document}Revised paper.\\end{document}\n",
        encoding="utf-8",
    )
    (source / "latex" / "wacv.sty").write_text(
        "% test style\n",
        encoding="utf-8",
    )
    (source / "review-rebuttal" / "author-response-draft.tex").write_text(
        "\\documentclass[10pt,twocolumn,letterpaper]{article}\n"
        "\\usepackage[rebuttal,algorithms]{wacv}\n"
        "\\def\\wacvPaperID{2237}\n"
        "\\begin{document}Response.\\end{document}\n",
        encoding="utf-8",
    )
    project_id = rebuttal.register_paper_for_studio(
        studio_id,
        str(source),
        title="2237",
    )["project"]["id"]
    reviewer = {
        "id": "R1",
        "label": "Reviewer R1",
        "concerns": [
            {
                "id": "R1-W1",
                "type": "weakness",
                "summary": "Clarify the theorem.",
                "severity": "high",
                "response_mode": "correct",
                "evidence_needed": "revised statement",
            }
        ],
    }
    out = source / rebuttal.OUTPUT_SUBDIR
    response_dir = out / rebuttal.RESPONSES_SUBDIR
    response_dir.mkdir(exist_ok=True)
    response = response_dir / "response-R1.md"
    response.write_text(
        "# Response to R1\n\n"
        "Thank you for the careful review.\n\n"
        "### R1-W1\n\n"
        "We clarify the conditional theorem and its exact assumptions in the "
        "revised source while keeping unsupported experiments prospective.\n",
        encoding="utf-8",
    )
    rebuttal.update_state(
        project_id,
        reviewers=[reviewer],
        responses={
            "R1": {
                "reviewer_id": "R1",
                "path": str(response),
                "characters": len(response.read_text(encoding="utf-8")),
            }
        },
        stage=rebuttal.STAGE_RESPONSES,
    )
    report = rebuttal.validate_project(project_id)
    assert report["ready"]
    rebuttal.update_state(
        project_id,
        validation=report,
        stage=rebuttal.STAGE_VALIDATED,
    )
    rebuttal.approve_project(project_id)
    return source, project_id


def _write_completion(prepared: dict, *, run_id: str = "") -> None:
    attempt = Path(prepared["attempt"])
    workspace = Path(prepared["workspace"])
    (attempt / delivery.REVISION_MAP_FILE).write_text(
        json.dumps(
            {
                "paper_id": "2237",
                "changes": [
                    {
                        "concern_ids": ["R1-W1"],
                        "section": "3",
                        "pages": "4",
                        "summary": "Clarified the conditional theorem.",
                        "status": "implemented",
                    }
                ],
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    marker = {
        "status": "complete",
        "run_id": run_id or prepared["run_id"],
        "input_digest": prepared["input_digest"],
        "rebuttal_tex": str(
            (
                workspace
                / "source"
                / "review-rebuttal"
                / "author-response-draft.tex"
            ).relative_to(workspace)
        ),
        "paper_tex": str(
            (workspace / "source" / "latex" / "main.tex").relative_to(workspace)
        ),
        "supplement": "",
        "revision_map": delivery.REVISION_MAP_FILE,
        "summary": "Prepared synchronized sources.",
    }
    Path(prepared["marker"]).write_text(json.dumps(marker), encoding="utf-8")


def _fake_builder(rebuttal_pages: int = 1, paper_pages: int = 2):
    def build(
        tex_path: Path,
        build_root: Path,
        output_name: str,
        *,
        timeout: int = 360,
    ) -> dict:
        del tex_path, timeout
        output = build_root / output_name
        _pdf(
            output,
            rebuttal_pages if output_name == "rebuttal.pdf" else paper_pages,
        )
        return {
            "ok": True,
            "pdf": str(output),
            "compiler": "test",
            "log": "",
            "attempts": [],
        }

    return build


def test_prepare_attempt_freezes_inputs_in_isolated_workspace(
    approved_wacv: tuple[Path, str],
) -> None:
    source, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    workspace = Path(prepared["workspace"])

    assert prepared["input_digest"]
    assert workspace != source
    assert (workspace / "source" / "latex" / "main.tex").is_file()
    assert (
        workspace
        / "source"
        / "review-rebuttal"
        / "author-response-draft.tex"
    ).is_file()
    assert (
        Path(prepared["attempt"])
        / "inputs"
        / "responses"
        / "response-R1.md"
    ).is_file()
    instructions = Path(prepared["instructions"]).read_text(encoding="utf-8")
    assert prepared["run_id"] in instructions
    assert prepared["input_digest"] in instructions
    assert "Never upload to OpenReview" in instructions


def test_stale_delivery_marker_is_rejected(
    approved_wacv: tuple[Path, str],
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared, run_id="stale-run")

    result = delivery.ingest_delivery_completion(project_id)

    assert not result["ok"]
    assert "stale" in result["error"]


def test_delivery_build_validates_and_approval_binds_hashes(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared)
    monkeypatch.setattr(delivery, "strict_build_pdf", _fake_builder())

    result = delivery.ingest_delivery_completion(project_id)

    assert result["ok"]
    state = rebuttal.read_state(project_id)
    assert state["stage"] == rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL
    assert state["delivery"]["validation"]["ready"]
    assert Path(state["delivery"]["artifacts"]["rebuttal"]["path"]).is_file()
    assert Path(state["delivery"]["artifacts"]["revised_paper"]["path"]).is_file()

    approved = delivery.approve_delivery(project_id)["project"]
    assert approved["stage"] == rebuttal.STAGE_BUNDLE_READY
    assert approved["delivery"]["final_approval"]["artifact_sha256"]
    bundle = Path(approved["delivery"]["bundle"]["path"])
    assert bundle.is_file()
    with zipfile.ZipFile(bundle) as archive:
        assert "rebuttal.pdf" in archive.namelist()
        assert "revised-paper.pdf" in archive.namelist()


def test_two_page_rebuttal_blocks_delivery(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared)
    monkeypatch.setattr(delivery, "strict_build_pdf", _fake_builder(2))

    result = delivery.ingest_delivery_completion(project_id)

    assert not result["ok"]
    assert "exactly 1 page" in result["error"]
    assert (
        rebuttal.read_state(project_id)["stage"]
        == rebuttal.STAGE_DELIVERY_BLOCKED
    )


def test_source_drift_invalidates_final_artifact_approval(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared)
    monkeypatch.setattr(delivery, "strict_build_pdf", _fake_builder())
    assert delivery.ingest_delivery_completion(project_id)["ok"]
    (source / "latex" / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}changed\\end{document}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source changed"):
        delivery.approve_delivery(project_id)


def test_artifact_drift_invalidates_final_artifact_approval(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared)
    monkeypatch.setattr(delivery, "strict_build_pdf", _fake_builder())
    assert delivery.ingest_delivery_completion(project_id)["ok"]
    state = rebuttal.read_state(project_id)
    artifact = Path(state["delivery"]["artifacts"]["rebuttal"]["path"])
    artifact.write_bytes(artifact.read_bytes() + b"changed")

    with pytest.raises(ValueError, match="artifact changed"):
        delivery.approve_delivery(project_id)


def test_total_revised_paper_pages_do_not_block_delivery(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared)
    monkeypatch.setattr(
        delivery,
        "strict_build_pdf",
        _fake_builder(paper_pages=100),
    )

    result = delivery.ingest_delivery_completion(project_id)

    assert result["ok"]


def test_wrong_wacv_track_is_blocked(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    workspace = Path(prepared["workspace"])
    response_tex = (
        workspace
        / "source"
        / "review-rebuttal"
        / "author-response-draft.tex"
    )
    response_tex.write_text(
        response_tex.read_text(encoding="utf-8").replace(
            "rebuttal,algorithms",
            "rebuttal,datasets",
        ),
        encoding="utf-8",
    )
    _write_completion(prepared)
    monkeypatch.setattr(delivery, "strict_build_pdf", _fake_builder())

    result = delivery.ingest_delivery_completion(project_id)

    assert not result["ok"]
    assert "wrong WACV track" in result["error"]


def test_three_model_figure_verification_requires_unanimous_pass(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared)
    monkeypatch.setattr(delivery, "strict_build_pdf", _fake_builder())
    assert delivery.ingest_delivery_completion(project_id)["ok"]
    monkeypatch.setattr(
        delivery.ar,
        "_cursor_models",
        lambda: {
            "ok": True,
            "models": list(delivery.ar.CURSOR_REVIEWER_MODELS),
        },
    )

    def fake_review(prompt, model, workspace, **kwargs):
        del prompt, workspace, kwargs
        passed = model != delivery.ar.CURSOR_REVIEWER_MODELS[-1]
        verdict = "PASS" if passed else "FAIL"
        rating = 8 if passed else 6
        return {
            "ok": True,
            "model": model,
            "review": (
                "# Figure Verification\n\n"
                f"Figure Verdict: {verdict}\n\n"
                "## Blocking Figure Issues\n"
                + ("- None\n" if passed else "- Figure 1 labels are unreadable.\n")
            ),
            "scores": {"rating": rating},
        }

    monkeypatch.setattr(delivery.ar, "_run_cursor_headless", fake_review)

    result = delivery.verify_delivery_figures(project_id)

    assert not result["ok"]
    assert (
        rebuttal.read_state(project_id)["stage"]
        == rebuttal.STAGE_DELIVERY_BLOCKED
    )
    assert [
        item["figure_pass"] for item in result["report"]["reviewers"]
    ] == [True, True, False]


def test_three_model_figure_verification_unlocks_final_approval(
    approved_wacv: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, project_id = approved_wacv
    prepared = delivery.prepare_delivery_attempt(project_id)
    _write_completion(prepared)
    monkeypatch.setattr(delivery, "strict_build_pdf", _fake_builder())
    assert delivery.ingest_delivery_completion(project_id)["ok"]
    state = rebuttal.read_state(project_id)
    state["delivery"]["figure_redraw"] = {"status": "complete"}
    rebuttal.write_state(project_id, state)
    monkeypatch.setattr(
        delivery.ar,
        "_cursor_models",
        lambda: {
            "ok": True,
            "models": list(delivery.ar.CURSOR_REVIEWER_MODELS),
        },
    )
    monkeypatch.setattr(
        delivery.ar,
        "_run_cursor_headless",
        lambda prompt, model, workspace, **kwargs: {
            "ok": True,
            "model": model,
            "review": (
                "# Figure Verification\n\n"
                "Figure Verdict: PASS\n\n"
                "## Blocking Figure Issues\n- None\n"
            ),
            "scores": {"rating": 8},
        },
    )

    result = delivery.verify_delivery_figures(project_id)

    assert result["ok"]
    assert (
        rebuttal.read_state(project_id)["stage"]
        == rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL
    )
    approved = delivery.approve_delivery(project_id)["project"]
    assert approved["stage"] == rebuttal.STAGE_BUNDLE_READY
