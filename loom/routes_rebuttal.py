"""Rebuttal Factory routes: conference studios, paper projects, the live agents, delivery, quick import, and the shared OpenReview session."""

from __future__ import annotations

import json
from typing import Any
import re
from pathlib import Path

from urllib.parse import quote as _urlquote

from loom import openreview_submit
from loom import paper_fetch
from loom import rebuttal_delivery as delivery
from loom import rebuttal_task as rebuttal
from loom.rud_task import CURSOR_DEFAULT_MODEL
from loom.web_jobs import (
    _ar_headless_model,
    _ar_run_async,
    _rebuttal_join_staged,
    _rebuttal_policy_job,
    _rebuttal_start_agent,
    _rebuttal_start_delivery_agent,
    _rebuttal_stop_agent,
    _rebuttal_stop_delivery_agent,
    _rebuttal_verify_figures_job,
)
from loom.web_util import _json_bytes


def handle_get(self, path, parsed) -> bool:  # noqa: C901
    if path == "/api/openreview/auth":
        st, b, h = _json_bytes(openreview_submit.auth_status())
        self._send(st, b, h)
        return True


    if path == "/api/rebuttal/catalog":
        st, b, h = _json_bytes(
            {
                "ok": True,
                "default_policy": rebuttal.DEFAULT_POLICY,
                "stages": [
                    rebuttal.STAGE_INTAKE,
                    rebuttal.STAGE_CONCERNS,
                    rebuttal.STAGE_RESPONSES,
                    rebuttal.STAGE_VALIDATED,
                    rebuttal.STAGE_APPROVED,
                ],
                "studio_stages": [
                    rebuttal.STUDIO_STAGE_POLICY_INPUT,
                    rebuttal.STUDIO_STAGE_POLICY_DRAFT,
                    rebuttal.STUDIO_STAGE_AWAIT_POLICY_REVIEW,
                    rebuttal.STUDIO_STAGE_ACTIVE,
                    rebuttal.STUDIO_STAGE_CLOSED,
                ],
            }
        )
        self._send(st, b, h)
        return True


    if path == "/api/rebuttal/studios":
        st, b, h = _json_bytes(
            {"ok": True, "studios": rebuttal.list_studios()}
        )
        self._send(st, b, h)
        return True


    m_rebuttal_studio_get = re.match(
        r"^/api/rebuttal/studios/([a-z0-9][a-z0-9-]{0,79})$",
        path,
    )
    if m_rebuttal_studio_get:
        payload = rebuttal.studio_payload(
            m_rebuttal_studio_get.group(1)
        )
        if not payload:
            st, b, h = _json_bytes(
                {"ok": False, "error": "conference studio not found"},
                404,
            )
        else:
            st, b, h = _json_bytes(payload)
        self._send(st, b, h)
        return True


    if path == "/api/rebuttal/projects":
        st, b, h = _json_bytes(
            {"ok": True, "projects": rebuttal.list_projects()}
        )
        self._send(st, b, h)
        return True


    m_rebuttal_delivery_artifact = re.match(
        r"^/api/rebuttal/projects/([0-9a-f]{12})/delivery/"
        r"(revised-paper|rebuttal|supplement|bundle|preflight|handoff)$",
        path,
    )
    if m_rebuttal_delivery_artifact:
        project_id = m_rebuttal_delivery_artifact.group(1)
        wanted = m_rebuttal_delivery_artifact.group(2)
        key = "revised_paper" if wanted == "revised-paper" else wanted
        artifact = delivery.artifact_path(project_id, key)
        if artifact is None:
            st, b, h = _json_bytes(
                {"ok": False, "error": "delivery artifact not found"},
                404,
            )
            self._send(st, b, h)
            return True
        try:
            body = artifact.read_bytes()
        except OSError as exc:
            st, b, h = _json_bytes(
                {"ok": False, "error": str(exc)},
                500,
            )
            self._send(st, b, h)
            return True
        content_type = {
            ".pdf": "application/pdf",
            ".zip": "application/zip",
            ".md": "text/markdown; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(artifact.suffix.lower(), "application/octet-stream")
        disposition = (
            "attachment"
            if artifact.suffix.lower() == ".zip"
            else "inline"
        )
        self._send(
            200,
            body,
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                (
                    "Content-Disposition",
                    f'{disposition}; filename="{artifact.name}"',
                ),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )
        return True


    m_rebuttal_get = re.match(r"^/api/rebuttal/projects/([0-9a-f]{12})$", path)
    if m_rebuttal_get:
        payload = rebuttal.project_payload(m_rebuttal_get.group(1))
        if not payload:
            st, b, h = _json_bytes(
                {"ok": False, "error": "rebuttal project not found"},
                404,
            )
        else:
            st, b, h = _json_bytes(payload)
        self._send(st, b, h)
        return True


    return False

def handle_post(self, path, parsed, body) -> bool:  # noqa: C901
    if path == "/api/rebuttal/studios":
        try:
            payload = rebuttal.register_studio(
                str(body.get("conference") or ""),
                body.get("year"),
                str(body.get("cfp_url") or ""),
                policy_url=str(body.get("policy_url") or ""),
                title=str(body.get("title") or ""),
            )
        except ValueError as exc:
            st, b, h = _json_bytes(
                {"ok": False, "error": str(exc)},
                400,
            )
        except OSError as exc:
            st, b, h = _json_bytes(
                {"ok": False, "error": f"could not create studio: {exc}"},
                500,
            )
        else:
            st, b, h = _json_bytes(payload, 201)
        self._send(st, b, h)
        return True


    m_rebuttal_studio_action = re.match(
        r"^/api/rebuttal/studios/([a-z0-9][a-z0-9-]{0,79})/([a-z-]+)$",
        path,
    )
    if m_rebuttal_studio_action:
        studio_id = m_rebuttal_studio_action.group(1)
        action = m_rebuttal_studio_action.group(2)
        state = rebuttal.read_studio(studio_id)
        if not state:
            st, b, h = _json_bytes(
                {"ok": False, "error": "conference studio not found"},
                404,
            )
            self._send(st, b, h)
            return True
        active = str(state.get("active_job") or "")

        if action == "discover-policy":
            if active:
                st, b, h = _json_bytes(
                    {"ok": True, "status": "running", "job": active},
                    202,
                )
            else:
                state["active_job"] = rebuttal.JOB_POLICY
                state["stage"] = rebuttal.STUDIO_STAGE_POLICY_DRAFT
                state["error"] = ""
                state["policy_approved_at"] = ""
                rebuttal.append_log(state, "started official policy discovery")
                rebuttal.write_studio(studio_id, state)
                model = (
                    str(body.get("model") or "").strip()
                    or _ar_headless_model(None)
                )
                _ar_run_async(_rebuttal_policy_job, studio_id, model)
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "status": "running",
                        "job": rebuttal.JOB_POLICY,
                    },
                    202,
                )
            self._send(st, b, h)
            return True

        if action == "policy":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                try:
                    payload = rebuttal.save_studio_policy(
                        studio_id,
                        body.get("policy")
                        if isinstance(body.get("policy"), dict)
                        else {},
                        strategy=body.get("strategy")
                        if isinstance(body.get("strategy"), dict)
                        else None,
                    )
                except (ValueError, OSError) as exc:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": str(exc)},
                        400,
                    )
                else:
                    st, b, h = _json_bytes(payload)
            self._send(st, b, h)
            return True

        if action == "approve-policy":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                try:
                    payload = rebuttal.approve_studio_policy(studio_id)
                except (ValueError, OSError) as exc:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": str(exc)},
                        409,
                    )
                else:
                    # Quick imports staged their packages while the
                    # policy was pending; approval is the last human
                    # step, so they join and start on their own now.
                    joined = _rebuttal_join_staged(
                        studio_id, self.claude_registry
                    )
                    if joined:
                        payload["joined_papers"] = joined
                    st, b, h = _json_bytes(payload)
            self._send(st, b, h)
            return True

        if action == "add-paper":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                try:
                    paper_source = str(body.get("path") or "").strip()
                    paper_title = str(body.get("title") or "")
                    if paper_source.startswith(("http://", "https://")):
                        # An OpenReview forum link: pull the submission
                        # PDF and every official review into a managed
                        # package, then import that like any directory.
                        fetched = paper_fetch.materialize_rebuttal_package(
                            paper_source,
                            Path.home() / ".loom" / "factories"
                            / "rebuttal" / studio_id,
                        )
                        paper_source = str(fetched["dir"])
                        paper_title = paper_title or str(fetched.get("title") or "")
                    payload = rebuttal.register_paper_for_studio(
                        studio_id,
                        paper_source,
                        title=paper_title,
                    )
                except (ValueError, OSError) as exc:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": str(exc)},
                        400,
                    )
                else:
                    project_id = str(payload["project"].get("id") or "")
                    auto_draft = bool(body.get("auto_draft", True))
                    manifest_ready = bool(
                        (payload["project"].get("manifest") or {}).get("ready")
                    )
                    if project_id and auto_draft and manifest_ready:
                        model = (
                            str(body.get("model") or "").strip()
                            or CURSOR_DEFAULT_MODEL
                        )
                        started = _rebuttal_start_agent(
                            project_id,
                            model,
                            self.claude_registry,
                        )
                        if not started.get("ok"):
                            paper_state = rebuttal.read_state(project_id)
                            paper_state["agent_status"] = "error"
                            paper_state["error"] = str(
                                started.get("error")
                                or "could not start live rebuttal agent"
                            )
                            rebuttal.append_log(
                                paper_state,
                                f"live agent start failed: {paper_state['error']}",
                            )
                            rebuttal.write_state(project_id, paper_state)
                        payload = rebuttal.project_payload(project_id)
                        payload["agent_start"] = started
                    st, b, h = _json_bytes(payload, 201)
            self._send(st, b, h)
            return True

        st, b, h = _json_bytes(
            {"ok": False, "error": f"unknown studio action: {action}"},
            404,
        )
        self._send(st, b, h)
        return True


    if path == "/api/openreview/login":
        try:
            result = openreview_submit.login(
                str(body.get("username") or ""),
                str(body.get("password") or ""),
            )
            st, b, h = _json_bytes(result)
        except ValueError as exc:
            st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
        self._send(st, b, h)
        return True


    if path == "/api/openreview/logout":
        st, b, h = _json_bytes(openreview_submit.logout())
        self._send(st, b, h)
        return True


    if path == "/api/rebuttal/quick-import":
        # One OpenReview forum link does everything derivable: venue
        # and year come off the submission itself, the studio is
        # found or created (policy discovery kicked off), and the
        # paper package is fetched. Only the policy approval stays
        # human - by design.
        try:
            st, b, h = _rebuttal_quick_import(self, body)
        except ValueError as exc:
            st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 400)
        self._send(st, b, h)
        return True


    if path == "/api/rebuttal/projects":
        try:
            payload = rebuttal.register_project(
                str(body.get("path") or ""),
                title=str(body.get("title") or ""),
                policy=body.get("policy") if isinstance(body.get("policy"), dict) else None,
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


    m_rebuttal_action = re.match(
        r"^/api/rebuttal/projects/([0-9a-f]{12})/([a-z-]+)$",
        path,
    )
    if m_rebuttal_action:
        project_id = m_rebuttal_action.group(1)
        action = m_rebuttal_action.group(2)
        state = rebuttal.read_state(project_id)
        if not state:
            st, b, h = _json_bytes(
                {"ok": False, "error": "rebuttal project not found"},
                404,
            )
            self._send(st, b, h)
            return True
        active = str(state.get("active_job") or "")
        delivery_state = (
            state.get("delivery")
            if isinstance(state.get("delivery"), dict)
            else {}
        )
        delivery_busy = delivery_state.get("agent_status") in (
            "running",
            "validating",
        )
        can_stop_delivery = (
            action == "stop-delivery"
            and delivery_state.get("agent_status") == "running"
        )
        if delivery_busy and not can_stop_delivery:
            st, b, h = _json_bytes(
                {
                    "ok": False,
                    "error": (
                        "delivery Agent or strict preflight is still running"
                    ),
                },
                409,
            )
            self._send(st, b, h)
            return True

        if action == "start-agent":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                model = (
                    str(body.get("model") or "").strip()
                    or CURSOR_DEFAULT_MODEL
                )
                started = _rebuttal_start_agent(
                    project_id,
                    model,
                    self.claude_registry,
                )
                if started.get("ok"):
                    payload = rebuttal.project_payload(project_id)
                    payload["agent_start"] = started
                    st, b, h = _json_bytes(payload)
                else:
                    st, b, h = _json_bytes(started, 500)
            self._send(st, b, h)
            return True

        if action == "stop-agent":
            result = _rebuttal_stop_agent(project_id)
            st, b, h = _json_bytes(
                rebuttal.project_payload(project_id)
                if result.get("ok")
                else result,
                200 if result.get("ok") else 500,
            )
            self._send(st, b, h)
            return True

        if action == "submit-openreview":
            # The human's confirm click is the trigger; a dry run
            # first shows exactly what would land where.
            auth = openreview_submit.cached_auth()
            if not auth:
                st, b, h = _json_bytes(
                    {"ok": False, "error": "not signed in to OpenReview"},
                    401,
                )
                self._send(st, b, h)
                return True
            if str(state.get("stage") or "") in (
                rebuttal.STAGE_INTAKE,
                rebuttal.STAGE_CONCERNS,
            ):
                st, b, h = _json_bytes(
                    {"ok": False, "error": "responses are not written yet"},
                    409,
                )
                self._send(st, b, h)
                return True
            source = rebuttal._source_for(project_id)
            forum_file = source / "forum.json" if source else None
            if forum_file is None or not forum_file.is_file():
                st, b, h = _json_bytes(
                    {
                        "ok": False,
                        "error": (
                            "no forum.json in the source package - only "
                            "papers imported from an OpenReview link "
                            "carry the note ids replies must target"
                        ),
                    },
                    400,
                )
                self._send(st, b, h)
                return True
            try:
                forum_info = json.loads(
                    forum_file.read_text(encoding="utf-8")
                )
                responses = {
                    rid: rebuttal.response_body(project_id, rid)
                    for rid in (state.get("responses") or {})
                }
                plan = openreview_submit.build_plan(
                    forum_info, responses, auth["token"]
                )
            except (ValueError, OSError) as exc:
                st, b, h = _json_bytes(
                    {"ok": False, "error": str(exc)}, 400
                )
                self._send(st, b, h)
                return True
            preview = [
                {
                    k: item.get(k)
                    for k in (
                        "reviewer_id",
                        "reviewer_label",
                        "replyto",
                        "characters",
                        "error",
                    )
                    if item.get(k) is not None
                }
                for item in plan["items"]
            ]
            if not body.get("confirm"):
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "dry_run": True,
                        "forum": plan["forum"],
                        "invitation": plan["invitation"],
                        "signature": plan["signature"],
                        "items": preview,
                        "user": auth["username"],
                    }
                )
                self._send(st, b, h)
                return True
            results = openreview_submit.execute_plan(plan, auth["token"])
            posted = sum(1 for r in results if r.get("ok"))
            state = rebuttal.read_state(project_id)
            state["openreview_submission"] = {
                "at": rebuttal._now(),
                "forum": plan["forum"],
                "invitation": plan["invitation"],
                "signature": plan["signature"],
                "by": auth["username"],
                "results": results,
            }
            rebuttal.append_log(
                state,
                f"OpenReview: posted {posted}/{len(results)} replies "
                f"as {plan['signature']}",
            )
            rebuttal.write_state(project_id, state)
            st, b, h = _json_bytes(
                {
                    "ok": posted == len(results) and posted > 0,
                    "results": results,
                    "project": rebuttal.project_payload(project_id),
                }
            )
            self._send(st, b, h)
            return True

        if action in ("start-delivery", "rerun-delivery"):
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                model = (
                    str(body.get("model") or "").strip()
                    or CURSOR_DEFAULT_MODEL
                )
                started = _rebuttal_start_delivery_agent(
                    project_id,
                    model,
                    self.claude_registry,
                    rerun=action == "rerun-delivery",
                    feedback=str(body.get("feedback") or ""),
                )
                if started.get("ok"):
                    payload = rebuttal.project_payload(project_id)
                    payload["delivery_start"] = started
                    st, b, h = _json_bytes(payload)
                else:
                    st, b, h = _json_bytes(started, 409)
            self._send(st, b, h)
            return True

        if action == "stop-delivery":
            result = _rebuttal_stop_delivery_agent(project_id)
            st, b, h = _json_bytes(
                rebuttal.project_payload(project_id)
                if result.get("ok")
                else result,
                200 if result.get("ok") else 500,
            )
            self._send(st, b, h)
            return True

        if action == "verify-figures":
            phase = str(delivery_state.get("phase") or "")
            artifacts = (
                delivery_state.get("artifacts")
                if isinstance(delivery_state.get("artifacts"), dict)
                else {}
            )
            if phase == "figure_verification_running":
                st, b, h = _json_bytes({"ok": True, "status": "running"}, 202)
            elif not artifacts.get("revised_paper"):
                st, b, h = _json_bytes(
                    {
                        "ok": False,
                        "error": "run the delivery preflight first",
                    },
                    409,
                )
            else:
                latest = rebuttal.read_state(project_id)
                current = dict(latest.get("delivery") or {})
                current["phase"] = "figure_verification_running"
                latest["delivery"] = current
                rebuttal.append_log(latest, "figure verification requested")
                rebuttal.write_state(project_id, latest)
                _ar_run_async(_rebuttal_verify_figures_job, project_id)
                st, b, h = _json_bytes({"ok": True, "status": "running"}, 202)
            self._send(st, b, h)
            return True

        if action == "approve-delivery":
            try:
                payload = delivery.approve_delivery(project_id)
            except ValueError as exc:
                st, b, h = _json_bytes(
                    {"ok": False, "error": str(exc)},
                    409,
                )
            else:
                st, b, h = _json_bytes(payload)
            self._send(st, b, h)
            return True

        if action == "rescan":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                try:
                    payload = rebuttal.register_project(
                        str(state.get("source_path") or ""),
                        title=str(state.get("title") or ""),
                        policy=state.get("policy")
                        if isinstance(state.get("policy"), dict)
                        else None,
                    )
                    fresh = payload["project"]
                    fresh["reviewers"] = []
                    fresh["responses"] = {}
                    fresh["validation"] = {}
                    fresh["stage"] = rebuttal.STAGE_INTAKE
                    fresh["approved_at"] = ""
                    fresh["content_approval"] = {}
                    rebuttal.invalidate_delivery(
                        fresh,
                        "source package was rescanned",
                    )
                    rebuttal.append_log(
                        fresh,
                        "cleared derived rebuttal artifacts after rescan",
                    )
                    rebuttal.write_state(project_id, fresh)
                    st, b, h = _json_bytes(
                        rebuttal.project_payload(project_id)
                    )
                except (ValueError, OSError) as exc:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": str(exc)},
                        400,
                    )
            self._send(st, b, h)
            return True

        if action == "policy":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                policy_input = dict(
                    state.get("policy")
                    if isinstance(state.get("policy"), dict)
                    else {}
                )
                if isinstance(body.get("policy"), dict):
                    policy_input.update(body["policy"])
                policy = rebuttal.normalize_policy(policy_input)
                state["policy"] = policy
                state["validation"] = {}
                state["content_approval"] = {}
                rebuttal.invalidate_delivery(
                    state,
                    "paper delivery policy changed",
                )
                if state.get("stage") in (
                    rebuttal.STAGE_VALIDATED,
                    rebuttal.STAGE_APPROVED,
                    rebuttal.STAGE_DELIVERY_AGENT,
                    rebuttal.STAGE_DELIVERY_VALIDATING,
                    rebuttal.STAGE_DELIVERY_BLOCKED,
                    rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL,
                    rebuttal.STAGE_BUNDLE_READY,
                ):
                    state["stage"] = rebuttal.STAGE_RESPONSES
                    state["approved_at"] = ""
                rebuttal.append_log(state, "updated venue rebuttal policy")
                rebuttal.write_state(project_id, state)
                st, b, h = _json_bytes(
                    rebuttal.project_payload(project_id)
                )
            self._send(st, b, h)
            return True

        if action == "save-response":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                try:
                    payload = rebuttal.save_response(
                        project_id,
                        str(body.get("reviewer_id") or ""),
                        str(body.get("body") or ""),
                    )
                except (ValueError, OSError) as exc:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": str(exc)},
                        400,
                    )
                else:
                    st, b, h = _json_bytes(payload)
            self._send(st, b, h)
            return True

        if action == "validate":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                report = rebuttal.validate_project(project_id)
                state = rebuttal.read_state(project_id)
                state["validation"] = report
                state["content_approval"] = {}
                rebuttal.invalidate_delivery(
                    state,
                    "response validation was rerun",
                )
                state["stage"] = (
                    rebuttal.STAGE_VALIDATED
                    if report.get("ready")
                    else rebuttal.STAGE_RESPONSES
                )
                state["approved_at"] = ""
                rebuttal.append_log(
                    state,
                    "validation passed"
                    if report.get("ready")
                    else f"validation blocked by {len(report.get('errors') or [])} issue(s)",
                )
                rebuttal.write_state(project_id, state)
                st, b, h = _json_bytes(
                    rebuttal.project_payload(project_id)
                )
            self._send(st, b, h)
            return True

        if action == "approve":
            if active:
                st, b, h = _json_bytes(
                    {"ok": False, "error": f"{active} is still running"},
                    409,
                )
            else:
                try:
                    payload = rebuttal.approve_project(project_id)
                except ValueError as exc:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": str(exc)},
                        409,
                    )
                else:
                    approved_state = rebuttal.read_state(project_id)
                    delivery_policy = delivery.normalize_delivery_policy(
                        approved_state,
                        Path(str(approved_state.get("source_path") or "")),
                    )
                    if delivery_policy.get("enabled"):
                        model = (
                            str(body.get("model") or "").strip()
                            or CURSOR_DEFAULT_MODEL
                        )
                        started = _rebuttal_start_delivery_agent(
                            project_id,
                            model,
                            self.claude_registry,
                        )
                        payload = rebuttal.project_payload(project_id)
                        payload["delivery_start"] = started
                    st, b, h = _json_bytes(payload)
            self._send(st, b, h)
            return True

        st, b, h = _json_bytes(
            {"ok": False, "error": f"unknown rebuttal action: {action}"},
            404,
        )
        self._send(st, b, h)
        return True


    return False

