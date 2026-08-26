"""Review Factory routes: register/import projects, run the panel, serve reports, fill the venue's OpenReview form."""

from __future__ import annotations

import re

from urllib.parse import parse_qs

from loom import review_task as review
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
            st, b, h = self._review_submit_openreview(project_id, body)
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
