"""One fetcher for every factory: URL validation, arXiv, OpenReview."""

from __future__ import annotations

import io
import json
import urllib.request

import pytest

from loom import paper_fetch
from loom import review_task as review


def _fake_urlopen(responses):
    """Map url-substring -> bytes; raises on anything unmapped."""
    def opener(request, timeout=0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        for key, data in responses.items():
            if key in url:
                return io.BytesIO(data)
        raise AssertionError(f"unexpected fetch: {url}")
    return opener


def test_arxiv_and_forum_url_resolution():
    assert paper_fetch._arxiv_pdf_url("https://arxiv.org/abs/2510.11696") \
        == "https://arxiv.org/pdf/2510.11696"
    assert paper_fetch._arxiv_pdf_url("https://arxiv.org/pdf/2510.11696v2.pdf") \
        == "https://arxiv.org/pdf/2510.11696"
    assert paper_fetch.openreview_forum_id(
        "https://openreview.net/forum?id=aB3_x9Yz"
    ) == "aB3_x9Yz"
    assert paper_fetch.openreview_forum_id("https://evil.example/?id=x") == ""


def test_fetch_paper_pdf_from_arxiv(tmp_path, monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        _fake_urlopen({"arxiv.org/pdf/2510.11696": b"%PDF-1.4 fake"}),
    )
    dest = tmp_path / "paper.pdf"
    out = paper_fetch.fetch_paper_pdf("https://arxiv.org/abs/2510.11696", dest)
    assert out["ok"] is True
    assert dest.read_bytes().startswith(b"%PDF")


def test_materialize_rebuttal_package(tmp_path, monkeypatch):
    forum = {
        "notes": [
            {"id": "aB3_x9Yz", "content": {"title": {"value": "A Paper"}}},
            {"id": "r1", "invitations": ["V/-/Official_Review"],
             "signatures": ["V/Reviewer_abc"],
             "content": {"summary": {"value": "solid"}, "rating": {"value": "6"}}},
            {"id": "m1", "invitations": ["V/-/Meta_Review"],
             "signatures": ["V/AC"], "content": {"recommendation": {"value": "accept"}}},
        ]
    }
    monkeypatch.setattr(
        urllib.request, "urlopen",
        _fake_urlopen({
            "api2.openreview.net/notes": json.dumps(forum).encode(),
            "openreview.net/pdf": b"%PDF-1.4 forum pdf",
        }),
    )
    out = paper_fetch.materialize_rebuttal_package(
        "https://openreview.net/forum?id=aB3_x9Yz", tmp_path
    )
    package = tmp_path / "a-paper"  # slugged title names the folder
    assert out["ok"] and out["title"] == "A Paper" and out["reviews"] == 1
    assert (package / "submission.pdf").read_bytes().startswith(b"%PDF")
    review_md = (package / "reviews" / "reviewer-1.md").read_text()
    assert "Reviewer_abc" in review_md and "solid" in review_md
    assert (package / "reviews" / "meta-review.md").is_file()
    assert json.loads((package / "forum.json").read_text())["forum"] == "aB3_x9Yz"


def test_review_import_from_url(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOM_REVIEW_REGISTRY", str(tmp_path / "reg.json"))
    monkeypatch.setenv("LOOM_REVIEW_ROOT", str(tmp_path / "papers"))
    monkeypatch.setattr(
        urllib.request, "urlopen",
        _fake_urlopen({"arxiv.org/pdf/2510.11696": b"%PDF-1.4 fake"}),
    )
    record = review.import_from_url(
        "https://arxiv.org/abs/2510.11696", venue="cvpr"
    )
    listed = review.list_projects()
    assert listed[0]["id"] == record["id"]
    assert listed[0]["venue"] == "cvpr"
    state = review.read_state(record["id"])
    assert state["source_url"].endswith("2510.11696")


def test_forum_without_reviews_is_refused(tmp_path, monkeypatch):
    forum = {"notes": [{"id": "aB3_x9Yz", "content": {"title": {"value": "T"}}}]}
    monkeypatch.setattr(
        urllib.request, "urlopen",
        _fake_urlopen({"api2.openreview.net/notes": json.dumps(forum).encode()}),
    )
    with pytest.raises(ValueError, match="no official reviews"):
        paper_fetch.materialize_rebuttal_package(
            "https://openreview.net/forum?id=aB3_x9Yz", tmp_path
        )
