"""The Review Factory: the panel as a service, shared with the Paper Factory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loom import ar_task as ar
from loom import review_task as review


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOM_REVIEW_REGISTRY", str(tmp_path / "registry.json"))
    source = tmp_path / "paper"
    source.mkdir()
    (source / "main.pdf").write_bytes(b"%PDF-1.4\n% test\n")
    return source


def test_register_list_and_unregister(registry):
    record = review.register_project(str(registry), title="My Paper", venue="iclr")
    assert record["id"] == review.project_id_for(registry)
    listed = review.list_projects()
    assert len(listed) == 1
    assert listed[0]["title"] == "My Paper"
    assert listed[0]["status"] == "idle"
    assert listed[0]["venue"] == "iclr"
    # Registering again updates rather than duplicates.
    review.register_project(str(registry), title="Renamed")
    assert [p["title"] for p in review.list_projects()] == ["Renamed"]
    assert review.unregister_project(record["id"]) is True
    assert review.list_projects() == []


def test_register_requires_a_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOM_REVIEW_REGISTRY", str(tmp_path / "registry.json"))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        review.register_project(str(empty))


def test_panel_review_delegates_with_the_default_rubric(monkeypatch, tmp_path):
    seen = {}

    def fake_run_reviewer(paper_dir, skill_text, **kwargs):
        seen["paper_dir"] = paper_dir
        seen["skill_text"] = skill_text
        seen["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(ar, "run_reviewer", fake_run_reviewer)
    out = review.panel_review(tmp_path, venue="iclr", round_n=3)
    assert out == {"ok": True}
    assert seen["paper_dir"] == tmp_path
    assert seen["kwargs"]["round_n"] == 3
    # No rubric given: the shared AR reviewer methodology rides along.
    assert "review" in seen["skill_text"].lower()


def test_run_project_review_persists_the_report(registry, monkeypatch):
    record = review.register_project(str(registry), venue="iclr")

    def fake_run_reviewer(paper_dir, skill_text, **kwargs):
        # The structural gate must be bypassed for an external PDF.
        assert kwargs["readiness"]["ready"] is True
        assert kwargs["build"]["pdf"].endswith("main.pdf")
        return {
            "ok": True,
            "review": "# Panel\nfine work",
            "scores": {"rating": 6},
            "headline": "solid",
            "deciding_model": "m1",
            "models": ["m1", "m2", "m3"],
            "reviewers": [{"model": "m1", "scores": {"rating": 6}}],
        }

    monkeypatch.setattr(ar, "run_reviewer", fake_run_reviewer)
    res = review.run_project_review(record["id"])
    assert res["ok"] is True
    state = review.read_state(record["id"])
    assert state["status"] == "done"
    assert state["latest_review"]["scores"]["rating"] == 6
    run_dir = Path(state["latest_review"]["path"])
    assert (run_dir / "review.md").read_text(encoding="utf-8").startswith("# Panel")
    assert json.loads((run_dir / "panel.json").read_text())["headline"] == "solid"
    listed = review.list_projects()
    assert listed[0]["rating"] == 6
