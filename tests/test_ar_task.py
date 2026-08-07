"""Tests for the AR (Automated Research) task pipeline."""

from __future__ import annotations

import io
import json
import re
import shutil
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


def test_paper_state_defaults_to_cursor_reviewer_panel() -> None:
    state = ar.new_paper_state(parent_slug="p", idea={"title": "T"})
    assert state["reviewer_models"] == list(ar.CURSOR_REVIEWER_MODELS)
    assert ar.CURSOR_REVIEWER_MODELS == (
        "gpt-5.6-sol-max",
        "claude-fable-5-thinking-max",
        "cursor-grok-4.5-high",
    )


def test_cursor_reviewer_panel_reads_only_isolated_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    pdf = paper / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% compiled artifact under test\n")
    (paper / "main.tex").write_text("LATEX_SECRET_MUST_NOT_LEAK", encoding="utf-8")

    ratings = {
        "gpt-5.6-sol-max": (4, "weak reject"),
        "claude-fable-5-thinking-max": (6, "borderline"),
        "cursor-grok-4.5-high": (8, "weak accept"),
    }
    review_commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        if cmd == ["agent", "models"]:
            listing = "Available models\n" + "\n".join(
                f"{model} - test model" for model in ar.CURSOR_REVIEWER_MODELS
            )
            return ar.subprocess.CompletedProcess(cmd, 0, stdout=listing, stderr="")

        review_commands.append(cmd)
        assert cmd[0:2] == ["agent", "--print"]
        assert cmd[cmd.index("--mode") + 1] == "ask"
        assert cmd[cmd.index("--output-format") + 1] == "json"
        assert "--trust" in cmd
        assert "--force" not in cmd
        assert "--yolo" not in cmd

        model = cmd[cmd.index("--model") + 1]
        workspace = Path(cmd[cmd.index("--workspace") + 1])
        assert (workspace / "submission.pdf").read_bytes() == pdf.read_bytes()
        assert not (workspace / "main.tex").exists()
        prompt = cmd[-1]
        assert str(workspace / "submission.pdf") in prompt
        assert "LATEX_SECRET_MUST_NOT_LEAK" not in prompt
        assert "LaTeX sources of the submission follow" not in prompt

        rating, recommendation = ratings[model]
        review = SAMPLE_REVIEW.replace("Rating: 4", f"Rating: {rating}").replace(
            "Recommendation: weak reject",
            f"Recommendation: {recommendation}",
        )
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": review,
        }
        return ar.subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(ar.subprocess, "run", fake_run)
    result = ar.run_reviewer(
        paper,
        "# reviewer methodology",
        venue="iclr",
        round_n=3,
        build={"ok": True, "clean": True, "pdf": str(pdf)},
        readiness={"ready": True, "failed": []},
    )

    assert result["ok"] is True
    assert {cmd[cmd.index("--model") + 1] for cmd in review_commands} == set(
        ar.CURSOR_REVIEWER_MODELS
    )
    assert len(review_commands) == 3
    assert result["models"] == list(ar.CURSOR_REVIEWER_MODELS)
    assert result["scores"]["rating"] == 6
    assert result["scores"]["recommendation"] == "borderline"
    assert result["headline"].startswith("3 reviewers")
    assert result["input_pdf"] == str(pdf)
    for model in ar.CURSOR_REVIEWER_MODELS:
        assert f"# Reviewer: `{model}`" in result["review"]


def test_cursor_reviewer_refuses_missing_compiled_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def should_not_run(*args, **kwargs):
        raise AssertionError("Cursor CLI must not run without a compiled PDF")

    monkeypatch.setattr(ar.subprocess, "run", should_not_run)
    result = ar.run_reviewer(
        tmp_path,
        "# reviewer methodology",
        build={"ok": False, "error": "latexmk failed"},
    )
    assert result["ok"] is False
    assert "compiled PDF" in result["error"]
    assert "latexmk failed" in result["error"]


def test_cursor_reviewer_refuses_incomplete_paper_before_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    def should_not_run(*args, **kwargs):
        raise AssertionError("Cursor models must not run when readiness fails")

    monkeypatch.setattr(ar.subprocess, "run", should_not_run)
    result = ar.run_reviewer(
        tmp_path,
        "# reviewer methodology",
        build={"ok": True, "clean": True, "pdf": str(pdf)},
        readiness={
            "ready": False,
            "failed": [
                {
                    "ok": False,
                    "label": "No AR placeholders remain",
                    "detail": "3 markers",
                }
            ],
        },
    )
    assert result["ok"] is False
    assert "readiness gate blocked" in result["error"]
    assert "No AR placeholders remain" in result["error"]


