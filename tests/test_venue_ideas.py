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


def test_operator_venue_url_leads_the_research_prompt(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_run(prompt, model="", timeout=0, on_line=None):
        captured["prompt"] = prompt
        return {"ok": True, "text": _REPORT_JSON, "cost": 0.0}

    monkeypatch.setattr(ar, "_run_headless", fake_run)

    with_url = ar.new_studio_state(
        direction="multimodal",
        venue="wacv",
        venue_url="https://wacv.example/awards ",
        venue_kickoff=True,
    )
    assert with_url["venue_url"] == "https://wacv.example/awards"
    assert with_url["venue_kickoff"] is True
    assert ar.new_studio_state(direction="multimodal")["venue_kickoff"] is False
    assert ar.research_venue_cycle(with_url)["ok"]
    assert "START HERE" in captured["prompt"]
    assert "https://wacv.example/awards" in captured["prompt"]

    without_url = ar.new_studio_state(direction="multimodal", venue="wacv")
    assert ar.research_venue_cycle(without_url)["ok"]
    assert "START HERE" not in captured["prompt"]
    assert "Use your own web search" in captured["prompt"]


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


def test_venue_job_chains_idea_generation_server_side(
    tmp_path: Path, monkeypatch
) -> None:
    root, slug = _studio(tmp_path)
    ar.update_ar_state(
        root, slug, venue_status="running", venue_chain_ideas=True
    )
    monkeypatch.setattr(
        web.ar,
        "research_venue_cycle",
        lambda state, model="", on_line=None: {
            "ok": True,
            "report": ar.normalize_venue_report(
                {"cycle": "WSDM 2026", "best_papers": [{"title": "Winner"}]}
            ),
            "cost": 0.1,
        },
    )
    launched: list = []
    monkeypatch.setattr(
        web, "_ar_run_async", lambda fn, *args: launched.append((fn, args))
    )

    web._ar_venue_job(root, slug, "claude-test")

    state = ar.read_ar_state(root, slug)
    assert state["venue_status"] == "done"
    assert state["venue_chain_ideas"] is False
    assert state["ideas_status"] == "running"
    assert launched == [
        (web._ar_ideas_job, (root, slug, 6, "claude-test", ar.IDEA_SOURCE_VENUE))
    ]


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
