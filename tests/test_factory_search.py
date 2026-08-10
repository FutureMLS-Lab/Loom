"""Research Factory search suggestion and mining state integration."""

from __future__ import annotations

from pathlib import Path

from loom import ar_task as ar
from loom import web
from loom.rud_task import create_task


def _studio(tmp_path: Path) -> tuple[Path, str]:
    (tmp_path / ".RUD").mkdir()
    meta = create_task(
        tmp_path,
        "Vision studio",
        "Find image generation topics",
        kind=ar.KIND_AR,
        auto_worktree=False,
    )
    state = ar.new_studio_state(
        direction="custom",
        custom_direction="Image or video generation for a vision conference.",
    )
    state["search_suggest_status"] = "running"
    ar.write_ar_state(tmp_path, meta.slug, state)
    return tmp_path, meta.slug


def test_search_suggestion_job_persists_editable_settings(
    tmp_path: Path, monkeypatch
) -> None:
    root, slug = _studio(tmp_path)
    monkeypatch.setattr(
        web.ar,
        "suggest_search_settings",
        lambda state, model, on_line: {
            "ok": True,
            "terms": ["image generation", "video generation", "flow matching"],
            "categories": ["cs.CV", "eess.IV"],
            "rationale": "Visual generation work is concentrated here.",
            "cost": 0.03,
        },
    )

    web._ar_search_suggest_job(root, slug, "claude-test")

    state = ar.read_ar_state(root, slug)
    assert state["search_suggest_status"] == "done"
    assert state["search_terms"] == [
        "image generation",
        "video generation",
        "flow matching",
    ]
    assert state["search_categories"] == ["cs.CV", "eess.IV"]
    assert state["search_terms_source"] == "model"
    assert state["search_suggest_rationale"].startswith("Visual generation")
    assert state["cost_usd"] == 0.03
    log = ar.job_log_path(root, slug, ar.JOB_SEARCH).read_text(encoding="utf-8")
    assert "terms: image generation" in log


def test_search_suggestion_job_preserves_manual_fallback_on_error(
    tmp_path: Path, monkeypatch
) -> None:
    root, slug = _studio(tmp_path)
    ar.update_ar_state(
        root,
        slug,
        search_terms=["manual term"],
        search_categories=["cs.CV"],
        search_terms_source="user",
    )
    monkeypatch.setattr(
        web.ar,
        "suggest_search_settings",
        lambda state, model, on_line: {
            "ok": False,
            "error": "model unavailable",
            "cost": 0.01,
        },
    )

    web._ar_search_suggest_job(root, slug, "claude-test")

    state = ar.read_ar_state(root, slug)
    assert state["search_suggest_status"] == "error"
    assert state["search_suggest_error"] == "model unavailable"
    assert state["search_terms"] == ["manual term"]
    assert state["search_categories"] == ["cs.CV"]
    assert state["cost_usd"] == 0.01


def test_mining_job_uses_persisted_settings_and_records_zero_results(
    tmp_path: Path, monkeypatch
) -> None:
    root, slug = _studio(tmp_path)
    ar.update_ar_state(
        root,
        slug,
        search_terms=["image generation", "video generation"],
        search_categories=["cs.CV", "eess.IV"],
        search_terms_source="user",
        papers_status="running",
    )
    seen = {}

    def fake_mine(direction, custom_direction, **kwargs):
        seen.update(kwargs)
        return {
            "ok": True,
            "papers": [],
            "query": "(cat:cs.CV) AND (abs:\"image generation\")",
        }

    monkeypatch.setattr(web.ar, "mine_papers", fake_mine)

    web._ar_mine_job(root, slug, 40, False)

    assert seen["search_terms"] == ["image generation", "video generation"]
    assert seen["categories"] == ["cs.CV", "eess.IV"]
    state = ar.read_ar_state(root, slug)
    assert state["papers_status"] == "done"
    assert state["papers"] == []
    assert state["papers_query"].startswith("(cat:cs.CV)")
