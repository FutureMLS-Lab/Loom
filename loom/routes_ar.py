"""Paper Factory (AR) routes: studios, papers, rounds, gates, files, PDFs, and the per-paper skills report."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from urllib.parse import parse_qs

from loom import ar_task as ar
from loom import rebuttal_task as rebuttal
from loom import researcher_profile as researcher_profiles
from loom.rud_task import list_tasks, path_under_task, read_meta, task_root
from loom.web_activity import _iso_now
from loom.web_jobs import (
    _ar_headless_model,
    _ar_ideas_job,
    _ar_link_job,
    _ar_merge_ideas,
    _ar_mine_job,
    _ar_review_job,
    _ar_review_payload,
    _ar_run_async,
    _ar_search_suggest_job,
    _ar_spawn_children,
    _ar_venue_job,
)
from loom.web_util import _SLUG_RE, _json_bytes

_PROFILE_ID_PATTERN = r"([a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?)"


def _profile_for_api(
    profile: dict[str, Any], *, summary: bool = False
) -> dict[str, Any]:
    """Return only fields the authenticated browser needs."""
    visible = {
        key: profile.get(key)
        for key in (
            "id",
            "name",
            "status",
            "fit_mode",
            "extraction_status",
            "updated_at",
        )
    }
    if summary:
        visible["source_count"] = len(profile.get("source_files") or [])
        return visible
    for key in (
        "extraction_error",
        "extraction_model",
        "extraction_started_at",
        "extraction_completed_at",
        "created_at",
        "activated_at",
    ):
        visible[key] = profile.get(key)
    for key in (
        "research_profile",
        "notes",
        "summary",
        "topics",
        "methods",
        "domains",
        "datasets",
        "tools",
        "strengths",
        "resources",
        "interests",
        "avoid",
        "evidence",
    ):
        visible[key] = profile.get(key)
    sources = [
        {
            key: item.get(key)
            for key in (
                "name",
                "filename",
                "kind",
                "media_type",
                "content_type",
                "size",
                "saved_at",
                "uploaded_at",
            )
        }
        for item in (profile.get("source_files") or [])
        if isinstance(item, dict)
    ]
    visible["source_files"] = sources
    return visible


def handle_get(self, path, parsed) -> bool:  # noqa: C901
    if path == "/api/ar/profiles":
        st, b, h = _json_bytes(
            {
                "ok": True,
                "profiles": [
                    _profile_for_api(profile, summary=True)
                    for profile in researcher_profiles.list_profiles()
                ],
            }
        )
        self._send(st, b, h)
        return True

    m_profile = re.match(rf"^/api/ar/profiles/{_PROFILE_ID_PATTERN}$", path)
    if m_profile:
        profile = researcher_profiles.read_profile(m_profile.group(1))
        if profile:
            st, b, h = _json_bytes(
                {"ok": True, "profile": _profile_for_api(profile)}
            )
        else:
            st, b, h = _json_bytes(
                {"ok": False, "error": "researcher profile not found"}, 404
            )
        self._send(st, b, h)
        return True

    m_ar_skills_report = re.match(
        r"^/api/tasks/([a-zA-Z0-9][a-zA-Z0-9_-]*)/ar/skills-report$", path
    )
    if m_ar_skills_report:
        root, pid = self._resolve_scope(parsed)
        if root is None:
            self._bad_project()
            return True
        slug = m_ar_skills_report.group(1)
        state = ar.read_ar_state(root, slug)
        if not state:
            st, b, h = _json_bytes(
                {"ok": False, "error": "this task has no AR state"}, 404
            )
        else:
            st, b, h = _json_bytes(
                {"ok": True, **ar.paper_skills_report(root, slug, state)}
            )
        self._send(st, b, h)
        return True


    if path == "/api/ar/skills":
        # What the agents are told, readable from the outside. One
        # skill's body when asked for, otherwise the catalogue.
        qs = parse_qs(parsed.query or "")
        wanted = (qs.get("id") or [""])[0].strip()
        if wanted:
            body = ar.skill_body(wanted)
            st, b, h = _json_bytes(
                {"ok": bool(body), "id": wanted, "body": body}
                if body else {"ok": False, "error": "no such skill"},
                200 if body else 404,
            )
        else:
            st, b, h = _json_bytes({"ok": True, "skills": ar.skill_catalog()})
        self._send(st, b, h)
        return True


    m_ar_files = re.match(r"^/api/tasks/([^/]+)/ar/files$", path)
    if m_ar_files:
        root, _pid = self._resolve_scope(parsed)
        if root is None:
            self._bad_project()
            return True
        slug = m_ar_files.group(1)
        if not _SLUG_RE.match(slug):
            st, b, h = _json_bytes({"error": "invalid slug"}, 400)
            self._send(st, b, h)
            return True
        qs = parse_qs(parsed.query or "")
        rel = (qs.get("path") or [""])[0].strip().lstrip("/")
        base = task_root(root, slug) / "work"
        target = path_under_task(base, rel) if rel else base
        if target is None or not target.exists():
            st, b, h = _json_bytes({"ok": False, "error": "not found"}, 404)
        elif target.is_dir():
            st, b, h = _json_bytes(
                {"ok": True, "path": rel, "dir": True, "entries": ar.browse_dir(target)}
            )
        else:
            st, b, h = _json_bytes(
                {"ok": True, "path": rel, "dir": False, "body": ar.read_text_file(target)}
            )
        self._send(st, b, h)
        return True


    if path == "/api/ar/catalog":
        data = ar.catalog()
        # The Research Factory is a standalone page, so it needs to be
        # told which project holds the AR tasks rather than inheriting
        # a selection from Loom's sidebar.
        for project in self.pr.list_projects():
            if project.get("path") == str(ar.ar_root()):
                data["project"] = project.get("id", "")
                break
        st, b, h = _json_bytes(data)
        self._send(st, b, h)
        return True


    if path == "/api/ar/overview":
        root, pid = self._resolve_scope(parsed)
        if root is None or pid is None:
            self._bad_project()
            return True
        st, b, h = _json_bytes(_ar_overview(self, root, pid))
        self._send(st, b, h)
        return True


    m_ar_pdf = re.match(r"^/api/tasks/([^/]+)/ar/pdf$", path)
    if m_ar_pdf:
        root, _pid = self._resolve_scope(parsed)
        if root is None:
            self._bad_project()
            return True
        slug = m_ar_pdf.group(1)
        if not _SLUG_RE.match(slug):
            st, b, h = _json_bytes({"error": "invalid slug"}, 400)
            self._send(st, b, h)
            return True
        pdf, err = _ar_resolve_pdf(self, root, slug)
        if pdf is None:
            st, b, h = _json_bytes({"ok": False, "error": err}, 404)
            self._send(st, b, h)
            return True
        try:
            body = pdf.read_bytes()
        except OSError as exc:
            st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 500)
            self._send(st, b, h)
            return True
        self._send(
            200,
            body,
            [
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(body))),
                ("Content-Disposition", f'attachment; filename="{slug}.pdf"'),
                ("Cache-Control", "no-store"),
            ],
        )
        return True


    m_ar_review = re.match(r"^/api/tasks/([^/]+)/ar/review/(\d+)$", path)
    if m_ar_review:
        root, _pid = self._resolve_scope(parsed)
        if root is None:
            self._bad_project()
            return True
        slug = m_ar_review.group(1)
        if not _SLUG_RE.match(slug):
            st, b, h = _json_bytes({"error": "invalid slug"}, 400)
            self._send(st, b, h)
            return True
        n = int(m_ar_review.group(2))
        payload = _ar_review_payload(root, slug, n)
        if payload is None:
            st, b, h = _json_bytes(
                {"ok": False, "error": f"no review for round {n}"}, 404
            )
            self._send(st, b, h)
            return True
        st, b, h = _json_bytes(payload)
        self._send(st, b, h)
        return True


    m_ar = re.match(r"^/api/tasks/([^/]+)/ar$", path)
    if m_ar:
        root, pid = self._resolve_scope(parsed)
        if root is None or pid is None:
            self._bad_project()
            return True
        slug = m_ar.group(1)
        if not _SLUG_RE.match(slug):
            st, b, h = _json_bytes({"error": "invalid slug"}, 400)
            self._send(st, b, h)
            return True
        st, b, h = _json_bytes(_ar_payload(self, root, pid, slug))
        self._send(st, b, h)
        return True


    return False


def handle_raw_post(self, path, parsed) -> bool:
    """Handle profile source bytes before web.py consumes the body as JSON."""
    match = re.match(
        rf"^/api/ar/profiles/{_PROFILE_ID_PATTERN}/sources$", path
    )
    if not match:
        return False
    query = parse_qs(parsed.query or "")
    filename = str((query.get("filename") or [""])[0]).strip()
    if not filename:
        st, b, h = _json_bytes({"ok": False, "error": "filename is required"}, 400)
        self._send(st, b, h)
        return True
    try:
        size = int(self.headers.get("Content-Length", "0") or 0)
    except (TypeError, ValueError):
        size = 0
    max_size = int(getattr(researcher_profiles, "MAX_SOURCE_BYTES", 20 * 1024 * 1024))
    if size <= 0:
        st, b, h = _json_bytes({"ok": False, "error": "source file is empty"}, 400)
        self._send(st, b, h)
        return True
    if size > max_size:
        st, b, h = _json_bytes(
            {"ok": False, "error": f"source file exceeds {max_size // (1024 * 1024)} MiB"},
            413,
        )
        self._send(st, b, h)
        return True
    data = self.rfile.read(size)
    if len(data) != size:
        st, b, h = _json_bytes(
            {"ok": False, "error": "source upload ended before Content-Length"}, 400
        )
        self._send(st, b, h)
        return True
    try:
        profile = researcher_profiles.save_source(
            match.group(1),
            filename,
            data,
            content_type=str(self.headers.get("Content-Type") or ""),
        )
    except (OSError, ValueError) as exc:
        st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
    else:
        st, b, h = _json_bytes(
            {"ok": True, "profile": _profile_for_api(profile)}, 201
        )
    self._send(st, b, h)
    return True


def handle_post(self, path, parsed, body) -> bool:  # noqa: C901
    if path == "/api/ar/profiles/generate":
        try:
            profile = researcher_profiles.generate_profile(
                body.get("research_profile"),
                notes=body.get("notes"),
                profile_id=str(body.get("id") or "").strip(),
            )
        except (OSError, TypeError, ValueError) as exc:
            st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
        else:
            st, b, h = _json_bytes(
                {"ok": True, "profile": _profile_for_api(profile)}, 202
            )
        self._send(st, b, h)
        return True

    if path == "/api/ar/profiles":
        try:
            profile = researcher_profiles.create_profile(
                str(body.get("name") or ""),
                notes=str(body.get("notes") or ""),
                fit_mode=str(body.get("fit_mode") or ""),
            )
        except (OSError, ValueError) as exc:
            st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
        else:
            st, b, h = _json_bytes(
                {"ok": True, "profile": _profile_for_api(profile)}, 201
            )
        self._send(st, b, h)
        return True

    m_profile_action = re.match(
        rf"^/api/ar/profiles/{_PROFILE_ID_PATTERN}/(extract|activate)$",
        path,
    )
    if m_profile_action:
        profile_id, action = m_profile_action.groups()
        try:
            if action == "extract":
                profile = researcher_profiles.start_extraction(
                    profile_id, model=str(body.get("model") or "")
                )
                status = 202
            else:
                profile = researcher_profiles.activate_profile(profile_id)
                status = 200
        except (OSError, ValueError) as exc:
            st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
        else:
            st, b, h = _json_bytes(
                {"ok": True, "profile": _profile_for_api(profile)}, status
            )
        self._send(st, b, h)
        return True

    m_ar_post = re.match(r"^/api/tasks/([^/]+)/ar/([a-z/-]+)$", path)
    if m_ar_post:
        root, pid = self._resolve_scope(parsed)
        if root is None or pid is None:
            self._bad_project()
            return True
        slug = m_ar_post.group(1)
        action = m_ar_post.group(2)
        if not _SLUG_RE.match(slug):
            st, b, h = _json_bytes({"error": "invalid slug"}, 400)
            self._send(st, b, h)
            return True
        result, status = _ar_action(self, root, pid, slug, action, body)
        st, b, h = _json_bytes(result, status)
        self._send(st, b, h)
        return True


    return False


def handle_put(self, path, parsed, body) -> bool:
    match = re.match(rf"^/api/ar/profiles/{_PROFILE_ID_PATTERN}$", path)
    if not match:
        return False
    try:
        profile = researcher_profiles.update_profile(match.group(1), body)
    except (OSError, ValueError) as exc:
        st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
    else:
        st, b, h = _json_bytes(
            {"ok": True, "profile": _profile_for_api(profile)}
        )
    self._send(st, b, h)
    return True


def handle_delete(self, path, parsed) -> bool:
    match = re.match(rf"^/api/ar/profiles/{_PROFILE_ID_PATTERN}$", path)
    if not match:
        return False
    try:
        deleted = researcher_profiles.delete_profile(match.group(1))
    except (OSError, ValueError) as exc:
        st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
    else:
        st, b, h = _json_bytes(
            {"ok": bool(deleted)},
            200 if deleted else 404,
        )
    self._send(st, b, h)
    return True


def _ar_payload(self, root: Path, project_id: str, slug: str) -> dict[str, Any]:
    """Everything the AR panel renders for one task."""
    state = ar.read_ar_state(root, slug)
    paper_dir = ar.paper_root(root, slug)
    pdf = paper_dir / "main.pdf"
    meta = read_meta(root, slug)
    payload: dict[str, Any] = {
        "ok": True,
        "slug": slug,
        "title": meta.title if meta else slug,
        "state": state,
        "catalog": ar.catalog(),
        "direction_label": ar.direction_label(state) if state else "",
        "paper_dir": str(paper_dir),
        "pdf_available": pdf.is_file(),
        "loop": self.ar_manager.status(project_id, slug),
        "logs": {
            job: ar.read_job_log(ar.job_log_path(root, slug, job))
            for job in (
                ar.JOB_SEARCH,
                ar.JOB_PAPERS,
                ar.JOB_IDEAS,
                ar.JOB_REVIEW,
                ar.JOB_VENUE,
            )
        },
    }
    if ar.is_studio(state):
        payload["search_settings"] = ar.search_settings(state)
    if ar.is_paper(state):
        payload["actions"] = ar.available_actions(
            state,
            loop_running=bool(payload["loop"].get("running")),
            review_running=str(state.get("review_status")) == "running",
            has_source=(paper_dir / "main.tex").is_file(),
            pdf_available=payload["pdf_available"],
        )
        # The pane the author runs in, so the Factory can show the work
        # happening instead of only its result.
        payload["pane"] = (
            (getattr(meta, "tmux_interview_target", "") or "") if meta else ""
        )
        payload["stage_label"] = ar.progress_summary(state)
        payload["latest_review"] = ar.latest_review(state) or {}
        payload["plateaued"] = ar.is_plateaued(state)
        payload["best_rating"] = ar.best_rating(state)
        payload["venues_available"] = ar.venue_is_available(
            str(state.get("venue") or ar.DEFAULT_VENUE)
        )
        prepared = ar.submission_path(root, slug)
        if prepared.is_file():
            try:
                payload["submission"] = json.loads(
                    prepared.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                pass
    return payload

def _ar_overview(self, root: Path, project_id: str) -> dict[str, Any]:
    """Every AR task in one payload, studios with their papers nested.

    The Factory dashboard needs the whole fleet at a glance; fetching
    each task separately would be one request per paper per poll.
    """
    studios: dict[str, dict[str, Any]] = {}
    papers: list[dict[str, Any]] = []
    for meta in list_tasks(root):
        if not ar.is_ar_kind(meta.kind):
            continue
        state = ar.read_ar_state(root, meta.slug)
        if not state:
            continue
        common = {
            "slug": meta.slug,
            "title": meta.title,
            "venue": ar.venue_entry(
                str(state.get("venue") or ar.DEFAULT_VENUE)
            )["label"],
            "cost_usd": float(state.get("cost_usd") or 0.0),
            "updated_at": state.get("updated_at", ""),
        }
        if ar.is_studio(state):
            studios[meta.slug] = {
                **common,
                "direction": ar.direction_label(state),
                "mode": state.get("mode", ""),
                "papers_found": len(state.get("papers") or []),
                "ideas": len(state.get("ideas") or []),
                "papers_status": state.get("papers_status", ""),
                "ideas_status": state.get("ideas_status", ""),
                "children": [],
            }
        elif ar.is_paper(state):
            papers.append(
                {
                    **common,
                    "parent_slug": state.get("parent_slug", ""),
                    "stage": state.get("stage", ""),
                    "stage_label": ar.progress_summary(state),
                    "round": ar.current_round(state),
                    "max_rounds": ar.max_rounds(state),
                    "best_rating": ar.best_rating(state),
                    "plateaued": ar.is_plateaued(state),
                    "loop_running": bool(state.get("loop_running")),
                    "pdf_available": (
                        ar.paper_root(root, meta.slug) / "main.pdf"
                    ).is_file(),
                    "awaiting_you": state.get("stage")
                    in (ar.STAGE_AWAIT_DRAFT_REVIEW, ar.STAGE_AWAIT_FINAL_REVIEW),
                }
            )

    orphans: list[dict[str, Any]] = []
    for paper in papers:
        parent = studios.get(str(paper.get("parent_slug")))
        (parent["children"] if parent else orphans).append(paper)

    return {
        "ok": True,
        "project": project_id,
        "root": str(root),
        "studios": list(studios.values()),
        "orphans": orphans,
        "totals": {
            "studios": len(studios),
            "papers": len(papers),
            "awaiting_you": sum(1 for p in papers if p["awaiting_you"]),
            "running": sum(1 for p in papers if p["loop_running"]),
            "cost_usd": round(
                sum(s["cost_usd"] for s in studios.values())
                + sum(p["cost_usd"] for p in papers),
                2,
            ),
        },
    }

def _ar_resolve_pdf(self, root: Path, slug: str) -> tuple[Path | None, str]:
    """The task's compiled PDF, building it once if it is not there yet."""
    paper_dir = ar.paper_root(root, slug)
    pdf = paper_dir / "main.pdf"
    if pdf.is_file():
        return pdf, ""
    if not (paper_dir / "main.tex").is_file():
        return None, "this task has no paper yet"
    build = ar.build_pdf(paper_dir)
    if not build.get("ok"):
        return None, str(build.get("error") or "build failed")
    return Path(str(build.get("pdf"))), ""

