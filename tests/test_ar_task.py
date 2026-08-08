"""Tests for the AR (Automated Research) task pipeline."""

from __future__ import annotations

import io
import json
import re
import shutil
import time
from pathlib import Path

import pytest

import loom.ar_task as ar
from loom.rud_task import create_task, task_root

CANNED_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2501.01234v1</id>
    <published>2025-01-02T18:00:00Z</published>
    <updated>2025-01-03T09:00:00Z</updated>
    <title>Outlier-Aware  KV Cache
      Quantization</title>
    <summary>We study 2-bit KV caches and find channel outliers dominate error.</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:comment>Accepted at ICLR 2025. 18 pages</arxiv:comment>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2502.09999v2</id>
    <published>2025-02-11T00:00:00Z</published>
    <title>A Paper With No Venue</title>
    <summary>Nothing announced.</summary>
    <author><name>Grace Hopper</name></author>
  </entry>
</feed>"""

SAMPLE_REVIEW = """## Summary
The paper proposes channel rescaling for 2-bit KV caches.

## Weaknesses
- **[critical]** `Table 1` - no matched-memory baseline -> add one.

## Scores
Soundness: 2
**Presentation:** 3
Contribution: 2/4
Rating: 4
Confidence: 4
Recommendation: weak reject
"""


# --- kind normalization -----------------------------------------------------


def test_normalize_kind_maps_legacy_aris() -> None:
    assert ar.normalize_kind("aris") == ar.KIND_AR
    assert ar.normalize_kind("ARIS") == ar.KIND_AR


class TestAvailableActions:
    """A button should only be live when pressing it would work."""

    def test_a_fresh_paper_can_only_be_started(self):
        can = ar.available_actions({"stage": ar.STAGE_DRAFT})
        assert can["start"]["ok"]
        assert can["start"]["action"] == "draft"
        assert not can["stop"]["ok"]
        assert not can["review"]["ok"], "there is nothing written to review"
        assert not can["gate"]["ok"]
        assert not can["pdf"]["ok"]

    def test_a_gate_blocks_the_author_and_opens_the_decision(self):
        can = ar.available_actions(
            {"stage": ar.STAGE_AWAIT_DRAFT_REVIEW}, has_source=True
        )
        assert can["gate"]["ok"]
        assert not can["start"]["ok"]
        assert "waiting for you" in can["start"]["why"]

    def test_stop_follows_the_loop_not_the_stage(self):
        loop = {"stage": ar.STAGE_LOOP}
        assert not ar.available_actions(loop)["stop"]["ok"]
        assert ar.available_actions(loop, loop_running=True)["stop"]["ok"]
        assert not ar.available_actions(loop, loop_running=True)["start"]["ok"]

    def test_start_is_named_for_what_it_does(self):
        loop = ar.available_actions({"stage": ar.STAGE_LOOP})["start"]
        assert loop["action"] == "loop/start" and "loop" in loop["label"]
        draft = ar.available_actions({"stage": ar.STAGE_DRAFT})["start"]
        assert draft["action"] == "draft" and "draft" in draft["label"]

    def test_delivered_stays_readable_but_not_restartable(self):
        can = ar.available_actions(
            {"stage": ar.STAGE_DELIVERED}, has_source=True, pdf_available=True
        )
        assert not can["start"]["ok"]
        assert can["pdf"]["ok"] and can["build"]["ok"]

    def test_every_refusal_explains_itself(self):
        for stage in ar.STAGE_LABELS:
            for name, rule in ar.available_actions({"stage": stage}).items():
                if not rule["ok"]:
                    assert rule["why"], f"{stage}/{name} refuses without saying why"


class TestSkillCatalog:
    def test_lists_the_roles_and_the_figure_skills(self):
        skills = ar.skill_catalog()
        roles = {s["role"] for s in skills}
        assert {"Studio", "Author", "Reviewer"} <= roles
        assert "Figures" in roles
        assert all(s["id"] and s["description"] for s in skills)

    def test_body_reads_a_catalogued_skill(self):
        first = ar.skill_catalog()[0]
        assert len(ar.skill_body(first["id"])) > 200

    def test_body_refuses_anything_not_in_the_catalog(self):
        assert ar.skill_body("../../../etc/passwd") == ""
        assert ar.skill_body("/etc/passwd") == ""


class TestBrowse:
    def test_hides_generated_clutter(self, tmp_path):
        (tmp_path / "code").mkdir()
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "run.py").write_text("print(1)")
        (tmp_path / "model.safetensors").write_bytes(b"\x00" * 10)
        entries = {e["name"]: e for e in ar.browse_dir(tmp_path)}
        assert set(entries) == {"code", "run.py", "model.safetensors"}
        assert entries["run.py"]["readable"]
        assert not entries["model.safetensors"]["readable"], "weights are not text"
        assert entries["code"]["dir"]

    def test_reads_text_but_not_binaries(self, tmp_path):
        src = tmp_path / "a.py"
        src.write_text("x = 1\n")
        assert ar.read_text_file(src) == "x = 1\n"
        blob = tmp_path / "a.bin"
        blob.write_bytes(b"\x00\x01")
        assert ar.read_text_file(blob) == ""
    assert ar.normalize_kind("ar") == ar.KIND_AR
    assert ar.normalize_kind("kernel") == "kernel"
    assert ar.normalize_kind("") == "agent"
    assert ar.normalize_kind(None) == "agent"


def test_is_ar_kind() -> None:
    assert ar.is_ar_kind("aris")
    assert ar.is_ar_kind("ar")
    assert not ar.is_ar_kind("kernel")
    assert not ar.is_ar_kind("agent")


# --- state round-trip -------------------------------------------------------


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".RUD").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_state_round_trip(tmp_path: Path) -> None:
    root = _project(tmp_path)
    meta = create_task(root, "AR studio", "goal", kind=ar.KIND_AR, auto_worktree=False)
    assert ar.read_ar_state(root, meta.slug) == {}

    state = ar.new_studio_state(direction="quantization", venue="icml", mode="seed", seed_idea="hi")
    assert ar.write_ar_state(root, meta.slug, state)

    back = ar.read_ar_state(root, meta.slug)
    assert back["role"] == ar.ROLE_STUDIO
    assert back["direction"] == "quantization"
    assert back["venue"] == "icml"
    assert back["mode"] == "seed"
    assert back["seed_idea"] == "hi"
    assert back["updated_at"]

    ar.update_ar_state(root, meta.slug, seed_idea="changed")
    assert ar.read_ar_state(root, meta.slug)["seed_idea"] == "changed"


def test_state_factories_reject_unknown_values() -> None:
    state = ar.new_studio_state(direction="nope", venue="nope", mode="nope", max_rounds=999)
    assert state["direction"] in ar.DIRECTION_IDS
    assert state["venue"] == ar.DEFAULT_VENUE
    assert state["mode"] == ar.MODE_AUTO
    assert state["max_rounds"] == ar.MAX_ROUNDS_LIMIT

    assert ar.new_studio_state(max_rounds="not a number")["max_rounds"] == ar.DEFAULT_MAX_ROUNDS
    assert ar.new_studio_state(max_rounds=0)["max_rounds"] == 1


def test_read_state_tolerates_corrupt_json(tmp_path: Path) -> None:
    root = _project(tmp_path)
    meta = create_task(root, "AR", "goal", kind=ar.KIND_AR, auto_worktree=False)
    (task_root(root, meta.slug) / ar.AR_STATE).write_text("{not json", encoding="utf-8")
    assert ar.read_ar_state(root, meta.slug) == {}


# --- idea cards -------------------------------------------------------------


def test_normalize_idea_fills_missing_fields() -> None:
    idea = ar.normalize_idea({"title": "T", "experiments": "one run", "score": "0.5"}, 0)
    assert idea["id"] == "idea-1"
    assert idea["experiments"] == ["one run"]
    assert idea["score"] == 0.5
    assert idea["status"] == ar.IDEA_STATUS_PROPOSED

    blank = ar.normalize_idea("not a dict", 3)
    assert blank["id"] == "idea-4"
    assert blank["title"] == "Idea 4"
    assert blank["score"] == 0.0


def test_normalize_edge() -> None:
    edge = ar.normalize_edge({"paper": "2210.17323", "title": "GPTQ", "relation": "Extends"})
    assert edge == {"paper": "2210.17323", "title": "GPTQ", "relation": "extends"}

    # A bare id is a valid edge; an unknown relation degrades rather than fails.
    assert ar.normalize_edge("2402.02750")["paper"] == "2402.02750"
    assert ar.normalize_edge({"title": "KIVI", "relation": "vibes"})["relation"] == (
        ar.DEFAULT_RELATION
    )
    # Nothing to point at is not an edge.
    assert ar.normalize_edge({}) is None
    assert ar.normalize_edge({"relation": "extends"}) is None
    assert ar.normalize_edge(42) is None


def test_normalize_idea_carries_edges() -> None:
    idea = ar.normalize_idea(
        {
            "title": "T",
            "derived_from": [
                {"paper": "2510.11696", "title": "QeRL", "relation": "contradicts"},
                {"nothing": "here"},
            ],
        }
    )
    assert idea["derived_from"] == [
        {"paper": "2510.11696", "title": "QeRL", "relation": "contradicts"}
    ]
    # An idea generated before the field existed simply has no edges.
    assert ar.normalize_idea({"title": "T"})["derived_from"] == []


def test_idea_summary_includes_experiments() -> None:
    text = ar.idea_summary(
        {"title": "T", "hypothesis": "H", "experiments": ["a", "b"], "risk": "R"}
    )
    assert "Title: T" in text
    assert "Hypothesis: H" in text
    assert "  - a" in text and "  - b" in text
    assert "Main risk: R" in text


def test_find_idea(tmp_path: Path) -> None:
    state = {"ideas": [{"id": "x", "title": "X"}, {"id": "y", "title": "Y"}]}
    assert ar.find_idea(state, "y")["title"] == "Y"
    assert ar.find_idea(state, "zzz") is None


# --- arXiv ------------------------------------------------------------------


def test_parse_arxiv_feed() -> None:
    papers = ar.parse_arxiv_feed(CANNED_FEED)
    assert len(papers) == 2
    first = papers[0]
    # Titles arrive wrapped across lines; whitespace must be collapsed.
    assert first["title"] == "Outlier-Aware KV Cache Quantization"
    assert first["venue"] == "ICLR 2025"
    assert first["arxiv_id"] == "2501.01234v1"
    assert first["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert papers[1]["venue"] == ""


def test_parse_arxiv_feed_tolerates_garbage() -> None:
    assert ar.parse_arxiv_feed("not xml at all") == []


def test_arxiv_query_is_bounded() -> None:
    q = ar._arxiv_query(["a", "b", "c", "d", "e"])
    # arXiv slows to a crawl on long boolean queries, so terms are capped.
    assert q.count('abs:"') == ar._ARXIV_MAX_TERMS
    assert "cat:cs.LG" in q
    assert ar._arxiv_query([]) == "(cat:cs.LG OR cat:cs.CL OR cat:cs.AI)"


def test_mine_papers_reports_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ar, "_arxiv_fetch", lambda url, timeout, attempts=3: ("", "HTTP 429"))
    res = ar.mine_papers("quantization")
    assert res["ok"] is False
    assert "429" in res["error"]
    assert res["papers"] == []


def test_mine_papers_filters_to_venue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ar, "_arxiv_fetch", lambda url, timeout, attempts=3: (CANNED_FEED, ""))
    both = ar.mine_papers("quantization")
    assert len(both["papers"]) == 2
    only = ar.mine_papers("quantization", venue_only=True)
    assert [p["venue"] for p in only["papers"]] == ["ICLR 2025"]


# --- job progress logs ------------------------------------------------------


def test_stream_event_line_renders_each_event_kind() -> None:
    assert ar.stream_event_line(
        {"type": "system", "subtype": "init", "model": "claude-fable-5"}
    ) == "started · model claude-fable-5"

    tool = ar.stream_event_line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "WebSearch", "input": {"query": "low-bit RL"}}
                ]
            },
        }
    )
    assert tool == "→ WebSearch: low-bit RL"

    assert ar.stream_event_line(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "found 3 results"}]},
        }
    ) == "   ← found 3 results"

    done = ar.stream_event_line(
        {"type": "result", "duration_ms": 9900, "num_turns": 2, "total_cost_usd": 0.4412}
    )
    assert done == "· finished in 9.9s, 2 turns, $0.441"

    # Protocol noise produces no line at all.
    assert ar.stream_event_line({"type": "rate_limit_event"}) is None
    assert ar.stream_event_line({"type": "assistant", "message": {"content": []}}) is None


def test_stream_event_line_clips_long_values() -> None:
    line = ar.stream_event_line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "x" * 400}}
                ]
            },
        }
    )
    assert len(line) < 160
    assert line.endswith("…")

    # Multi-line text collapses to one log line.
    text = ar.stream_event_line(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "a\n\nb   c"}]}}
    )
    assert text == "a b c"


def test_job_log_round_trip(tmp_path: Path) -> None:
    root = _project(tmp_path)
    meta = create_task(root, "AR", "goal", kind=ar.KIND_AR, auto_worktree=False)
    path = ar.job_log_path(root, meta.slug, ar.JOB_IDEAS)
    assert path.name == "ar-ideas.log"
    assert ar.read_job_log(path) == []

    ar.reset_job_log(path)
    ar.append_job_log(path, "started")
    ar.append_job_log(path, "→ WebSearch: quantization")
    lines = ar.read_job_log(path)
    assert len(lines) == 2
    assert lines[0].endswith("started")
    # Every line carries a timestamp so a stalled job is obvious.
    assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] ", lines[0])

    ar.reset_job_log(path)
    assert ar.read_job_log(path) == []


def test_job_log_is_bounded(tmp_path: Path) -> None:
    root = _project(tmp_path)
    meta = create_task(root, "AR", "goal", kind=ar.KIND_AR, auto_worktree=False)
    path = ar.job_log_path(root, meta.slug, ar.JOB_REVIEW)
    ar.reset_job_log(path)
    for i in range(ar.AR_LOG_MAX_LINES * 2 + 50):
        ar.append_job_log(path, f"line {i}")
    # Trimming is amortised - the file is rewritten only once it doubles the
    # cap - so it oscillates between the cap and twice it, never growing.
    on_disk = path.read_text(encoding="utf-8").splitlines()
    assert ar.AR_LOG_MAX_LINES <= len(on_disk) <= ar.AR_LOG_MAX_LINES * 2 + 1
    assert on_disk[-1].endswith(f"line {ar.AR_LOG_MAX_LINES * 2 + 49}")
    assert len(ar.read_job_log(path)) == ar.AR_LOG_TAIL


# --- shared paper store -----------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOOM_AR_ROOT", str(tmp_path / "ar"))
    return ar.paper_store_path()


def test_store_round_trip(store: Path) -> None:
    assert ar.store_get("2510.11696") is None
    ar.store_put("2510.11696", {"verified": True, "real_title": "QeRL", "year": 2025})
    got = ar.store_get("2510.11696")
    assert got["real_title"] == "QeRL"
    assert got["verified"] is True
    assert store.is_file()
    assert ar.store_stats()["papers"] == 1


def test_store_expiry(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ar.store_put("2510.11696", {"verified": True})
    ar.store_put("2999.99999", {"verified": False, "reason": "not found"})
    assert ar.store_get("2510.11696") is not None
    assert ar.store_get("2999.99999") is not None

    # A miss is re-checked far sooner than a hit: indexing lags publication, so
    # today's absence is not tomorrow's.
    later = time.time() + ar.STORE_TTL_MISS + 60
    monkeypatch.setattr(ar.time, "time", lambda: later)
    assert ar.store_get("2510.11696") is not None
    assert ar.store_get("2999.99999") is None

    much_later = time.time() + ar.STORE_TTL_HIT + 60
    monkeypatch.setattr(ar.time, "time", lambda: much_later)
    assert ar.store_get("2510.11696") is None


def test_store_survives_corruption(store: Path) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{not json", encoding="utf-8")
    assert ar.read_paper_store() == {}
    assert ar.store_get("2510.11696") is None
    ar.store_put("2510.11696", {"verified": True})
    assert ar.store_get("2510.11696") is not None


def test_verify_paper_uses_the_store(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("verify_paper hit the network on a cached id")

    ar.store_put("2510.11696", {"verified": True, "real_title": "QeRL"})
    monkeypatch.setattr(ar.urllib.request, "urlopen", boom)
    got = ar.verify_paper("2510.11696")
    assert got["real_title"] == "QeRL"
    assert "fetched_at" not in got  # bookkeeping stays inside the store
    assert not calls

    # A version suffix is the same paper.
    assert ar.verify_paper("2510.11696v3")["verified"] is True
    # A malformed id never reaches the network either.
    assert ar.verify_paper("nonsense")["verified"] is False


def test_remember_papers_from_mining(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ar, "_arxiv_fetch", lambda url, timeout, attempts=3: (CANNED_FEED, "")
    )
    res = ar.mine_papers("quantization")
    assert res["ok"]
    # Mining is itself proof the paper exists, so a later verify is free.
    cached = ar.store_get("2501.01234")
    assert cached["verified"] is True
    assert cached["source"] == "arxiv"
    assert cached["real_title"] == "Outlier-Aware KV Cache Quantization"

    def boom(*_a, **_k):
        raise AssertionError("hit the network for a paper mining already saw")

    monkeypatch.setattr(ar.urllib.request, "urlopen", boom)
    assert ar.verify_paper("2501.01234")["verified"] is True


def test_openalex_facts_win_over_arxiv(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ar.store_put(
        "2510.11696",
        {"verified": True, "real_title": "Full OpenAlex title", "cited_by": 42, "source": "openalex"},
    )
    monkeypatch.setattr(
        ar, "_arxiv_fetch", lambda url, timeout, attempts=3: (CANNED_FEED, "")
    )
    ar.remember_papers([{"arxiv_id": "2510.11696", "title": "short", "published": "2025-10-13"}])
    kept = ar.store_get("2510.11696")
    assert kept["real_title"] == "Full OpenAlex title"
    assert kept["cited_by"] == 42


# --- review parsing ---------------------------------------------------------


def test_parse_review_scores() -> None:
    scores = ar.parse_review_scores(SAMPLE_REVIEW)
    assert scores == {
        "soundness": 2,
        "presentation": 3,
        "contribution": 2,
        "rating": 4,
        "confidence": 4,
        "recommendation": "weak reject",
    }


def test_parse_review_scores_ignores_out_of_range() -> None:
    scores = ar.parse_review_scores("Soundness: 9\nRating: 7\n")
    assert "soundness" not in scores
    assert scores["rating"] == 7


def test_parse_review_scores_empty() -> None:
    assert ar.parse_review_scores("no scores here") == {}
    assert ar.review_headline({}) == "no scores parsed"


def test_review_headline() -> None:
    headline = ar.review_headline({"rating": 6, "soundness": 3, "recommendation": "borderline"})
    assert "rating 6/10" in headline
    assert "soundness 3/4" in headline
    assert "borderline" in headline


# --- gates and rounds -------------------------------------------------------


def _paper_state(**kw) -> dict:
    return ar.new_paper_state(parent_slug="p", idea={"title": "T"}, **kw)


def test_draft_gate_opens_and_reopens() -> None:
    state = _paper_state()
    assert state["stage"] == ar.STAGE_DRAFT

    state["stage"] = ar.STAGE_AWAIT_DRAFT_REVIEW
    ar.record_gate(state, ar.GATE_DRAFT, "reject", "tighten the method")
    assert state["stage"] == ar.STAGE_DRAFT
    assert ar.last_gate(state, ar.GATE_DRAFT)["note"] == "tighten the method"

    state["stage"] = ar.STAGE_AWAIT_DRAFT_REVIEW
    ar.record_gate(state, ar.GATE_DRAFT, "approve")
    assert state["stage"] == ar.STAGE_LOOP
    assert len(state["gates"]) == 2


def test_final_gate_delivers_or_extends() -> None:
    state = _paper_state(max_rounds=10)
    state["stage"] = ar.STAGE_AWAIT_FINAL_REVIEW
    ar.record_gate(state, ar.GATE_FINAL, "reject", "needs a real baseline")
    # A rejection buys another batch of rounds rather than ending the task.
    assert state["stage"] == ar.STAGE_LOOP
    assert state["max_rounds"] == 20

    state["stage"] = ar.STAGE_AWAIT_FINAL_REVIEW
    ar.record_gate(state, ar.GATE_FINAL, "approve")
    assert state["stage"] == ar.STAGE_DELIVERED
    assert state["loop_running"] is False


def test_ensure_round_is_idempotent_and_sorted() -> None:
    state = _paper_state()
    ar.ensure_round(state, 2)
    ar.ensure_round(state, 1)
    again = ar.ensure_round(state, 2)
    assert [r["n"] for r in state["rounds"]] == [1, 2]
    again["author"] = {"summary": "done"}
    assert ar.round_record(state, 2)["author"]["summary"] == "done"


def test_latest_review_and_completion() -> None:
    state = _paper_state(max_rounds=2)
    assert ar.latest_review(state) is None

    ar.ensure_round(state, 1)["review"] = {"headline": "rating 3/10"}
    ar.ensure_round(state, 2)["review"] = {"headline": "rating 5/10"}
    assert ar.latest_review(state)["headline"] == "rating 5/10"

    state["round"] = 1
    assert not ar.loop_is_complete(state)
    state["round"] = 2
    assert ar.loop_is_complete(state)


def test_progress_summary_shows_round_counter() -> None:
    state = _paper_state(max_rounds=10)
    state["stage"] = ar.STAGE_LOOP
    state["round"] = 3
    assert ar.progress_summary(state) == "Author / reviewer rounds (3/10)"
    state["stage"] = ar.STAGE_DELIVERED
    assert ar.progress_summary(state) == "Delivered"


# --- adapting the loop ------------------------------------------------------


def _with_reviews(*ratings, **dims) -> dict:
    """A paper state whose rounds carry the given rating sequence."""
    state = _paper_state(max_rounds=10)
    for i, rating in enumerate(ratings, start=1):
        scores = {"rating": rating}
        for field, values in dims.items():
            if i <= len(values):
                scores[field] = values[i - 1]
        ar.ensure_round(state, i)["review"] = {"scores": scores, "headline": ""}
    state["round"] = len(ratings)
    return state


def test_score_history_and_best_rating() -> None:
    state = _with_reviews(3, 4, 4, 4, 5)
    assert ar.score_history(state) == [3.0, 4.0, 4.0, 4.0, 5.0]
    assert ar.best_rating(state) == 5.0
    assert ar.score_history(_paper_state()) == []
    assert ar.best_rating(_paper_state()) == 0.0


def test_plateau_matches_the_real_run() -> None:
    # The sequence the live low-bit-RL paper actually produced.
    assert ar.is_plateaued(_with_reviews(3)) is False
    assert ar.is_plateaued(_with_reviews(3, 4)) is False
    assert ar.is_plateaued(_with_reviews(3, 4, 4)) is False
    # Three identical ratings in a row is a stall.
    assert ar.is_plateaued(_with_reviews(3, 4, 4, 4)) is True
    # A genuine improvement clears it.
    assert ar.is_plateaued(_with_reviews(3, 4, 4, 4, 5)) is False
    # So does steady progress.
    assert ar.is_plateaued(_with_reviews(3, 4, 5, 6)) is False
    # Sliding backwards is still a stall: nothing improved on the best so far.
    assert ar.is_plateaued(_with_reviews(6, 5, 4, 3)) is True


def test_stuck_dimensions() -> None:
    state = _with_reviews(
        3, 4, 4, 4,
        contribution=[2, 2, 2, 2],
        soundness=[2, 3, 3, 3],
        presentation=[3, 3, 3, 4],
    )
    stuck = ar.stuck_dimensions(state)
    assert "contribution" in stuck
    assert "soundness" in stuck        # 3, 3, 3 over the window
    assert "presentation" not in stuck  # moved to 4


def test_reviewer_rotation_only_when_stuck() -> None:
    moving = _with_reviews(3, 4, 5)
    assert ar.reviewer_model_for(moving, "claude-fable-5", 4) == "claude-fable-5"

    stalled = _with_reviews(4, 4, 4)
    picked = ar.reviewer_model_for(stalled, "claude-fable-5", 4)
    assert picked != "claude-fable-5"
    assert picked in ar.REVIEWER_ROTATION


def test_plateau_note_tells_the_author_to_change_tack() -> None:
    assert ar.plateau_note(_with_reviews(3, 4, 5)) == ""
    note = ar.plateau_note(_with_reviews(4, 4, 4, contribution=[2, 2, 2]))
    assert "has not improved in 3 rounds" in note
    assert "contribution" in note
    assert "narrow the claim" in note


def test_early_stop() -> None:
    assert ar.should_stop_early(_paper_state()) is False
    assert ar.should_stop_early(_with_reviews(3, 4, 5)) is False
    assert ar.should_stop_early(_with_reviews(3, 8)) is True

    lenient = _with_reviews(6)
    lenient["stop_rating"] = 6
    assert ar.should_stop_early(lenient) is True
    assert ar.stop_rating(lenient) == 6
    assert ar.stop_rating(_paper_state()) == ar.DEFAULT_STOP_RATING


def test_new_paper_state_carries_budget_fields() -> None:
    state = _paper_state()
    assert state["cost_usd"] == 0.0
    assert state["stop_rating"] == ar.DEFAULT_STOP_RATING
    assert state["stop_reason"] == ""


def test_agent_env_points_every_task_at_one_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOOM_AR_ROOT", str(tmp_path / "ar"))
    env = ar.agent_env()
    shared = tmp_path / "ar" / ".cache"
    assert env["HF_HOME"] == str(shared / "huggingface")
    assert env["HF_HUB_CACHE"].startswith(str(shared))
    assert env["TORCH_HOME"] == str(shared / "torch")
    assert env["PIP_CACHE_DIR"] == str(shared / "pip")
    # The directories are created, so the first run does not race on them.
    assert (shared / "huggingface").is_dir()
    assert (shared / "torch").is_dir()


# --- paper layout and skeleton ----------------------------------------------


def test_ensure_ar_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "ar"
    monkeypatch.setenv("LOOM_AR_ROOT", str(target))

    root, created = ar.ensure_ar_root()
    assert root == target
    assert created is True
    assert (target / ".RUD").is_dir()

    # Starting again must not report a fresh creation.
    root, created = ar.ensure_ar_root()
    assert root == target
    assert created is False


def test_ar_root_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    from loom.paths import ar_root

    monkeypatch.delenv("LOOM_AR_ROOT", raising=False)
    assert ar_root() == Path.home() / "ar"


def test_work_layout(tmp_path: Path) -> None:
    root = _project(tmp_path)
    meta = create_task(root, "AR paper", "goal", kind=ar.KIND_AR, auto_worktree=False)
    work = task_root(root, meta.slug) / "work"
    assert ar.work_root(root, meta.slug) == work
    assert ar.code_root(root, meta.slug) == work / "code"
    assert ar.paper_root(root, meta.slug) == work / "manuscript"


def test_child_slug_groups_under_its_studio() -> None:
    assert ar.child_slug("low-bit-rl", "Matched-Entropy Controls") == (
        "low-bit-rl--matched-entropy-controls"
    )
    # Long titles are cut to the slug limit without leaving a trailing dash.
    long = ar.child_slug("low-bit-rl", "A " + "very " * 40 + "long title")
    assert len(long) <= 80
    assert long.startswith("low-bit-rl--")
    assert not long.endswith("-")
    # A title that slugifies to nothing still yields a usable slug.
    assert ar.child_slug("studio", "!!!") == "studio--task"


def test_init_paper_workspace(tmp_path: Path) -> None:
    if not ar.venue_is_available("iclr"):
        pytest.skip("styles not vendored")
    root = _project(tmp_path)
    meta = create_task(root, "AR paper", "goal", kind=ar.KIND_AR, auto_worktree=False)
    layout = ar.init_paper_workspace(root, meta.slug, "iclr", {"title": "A Paper"})
    assert layout["ok"], layout

    code = ar.code_root(root, meta.slug)
    paper = ar.paper_root(root, meta.slug)
    # Both halves are real repositories, so results stay traceable to code.
    assert (code / ".git").is_dir()
    assert (paper / ".git").is_dir()
    assert (code / "README.md").is_file()
    assert (paper / "main.tex").is_file()

    # Re-running is safe: it must not clobber a repo that already has work.
    (code / "run.py").write_text("print('hi')", encoding="utf-8")
    again = ar.init_paper_workspace(root, meta.slug, "iclr", {"title": "A Paper"})
    assert again["code_repo"] == "already a repository"
    assert (code / "run.py").is_file()


def test_round_paths(tmp_path: Path) -> None:
    root = _project(tmp_path)
    meta = create_task(root, "AR paper", "goal", kind=ar.KIND_AR, auto_worktree=False)
    assert ar.author_note_path(root, meta.slug, 0).name == ar.AUTHOR_NOTE
    assert ar.round_dir(root, meta.slug, 7).name == "round-07"
    assert ar.review_note_path(root, meta.slug, 3).parent.name == "round-03"


@pytest.mark.parametrize("venue", [v["id"] for v in ar.VENUES])
def test_seed_paper_skeleton(tmp_path: Path, venue: str) -> None:
    if not ar.venue_is_available(venue):
        pytest.skip(f"{venue} styles not vendored; run scripts/fetch_paper_styles.py")
    dest = tmp_path / venue
    ok, msg = ar.seed_paper_skeleton(dest, venue, {"title": "A 50% Faster & Better Method"})
    assert ok, msg
    assert (dest / "main.tex").is_file()
    assert (dest / "main.bib").is_file()
    assert (dest / "ar_macros.tex").is_file()
    assert (dest / "sections" / "04_experiments.tex").is_file()
    assert (dest / "figures").is_dir()

    main = (dest / "main.tex").read_text(encoding="utf-8")
    assert ar.TOKEN_TITLE not in main
    assert ar.TOKEN_RUNNING_TITLE not in main
    assert ar.TOKEN_KEYWORDS not in main
    # LaTeX specials in the idea title must not break the build.
    assert r"50\% Faster \& Better" in main


def test_seed_paper_skeleton_refuses_to_clobber(tmp_path: Path) -> None:
    dest = tmp_path / "paper"
    dest.mkdir()
    (dest / "main.tex").write_text("mine", encoding="utf-8")
    ok, msg = ar.seed_paper_skeleton(dest, ar.DEFAULT_VENUE, {"title": "T"})
    assert not ok
    assert "already exists" in msg
    assert (dest / "main.tex").read_text(encoding="utf-8") == "mine"

    ok, _ = ar.seed_paper_skeleton(dest, ar.DEFAULT_VENUE, {"title": "T"}, overwrite=True)
    assert ok
    assert (dest / "main.tex").read_text(encoding="utf-8") != "mine"


def test_seed_paper_skeleton_unknown_venue(tmp_path: Path) -> None:
    # An unknown id resolves to the first venue rather than failing, so a stale
    # ar.json can still produce a paper.
    ok, _ = ar.seed_paper_skeleton(tmp_path / "p", "not-a-venue", {"title": "T"})
    assert ok is ar.venue_is_available(ar.VENUES[0]["id"])


# --- PDF build --------------------------------------------------------------


def test_build_pdf_without_source(tmp_path: Path) -> None:
    res = ar.build_pdf(tmp_path)
    assert res["ok"] is False
    assert "no main.tex" in res["error"]


@pytest.mark.skipif(shutil.which("latexmk") is None, reason="latexmk not installed")
def test_build_pdf_compiles_the_skeleton(tmp_path: Path) -> None:
    venue = ar.DEFAULT_VENUE
    if not ar.venue_is_available(venue):
        pytest.skip("styles not vendored; run scripts/fetch_paper_styles.py")
    dest = tmp_path / "paper"
    ok, msg = ar.seed_paper_skeleton(dest, venue, {"title": "Draft Under Test"})
    assert ok, msg
    res = ar.build_pdf(dest)
    assert res["ok"], res.get("error")
    assert res["clean"], ar.latex_errors(res.get("log", ""))
    assert res["bytes"] > 1000
    assert Path(res["pdf"]).is_file()


def test_missing_latex_packages() -> None:
    log = "! LaTeX Error: File `inconsolata.sty' not found.\nfoo\n"
    assert ar.missing_latex_packages(log) == ["inconsolata"]
    assert ar.missing_latex_packages("nothing wrong") == []


def test_latex_errors_extracts_file_line_messages() -> None:
    log = "./main.tex:12: Undefined control sequence.\nnoise\n./x.sty:3: Emergency stop."
    assert ar.latex_errors(log) == [
        "./main.tex:12: Undefined control sequence.",
        "./x.sty:3: Emergency stop.",
    ]


def test_paper_source_text_concatenates_sections(tmp_path: Path) -> None:
    venue = ar.DEFAULT_VENUE
    if not ar.venue_is_available(venue):
        pytest.skip("styles not vendored; run scripts/fetch_paper_styles.py")
    dest = tmp_path / "paper"
    ar.seed_paper_skeleton(dest, venue, {"title": "T"})
    text = ar.paper_source_text(dest)
    assert "% ===== main.tex =====" in text
    assert "sections/04_experiments.tex" in text
    assert len(ar.paper_source_text(dest, limit=500)) <= 600


# --- OpenReview submission prep ---------------------------------------------


def test_submission_invitation_ids() -> None:
    assert ar.submission_invitation("iclr", 2027) == "ICLR.cc/2027/Conference/-/Submission"
    assert ar.submission_invitation("icml", 2027) == "ICML.cc/2027/Conference/-/Submission"
    assert (
        ar.submission_invitation("neurips", 2026)
        == "NeurIPS.cc/2026/Conference/-/Submission"
    )
    assert (
        ar.submission_invitation("colm", 2026)
        == "colmweb.org/COLM/2026/Conference/-/Submission"
    )


def test_delatex_drops_placeholders_with_their_prompts() -> None:
    # An \ARTODO's argument is an instruction to the author, so an unwritten
    # section must come out empty rather than looking written.
    assert ar._delatex(r"\ARTODO{write the context sentence}") == ""
    assert ar._delatex(r"\ARfig[0.8]{a figure that does not exist yet}") == ""
    assert (
        ar._delatex(r"We show \textbf{2-bit} caches work~\citep{x} at \ARnum{} cost.")
        == "We show 2-bit caches work at cost."
    )
    assert ar._delatex("% only a comment\n") == ""


def test_extract_paper_fields(tmp_path: Path) -> None:
    if not ar.venue_is_available("iclr"):
        pytest.skip("styles not vendored")
    paper = tmp_path / "paper"
    ar.seed_paper_skeleton(paper, "iclr", {"title": "A Concrete Title"})
    fields = ar.extract_paper_fields(paper)
    assert fields["title"] == "A Concrete Title"
    # The shipped abstract is all placeholders, so it must extract as empty.
    assert fields["abstract"] == ""
    assert fields["abstract_markers"] > 0

    (paper / "sections" / "00_abstract.tex").write_text(
        "We establish a real result.", encoding="utf-8"
    )
    rewritten = ar.extract_paper_fields(paper)
    assert rewritten["abstract"] == "We establish a real result."
    assert rewritten["abstract_markers"] == 0


def test_extract_paper_fields_icml_title_and_keywords(tmp_path: Path) -> None:
    if not ar.venue_is_available("icml"):
        pytest.skip("styles not vendored")
    paper = tmp_path / "paper"
    ar.seed_paper_skeleton(paper, "icml", {"title": "ICML Title", "metric": "ppl, speed"})
    fields = ar.extract_paper_fields(paper)
    assert fields["title"] == "ICML Title"
    assert fields["keywords"] == ["ppl", "speed"]


def test_placeholder_and_results_detection(tmp_path: Path) -> None:
    if not ar.venue_is_available("iclr"):
        pytest.skip("styles not vendored")
    paper = tmp_path / "paper"
    ar.seed_paper_skeleton(paper, "iclr", {"title": "T"})
    assert ar.count_placeholder_markers(paper) > 0
    # Everything in the fresh experiments section is commented out.
    assert ar._has_real_results(paper) is False

    exp = paper / "sections" / "04_experiments.tex"
    exp.write_text(
        "% \\begin{table}[t] commented out\n\\begin{table}[t]\nreal\n\\end{table}\n",
        encoding="utf-8",
    )
    assert ar._has_real_results(paper) is True

    for name in ("01_introduction", "02_related_work", "03_method", "05_conclusion", "06_appendix", "00_abstract"):
        (paper / "sections" / f"{name}.tex").write_text("done", encoding="utf-8")
    assert ar.count_placeholder_markers(paper) == 0


def test_bib_entry_count(tmp_path: Path) -> None:
    if not ar.venue_is_available("iclr"):
        pytest.skip("styles not vendored")
    paper = tmp_path / "paper"
    ar.seed_paper_skeleton(paper, "iclr", {"title": "T"})
    assert ar._bib_entry_count(paper) == ar.SEED_BIB_ENTRIES


def test_build_submission_flags_an_unfinished_paper(tmp_path: Path) -> None:
    if not ar.venue_is_available("iclr"):
        pytest.skip("styles not vendored")
    root = _project(tmp_path)
    meta = create_task(root, "sub", "g", kind=ar.KIND_AR, auto_worktree=False)
    state = ar.new_paper_state(parent_slug="p", idea={"title": "T"}, venue="iclr")
    ar.write_ar_state(root, meta.slug, state)
    ar.seed_paper_skeleton(ar.paper_root(root, meta.slug), "iclr", {"title": "T"})

    # check_invitation=False keeps the test off the network.
    sub = ar.build_submission(root, meta.slug, state, check_invitation=False)
    assert sub["ready"] is False
    labels = {c["label"]: c["ok"] for c in sub["checks"]}
    assert labels["You approved the paper at the final gate"] is False
    assert labels["No unfilled placeholders left"] is False
    assert labels["Abstract is written"] is False
    assert labels["Experiments section has a real table or figure"] is False
    assert labels["Bibliography goes beyond the template seeds"] is False
    assert sub["fields"]["title"] == "T"
    # The command is prep-only: it must never carry credentials.
    assert "post_note_edit" in sub["command"]
    assert "password" in sub["command"]
    assert "you@example.com" in sub["command"]


def test_fetch_invitation_classifies_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def raise_http(code: int, name: str, message: str):
        def _open(req, timeout=0):
            raise urllib.error.HTTPError(
                "u", code, message, {},  # type: ignore[arg-type]
                io.BytesIO(json.dumps({"name": name, "message": message}).encode()),
            )
        return _open

    monkeypatch.setattr(
        ar.urllib.request, "urlopen", raise_http(400, "InvitationExpiredError", "expired")
    )
    assert ar.fetch_invitation("X")["status"] == "expired"

    monkeypatch.setattr(
        ar.urllib.request, "urlopen", raise_http(404, "NotFoundError", "nope")
    )
    assert ar.fetch_invitation("X")["status"] == "missing"

    monkeypatch.setattr(
        ar.urllib.request, "urlopen", raise_http(403, "ChallengeRequiredError", "challenge")
    )
    blocked = ar.fetch_invitation("X")
    assert blocked["status"] == "blocked"
    assert blocked["ok"] is False


def test_resolve_invitation_prefers_an_open_window(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake(invitation_id, timeout=20):
        seen.append(invitation_id)
        if invitation_id.startswith("ICLR.cc/2030"):
            return {"ok": True, "status": "open", "fields": ["title"], "required": ["title"]}
        return {"ok": False, "status": "missing", "message": "nope"}

    monkeypatch.setattr(ar, "fetch_invitation", fake)
    got = ar.resolve_invitation("iclr", years=[2029, 2030])
    assert got["status"] == "open"
    assert got["year"] == 2030
    assert len(seen) == 2

    monkeypatch.setattr(
        ar, "fetch_invitation", lambda i, timeout=20: {"ok": False, "status": "expired", "message": "gone"}
    )
    assert ar.resolve_invitation("iclr", years=[2025])["status"] == "expired"


# --- skills and prompts -----------------------------------------------------


@pytest.mark.parametrize(
    "name", [ar.SKILL_STUDIO, ar.SKILL_AUTHOR, ar.SKILL_REVIEWER]
)
def test_ar_skills_are_bundled(name: str) -> None:
    assert len(ar.ar_skill_text(name)) > 500


def test_figure_skills_are_bundled() -> None:
    skills = {s["name"] for s in ar.figure_skills()}
    assert {"teaser-figure", "results-figure", "checkbib"} <= skills
    for skill in ar.figure_skills():
        assert Path(skill["path"]).is_file()
        assert skill["description"], f"{skill['name']} has no description"
        # Only the summary line travels in a prompt, never the whole skill.
        assert len(skill["description"]) < 400


def test_figure_skills_block_stays_compact() -> None:
    block = ar.figure_skills_block()
    assert "teaser-figure" in block and "checkbib" in block
    # Five SKILL.md files are ~38k chars; the menu must be a fraction of that.
    assert len(block) < 3000


def test_author_prompts_point_at_the_figure_skills(tmp_path: Path) -> None:
    state = _paper_state()
    draft = ar.author_draft_prompt(tmp_path, tmp_path / "manuscript", state)
    rnd = ar.author_round_prompt(tmp_path, tmp_path / "manuscript", state, 2)
    for prompt in (draft, rnd):
        assert "teaser-figure" in prompt
        assert "SKILL.md" in prompt


def test_ar_skill_text_missing_file() -> None:
    assert ar.ar_skill_text("NOPE.md") == ""


def test_author_prompts_carry_the_contract(tmp_path: Path) -> None:
    state = _paper_state(venue="icml")
    task_dir = tmp_path / "task"
    paper_dir = tmp_path / "task" / "work" / "paper"

    draft = ar.author_draft_prompt(task_dir, paper_dir, state)
    assert "FIRST DRAFT" in draft
    assert str(ar.author_note_path_for(task_dir, 0)) in draft
    assert "ICML" in draft
    assert r"\ARnum" in draft

    rnd = ar.author_round_prompt(
        task_dir, paper_dir, state, 3, review_text="Rating: 4", gate_note="add a baseline"
    )
    assert "ROUND 3 of 10" in rnd
    assert "Rating: 4" in rnd
    assert "add a baseline" in rnd
    assert str(ar.author_note_path_for(task_dir, 3)) in rnd

    first = ar.author_round_prompt(task_dir, paper_dir, state, 1)
    assert "no reviewer report yet" in first


def test_studio_prompt_reflects_mode(tmp_path: Path) -> None:
    auto = ar.studio_prompt(tmp_path, ar.new_studio_state(mode="auto"), "goal")
    assert "Mode: auto direction" in auto
    assert "goal" in auto

    seed = ar.studio_prompt(
        tmp_path, ar.new_studio_state(mode="seed", seed_idea="try rescaling"), ""
    )
    assert "Mode: seed idea" in seed
    assert "try rescaling" in seed


# --- catalog ----------------------------------------------------------------


def test_catalog_shape() -> None:
    cat = ar.catalog()
    assert {d["id"] for d in cat["directions"]} == ar.DIRECTION_IDS
    assert {v["id"] for v in cat["venues"]} == ar.VENUE_IDS
    assert cat["default_venue"] in ar.VENUE_IDS
    assert cat["default_max_rounds"] == ar.DEFAULT_MAX_ROUNDS
    assert [m["id"] for m in cat["modes"]] == [ar.MODE_AUTO, ar.MODE_SEED]


def test_default_general_goal_uses_the_paper_content() -> None:
    seeded = ar.default_general_goal(
        ar.new_studio_state(mode="seed", seed_idea="2-bit KV caches", venue="icml")
    )
    assert seeded == "Write a paper for ICML on: 2-bit KV caches"

    auto = ar.default_general_goal(
        ar.new_studio_state(direction="cot-efficiency", venue="iclr")
    )
    assert "ICLR" in auto
    assert "Chain-of-thought efficiency" in auto

    custom = ar.default_general_goal(
        ar.new_studio_state(direction="custom", custom_direction="weird optimizers")
    )
    assert "weird optimizers" in custom


def test_direction_label_prefers_custom_text() -> None:
    state = ar.new_studio_state(direction="custom", custom_direction="weird optimizers")
    assert ar.direction_label(state) == "weird optimizers"
    assert ar.direction_label(ar.new_studio_state(direction="moe")) == "Mixture of experts"


def test_every_direction_has_search_terms() -> None:
    for d in ar.DIRECTIONS:
        if d["id"] == "custom":
            assert d["terms"] == []
        else:
            assert d["terms"], f"{d['id']} has no arXiv search terms"


def test_sweep_stale_jobs_unwedges_interrupted_work(tmp_path: Path) -> None:
    from loom.web import ARLoopManager

    root = _project(tmp_path)
    stuck = create_task(root, "stuck studio", "g", kind=ar.KIND_AR, auto_worktree=False)
    fine = create_task(root, "fine studio", "g", kind=ar.KIND_AR, auto_worktree=False)
    plain = create_task(root, "plain task", "g", auto_worktree=False)

    state = ar.new_studio_state()
    state["ideas_status"] = "running"
    state["papers_status"] = "done"
    ar.write_ar_state(root, stuck.slug, state)
    ar.write_ar_state(root, fine.slug, ar.new_studio_state())

    cleared = ARLoopManager.sweep_stale_jobs([("p", root)])
    assert cleared == 1

    after = ar.read_ar_state(root, stuck.slug)
    assert after["ideas_status"] == "error"
    assert "restart" in after["ideas_error"]
    # Statuses that were not mid-flight are left exactly as they were.
    assert after["papers_status"] == "done"
    assert "ideas_status" not in ar.read_ar_state(root, fine.slug)
    assert ar.read_ar_state(root, plain.slug) == {}

    # Sweeping again is a no-op once nothing is running.
    assert ARLoopManager.sweep_stale_jobs([("p", root)]) == 0


def test_every_venue_template_is_vendored() -> None:
    missing = [v["id"] for v in ar.VENUES if not ar.venue_is_available(v["id"])]
    assert not missing, f"run scripts/fetch_paper_styles.py for: {missing}"
