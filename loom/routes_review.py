"""Review Factory routes: register/import projects, run the panel, serve reports, fill the venue's OpenReview form."""

from __future__ import annotations

import re
from typing import Any

from urllib.parse import parse_qs

from loom import review_task as review
from loom import openreview_submit
from loom import paper_fetch
from loom.web_jobs import _ar_run_async, _review_run_job
from loom.web_util import _json_bytes


def handle_get(self, path, parsed) -> bool:  # noqa: C901
    if path == "/api/review/projects":
        st, b, h = _json_bytes(
            {"ok": True, "projects": review.list_projects()}
        )
        self._send(st, b, h)
        return True


    m_review_get = re.match(r"^/api/review/projects/([0-9a-f]{12})$", path)
    if m_review_get:
        project_id = m_review_get.group(1)
        state = review.read_state(project_id)
        record = review._project_record(project_id)
        if not record:
            st, b, h = _json_bytes(
                {"ok": False, "error": "unknown review project"}, 404
            )
        else:
            st, b, h = _json_bytes(
                {
                    "ok": True,
                    "project": record,
                    "state": state,
                    "runs": review.list_runs(project_id),
                }
            )
        self._send(st, b, h)
        return True


    m_review_file = re.match(
        r"^/api/review/projects/([0-9a-f]{12})/runs/"
        r"([0-9][0-9T.:Z\-]{7,39})/(review\.md|panel\.json)$",
        path,
    )
    if m_review_file:
        project_id, run, name = m_review_file.groups()
        file_path = review.run_file(project_id, run, name)
        if file_path is None:
            st, b, h = _json_bytes({"ok": False, "error": "no such report"}, 404)
            self._send(st, b, h)
            return True
        data = file_path.read_bytes()
        headers = [
            (
                "Content-Type",
                "text/markdown; charset=utf-8"
                if name.endswith(".md")
                else "application/json; charset=utf-8",
            ),
            ("Content-Length", str(len(data))),
            ("Cache-Control", "no-store"),
        ]
        qs = parse_qs(parsed.query or "")
        if (qs.get("dl") or [""])[0]:
            # Download names carry the run stamp so two reports of the
            # same paper don't overwrite each other in ~/Downloads.
            headers.append(
                (
                    "Content-Disposition",
                    f'attachment; filename="review-{run}-{name}"',
                )
            )
        self._send(200, data, headers)
        return True


    return False

def handle_post(self, path, parsed, body) -> bool:  # noqa: C901
    if path == "/api/review/projects":
        try:
            url_value = str(body.get("url") or "").strip()
            if url_value:
                payload = review.import_from_url(
                    url_value,
                    title=str(body.get("title") or ""),
                    venue=str(body.get("venue") or ""),
                )
            else:
                payload = review.register_project(
                    str(body.get("path") or ""),
                    title=str(body.get("title") or ""),
                    venue=str(body.get("venue") or ""),
                    rubric_path=str(body.get("rubric_path") or ""),
                )
        except ValueError as exc:
            st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
        except OSError as exc:
            st, b, h = _json_bytes(
                {"ok": False, "error": f"could not import package: {exc}"},
                500,
            )
        else:
            st, b, h = _json_bytes(payload, 201)
        self._send(st, b, h)
        return True


    m_review_action = re.match(
        r"^/api/review/projects/([0-9a-f]{12})/([a-z-]+)$", path
    )
    if m_review_action:
        project_id, action = m_review_action.groups()
        if review._project_record(project_id) is None:
            st, b, h = _json_bytes(
                {"ok": False, "error": "unknown review project"}, 404
            )
        elif action == "run":
            state = review.read_state(project_id)
            if str(state.get("status")) == "running":
                st, b, h = _json_bytes({"ok": True, "status": "running"}, 202)
            else:
                review.update_state(project_id, status="running", error="")
                _ar_run_async(_review_run_job, project_id)
                st, b, h = _json_bytes({"ok": True, "status": "running"}, 202)
        elif action == "submit-openreview":
            st, b, h = _review_submit_openreview(self, project_id, body)
        else:
            st, b, h = _json_bytes(
                {"ok": False, "error": f"unknown review action {action!r}"}, 404
            )
        self._send(st, b, h)
        return True


    return False