def handle_delete(self, path, parsed) -> bool:  # noqa: C901
    m_rebuttal_studio_del = re.match(
        r"^/api/rebuttal/studios/([a-z0-9][a-z0-9-]{0,79})$",
        path,
    )
    if m_rebuttal_studio_del:
        studio_id = m_rebuttal_studio_del.group(1)
        state = rebuttal.read_studio(studio_id)
        if not state:
            st, b, h = _json_bytes(
                {"ok": False, "error": "conference studio not found"},
                404,
            )
        elif state.get("active_job"):
            st, b, h = _json_bytes(
                {
                    "ok": False,
                    "error": f"{state['active_job']} is still running",
                },
                409,
            )
        else:
            try:
                rebuttal.delete_studio(studio_id)
            except ValueError as exc:
                st, b, h = _json_bytes(
                    {"ok": False, "error": str(exc)},
                    409,
                )
            else:
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "id": studio_id,
                        "note": "policy artifacts were preserved",
                    }
                )
        self._send(st, b, h)
        return True


    m_rebuttal_del = re.match(
        r"^/api/rebuttal/projects/([0-9a-f]{12})$",
        path,
    )
    if m_rebuttal_del:
        project_id = m_rebuttal_del.group(1)
        state = rebuttal.read_state(project_id)
        if not state:
            st, b, h = _json_bytes(
                {"ok": False, "error": "rebuttal project not found"},
                404,
            )
        elif state.get("active_job"):
            st, b, h = _json_bytes(
                {
                    "ok": False,
                    "error": f"{state['active_job']} is still running",
                },
                409,
            )
        elif state.get("agent_status") == "running":
            st, b, h = _json_bytes(
                {
                    "ok": False,
                    "error": "stop the live rebuttal agent before forgetting the paper",
                },
                409,
            )
        elif (
            isinstance(state.get("delivery"), dict)
            and state["delivery"].get("agent_status") == "running"
        ):
            st, b, h = _json_bytes(
                {
                    "ok": False,
                    "error": "stop the delivery agent before forgetting the paper",
                },
                409,
            )
        else:
            rebuttal.delete_project(project_id)
            st, b, h = _json_bytes(
                {
                    "ok": True,
                    "id": project_id,
                    "note": "source materials and rebuttal-output were preserved",
                }
            )
        self._send(st, b, h)
        return True


    return False