def test_loop_driver_returns_failed_readiness_to_same_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.web import _ARLoopDriver

    root = _project(tmp_path)
    meta = create_task(
        root, "readiness", "goal", kind=ar.KIND_AR, auto_worktree=False
    )
    state = ar.new_paper_state(parent_slug="studio", idea={"title": "T"})
    state["stage"] = ar.STAGE_LOOP
    state["round"] = 1
    ar.ensure_round(state, 1)
    ar.write_ar_state(root, meta.slug, state)
    note = ar.author_note_path(root, meta.slug, 1)
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Round 1\n\nclaimed complete", encoding="utf-8")

    readiness = {
        "ready": False,
        "checks": [
            {
                "ok": False,
                "label": "No AR placeholders remain",
                "detail": "2 markers",
            }
        ],
        "failed": [
            {
                "ok": False,
                "label": "No AR placeholders remain",
                "detail": "2 markers",
            }
        ],
        "pdf": str(tmp_path / "main.pdf"),
        "checked_at": "2026-08-07T00:00:00+00:00",
    }
    driver = _ARLoopDriver(object(), root, "project", meta.slug)
    monkeypatch.setattr(
        driver,
        "_build",
        lambda: {"ok": True, "clean": True, "pdf": str(tmp_path / "main.pdf")},
    )
    monkeypatch.setattr(ar, "review_readiness", lambda *args, **kwargs: readiness)

    def reviewer_must_not_run(*args, **kwargs):
        raise AssertionError("reviewer ran before the readiness gate passed")

    monkeypatch.setattr(ar, "run_reviewer", reviewer_must_not_run)
    repair_prompts: list[int] = []
    monkeypatch.setattr(
        driver,
        "_send_readiness_prompt",
        lambda current_state, round_n: repair_prompts.append(round_n),
    )

    driver._close_round(state, 1, note)

    after = ar.read_ar_state(root, meta.slug)
    rec = ar.round_record(after, 1)
    assert rec is not None
    assert rec["readiness"]["ready"] is False
    assert rec["review"] is None
    assert "author" not in rec
    assert len(rec["readiness_attempts"]) == 1
    assert Path(rec["readiness_attempts"][0]["note"]).is_file()
    assert Path(rec["readiness_attempts"][0]["report"]).is_file()
    assert not note.exists()
    assert repair_prompts == [1]


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


# --- paper layout and skeleton ----------------------------------------------


def test_paper_root_falls_back_to_work_dir(tmp_path: Path) -> None:
    root = _project(tmp_path)
    meta = create_task(root, "AR paper", "goal", kind=ar.KIND_AR, auto_worktree=False)
    expected = task_root(root, meta.slug) / "work" / ar.PAPER_SUBDIR
    assert ar.paper_root(root, meta.slug) == expected


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


def _write_ready_paper(tmp_path: Path) -> Path:
    paper = tmp_path / "paper"
    ok, msg = ar.seed_paper_skeleton(
        paper,
        "iclr",
        {"title": "A Complete Submission", "metric": "accuracy, latency"},
    )
    assert ok, msg
    sections = {
        "00_abstract.tex": (
            "We introduce a concrete method for efficient inference and evaluate "
            "it against matched baselines. Across repeated measurements, the method "
            "improves accuracy while preserving latency, with limitations stated."
        ),
        "01_introduction.tex": (
            "\\section{Introduction}\nThis paper studies an important efficiency "
            "problem, identifies a precise gap, and contributes a reproducible "
            "method plus controlled empirical evidence."
        ),
        "02_related_work.tex": (
            "\\section{Related Work}\nPrior efficient inference and quantization "
            "methods provide the closest comparisons. Our contribution differs in "
            "its mechanism and matched-cost evaluation \\citep{vaswani2017attention}."
        ),
        "03_method.tex": (
            "\\section{Method}\nWe define the transformation, objective, algorithm, "
            "and assumptions in enough detail to reproduce every operation. The "
            "runtime overhead is measured rather than asserted."
        ),
        "04_experiments.tex": (
            "\\section{Experiments}\nWe evaluate three seeds against tuned baselines "
            "using the same data and compute budget. "
            "\\begin{table}[t]\\caption{Measured results over three seeds.}"
            "\\begin{tabular}{lc}Baseline & 71.2\\\\Ours & 74.8\\end{tabular}"
            "\\end{table}\n"
            "\\begin{figure}[t]\\includegraphics{figures/result}"
            "\\caption{Measured accuracy and latency.}\\end{figure}\n"
            "Ablations isolate the proposed mechanism and the analysis reports "
            "variance, failure cases, memory, and latency."
        ),
        "05_conclusion.tex": (
            "\\section{Conclusion}\nThe measured evidence supports the narrow claim "
            "that the method improves the tested setting. We state the principal "
            "scope limitation and the next experiment needed for broader use."
        ),
        "06_appendix.tex": (
            "\\section{Reproducibility}\nThe appendix records exact commands, "
            "environments, hyperparameters, seeds, negative results, and additional "
            "breakdowns needed to reproduce the reported measurements."
        ),
    }
    for name, text in sections.items():
        (paper / "sections" / name).write_text(text, encoding="utf-8")
    figure = paper / "figures" / "result.pdf"
    figure.write_bytes(b"%PDF-1.4\n% generated figure\n")
    with (paper / "main.bib").open("a", encoding="utf-8") as fh:
        fh.write(
            "\n@inproceedings{extra2026complete,\n"
            "  title={A Complete Baseline}, author={A. Author}, year={2026}\n}\n"
        )
    (paper / "main.pdf").write_bytes(b"%PDF-1.4\n% complete paper\n")
    return paper