def handle_delete(self, path, parsed) -> bool:  # noqa: C901
    m_review_del = re.match(r"^/api/review/projects/([0-9a-f]{12})$", path)
    if m_review_del:
        project_id = m_review_del.group(1)
        if review._project_record(project_id) is None:
            st, b, h = _json_bytes(
                {"ok": False, "error": "unknown review project"}, 404
            )
        elif str(review.read_state(project_id).get("status")) == "running":
            st, b, h = _json_bytes(
                {"ok": False, "error": "a review is still running"}, 409
            )
        else:
            review.unregister_project(project_id)
            # Reports stay on disk under review-output/, by design.
            st, b, h = _json_bytes({"ok": True})
        self._send(st, b, h)
        return True


    return False


def _review_submit_openreview(
    self, project_id: str, body: dict[str, Any]
) -> tuple[int, bytes, list[tuple[str, str]]]:
    """Fill the venue's Official_Review form from the panel report.

    Dry run by default; ``confirm: true`` posts. Only projects that
    were imported off an OpenReview forum link know their forum, and
    only an account holding the reviewer role can sign the form.
    """
    auth = openreview_submit.cached_auth()
    if not auth:
        return _json_bytes(
            {"ok": False, "error": "not signed in to OpenReview"}, 401
        )
    state = review.read_state(project_id)
    forum = paper_fetch.openreview_forum_id(str(state.get("source_url") or ""))
    if not forum:
        return _json_bytes(
            {
                "ok": False,
                "error": (
                    "this project was not imported from an OpenReview "
                    "forum link, so there is no forum to submit to"
                ),
            },
            400,
        )
    latest = state.get("latest_review") or {}
    review_md = review.review_text(project_id)
    if not latest or not review_md:
        return _json_bytes(
            {"ok": False, "error": "run the reviewer panel first"}, 409
        )
    try:
        invitation = openreview_submit.review_invitation(
            forum, auth["token"]
        )
        if invitation is None:
            raise ValueError(
                "no open Official_Review invitation this account can "
                "sign - are you an assigned reviewer of this paper, "
                "and is the review window open?"
            )
        signature = openreview_submit.pick_reviewer_signature(invitation)
        content, mapping = openreview_submit.build_review_content(
            invitation,
            review_md,
            latest.get("scores") or {},
            headline=str(latest.get("headline") or ""),
        )
    except ValueError as exc:
        return _json_bytes({"ok": False, "error": str(exc)}, 400)
    fields = [
        {
            "field": name,
            "chars": len(str(value.get("value"))),
            "preview": str(value.get("value"))[:160],
        }
        for name, value in content.items()
    ]
    if not body.get("confirm"):
        return _json_bytes(
            {
                "ok": True,
                "dry_run": True,
                "forum": forum,
                "invitation": str(invitation.get("id") or ""),
                "signature": signature,
                "fields": fields,
                "mapping": mapping,
                "user": auth["username"],
            }
        )
    try:
        note_id = openreview_submit.post_reply(
            auth["token"],
            str(invitation.get("id") or ""),
            signature,
            forum,
            forum,  # a review replies to the submission note itself
            content,
        )
    except ValueError as exc:
        return _json_bytes({"ok": False, "error": str(exc)}, 400)
    review.update_state(
        project_id,
        openreview_review={
            "at": review._now(),
            "forum": forum,
            "invitation": str(invitation.get("id") or ""),
            "signature": signature,
            "note_id": note_id,
            "by": auth["username"],
        },
    )
    return _json_bytes({"ok": True, "note_id": note_id, "fields": fields})

# ===== GET =====