def _rebuttal_quick_import(
    self, body: dict[str, Any]
) -> tuple[int, bytes, list[tuple[str, str]]]:
    url = str(body.get("url") or "").strip()
    forum = paper_fetch.openreview_forum_id(url)
    if not forum:
        raise ValueError(
            "paste an openreview.net forum link (…?id=<forum>)"
        )
    info = paper_fetch.fetch_openreview_forum(forum)
    conference, year = paper_fetch.venue_of_submission(
        info.get("submission") or {}
    )
    if not conference or not year:
        raise ValueError(
            "could not read the venue off this submission - create "
            "the Conference Studio by hand, then add this link there"
        )

    # One studio per conference cycle: reuse it when it exists.
    studio = next(
        (
            s
            for s in rebuttal.list_studios()
            if str(s.get("conference") or "").lower() == conference.lower()
            and int(s.get("year") or 0) == year
        ),
        None,
    )
    created = False
    if studio is None:
        group = str(
            (info.get("submission") or {}).get("domain")
            or f"{conference}.cc/{year}/Conference"
        )
        payload = rebuttal.register_studio(
            conference,
            year,
            f"https://openreview.net/group?id={_urlquote(group)}",
        )
        studio = payload.get("studio") or payload
        created = True
    studio_id = str(studio.get("id") or "")

    # The paper package lands on disk either way; registration waits
    # for the human policy gate when the studio is not active yet.
    fetched = paper_fetch.materialize_rebuttal_package(
        url, Path.home() / ".loom" / "factories" / "rebuttal" / studio_id
    )
    state = rebuttal.read_studio(studio_id)
    if str(state.get("stage")) == rebuttal.STUDIO_STAGE_ACTIVE:
        project = rebuttal.register_paper_for_studio(
            studio_id, str(fetched["dir"]), title=str(fetched.get("title") or "")
        )
        project_id = str((project.get("project") or {}).get("id") or "")
        if project_id and bool(
            ((project.get("project") or {}).get("manifest") or {}).get("ready")
        ):
            started = _rebuttal_start_agent(
                project_id, CURSOR_DEFAULT_MODEL, self.claude_registry
            )
            project["agent_start"] = started
        return _json_bytes(
            {
                "ok": True,
                "studio_id": studio_id,
                "project_id": project_id,
                "title": fetched.get("title") or "",
                "message": "paper registered - the rebuttal agent is on it",
            },
            201,
        )

    # Fresh (or unapproved) studio: kick policy discovery so the only
    # human step left is the approval.
    if not str(state.get("active_job") or ""):
        state["active_job"] = rebuttal.JOB_POLICY
        state["stage"] = rebuttal.STUDIO_STAGE_POLICY_DRAFT
        state["error"] = ""
        state["policy_approved_at"] = ""
        rebuttal.append_log(
            state, "quick import: started official policy discovery"
        )
        rebuttal.write_studio(studio_id, state)
        _ar_run_async(
            _rebuttal_policy_job, studio_id, _ar_headless_model(None)
        )
    return _json_bytes(
        {
            "ok": True,
            "studio_id": studio_id,
            "staged_dir": str(fetched["dir"]),
            "title": fetched.get("title") or "",
            "created_studio": created,
            "message": (
                f"{conference} {year} policy is being discovered - "
                "approve it once and the paper joins and starts by itself"
            ),
        },
        202,
    )
