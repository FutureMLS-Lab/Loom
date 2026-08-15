"""Venue-cycle research and venue-informed idea generation."""

from __future__ import annotations

from pathlib import Path

from loom import ar_task as ar
from loom import web
from loom.rud_task import create_task

_REPORT_JSON = """Here is what I found.

```json
{"cycle": "WACV 2026",
 "best_papers": [{"title": "Winner One", "arxiv_id": "2410.01234",
                  "topic": "3D reconstruction", "note": "unanimous award"}],
 "orals": [{"title": "Oral One", "arxiv_id": "", "topic": "video editing",
            "note": ""}],
 "hot_topics": [{"topic": "feed-forward 3D", "evidence": "12 accepted papers",
                 "papers": [{"title": "Rep A", "arxiv_id": "2409.09999"}]}],
 "gaps": ["evaluation beyond curated benchmarks"],
 "summary": "3D and generative video dominated the cycle."}
```
"""


def _studio(tmp_path: Path) -> tuple[Path, str]:
    (tmp_path / ".RUD").mkdir()
    meta = create_task(
        tmp_path,
        "Vision studio",
        "Find vision topics",
        kind=ar.KIND_AR,
        auto_worktree=False,
    )
    state = ar.new_studio_state(direction="multimodal", venue="wacv")
    ar.write_ar_state(tmp_path, meta.slug, state)
    return tmp_path, meta.slug


def test_normalize_venue_report_bounds_and_drops_empty_titles() -> None:
    raw = {
        "cycle": "X" * 500,
        "best_papers": [{"title": ""}, {"title": "Kept", "note": "n" * 900}]
        + [{"title": f"P{i}"} for i in range(40)],
        "hot_topics": [{"topic": "", "papers": []}]
        + [{"topic": f"T{i}", "papers": [{"title": "p"}] * 20} for i in range(20)],
        "gaps": ["", "  real gap  "] + [f"g{i}" for i in range(20)],
        "summary": "s" * 5000,
    }
    report = ar.normalize_venue_report(raw)
    assert len(report["cycle"]) == 120
    assert report["best_papers"][0]["title"] == "Kept"
    assert len(report["best_papers"][0]["note"]) == 400
    assert len(report["best_papers"]) == ar.VENUE_REPORT_MAX_ENTRIES
    assert len(report["hot_topics"]) == ar.VENUE_REPORT_MAX_TOPICS
    assert all(len(t["papers"]) <= 6 for t in report["hot_topics"])
    assert report["gaps"][0] == "real gap"
    assert len(report["gaps"]) == ar.VENUE_REPORT_MAX_GAPS
    assert len(report["summary"]) == 2000


def test_research_venue_cycle_parses_fenced_report(monkeypatch) -> None:
    state = ar.new_studio_state(direction="multimodal", venue="wacv")
    monkeypatch.setattr(
        ar,
        "_run_headless",
        lambda prompt, model="", timeout=0, on_line=None: {
            "ok": True,
            "text": _REPORT_JSON,
            "cost": 0.42,
        },
    )
    res = ar.research_venue_cycle(state)
    assert res["ok"]
    assert res["cost"] == 0.42
    assert res["report"]["cycle"] == "WACV 2026"
    assert res["report"]["best_papers"][0]["arxiv_id"] == "2410.01234"
    assert res["report"]["hot_topics"][0]["papers"][0]["title"] == "Rep A"


def test_research_venue_cycle_rejects_empty_report(monkeypatch) -> None:
    state = ar.new_studio_state(direction="multimodal", venue="wacv")
    monkeypatch.setattr(
        ar,
        "_run_headless",
        lambda prompt, model="", timeout=0, on_line=None: {
            "ok": True,
            "text": '{"cycle": "WACV 2026", "summary": "nothing found"}',
            "cost": 0.1,
        },
    )
    res = ar.research_venue_cycle(state)
    assert not res["ok"]
    assert "empty" in res["error"]


def test_propose_ideas_venue_source_grounds_in_report(monkeypatch) -> None:
    state = ar.new_studio_state(direction="multimodal", venue="wacv")
    state["venue_report"] = ar.normalize_venue_report(
        {
            "cycle": "WACV 2026",
            "best_papers": [{"title": "Winner One", "arxiv_id": "2410.01234"}],
            "hot_topics": [],
        }
    )
    captured: dict[str, str] = {}

    def fake_run(prompt, model="", timeout=0, on_line=None):
        captured["prompt"] = prompt
        return {
            "ok": True,
            "text": '[{"id": "a", "title": "Idea A", "hypothesis": "h"}]',
            "cost": 0.0,
        }

    monkeypatch.setattr(ar, "_run_headless", fake_run)
    res = ar.propose_ideas(state, "skill", source=ar.IDEA_SOURCE_VENUE)
    assert res["ok"]
    assert "MODE: venue-informed" in captured["prompt"]
    assert "Winner One [2410.01234]" in captured["prompt"]
    assert "mined from arXiv" not in captured["prompt"]


def test_propose_ideas_venue_source_requires_report() -> None:
    state = ar.new_studio_state(direction="multimodal", venue="wacv")
    res = ar.propose_ideas(state, "skill", source=ar.IDEA_SOURCE_VENUE)
    assert not res["ok"]
    assert "venue-cycle research" in res["error"]


def test_venue_job_persists_report_and_cost(tmp_path: Path, monkeypatch) -> None:
    root, slug = _studio(tmp_path)
    ar.update_ar_state(root, slug, venue_status="running")
    monkeypatch.setattr(
        web.ar,
        "research_venue_cycle",
        lambda state, model="", on_line=None: {
            "ok": True,
            "report": ar.normalize_venue_report(
                {"cycle": "WACV 2026", "best_papers": [{"title": "Winner One"}]}
            ),
            "cost": 0.5,
        },
    )

    web._ar_venue_job(root, slug, "claude-test")

    state = ar.read_ar_state(root, slug)
    assert state["venue_status"] == "done"
    assert state["venue_report"]["cycle"] == "WACV 2026"
    assert state["cost_usd"] == 0.5


def test_venue_job_records_error(tmp_path: Path, monkeypatch) -> None:
    root, slug = _studio(tmp_path)
    ar.update_ar_state(root, slug, venue_status="running")
    monkeypatch.setattr(
        web.ar,
        "research_venue_cycle",
        lambda state, model="", on_line=None: {"ok": False, "error": "no web"},
    )

    web._ar_venue_job(root, slug, "claude-test")

    state = ar.read_ar_state(root, slug)
    assert state["venue_status"] == "error"
    assert state["venue_error"] == "no web"
    assert not state["venue_report"]