def test_review_readiness_accepts_complete_rendered_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = _write_ready_paper(tmp_path)
    monkeypatch.setattr(ar, "pdf_page_count", lambda pdf: 9)
    monkeypatch.setattr(
        ar,
        "_pdf_text",
        lambda pdf: {
            "ok": True,
            "text": "A Complete Submission\nMeasured results and real figures.",
        },
    )
    result = ar.review_readiness(
        paper,
        venue="iclr",
        build={"ok": True, "clean": True, "pdf": str(paper / "main.pdf"), "log": ""},
    )
    assert result["ready"] is True
    assert result["failed"] == []
    assert all(item["ok"] for item in result["checks"])
    report = ar.review_readiness_markdown(result)
    assert "PASS — reviewer may run" in report


def test_review_readiness_rejects_fresh_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not ar.venue_is_available("iclr"):
        pytest.skip("styles not vendored")
    paper = tmp_path / "paper"
    ar.seed_paper_skeleton(paper, "iclr", {"title": "Draft"})
    (paper / "main.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(ar, "pdf_page_count", lambda pdf: 7)
    monkeypatch.setattr(
        ar,
        "_pdf_text",
        lambda pdf: {"ok": True, "text": "TODO: unfinished result ?? FIGURE PLACEHOLDER"},
    )
    result = ar.review_readiness(
        paper,
        venue="iclr",
        build={"ok": True, "clean": True, "pdf": str(paper / "main.pdf"), "log": ""},
    )
    labels = {item["label"]: item["ok"] for item in result["checks"]}
    assert result["ready"] is False
    assert labels["No AR placeholders remain"] is False
    assert labels["Experiments contain a real table or figure"] is False
    assert labels["Rendered PDF has no visible placeholders or question marks"] is False


def test_review_readiness_rejects_missing_figure_and_question_mark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = _write_ready_paper(tmp_path)
    (paper / "figures" / "result.pdf").unlink()
    monkeypatch.setattr(ar, "pdf_page_count", lambda pdf: 9)
    monkeypatch.setattr(
        ar,
        "_pdf_text",
        lambda pdf: {"ok": True, "text": "Results are still ?? and TBD."},
    )
    result = ar.review_readiness(
        paper,
        venue="iclr",
        build={"ok": True, "clean": True, "pdf": str(paper / "main.pdf"), "log": ""},
    )
    labels = {item["label"]: item["ok"] for item in result["checks"]}
    assert result["ready"] is False
    assert labels["Every referenced figure file exists"] is False
    assert labels["Rendered PDF has no visible placeholders or question marks"] is False


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
    assert "hard review-readiness gate" in rnd
    assert "ready-to-submit artifact" in rnd

    first = ar.author_round_prompt(task_dir, paper_dir, state, 1)
    assert "no reviewer report yet" in first

    repair = ar.author_readiness_repair_prompt(
        task_dir,
        paper_dir,
        state,
        3,
        {
            "ready": False,
            "failed": [
                {
                    "label": "Every referenced figure file exists",
                    "detail": "missing: figures/main.pdf",
                }
            ],
        },
        report_path=task_dir / "rounds" / "round-03" / "readiness-attempt-01.md",
    )
    assert "reviewer panel was NOT called" in repair
    assert "missing: figures/main.pdf" in repair
    assert "Continue the SAME round" in repair
    assert str(ar.author_note_path_for(task_dir, 3)) in repair


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