def _ar_require_state(
    self, root: Path, slug: str, role: str = ""
) -> tuple[dict[str, Any] | None, str]:
    state = ar.read_ar_state(root, slug)
    if not state:
        return None, "this task has no AR state"
    if role == ar.ROLE_STUDIO and not ar.is_studio(state):
        return None, "this is not an AR studio task"
    if role == ar.ROLE_PAPER and not ar.is_paper(state):
        return None, "this is not an AR paper task"
    return state, ""

def _ar_action(
    self,
    root: Path,
    project_id: str,
    slug: str,
    action: str,
    body: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Dispatch one POST /api/tasks/<slug>/ar/<action>.

    Search suggestion, mining and idea generation can run for minutes,
    so they hand off to a thread and report progress through ar.json;
    the panel polls GET /ar the same way it polls everything else.
    """
    if action == "background":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_STUDIO)
        if state is None:
            return {"ok": False, "error": err}, 400
        profile_id = str(body.get("profile_id") or "").strip()
        if profile_id and not _SLUG_RE.match(profile_id):
            return {"ok": False, "error": "invalid researcher profile id"}, 400
        fit_mode = str(
            body.get("fit_mode") or ar.DEFAULT_BACKGROUND_FIT_MODE
        ).strip().lower()
        if fit_mode not in ar.BACKGROUND_FIT_MODES:
            return {"ok": False, "error": "unknown background exploration mode"}, 400
        if not profile_id:
            ar.update_ar_state(
                root,
                slug,
                background_profile_id="",
                background_profile_snapshot={},
                background_fit_mode=fit_mode,
            )
            return _ar_payload(self, root, project_id, slug), 200
        try:
            profile = researcher_profiles.read_profile(profile_id)
        except ValueError:
            return {"ok": False, "error": "invalid researcher profile id"}, 400
        if not profile:
            return {"ok": False, "error": "researcher profile not found"}, 404
        if str(profile.get("status") or "") != "active":
            return {
                "ok": False,
                "error": "activate the researcher profile before attaching it",
            }, 409
        snapshot = researcher_profiles.profile_snapshot(profile, fit_mode=fit_mode)
        ar.update_ar_state(
            root,
            slug,
            background_profile_id=profile_id,
            background_profile_snapshot=snapshot,
            background_fit_mode=fit_mode,
        )
        return _ar_payload(self, root, project_id, slug), 200

    if action == "search/suggest":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_STUDIO)
        if state is None:
            return {"ok": False, "error": err}, 400
        if str(state.get("search_suggest_status")) == "running":
            return {"ok": True, "status": "running"}, 202
        busy = [
            name
            for name in ("papers", "ideas", "link", "venue")
            if str(state.get(f"{name}_status")) == "running"
        ]
        if busy:
            return {
                "ok": False,
                "error": f"another Studio job is running: {busy[0]}",
            }, 409
        meta = read_meta(root, slug)
        model = str(body.get("model", "")).strip() or _ar_headless_model(meta)
        ar.update_ar_state(
            root,
            slug,
            search_suggest_status="running",
            search_suggest_error="",
        )
        _ar_run_async(_ar_search_suggest_job, root, slug, model)
        return {"ok": True, "status": "running"}, 202

    if action == "mine":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_STUDIO)
        if state is None:
            return {"ok": False, "error": err}, 400
        if str(state.get("papers_status")) == "running":
            return {"ok": True, "status": "running"}, 202
        if str(state.get("search_suggest_status")) == "running":
            return {"ok": False, "error": "search suggestion is still running"}, 409
        current = ar.search_settings(state)
        supplied = "search_terms" in body or "search_categories" in body
        raw_terms = body.get("search_terms", current["terms"])
        raw_categories = body.get("search_categories", current["categories"])
        terms, categories, settings_error = ar.validate_search_settings(
            raw_terms, raw_categories
        )
        if settings_error:
            return {"ok": False, "error": settings_error}, 400
        limit = max(5, min(100, int(body.get("limit", 40) or 40)))
        venue_only = bool(body.get("venue_only"))
        changes: dict[str, Any] = {
            "search_terms": terms,
            "search_categories": categories,
            "papers_status": "running",
            "papers_error": "",
        }
        if supplied:
            changes.update(
                search_terms_source="user",
                search_terms_updated_at=_iso_now(),
            )
        ar.update_ar_state(root, slug, **changes)
        _ar_run_async(_ar_mine_job, root, slug, limit, venue_only)
        return {"ok": True, "status": "running"}, 202

    if action == "venue":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_STUDIO)
        if state is None:
            return {"ok": False, "error": err}, 400
        if str(state.get("venue_status")) == "running":
            return {"ok": True, "status": "running"}, 202
        busy = [
            name
            for name in ("search_suggest", "papers", "ideas", "link")
            if str(state.get(f"{name}_status")) == "running"
        ]
        if busy:
            return {
                "ok": False,
                "error": f"another Studio job is running: {busy[0]}",
            }, 409
        venue_url = str(body.get("url", "")).strip()
        if venue_url and not venue_url.startswith(("http://", "https://")):
            return {
                "ok": False,
                "error": "venue URL must be an http(s) address",
            }, 400
        meta = read_meta(root, slug)
        model = str(body.get("model", "")).strip() or _ar_headless_model(meta)
        changes: dict[str, Any] = {
            "venue_status": "running",
            "venue_error": "",
            "venue_chain_ideas": bool(body.get("chain_ideas")),
        }
        if venue_url:
            changes["venue_url"] = venue_url
        ar.update_ar_state(root, slug, **changes)
        _ar_run_async(_ar_venue_job, root, slug, model)
        return {"ok": True, "status": "running"}, 202

    if action == "ideas":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_STUDIO)
        if state is None:
            return {"ok": False, "error": err}, 400
        pasted = body.get("ideas")
        if isinstance(pasted, list):
            ideas = [ar.normalize_idea(x, i) for i, x in enumerate(pasted)]
            ideas = [i for i in ideas if i["title"]]
            ar.update_ar_state(
                root,
                slug,
                ideas=_ar_merge_ideas(state, ideas),
                ideas_status="done",
                ideas_error="",
                ideas_updated_at=_iso_now(),
            )
            return _ar_payload(self, root, project_id, slug), 200
        if str(state.get("ideas_status")) == "running":
            return {"ok": True, "status": "running"}, 202
        if str(state.get("venue_status")) == "running":
            return {"ok": False, "error": "venue research is still running"}, 409
        source = str(body.get("source", "")).strip() or (
            # A last-cycle studio's natural grounding is its venue
            # report; plain "Generate ideas" should not demand arXiv.
            ar.IDEA_SOURCE_VENUE
            if state.get("venue_kickoff") and state.get("venue_report")
            else ar.IDEA_SOURCE_PAPERS
        )
        if source not in (ar.IDEA_SOURCE_PAPERS, ar.IDEA_SOURCE_VENUE):
            return {"ok": False, "error": "unknown idea source"}, 400
        if source == ar.IDEA_SOURCE_VENUE and not state.get("venue_report"):
            return {
                "ok": False,
                "error": "run the venue-cycle research first",
            }, 400
        count = max(1, min(12, int(body.get("count", 6) or 6)))
        meta = read_meta(root, slug)
        model = str(body.get("model", "")).strip() or _ar_headless_model(meta)
        ar.update_ar_state(root, slug, ideas_status="running", ideas_error="")
        _ar_run_async(_ar_ideas_job, root, slug, count, model, source)
        return {"ok": True, "status": "running"}, 202

    if action == "link":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_STUDIO)
        if state is None:
            return {"ok": False, "error": err}, 400
        if str(state.get("link_status")) == "running":
            return {"ok": True, "status": "running"}, 202
        meta = read_meta(root, slug)
        model = str(body.get("model", "")).strip() or _ar_headless_model(meta)
        ar.update_ar_state(root, slug, link_status="running", link_error="")
        _ar_run_async(_ar_link_job, root, slug, model)
        return {"ok": True, "status": "running"}, 202

    if action == "spawn":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_STUDIO)
        if state is None:
            return {"ok": False, "error": err}, 400
        raw_ids = body.get("idea_ids")
        idea_ids = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
        if not idea_ids:
            return {"ok": False, "error": "select at least one idea"}, 400
        spawned, errors = _ar_spawn_children(root, slug, state, idea_ids)
        # Spawning used to stop at the draft gate and wait for a manual
        # "Start the draft" per paper. Operators want a studio's picks to
        # begin writing immediately, so kick off each freshly spawned
        # paper's author loop here (same seed + start the draft action
        # runs). Papers that fail to start are reported, not fatal.
        started: list[str] = []
        for item in spawned:
            child = str(item.get("slug") or "")
            if not child:
                continue
            try:
                cstate = ar.read_ar_state(root, child)
                paper_dir = ar.paper_root(root, child)
                if not (paper_dir / "main.tex").is_file():
                    ok_seed, msg_seed = ar.seed_paper_skeleton(
                        paper_dir,
                        str(cstate.get("venue") or ar.DEFAULT_VENUE),
                        cstate.get("idea"),
                    )
                    if ok_seed:
                        ar.update_ar_state(
                            root, child, paper_dir=str(paper_dir)
                        )
                    else:
                        errors.append(f"{child}: {msg_seed}")
                        continue
                res = self.ar_manager.start(root, project_id, child)
                if res.get("ok"):
                    started.append(child)
                else:
                    errors.append(
                        f"{child}: {res.get('error') or 'failed to start'}"
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{child}: autostart failed: {exc}")
        payload = _ar_payload(self, root, project_id, slug)
        payload["spawned"] = spawned
        payload["started"] = started
        payload["errors"] = errors
        return payload, 200

    if action in ("draft", "loop/start"):
        state, err = _ar_require_state(self, root, slug, ar.ROLE_PAPER)
        if state is None:
            return {"ok": False, "error": err}, 400
        if action == "draft":
            paper_dir = ar.paper_root(root, slug)
            if not (paper_dir / "main.tex").is_file():
                ok, msg = ar.seed_paper_skeleton(
                    paper_dir,
                    str(state.get("venue") or ar.DEFAULT_VENUE),
                    state.get("idea"),
                )
                if not ok:
                    return {"ok": False, "error": msg}, 500
                ar.update_ar_state(root, slug, paper_dir=str(paper_dir))
        res = self.ar_manager.start(root, project_id, slug)
        if not res.get("ok"):
            return res, 409
        payload = _ar_payload(self, root, project_id, slug)
        payload["started"] = True
        return payload, 200

    if action == "loop/stop":
        self.ar_manager.stop(root, project_id, slug)
        return _ar_payload(self, root, project_id, slug), 200

    if action == "gate":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_PAPER)
        if state is None:
            return {"ok": False, "error": err}, 400
        gate = str(body.get("gate", "")).strip().lower()
        decision = str(body.get("decision", "")).strip().lower()
        note = str(body.get("note", ""))
        if gate not in (ar.GATE_DRAFT, ar.GATE_FINAL):
            return {"ok": False, "error": "gate must be draft or final"}, 400
        if decision not in ("approve", "reject"):
            return {"ok": False, "error": "decision must be approve or reject"}, 400
        expected = (
            ar.STAGE_AWAIT_DRAFT_REVIEW
            if gate == ar.GATE_DRAFT
            else ar.STAGE_AWAIT_FINAL_REVIEW
        )
        if str(state.get("stage")) != expected:
            return (
                {
                    "ok": False,
                    "error": (
                        f"this task is not at the {gate} gate "
                        f"(stage: {ar.progress_summary(state)})"
                    ),
                },
                409,
            )
        ar.record_gate(state, gate, decision, note)
        if gate == ar.GATE_FINAL and decision == "approve":
            build = ar.build_pdf(ar.paper_root(root, slug))
            if build.get("ok"):
                state["pdf_path"] = str(build.get("pdf") or "")
                state["pdf_built_at"] = _iso_now()
            # A delivered paper will meet reviewers eventually; hand
            # its manuscript to the Rebuttal Factory now so the
            # reviews have somewhere to land. Best-effort: delivery
            # must not fail because a registry write did.
            try:
                meta = read_meta(root, slug)
                record = rebuttal.register_project(
                    str(ar.paper_root(root, slug)),
                    title=(meta.title if meta else slug),
                )
                state["rebuttal_project_id"] = str(record.get("id") or "")
            except Exception as exc:  # noqa: BLE001
                print(f"[ar] {slug}: rebuttal handoff failed: {exc}", flush=True)
        ar.write_ar_state(root, slug, state)
        if str(state.get("stage")) == ar.STAGE_LOOP:
            self.ar_manager.start(root, project_id, slug)
        return _ar_payload(self, root, project_id, slug), 200

    if action == "review":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_PAPER)
        if state is None:
            return {"ok": False, "error": err}, 400
        if str(state.get("review_status")) == "running":
            return {"ok": True, "status": "running"}, 202
        ar.update_ar_state(root, slug, review_status="running", review_error="")
        _ar_run_async(_ar_review_job, root, slug)
        return {"ok": True, "status": "running"}, 202

    if action == "submission":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_PAPER)
        if state is None:
            return {"ok": False, "error": err}, 400
        payload = ar.build_submission(root, slug, state)
        try:
            ar.submission_path(root, slug).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            return {"ok": False, "error": f"could not write submission.json: {exc}"}, 500
        out = _ar_payload(self, root, project_id, slug)
        out["submission"] = payload
        return out, 200

    if action == "build":
        state, err = _ar_require_state(self, root, slug, ar.ROLE_PAPER)
        if state is None:
            return {"ok": False, "error": err}, 400
        build = ar.build_pdf(ar.paper_root(root, slug))
        changes: dict[str, Any] = {"paper_dir": str(ar.paper_root(root, slug))}
        if build.get("ok"):
            changes["pdf_path"] = str(build.get("pdf") or "")
            changes["pdf_built_at"] = _iso_now()
            changes["pdf_error"] = (
                "" if build.get("clean") else "compiled with LaTeX errors"
            )
        else:
            changes["pdf_error"] = str(build.get("error") or "build failed")
        ar.update_ar_state(root, slug, **changes)
        payload = _ar_payload(self, root, project_id, slug)
        payload["build"] = {
            k: build.get(k)
            for k in ("ok", "clean", "bytes", "error", "missing_packages")
        }
        payload["latex_errors"] = ar.latex_errors(str(build.get("log") or ""))
        return payload, 200

    return {"ok": False, "error": f"unknown AR action {action!r}"}, 404
