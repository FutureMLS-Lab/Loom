"""The OpenReview submission path, with the network mocked out.

Live posting is never exercised here - a real forum is a public place.
These tests pin the plan-building contract (reviewer-N answers the N-th
official review), the schema-filling rules, and the credential cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loom import openreview_submit as ors


INVITATION = {
    "id": "AConf.cc/2027/Conference/Submission7/-/Official_Comment",
    "edit": {
        "signatures": {
            "param": {
                "items": [
                    {"prefix": "AConf.cc/2027/Conference/Submission7/Reviewer_.*"},
                    {"value": "AConf.cc/2027/Conference/Submission7/Authors"},
                ]
            }
        },
        "note": {
            "content": {
                "title": {"value": {"param": {"type": "string", "optional": True}}},
                "comment": {"value": {"param": {"type": "string"}}},
            }
        },
    },
}


def test_login_caches_token_with_tight_permissions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_OPENREVIEW_AUTH", str(tmp_path / "auth.json"))
    monkeypatch.setattr(ors, "_request", lambda *a, **k: {"token": "tok-1", "user": {}})
    result = ors.login("me@lab.org", "hunter2")
    assert result == {"ok": True, "user": "me@lab.org"}
    cache = tmp_path / "auth.json"
    assert (cache.stat().st_mode & 0o777) == 0o600
    data = json.loads(cache.read_text())
    assert data == {"username": "me@lab.org", "token": "tok-1"}
    assert ors.auth_status() == {"logged_in": True, "user": "me@lab.org"}
    ors.logout()
    assert ors.auth_status() == {"logged_in": False}


def test_login_requires_both_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOOM_OPENREVIEW_AUTH", str(tmp_path / "auth.json"))
    with pytest.raises(ValueError):
        ors.login("me@lab.org", "")


def test_pick_author_signature_skips_patterns() -> None:
    assert ors.pick_author_signature(INVITATION) == (
        "AConf.cc/2027/Conference/Submission7/Authors"
    )
    assert ors.pick_author_signature({"edit": {"signatures": []}}) == ""


def test_build_note_content_fills_the_schema() -> None:
    content = ors.build_note_content(INVITATION, "Response to Reviewer gZk1", "body text")
    assert content == {
        "comment": {"value": "body text"},
        "title": {"value": "Response to Reviewer gZk1"},
    }


def test_build_note_content_prefers_rebuttal_field() -> None:
    invitation = {
        "edit": {"note": {"content": {
            "rebuttal": {"value": {"param": {"type": "string"}}},
            "comment": {"value": {"param": {"type": "string", "optional": True}}},
        }}}
    }
    content = ors.build_note_content(invitation, "t", "the reply")
    assert content == {"rebuttal": {"value": "the reply"}}


def test_build_note_content_refuses_unfillable_required_field() -> None:
    invitation = {
        "edit": {"note": {"content": {
            "comment": {"value": {"param": {"type": "string"}}},
            "confidential_disclosure": {"value": {"param": {"type": "string"}}},
        }}}
    }
    with pytest.raises(ValueError, match="confidential_disclosure"):
        ors.build_note_content(invitation, "t", "b")


def test_build_plan_maps_reviewer_n_to_nth_review(monkeypatch) -> None:
    monkeypatch.setattr(ors, "reply_invitations", lambda forum, token: [INVITATION])
    forum_info = {
        "forum": "forum-1",
        "reviews": [
            {"id": "rev-a", "signatures": ["AConf.cc/2027/Conference/Submission7/Reviewer_gZk1"]},
            {"id": "rev-b", "signatures": ["AConf.cc/2027/Conference/Submission7/Reviewer_Hq2x"]},
        ],
    }
    plan = ors.build_plan(
        forum_info,
        {"reviewer-2": "reply to the second", "reviewer-1": "reply to the first"},
        "tok",
    )
    assert plan["forum"] == "forum-1"
    assert plan["signature"].endswith("/Authors")
    assert [item["replyto"] for item in plan["items"]] == ["rev-a", "rev-b"]
    assert plan["items"][0]["reviewer_label"] == "Reviewer_gZk1"
    assert plan["items"][0]["content"]["comment"]["value"] == "reply to the first"
    assert plan["items"][0]["content"]["title"]["value"] == "Response to Reviewer gZk1"


def test_build_plan_flags_unmatched_reviewers(monkeypatch) -> None:
    monkeypatch.setattr(ors, "reply_invitations", lambda forum, token: [INVITATION])
    forum_info = {"forum": "forum-1", "reviews": [{"id": "rev-a", "signatures": ["x/Reviewer_A"]}]}
    plan = ors.build_plan(forum_info, {"reviewer-1": "ok", "reviewer-9": "orphan"}, "tok")
    by_id = {item["reviewer_id"]: item for item in plan["items"]}
    assert "error" not in by_id["reviewer-1"]
    assert by_id["reviewer-9"]["error"]


def test_build_plan_without_forum_or_invitation(monkeypatch) -> None:
    with pytest.raises(ValueError, match="forum"):
        ors.build_plan({"forum": "", "reviews": []}, {}, "tok")
    monkeypatch.setattr(ors, "reply_invitations", lambda forum, token: [])
    with pytest.raises(ValueError, match="invitation"):
        ors.build_plan(
            {"forum": "f", "reviews": [{"id": "r"}]}, {"reviewer-1": "x"}, "tok"
        )


def test_execute_plan_posts_each_item_and_isolates_failures(monkeypatch) -> None:
    calls = []

    def fake_post(token, invitation_id, signature, forum, replyto, content):
        calls.append(replyto)
        if replyto == "rev-b":
            raise ValueError("window closed")
        return f"note-{replyto}"

    monkeypatch.setattr(ors, "post_reply", fake_post)
    plan = {
        "forum": "f", "invitation": "inv", "signature": "sig",
        "items": [
            {"reviewer_id": "reviewer-1", "replyto": "rev-a", "content": {}},
            {"reviewer_id": "reviewer-2", "replyto": "rev-b", "content": {}},
            {"reviewer_id": "reviewer-3", "error": "no matching official review"},
        ],
    }
    results = ors.execute_plan(plan, "tok")
    assert calls == ["rev-a", "rev-b"]
    assert results[0] == {"reviewer_id": "reviewer-1", "note_id": "note-rev-a", "ok": True}
    assert results[1]["error"] == "window closed"
    assert results[2]["error"] == "no matching official review"
