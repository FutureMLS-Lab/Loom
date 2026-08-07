"""Lightweight local web UI for `.RUD` tasks.

Three concerns after the agent-loop rewrite:

1. **Task CRUD** - list / create / delete tasks (``<project>/.RUD/<slug>/``).
   Each new task auto-creates a git worktree at
   ``<task>/work/<repo>`` on branch ``zhongzhu/<slug>`` (best-effort -
   non-git project roots just skip the worktree step).
2. **Project notes** - one ``<project>/.RUD/NOTES.md`` per project,
   served by ``GET/PUT /api/notes``.
3. **Claude pane** - launch a tmux + ``claude`` CLI in the task's
   worktree, automatically capture the Claude Code session UUID from
   ``~/.claude/projects/<encoded>/``, and let the UI resume any
   previously-captured session even after tmux is killed.

The only per-task editable template is ``PLAN.md``.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from loom import ar_task as ar
from loom.openclaw import OpenClawClient, OpenClawConfig, openclaw_status
from loom.paths import (
    KERNEL_HUB_ENV,
    bundled_skills_path,
    kernel_hub_dir,
    web_static_dir,
)
from loom.rud_task import (
    AGENT_CURSOR,
    AGENT_CLAUDE,
    AGENT_CODEX,
    CURSOR_DEFAULT_MODEL,
    DEFAULT_MONITOR_PATTERN,
    PLAN,
    SKILLS_PATH_SEP,
    SUPPORTED_AGENTS,
    add_claude_session,
    agent_default_model,
    agent_label,
    agent_model_options,
    build_agent_command,
    create_task,
    delete_task,
    detect_and_persist_worktree,
    ensure_cursor_default_model_config,
    join_skills_paths,
    list_session_files,
    list_task_markdown_files,
    list_task_worktree_statuses,
    list_task_worktrees,
    list_tasks,
    list_worktree_candidates,
    load_skills_text,
    merge_worktree_to_base,
    normalize_agent,
    prepare_task_worktree_from,
    push_worktree_branch,
    read_kernel_interview,
    read_meta,
    read_markdown_asset,
    read_project_notes,
    read_task_markdown_file,
    read_task_monitor,
    read_template,
    rud_root,
    remove_task_worktree,
    reorder_tasks,
    rename_task_meta,
    session_id_from_path,
    split_skills_paths,
    task_root,
    task_worktree_diffs,
    task_worktree_path,
    update_meta,
    worktree_diff,
    worktree_status,
    write_kernel_interview,
    write_project_notes,
    write_task_monitor,
    write_template,
)
from loom.tmux_util import (
    capture_pane,
    list_tmux_panes,
    list_tmux_sessions,
    open_pane_attach,
    scroll_pane,
    send_pane_key,
    send_pane_literal,
    send_pane_text,
    tmux_available,
    tmux_subprocess_env,
    validate_tmux_target,
)
from loom.web_projects import WebProjectRegistry

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,80}$")
_STATIC_MIME: dict[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}


def _project_worktree_candidates(
    registry: WebProjectRegistry, root: Path, project_id: str
) -> list[dict[str, Any]]:
    preferred = registry.get_code_root(project_id)
    return list_worktree_candidates(
        root, [preferred] if preferred is not None else []
    )


# --- naming / filtering helpers --------------------------------------------


def _tmux_id_fragment(project_id: str) -> str:
    frag = re.sub(r"[^A-Za-z0-9]+", "", (project_id or "x"))[:8]
    return frag or "proj"


# Current brand prefix for new tmux session names. "claudeloop" is the legacy
# prefix from before the rename and is still recognized for reuse/cleanup so
# panes started by older builds keep working.
_SESSION_BRAND = "loom"
_SESSION_BRANDS = ("loom", "claudeloop")


def _sanitize_session_name(raw: str, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.@-]+", "-", raw).strip("-")
    return safe[:90] or fallback


def _safe_claude_session_name(project_id: str, slug: str, agent: str = AGENT_CURSOR) -> str:
    """Tmux session name for a task's agent pane (current ``loom-`` brand).

    The agent name is part of the prefix so a claude pane and a codex pane for
    the same project never share a tmux session if the user ever changes agent.
    The legacy ``claudeloop-`` prefix and old ``interview`` pane name are handled
    via ``_legacy_claude_session_name`` / ``_session_name_aliases`` and
    ``_filter_tmux_sessions_for_project``.
    """
    tid = _tmux_id_fragment(project_id)
    agent = normalize_agent(agent)
    return _sanitize_session_name(f"{_SESSION_BRAND}-{agent}-{tid}-{slug}", f"{_SESSION_BRAND}-{agent}")


def _legacy_claude_session_name(project_id: str, slug: str, agent: str = AGENT_CURSOR) -> str:
    """Pre-rename ``claudeloop-`` session name for the same task/agent."""
    tid = _tmux_id_fragment(project_id)
    agent = normalize_agent(agent)
    return _sanitize_session_name(f"claudeloop-{agent}-{tid}-{slug}", f"claudeloop-{agent}")


def _session_name_aliases(project_id: str, slug: str) -> set[str]:
    """Every session name this task could use across brands + agents (plus the
    old ``interview`` pane name) - so we can find/clean up its pane regardless of
    which build started it."""
    tid = _tmux_id_fragment(project_id)
    names: set[str] = set()
    for brand in _SESSION_BRANDS:
        for ag in (*SUPPORTED_AGENTS, "interview"):
            names.add(_sanitize_session_name(f"{brand}-{ag}-{tid}-{slug}", f"{brand}-{ag}"))
    return names


def _path_within(child: Path, parent: Path) -> bool:
    """True if *child* resolves to *parent* or a path inside it (works for paths
    that don't exist yet)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _git_clone(repo_url: str, dest: Path, timeout: int = 900) -> tuple[bool, str]:
    """``git clone`` *repo_url* into *dest*. Returns ``(ok, error)``."""
    import shutil

    if not shutil.which("git"):
        return False, "git is not installed on the server"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, str(exc)
    try:
        # ``--`` so a repo URL can never be misread as a git option.
        r = subprocess.run(
            ["git", "clone", "--", repo_url, str(dest)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"git clone timed out after {timeout}s"
    except OSError as exc:
        return False, str(exc)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "git clone failed").strip()[-2000:]
    return True, ""


def _session_name_from_tmux_target(target: str) -> str:
    """``session:0.0`` -> ``session`` (we never put ``:`` in session names)."""
    t = (target or "").strip()
    if ":" in t:
        return t.split(":", 1)[0].strip()
    return t


def _task_meta_tmux_session_names(project_root: Path) -> set[str]:
    out: set[str] = set()
    try:
        root = project_root.resolve()
    except OSError:
        return out
    if not root.is_dir():
        return out
    for meta in list_tasks(root):
        n = _session_name_from_tmux_target(getattr(meta, "tmux_interview_target", "") or "")
        if n:
            out.add(n)
    return out


def _filter_tmux_sessions_for_project(
    sessions: list[dict[str, str]],
    project_id: str,
    project_root: Path | None,
) -> list[dict[str, str]]:
    tid = _tmux_id_fragment(project_id)
    picked: dict[str, dict[str, str]] = {}
    # We accept session-name prefixes for every supported agent plus the
    # legacy "claudeloop-interview-<tid>-..." used before the rename.
    prefixes = tuple(
        f"{brand}-{name}-{tid}-"
        for brand in _SESSION_BRANDS
        for name in (*SUPPORTED_AGENTS, "interview")
    )
    for s in sessions:
        name = str(s.get("name", ""))
        if name and tid and any(name.startswith(p) for p in prefixes):
            picked[name] = s
    if project_root is not None:
        for nm in _task_meta_tmux_session_names(project_root):
            for s in sessions:
                if str(s.get("name", "")) == nm:
                    picked[nm] = s
                    break
    return sorted(picked.values(), key=lambda x: str(x.get("name", "")).lower())


def _launch_root_child_dirs(launch_root: Path, *, limit: int = 200) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    try:
        root = launch_root.resolve()
    except OSError:
        return out
    if not root.is_dir():
        return out
    try:
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if len(out) >= limit:
                break
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            if child.name.startswith("."):
                continue
            try:
                out.append({"name": child.name, "path": str(child.resolve())})
            except OSError:
                continue
    except OSError:
        return out
    return out


def _available_skill_options(
    default_skills: Path,
    project_root: Path | None = None,  # kept for call-site compatibility; unused
    *,
    limit: int = 500,
) -> list[dict[str, str]]:
    """Return selectable skill markdown files for the web UI.

    Scope is intentionally limited to the bundled ``loom/skills``
    directory (plus the configured default skills file). We do **not** scan
    the user's project tree, so unrelated README/PLAN/etc. markdown never
    shows up in the Skills picker - only real skills files are selectable.
    """
    del project_root  # skills come only from the skills directory
    seen: set[Path] = set()
    options: list[dict[str, str]] = []
    skills_root = bundled_skills_path().parent

    def add(path: Path) -> None:
        try:
            p = path.expanduser().resolve()
        except OSError:
            return
        if (
            len(options) >= limit
            or not p.is_file()
            or p.suffix.lower() != ".md"
            or p in seen
        ):
            return
        seen.add(p)
        label = p.name
        try:
            label = str(p.relative_to(skills_root))
        except ValueError:
            pass
        options.append({"label": label, "path": str(p)})

    add(default_skills)
    if skills_root.is_dir():
        for p in sorted(skills_root.rglob("*.md"), key=lambda x: str(x).lower()):
            add(p)
    return options


# --- HTTP response helpers --------------------------------------------------


def _json_bytes(obj: Any, status: int = 200) -> tuple[int, bytes, list[tuple[str, str]]]:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    return status, body, headers


def _text_bytes(
    text: str | bytes,
    status: int = 200,
    content_type: str = "text/plain; charset=utf-8",
) -> tuple[int, bytes, list[tuple[str, str]]]:
    body = text if isinstance(text, bytes) else text.encode("utf-8")
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
    ]
    return status, body, headers


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    n = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(n) if n > 0 else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _safe_static_path(static_root: Path, url_path: str) -> Path | None:
    if not url_path.startswith("/static/"):
        return None
    rel = unquote(url_path[len("/static/") :])
    if not rel or ".." in rel.split("/"):
        return None
    candidate = (static_root / rel).resolve()
    try:
        candidate.relative_to(static_root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


# --- structured agent conversations ---------------------------------------

_CONVERSATION_CACHE_LOCK = threading.Lock()
_CONVERSATION_CACHE: dict[str, tuple[int, int, list[dict[str, Any]]]] = {}
_CONVERSATION_PREVIEW_LIMIT = 4000


def _conversation_redact(text: str) -> str:
    """Keep credentials from being surfaced by the mobile transcript view."""
    value = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+",
        r"\1‹redacted›",
        text,
    )
    value = re.sub(
        r"(?i)((?:token|password|secret|api[_-]?key)[A-Za-z0-9_-]*\s*[=:]\s*)[^\s\"']+",
        r"\1‹redacted›",
        value,
    )
    return re.sub(r"\b[0-9a-fA-F]{40,}\b", "‹redacted›", value)


def _conversation_clip(value: Any, limit: int = _CONVERSATION_PREVIEW_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = str(value)
    text = _conversation_redact(text.strip())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}\n…"


def _conversation_user_text(text: str) -> str:
    """Extract the actual prompt from Cursor's context-wrapped user event."""
    matches = re.findall(r"<user_query>\s*(.*?)\s*</user_query>", text, re.DOTALL)
    if matches:
        return _conversation_clip(matches[-1], 24000)
    value = re.sub(
        r"<(?:system_reminder|open_and_recently_viewed_files|timestamp)>.*?</(?:system_reminder|open_and_recently_viewed_files|timestamp)>",
        "",
        text,
        flags=re.DOTALL,
    )
    return _conversation_clip(value, 24000)


def _conversation_timestamp(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value * 1000 if value < 10_000_000_000 else value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _conversation_tool_summary(name: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return name
    for key in (
        "description",
        "path",
        "file_path",
        "target_file",
        "query",
        "pattern",
        "url",
        "command",
        "prompt",
    ):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            line = _conversation_redact(candidate.strip().splitlines()[0])
            return line[:180] + ("…" if len(line) > 180 else "")
    return name


def _conversation_question_tool(name: str, payload: Any) -> dict[str, Any] | None:
    if name not in {"AskQuestion", "AskUserQuestion"} or not isinstance(payload, dict):
        return None
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return None
    questions: list[dict[str, Any]] = []
    for index, raw_question in enumerate(raw_questions):
        if not isinstance(raw_question, dict):
            continue
        prompt = str(
            raw_question.get("prompt") or raw_question.get("question") or ""
        ).strip()
        raw_options = raw_question.get("options")
        if not prompt or not isinstance(raw_options, list):
            continue
        options: list[dict[str, str]] = []
        for option_index, raw_option in enumerate(raw_options):
            if not isinstance(raw_option, dict):
                continue
            label = str(raw_option.get("label") or "").strip()
            if not label:
                continue
            option_id = str(raw_option.get("id") or option_index + 1)
            options.append(
                {
                    "id": option_id,
                    "label": _conversation_clip(label, 500),
                    "description": _conversation_clip(
                        raw_option.get("description"), 1000
                    ),
                    # Cursor/Claude's terminal prompt accepts the visible answer.
                    "value": _conversation_clip(label, 500),
                }
            )
        if len(options) < 2:
            continue
        questions.append(
            {
                "id": str(raw_question.get("id") or index + 1),
                "header": _conversation_clip(raw_question.get("header"), 120),
                "prompt": _conversation_clip(prompt, 2000),
                "allow_multiple": bool(
                    raw_question.get("allow_multiple")
                    or raw_question.get("multiSelect")
                ),
                "options": options,
            }
        )
    if not questions:
        return None
    return {
        "title": _conversation_clip(payload.get("title"), 160) or "Input needed",
        "source": "transcript",
        "status": "pending",
        "questions": questions,
    }


def _conversation_numbered_question(text: str) -> dict[str, Any] | None:
    """Recognize a final plain-text 1/2/3 choice without parsing normal lists."""
    lowered = text.lower()
    if not (
        "?" in text
        or "？" in text
        or any(
            cue in lowered
            for cue in (
                "choose",
                "select",
                "pick one",
                "which option",
                "reply with",
                "请选择",
                "选择一个",
                "回复数字",
                "选哪",
            )
        )
    ):
        return None
    matches = list(
        re.finditer(
            r"(?m)^\s*(\d{1,2})[\.\)、:：]\s+(.+?)\s*$",
            text,
        )
    )
    if not 2 <= len(matches) <= 8:
        return None
    numbers = [int(match.group(1)) for match in matches]
    if numbers != list(range(1, len(matches) + 1)):
        return None
    options = []
    for match in matches:
        label = re.sub(r"^\*\*(.*?)\*\*$", r"\1", match.group(2).strip())
        options.append(
            {
                "id": match.group(1),
                "label": _conversation_clip(label, 500),
                "description": "",
                "value": match.group(1),
            }
        )
    prompt = text[: matches[0].start()].strip()
    prompt_lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    return {
        "title": "Choose an option",
        "source": "numbered",
        "status": "pending",
        "questions": [
            {
                "id": "choice",
                "header": "",
                "prompt": _conversation_clip(
                    prompt_lines[-1] if prompt_lines else "What should the agent do?",
                    1000,
                ),
                "allow_multiple": False,
                "options": options,
            }
        ],
    }


def _conversation_terminal_question(text: str) -> dict[str, Any] | None:
    """Parse the active Cursor/Claude checkbox prompt from a tmux snapshot."""
    raw_lines = text.splitlines()
    marker_index = next(
        (
            index
            for index, line in enumerate(raw_lines)
            if re.search(r"\bQuestion\s+\d+\s+of\s+\d+\b", line, re.IGNORECASE)
        ),
        None,
    )
    if marker_index is None:
        return None

    marker_match = re.search(
        r"\bQuestion\s+(\d+)\s+of\s+(\d+)\b",
        raw_lines[marker_index],
        re.IGNORECASE,
    )
    if marker_match is None:
        return None

    def clean(line: str) -> str:
        value = re.sub(r"^[\s│┃┆┊╎╏┌└├┬┴┼─━╭╰]+", "", line)
        return re.sub(r"[\s│┃┆┊╎╏─━╮╯]+$", "", value).strip()

    prompt = ""
    options: list[dict[str, Any]] = []
    footer = ""
    for raw_line in raw_lines[marker_index + 1 :]:
        line = clean(raw_line)
        if not line:
            continue
        if re.search(r"(?:Space\s+select|Enter\s+(?:next|submit)|Esc\s+to\s+skip)", line, re.I):
            footer = line
            break
        question_match = re.match(r"\d+[\.\)、:：]\s*(.+)", line)
        if question_match and not prompt:
            prompt = question_match.group(1).strip()
            continue
        option_match = re.match(
            r"(?:[›❯>]\s*)?[\[(]([ xX✓✔●○]?)[\])]\s*(.*)",
            line,
        )
        if option_match:
            label = option_match.group(2).strip()
            focused = bool(re.match(r"[›❯>]\s*", line))
            options.append(
                {
                    "id": str(len(options)),
                    "label": label,
                    "description": "",
                    "value": str(len(options)),
                    "terminal_index": len(options),
                    "selected": option_match.group(1).strip().lower()
                    in {"x", "✓", "✔", "●"},
                    "focused": focused,
                }
            )
            continue
        if options and not re.search(r"[↑↓←→].*(?:option|question)", line, re.I):
            options[-1]["label"] = f"{options[-1]['label']} {line}".strip()

    if not prompt or len(options) < 2 or not footer:
        return None
    title = f"Question {marker_match.group(1)} of {marker_match.group(2)}"
    fingerprint_payload = json.dumps(
        {
            "title": title,
            "prompt": prompt,
            "options": [option["label"] for option in options],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    question_id = str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint_payload))
    return {
        "id": question_id,
        "title": title,
        "source": "terminal",
        "status": "pending",
        "questions": [
            {
                "id": "current",
                "header": "",
                "prompt": _conversation_clip(prompt, 2000),
                "allow_multiple": bool(re.search(r"Space\s+select", footer, re.I)),
                "options": options,
            }
        ],
    }


def _conversation_terminal_answer_keys(
    question: dict[str, Any],
    selected_ids: list[str],
    *,
    submit: bool = True,
) -> list[str]:
    prompts = question.get("questions") or []
    if len(prompts) != 1 or not isinstance(prompts[0], dict):
        return []
    prompt = prompts[0]
    options = prompt.get("options") or []
    if not options:
        return []
    selected = set(selected_ids)
    valid_ids = {str(option.get("id")) for option in options}
    if not selected or not selected.issubset(valid_ids):
        return []
    focused_index = next(
        (
            index
            for index, option in enumerate(options)
            if bool(option.get("focused"))
        ),
        0,
    )
    keys: list[str] = []
    cursor_index = focused_index

    def move_to(index: int) -> None:
        nonlocal cursor_index
        difference = index - cursor_index
        keys.extend(["Down"] * max(0, difference))
        keys.extend(["Up"] * max(0, -difference))
        cursor_index = index

    if bool(prompt.get("allow_multiple")):
        for index, option in enumerate(options):
            currently_selected = bool(option.get("selected"))
            should_select = str(option.get("id")) in selected
            if currently_selected != should_select:
                move_to(index)
                keys.append("Space")
    else:
        selected_id = next(iter(selected))
        selected_index = next(
            index
            for index, option in enumerate(options)
            if str(option.get("id")) == selected_id
        )
        move_to(selected_index)
    if submit:
        keys.append("Enter")
    return keys


def _conversation_block_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        text = value.get("text") or value.get("content")
        if isinstance(text, str):
            return text
    return _conversation_clip(value)


def _cursor_transcript_path(session_id: str, metadata_path: Path) -> Path | None:
    if not _SESSION_ID_RE.match(session_id):
        return None
    cursor_root = Path.home() / ".cursor" / "projects"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    cwd = str(metadata.get("cwd") or "").strip()
    if cwd:
        encoded = cwd.lstrip("/").replace("/", "-")
        candidate = (
            cursor_root
            / encoded
            / "agent-transcripts"
            / session_id
            / f"{session_id}.jsonl"
        )
        if candidate.is_file() and _path_within(candidate, cursor_root):
            return candidate
    try:
        for candidate in cursor_root.glob(
            f"*/agent-transcripts/{session_id}/{session_id}.jsonl"
        ):
            if candidate.is_file() and _path_within(candidate, cursor_root):
                return candidate
    except OSError:
        pass
    return None


def _conversation_transcript_path(
    session: dict[str, Any], agent: str
) -> Path | None:
    session_id = str(session.get("id") or "").strip()
    if not _SESSION_ID_RE.match(session_id):
        return None
    raw_path = str(session.get("path") or "").strip()
    path = Path(raw_path).expanduser() if raw_path else None
    if agent == AGENT_CURSOR and path is not None:
        return _cursor_transcript_path(session_id, path)
    if path is not None and path.is_file() and path.suffix.lower() == ".jsonl":
        return path
    if agent == AGENT_CODEX:
        codex_root = Path.home() / ".codex" / "sessions"
        try:
            for candidate in codex_root.rglob(f"*{session_id}*.jsonl"):
                if candidate.is_file() and _path_within(candidate, codex_root):
                    return candidate
        except OSError:
            pass
    return None


def _parse_conversation_transcript(path: Path, agent: str) -> list[dict[str, Any]]:
    """Normalize Claude/Cursor JSONL into a small Happy-style message protocol."""
    try:
        stat = path.stat()
    except OSError:
        return []
    key = str(path)
    signature = (stat.st_mtime_ns, stat.st_size)
    with _CONVERSATION_CACHE_LOCK:
        cached = _CONVERSATION_CACHE.get(key)
        if cached and cached[:2] == signature:
            return cached[2]

    messages: list[dict[str, Any]] = []
    tools_by_external_id: dict[str, dict[str, Any]] = {}
    questions_by_external_id: dict[str, dict[str, Any]] = {}
    question_messages: list[dict[str, Any]] = []
    cursor_running_tools: list[dict[str, Any]] = []
    session_id = path.stem

    def add_text(kind: str, text: str, line_number: int, index: int, created_at: int | None) -> None:
        normalized = (
            _conversation_user_text(text)
            if kind == "user"
            else _conversation_clip(text, 24000)
        )
        if not normalized:
            return
        if kind == "user":
            for question_message in question_messages:
                question = question_message.get("question") or {}
                if question.get("status") == "pending":
                    question["status"] = "answered"
                    question["answer"] = normalized
        messages.append(
            {
                "id": f"{session_id}:{line_number}:{index}",
                "kind": kind,
                "text": normalized,
                "created_at": created_at,
            }
        )

    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(row, dict):
                    continue

                if agent == AGENT_CURSOR and cursor_running_tools:
                    for tool_message in cursor_running_tools:
                        tool_message["tool"]["status"] = "completed"
                    cursor_running_tools = []

                role = str(row.get("role") or row.get("type") or "")
                message = row.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                created_at = _conversation_timestamp(row.get("timestamp"))
                if isinstance(content, str):
                    content = [{"type": "text", "text": content}]
                if not isinstance(content, list):
                    if agent == AGENT_CURSOR and row.get("type") == "turn_ended":
                        for tool_message in cursor_running_tools:
                            tool_message["tool"]["status"] = "completed"
                        cursor_running_tools = []
                    continue

                for index, block in enumerate(content):
                    if not isinstance(block, dict):
                        continue
                    block_type = str(block.get("type") or "")
                    if role == "user" and block_type == "text":
                        add_text("user", str(block.get("text") or ""), line_number, index, created_at)
                        continue
                    if role == "assistant" and block_type == "text":
                        add_text(
                            "assistant",
                            str(block.get("text") or ""),
                            line_number,
                            index,
                            created_at,
                        )
                        continue
                    if role == "assistant" and block_type == "tool_use":
                        name = str(block.get("name") or "Tool")
                        payload = block.get("input")
                        external_id = str(block.get("id") or f"{line_number}:{index}")
                        question = _conversation_question_tool(name, payload)
                        if question is not None:
                            question_message = {
                                "id": f"{session_id}:{line_number}:{index}",
                                "kind": "question",
                                "created_at": created_at,
                                "question": question,
                            }
                            messages.append(question_message)
                            question_messages.append(question_message)
                            questions_by_external_id[external_id] = question_message
                            continue
                        tool_message = {
                            "id": f"{session_id}:{line_number}:{index}",
                            "kind": "tool",
                            "created_at": created_at,
                            "tool": {
                                "name": name,
                                "summary": _conversation_tool_summary(name, payload),
                                "status": "running",
                                "input": _conversation_clip(payload),
                                "output": "",
                            },
                        }
                        messages.append(tool_message)
                        tools_by_external_id[external_id] = tool_message
                        if agent == AGENT_CURSOR:
                            cursor_running_tools.append(tool_message)
                        continue
                    if role == "user" and block_type == "tool_result":
                        external_id = str(block.get("tool_use_id") or "")
                        question_message = questions_by_external_id.get(external_id)
                        if question_message is not None:
                            question = question_message["question"]
                            question["status"] = (
                                "error" if bool(block.get("is_error")) else "answered"
                            )
                            question["answer"] = _conversation_clip(
                                _conversation_block_text(block.get("content"))
                            )
                            continue
                        tool_message = tools_by_external_id.get(external_id)
                        if tool_message is not None:
                            tool_message["tool"]["status"] = (
                                "error" if bool(block.get("is_error")) else "completed"
                            )
                            tool_message["tool"]["output"] = _conversation_clip(
                                _conversation_block_text(block.get("content"))
                            )
    except OSError:
        return []

    for message_index, question_message in enumerate(messages):
        if question_message.get("kind") != "question":
            continue
        question = question_message.get("question") or {}
        if question.get("status") != "pending":
            continue
        if any(
            later.get("kind") in {"user", "assistant"}
            for later in messages[message_index + 1 :]
        ):
            question["status"] = "answered"

    if messages and messages[-1].get("kind") == "assistant":
        question = _conversation_numbered_question(str(messages[-1].get("text") or ""))
        if question is not None:
            messages.append(
                {
                    "id": f"{messages[-1]['id']}:choices",
                    "kind": "question",
                    "created_at": messages[-1].get("created_at"),
                    "question": question,
                }
            )

    with _CONVERSATION_CACHE_LOCK:
        _CONVERSATION_CACHE[key] = (*signature, messages)
        if len(_CONVERSATION_CACHE) > 64:
            oldest = next(iter(_CONVERSATION_CACHE))
            if oldest != key:
                _CONVERSATION_CACHE.pop(oldest, None)
    return messages


# --- Kernel Lab (vendored kernel hub) ---------------------------------------
# Loom drives kernel-optimization runs by shelling out to the bundled
# kernel_hub/scaffold/agent_runner/rud_kernel.py helper (JSON in/out). Run
# records and artifacts are stored under
# <root>/.RUD/<task>/kernel/runs/<id>/.

_KERNEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _kernel_runs_dir(root: Path) -> Path:
    """Legacy project-level run directory (read/migrate only)."""
    return root / ".RUD" / "kernel-runs"


def _kernel_task_dir(root: Path, slug: str) -> Path:
    return task_root(root, slug) / "kernel"


def _kernel_contract_dir(root: Path, slug: str) -> Path:
    return _kernel_task_dir(root, slug) / "contract"


def _kernel_task_runs_dir(root: Path, slug: str) -> Path:
    return _kernel_task_dir(root, slug) / "runs"


def _kernel_task_run_dir(root: Path, slug: str, run_uid: str) -> Path:
    return _kernel_task_runs_dir(root, slug) / run_uid


def _kernel_task_agent_dir(root: Path, slug: str, run_uid: str, agent_index: str) -> Path:
    return _kernel_task_run_dir(root, slug, run_uid) / "agents" / f"agent-{agent_index}"


def _kernel_winners_dir(root: Path, slug: str) -> Path:
    return _kernel_task_dir(root, slug) / "winners"


def _ensure_task_contract_wrapper(root: Path, slug: str, plugin: str) -> Path | None:
    contract_dir = _kernel_contract_dir(root, slug)
    contract_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(contract_dir.glob("*.py"))
    if existing:
        return contract_dir / "plugin.py" if (contract_dir / "plugin.py").is_file() else existing[0]
    if not plugin:
        return None
    wrapper = contract_dir / "plugin.py"
    wrapper.write_text(
        f'"""Task-local contract wrapper for {plugin}."""\n'
        "from kernel_evaluator.services.plugins import (\n"
        "    KernelEvalPlugin, _CONTRACT_FACTORIES, _REFERENCE_FACTORIES,\n"
        ")\n"
        f'PLUGIN_NAME = "{plugin}"\n'
        "PLUGIN = KernelEvalPlugin(\n"
        "    name=PLUGIN_NAME,\n"
        "    reference_factory=_REFERENCE_FACTORIES[PLUGIN_NAME],\n"
        "    contract_factory=_CONTRACT_FACTORIES.get(PLUGIN_NAME),\n"
        ")\n",
        encoding="utf-8",
    )
    return wrapper


def _task_contract_plugins(root: Path, slug: str) -> list[str]:
    names: list[str] = []
    for path in sorted(_kernel_contract_dir(root, slug).glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = re.search(r'^PLUGIN_NAME\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def _ensure_kernel_task_layout(root: Path, slug: str) -> Path:
    base = _kernel_task_dir(root, slug)
    for directory in (
        base,
        _kernel_contract_dir(root, slug),
        _kernel_task_runs_dir(root, slug),
        _kernel_winners_dir(root, slug),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    # Migrate task docs from the pre-layout task root.
    for name in ("INSTRUCTION.md", "EVALUATION.md", "WIKI.md"):
        old = task_root(root, slug) / name
        new = base / name
        if old.is_file() and not new.exists():
            try:
                old.replace(new)
            except OSError:
                shutil.copy2(old, new)
                old.unlink(missing_ok=True)
    return base


def _kernel_record_path(root: Path, slug: str, run_uid: str) -> Path:
    return _kernel_task_run_dir(root, slug, run_uid) / "run.json"


def _kernel_write_record(root: Path, rec: dict[str, Any]) -> None:
    slug = str(rec.get("slug") or "").strip()
    if slug:
        _ensure_kernel_task_layout(root, slug)
        run_dir = _kernel_task_run_dir(root, slug, str(rec["id"]))
        run_dir.mkdir(parents=True, exist_ok=True)
        dest = run_dir / "run.json"
    else:
        # Compatibility for old/orphan records with no task ownership.
        d = _kernel_runs_dir(root)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{rec['id']}.json"
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    tmp.replace(dest)


def _kernel_read_record(root: Path, run_uid: str) -> dict[str, Any] | None:
    candidates = list((root / ".RUD").glob(f"*/kernel/runs/{run_uid}/run.json"))
    candidates.append(_kernel_runs_dir(root) / f"{run_uid}.json")
    for f in candidates:
        if not f.is_file():
            continue
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _kernel_delete_record(root: Path, run_uid: str) -> bool:
    """Remove a run's record JSON (and its build log) from disk. Used by the UI
    to clear finished/errored runs. Returns True if the JSON existed."""
    rec = _kernel_read_record(root, run_uid)
    existed = False
    if rec and rec.get("slug"):
        run_dir = _kernel_task_run_dir(root, str(rec["slug"]), run_uid)
        if run_dir.is_dir():
            shutil.rmtree(run_dir, ignore_errors=True)
            existed = True
    d = _kernel_runs_dir(root)
    for f in (d / f"{run_uid}.json", d / f"{run_uid}.json.tmp", d / f"{run_uid}.log"):
        try:
            if f.is_file():
                if f.suffix == ".json":
                    existed = True
                f.unlink()
        except OSError:
            pass
    return existed


def _kernel_delete_task_records(root: Path, slug: str) -> dict[str, Any]:
    """Stop and remove every kernel-run record owned by a deleted task.

    Run records live at project scope (``.RUD/kernel-runs``), not inside the
    task directory. Without this cleanup, recreating a task with the same slug
    resurrects the deleted task's runs. Active runs are stopped best-effort
    first; local records/logs are removed even when their remote cluster is
    temporarily unreachable.
    """
    records = _kernel_list_records(root, slug)
    stopped = 0
    stop_errors: list[str] = []
    deleted = 0
    for rec in records:
        run_uid = str(rec.get("id") or "").strip()
        if not run_uid:
            continue
        if rec.get("state") in ("launching", "running", "resolving") and rec.get("run_id"):
            ok, result = _run_kernel_helper(
                root,
                ["stop", "--run-id", str(rec["run_id"])],
                timeout=90,
                cluster=_kernel_record_cluster(rec),
            )
            if ok:
                stopped += 1
            else:
                stop_errors.append(
                    f"{run_uid}: {(result or {}).get('error', 'stop failed')}"
                )
        if _kernel_delete_record(root, run_uid):
            deleted += 1
    return {
        "records_deleted": deleted,
        "active_runs_stopped": stopped,
        "stop_errors": stop_errors,
    }


def _migrate_legacy_kernel_records(root: Path, slug: str | None = None) -> int:
    """Move old project-level records/logs into their owning task tree."""
    legacy = _kernel_runs_dir(root)
    if not legacy.is_dir():
        return 0
    moved = 0
    for record_file in legacy.glob("*.json"):
        try:
            rec = json.loads(record_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        owner = str(rec.get("slug") or rec.get("task_slug") or "").strip()
        if not owner or (slug and owner != slug) or not task_root(root, owner).is_dir():
            continue
        rec["slug"] = owner
        _ensure_kernel_task_layout(root, owner)
        contract = _ensure_task_contract_wrapper(
            root, owner, str(rec.get("plugin") or (rec.get("config") or {}).get("plugin") or "")
        )
        if contract is not None:
            rec["contract_file"] = str(contract)
        run_uid = str(rec.get("id") or record_file.stem)
        judge = rec.get("judge") or {}
        exported = Path(str(judge.get("export_path") or ""))
        job_id = str(judge.get("job_id") or "")
        if judge.get("verdict") == "pass" and exported.is_file() and job_id:
            winner_dir = _kernel_winners_dir(root, owner) / job_id
            winner_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(exported, winner_dir / "kernel.py")
            (winner_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "run_record": run_uid,
                        "job_id": job_id,
                        "plugin": rec.get("plugin") or (rec.get("config") or {}).get("plugin"),
                        "speedup": judge.get("speedup"),
                        "promoted_to": str(exported),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        run_dir = _kernel_task_run_dir(root, owner, run_uid)
        run_dir.mkdir(parents=True, exist_ok=True)
        _kernel_write_record(root, rec)
        old_log = legacy / f"{run_uid}.log"
        if old_log.is_file():
            try:
                old_log.replace(run_dir / "launcher.log")
            except OSError:
                shutil.copy2(old_log, run_dir / "launcher.log")
                old_log.unlink(missing_ok=True)
        record_file.unlink(missing_ok=True)
        (legacy / f"{run_uid}.json.tmp").unlink(missing_ok=True)
        moved += 1
    return moved


def _sweep_stale_kernel_runs(roots: list[Path]) -> int:
    """Mark any ``launching``/``resolving`` run records as ``error`` across the
    given project roots. Called at server startup: a launch/prepare's worker
    thread can't survive a restart, so such records are definitionally stale."""
    swept = 0
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            key = str(root)
        if key in seen:
            continue
        seen.add(key)
        _migrate_legacy_kernel_records(root)
        files = list((root / ".RUD").glob("*/kernel/runs/*/run.json"))
        files += list(_kernel_runs_dir(root).glob("*.json"))
        for f in files:
            try:
                rec = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if rec.get("state") in ("launching", "resolving"):
                rec["state"] = "error"
                rec["error"] = "launch interrupted by a server restart (stale)"
                try:
                    f.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
                    swept += 1
                except OSError:
                    pass
    return swept


def _kernel_list_records(root: Path, slug: str | None = None) -> list[dict[str, Any]]:
    _migrate_legacy_kernel_records(root, slug)
    recs: list[dict[str, Any]] = []
    if slug:
        files = list(_kernel_task_runs_dir(root, slug).glob("*/run.json"))
    else:
        files = list((root / ".RUD").glob("*/kernel/runs/*/run.json"))
        files += list(_kernel_runs_dir(root).glob("*.json"))
    for f in files:
        try:
            rec = json.loads(f.read_text())
            if rec.get("slug") and not rec.get("submissions_seen") and rec.get("status"):
                _kernel_merge_submissions(root, rec, rec["status"])
                rec = _kernel_read_record(root, str(rec.get("id"))) or rec
            recs.append(rec)
        except (json.JSONDecodeError, OSError):
            continue
    if slug:
        # Strict per-task scoping: a task shows ONLY its own runs (matched by the
        # Loom task slug). Older runs created before per-task scoping have no slug
        # and used to be shown under *every* task — that made separate kernel
        # tasks appear to "share" the same runs/leaderboards. They no longer leak
        # across tasks; such orphans simply don't appear under any task (the JSON
        # files remain on disk and can be cleaned up or re-attributed manually).
        scoped: list[dict[str, Any]] = []
        for r in recs:
            rslug = str(r.get("slug") or r.get("task_slug") or "").strip()
            if rslug == slug:
                scoped.append(r)
        recs = scoped
    recs.sort(key=lambda r: r.get("created_at", 0.0), reverse=True)
    return recs


def _kernel_helper_cmd(script_name: str) -> tuple[list[str] | None, str]:
    """Resolve how to invoke the bundled kernel helper, returning
    ``(base_cmd, error)``.

    The kernel stack lives under ``loom/kernel_hub/scaffold/agent_runner/``;
    the helper's own ``REPO_ROOT`` resolves to ``kernel_hub/`` so
    docker-compose and the kernel_evaluator service are found right beside it.
    It is not shipped in the wheel, so an installed Loom needs
    ``LOOM_KERNEL_HUB_DIR`` pointed at a source checkout.
    """
    bundled = kernel_hub_dir() / "scaffold" / "agent_runner" / script_name
    if bundled.is_file():
        return [sys.executable, str(bundled)], ""
    return None, (
        f"Kernel Lab helper '{script_name}' not found at {bundled}. The Kernel "
        f"Hub bundle is not shipped in the Loom wheel; clone "
        f"https://github.com/FutureMLS-Lab/Loom and set {KERNEL_HUB_ENV}=<checkout>/loom/kernel_hub"
    )


# --- Kernel cluster profiles ---
# The kernel stack can target different GPU clusters. Machine-specific profile
# files live outside the repository under ~/.config/loom/kernel-clusters/*.env
# (or LOOM_KERNEL_PROFILES_DIR), and are loaded by rud_kernel through
# LOOM_KERNEL_ENV_FILE. Each run records only the opaque profile name so
# status/log/stop route correctly without committing infrastructure topology.


def _kernel_cluster_profiles() -> dict[str, Path]:
    out: dict[str, Path] = {}
    profile_dir = Path(
        os.environ.get(
            "LOOM_KERNEL_PROFILES_DIR",
            str(Path.home() / ".config" / "loom" / "kernel-clusters"),
        )
    ).expanduser()
    try:
        for f in sorted(profile_dir.glob("*.env")):
            name = f.stem
            if name and f.is_file():
                out[name] = f
    except OSError:
        pass
    return out


def _kernel_cluster_env(cluster: str) -> dict[str, str] | None:
    """Subprocess env for a cluster profile ('' = default env)."""
    cluster = (cluster or "").strip()
    if not cluster:
        return None
    profile = _kernel_cluster_profiles().get(cluster)
    if profile is None:
        return None
    return {**os.environ, "LOOM_KERNEL_ENV_FILE": str(profile)}


def _kernel_record_cluster(rec: dict[str, Any] | None) -> str:
    cfg = (rec or {}).get("config") or {}
    return str(cfg.get("cluster") or "").strip()


# Short TTL cache for `service-status` so frequent polls (and concurrent
# browser tabs) don't each spawn a subprocess + network health-check.
_KERNEL_SERVICE_CACHE: dict[str, tuple[float, bool, dict[str, Any]]] = {}
_KERNEL_SERVICE_TTL = 6.0
_kernel_service_lock = threading.Lock()


def _kernel_service_status_cached(root: Path, cluster: str = "") -> tuple[bool, dict[str, Any]]:
    key = f"{root}::{cluster}"
    now = time.time()
    with _kernel_service_lock:
        hit = _KERNEL_SERVICE_CACHE.get(key)
        if hit and (now - hit[0]) < _KERNEL_SERVICE_TTL:
            return hit[1], hit[2]
    ok, data = _run_kernel_helper(root, ["service-status"], timeout=20, cluster=cluster)
    with _kernel_service_lock:
        _KERNEL_SERVICE_CACHE[key] = (now, ok, data)
    return ok, data


def _run_kernel_helper(
    root: Path, helper_args: list[str], timeout: int = 600, cluster: str = ""
) -> tuple[bool, dict[str, Any]]:
    """Invoke rud_kernel (in-project script or pip module) and parse its JSON."""
    base, err = _kernel_helper_cmd("rud_kernel.py")
    if base is None:
        return False, {"ok": False, "error": err}
    try:
        proc = subprocess.run(
            [*base, *helper_args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_kernel_cluster_env(cluster),
        )
    except subprocess.TimeoutExpired:
        return False, {"ok": False, "error": f"kernel helper timed out after {timeout}s"}
    out = (proc.stdout or "").strip()
    last = out.splitlines()[-1] if out else ""
    try:
        data = json.loads(last)
    except json.JSONDecodeError:
        return False, {
            "ok": False,
            "error": "kernel helper returned non-JSON",
            "stdout": out[-1000:],
            "stderr": (proc.stderr or "")[-1000:],
        }
    return bool(data.get("ok")), data


def _shape_to_str(shape: Any) -> str:
    return shape if isinstance(shape, str) else json.dumps(shape)


def _kernel_run_log_path(root: Path, run_uid: str) -> Path:
    rec = _kernel_read_record(root, run_uid)
    if rec and rec.get("slug"):
        return _kernel_task_run_dir(root, str(rec["slug"]), run_uid) / "launcher.log"
    return _kernel_runs_dir(root) / f"{run_uid}.log"


KERNEL_WIKI = "kernel/WIKI.md"


def _initialize_kernel_run_artifacts(root: Path, rec: dict[str, Any]) -> Path | None:
    slug = str(rec.get("slug") or "").strip()
    run_uid = str(rec.get("id") or "").strip()
    if not slug or not run_uid:
        return None
    run_dir = _kernel_task_run_dir(root, slug, run_uid)
    run_dir.mkdir(parents=True, exist_ok=True)
    source_wiki = task_root(root, slug) / KERNEL_WIKI
    run_wiki = run_dir / "WIKI.md"
    if source_wiki.is_file() and not run_wiki.exists():
        shutil.copy2(source_wiki, run_wiki)
    count = int((rec.get("config") or {}).get("n_agents") or 0)
    for index in range(1, count + 1):
        agent_dir = _kernel_task_agent_dir(root, slug, run_uid, str(index))
        (agent_dir / "attempts").mkdir(parents=True, exist_ok=True)
    return run_dir


def _kernel_mirror_submission(
    root: Path,
    rec: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    slug = str(rec.get("slug") or "").strip()
    run_uid = str(rec.get("id") or "").strip()
    job_id = str(item.get("job_id") or "").strip()
    if not slug or not run_uid or not job_id:
        return item
    agent_index = str(item.get("agent_index") if item.get("agent_index") is not None else "unknown")
    agent_dir = _kernel_task_agent_dir(root, slug, run_uid, agent_index)
    attempts_dir = agent_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    attempt_no = item.get("n") or job_id[:8]
    result_path = attempts_dir / f"{attempt_no}-{job_id}.json"
    source_ext = ".py" if (rec.get("config") or {}).get("target") in ("cutedsl", "triton") else ".cu"
    source_path = attempts_dir / f"{attempt_no}-{job_id}{source_ext}"
    try:
        result_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        item["local_result_path"] = str(result_path)
    except OSError:
        pass
    if not source_path.is_file():
        ok, source_data = _run_kernel_helper(
            root,
            ["job-source", "--job-id", job_id],
            timeout=30,
            cluster=_kernel_record_cluster(rec),
        )
        source = str((source_data or {}).get("source") or "")
        if ok and source:
            try:
                source_path.write_text(source.rstrip() + "\n", encoding="utf-8")
            except OSError:
                pass
    if source_path.is_file():
        item["local_source_path"] = str(source_path)
        latest = agent_dir / f"latest{source_ext}"
        try:
            shutil.copy2(source_path, latest)
            item["local_latest_path"] = str(latest)
        except OSError:
            pass
    return item


def _kernel_mirror_agent_log(
    root: Path,
    rec: dict[str, Any],
    agent_index: str,
    text: str,
) -> str:
    slug = str(rec.get("slug") or "").strip()
    run_uid = str(rec.get("id") or "").strip()
    if not slug or not run_uid:
        return ""
    agent_dir = _kernel_task_agent_dir(root, slug, run_uid, agent_index)
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "agent.log"
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        return ""
    return str(path)


def _mirror_kernel_agent_logs(root: Path, rec: dict[str, Any], agents: list[dict[str, Any]]) -> None:
    for agent in agents:
        index = str(agent.get("index") or "").strip()
        if not index.isdigit():
            continue
        ok, data = _run_kernel_helper(
            root,
            [
                "agent-log",
                "--run-id",
                str(rec.get("run_id") or ""),
                "--agent",
                index,
                "--tail",
                "2000",
            ],
            timeout=40,
            cluster=_kernel_record_cluster(rec),
        )
        if ok and (data or {}).get("log"):
            _kernel_mirror_agent_log(root, rec, index, str(data["log"]))


def _maybe_mirror_kernel_agent_logs(
    root: Path, rec: dict[str, Any], status: dict[str, Any]
) -> None:
    now = time.time()
    if now - float(rec.get("logs_mirrored_at") or 0) < 30:
        return
    rec["logs_mirrored_at"] = now
    _kernel_write_record(root, rec)
    threading.Thread(
        target=_mirror_kernel_agent_logs,
        args=(root, dict(rec), list(status.get("agents") or [])),
        daemon=True,
    ).start()


def _kernel_merge_submissions(root: Path, rec: dict[str, Any], status: dict[str, Any]) -> None:
    """Merge the submissions the evaluator currently remembers into the run
    record on disk, so the per-attempt history survives the evaluator's
    in-memory TTL/restarts. Attempt numbers are assigned once (first seen) and
    stay stable. Mutates ``status['submissions']`` to the merged view."""
    by_id: dict[str, dict[str, Any]] = {
        s.get("job_id"): dict(s)
        for s in rec.get("submissions_seen") or []
        if s.get("job_id")
    }
    changed = False
    for s in status.get("submissions") or []:
        jid = s.get("job_id")
        if not jid:
            continue
        incoming = dict(s)
        if jid in by_id:
            incoming["n"] = by_id[jid].get("n")
            if by_id[jid] != incoming:
                by_id[jid] = incoming
                changed = True
        else:
            incoming["n"] = len(by_id) + 1
            by_id[jid] = incoming
            changed = True
    # Correct kernels persist in the DB-backed archive after in-memory jobs
    # expire. Merge them too so task-local history remains complete.
    for archived in status.get("archive") or []:
        jid = archived.get("job_id")
        if not jid or jid in by_id:
            continue
        by_id[jid] = {
            "n": len(by_id) + 1,
            "job_id": jid,
            "agent_index": archived.get("agent_index"),
            "state": "completed",
            "correct": True,
            "speedup": archived.get("speedup"),
            "candidate_us": archived.get("kernel_us"),
            "baseline_us": archived.get("baseline_us"),
            "error": None,
            "achieved_at": archived.get("achieved_at"),
        }
        changed = True
    merged = sorted(by_id.values(), key=lambda x: x.get("n") or 0)
    for item in merged:
        _kernel_mirror_submission(root, rec, item)
    slug = str(rec.get("slug") or "").strip()
    run_dir = _initialize_kernel_run_artifacts(root, rec)
    if run_dir is not None:
        rec["artifact_root"] = str(run_dir)
        for agent in status.get("agents") or []:
            index = str(agent.get("index") or "unknown")
            agent["local_dir"] = str(
                _kernel_task_agent_dir(root, slug, str(rec.get("id")), index)
            )
    # Mirror terminal evaluator outcomes into the task's public WIKI.md. This
    # is the host-side durable knowledge base; workers also share a run-local
    # WIKI.md on the cluster, updated directly by bench-poll.
    plan_seen = set(rec.get("plan_submission_ids") or [])
    plan_path = task_root(root, slug) / KERNEL_WIKI if slug else None
    plan_blocks: list[str] = []
    for item in merged:
        jid = str(item.get("job_id") or "")
        state = str(item.get("state") or "")
        if not jid or jid in plan_seen:
            continue
        if state != "completed" and not state.endswith("_failed"):
            continue
        n = item.get("n") or "?"
        agent = item.get("agent_index")
        correct = item.get("correct")
        speedup = item.get("speedup")
        candidate = item.get("candidate_us")
        baseline = item.get("baseline_us")
        error = str(item.get("error") or "").strip()
        lines = [
            "",
            f"<!-- kernel-submission:{jid} -->",
            f"### Kernel submission #{n} — agent {agent if agent is not None else '?'}",
            f"- Job: `{jid}`",
            f"- State: `{state}`",
        ]
        if correct is not None:
            lines.append(f"- Correct: `{bool(correct)}`")
        if isinstance(speedup, (int, float)):
            lines.append(
                f"- Performance: `{speedup:.4f}×`"
                + (
                    f" ({candidate:.2f}µs vs {baseline:.2f}µs baseline)"
                    if isinstance(candidate, (int, float)) and isinstance(baseline, (int, float))
                    else ""
                )
            )
        if error:
            lines += ["- Evaluator issue:", "```text", error[:3000], "```"]
        if state.endswith("_failed"):
            lines.append("- Next action: resolve the evaluator error before changing optimization strategy.")
        elif correct is False:
            lines.append("- Next action: fix the numerical/ABI mismatch and preserve this attempt's lessons.")
        elif isinstance(speedup, (int, float)) and speedup < 1:
            lines.append("- Next action: correctness passes; preserve it while reducing latency.")
        plan_blocks.append("\n".join(lines))
        plan_seen.add(jid)
        changed = True
    if plan_blocks and plan_path is not None:
        try:
            existing = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else "# Plan\n"
            heading = (
                "\n\n## Kernel evaluator knowledge"
                if "## Kernel evaluator knowledge" not in existing
                else ""
            )
            plan_path.write_text(
                existing.rstrip() + heading + "\n" + "\n".join(plan_blocks) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    if plan_seen:
        rec["plan_submission_ids"] = sorted(plan_seen)
    if changed:
        rec["submissions_seen"] = merged
        _kernel_write_record(root, rec)
    if merged:
        status["submissions"] = merged
    _maybe_mirror_kernel_agent_logs(root, rec, status)


def _run_kernel_launch_streaming(
    root: Path, run_uid: str, helper_args: list[str], timeout: int = 2400,
    cluster: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Run the launch helper, streaming its progress (docker build, agent
    bring-up, …) to ``<run_uid>.log`` live so the web UI can tail it. The
    helper prints its final single-line JSON result to stdout (captured);
    everything else (the build log) goes to stderr → the log file."""
    base, err = _kernel_helper_cmd("rud_kernel.py")
    if base is None:
        return False, {"ok": False, "error": err}
    log_path = _kernel_run_log_path(root, run_uid)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = ""
    try:
        with open(log_path, "w", encoding="utf-8") as lf:
            lf.write(f"$ {' '.join(base + helper_args)}\n")
            lf.write(f"cluster: {cluster or 'default'}\n\n")
            lf.flush()
            proc = subprocess.Popen(
                [*base, *helper_args],
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=lf,
                text=True,
                env=_kernel_cluster_env(cluster),
            )
            try:
                out, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
                out = (out or "") + f"\n[helper timed out after {timeout}s]"
    except OSError as exc:
        return False, {"ok": False, "error": str(exc)}
    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write("\n" + (out or ""))
    except OSError:
        pass
    data: dict[str, Any] | None = None
    for line in reversed((out or "").splitlines()):
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                data = json.loads(s)
                break
            except json.JSONDecodeError:
                continue
    if data is None:
        return False, {"ok": False, "error": "launch produced no result (see build log)"}
    return bool(data.get("ok")), data


# --- Kernel task docs: INSTRUCTION.md (worker brief) + EVALUATION.md (judge
# criteria), generated from the kernel interview and kept as editable files in
# the task dir. INSTRUCTION.md is shipped into every agent workdir at launch;
# EVALUATION.md drives the judge agent that reviews the winning kernel source
# against the task intent alongside the hard eval-service results.


def _kernel_doc_path(root: Path, slug: str, name: str) -> Path:
    return _kernel_task_dir(root, slug) / name


def _seed_kernel_wiki(root: Path, slug: str, spec: dict[str, Any], plugin: str) -> None:
    """Create the durable task-level knowledge ledger for a kernel task.

    Preserve an existing user/agent-authored wiki; otherwise seed the shared
    contract, CUDA/PTX notes, acceptance gates, and evaluator ledger.
    """
    path = task_root(root, slug) / KERNEL_WIKI
    existing = ""
    try:
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        pass
    if existing:
        return
    target = spec.get("target_speedup")
    target_text = f"{float(target):.2f}×" if isinstance(target, (int, float)) else "the configured target"
    content = f"""# Kernel Knowledge Base

## Goal
Build and validate `{plugin}` on `{spec.get('cluster') or 'default'}` / `{spec.get('target') or 'unknown'}`.

## Contract
- Source/reference: {spec.get('source') or '(described in INSTRUCTION.md)'}
- Requested precision: `{spec.get('dtype') or 'unspecified'}`
- Shape: `{json.dumps(spec.get('shape') or {}, sort_keys=True)}`
- Worker brief: `INSTRUCTION.md`
- Evaluator rubric: `EVALUATION.md`

## CUDA / PTX field notes
- CUDA/CuTe/Triton source is lowered through PTX to a GPU binary; always verify the actual target architecture (for example `sm_90a` or `sm_100`).
- PTX is an intermediate ISA, while `ptxas` produces SASS/cubin. Register count, shared memory, spills, occupancy, and memory traffic decide whether a mathematically faster kernel is actually faster.
- Use evaluator artifacts (`ptx`, `cuobjdump`, Nsight summaries) to confirm tensor-core instructions and catch accidental scalar/fallback paths.
- Timed launch code must be CUDA-graph safe: no `.cpu()`, `.item()`, host synchronization, JIT compilation, or data-dependent host control flow.
- For NVFP4 on SM100, verify e2m1 operands, per-block scale-factor layout, tcgen05/block-scaled MMA use, fp32 accumulation, and that both QK and PV execute.
- Correctness comes first, but a correct diagnostic probe is not a valid winner if it skips required work; EVALUATION.md is authoritative.

## Acceptance
- [ ] Evaluator reports `correct=True`.
- [ ] Speedup reaches {target_text}.
- [ ] Evaluator judge passes the source-level rubric.

## Next steps
- [ ] Launch workers.
- [ ] Read the shared attempt log before each new strategy.
- [ ] Preserve correctness while resolving the latest evaluator issue.

## Kernel evaluator knowledge
Every submission, hard result, error, diagnosis, and judge verdict is appended here.
"""
    try:
        path.write_text(content, encoding="utf-8")
        legacy_plan = task_root(root, slug) / PLAN
        if legacy_plan.is_file():
            legacy_text = legacy_plan.read_text(encoding="utf-8", errors="replace")
            if "How will we know it's done?" in legacy_text:
                legacy_plan.unlink()
    except OSError:
        pass


def _generate_kernel_docs(
    root: Path, slug: str, spec: dict[str, Any], messages: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Generate INSTRUCTION.md + EVALUATION.md from the interview (host claude).
    Existing files are kept (the user may have edited them)."""
    _ensure_kernel_task_layout(root, slug)
    ipath = _kernel_doc_path(root, slug, "INSTRUCTION.md")
    epath = _kernel_doc_path(root, slug, "EVALUATION.md")
    if ipath.is_file() and epath.is_file():
        return {"ok": True, "generated": False,
                "instruction": str(ipath), "evaluation": str(epath)}
    convo = "\n".join(
        f"[{m.get('role', '?')}] {m.get('content', '')}" for m in (messages or [])
    )[:12000]
    prompt = (
        "You are preparing a GPU-kernel optimization task for autonomous worker "
        "agents and for a judge agent, based on a user interview.\n\n"
        f"Interview transcript:\n{convo or '(none)'}\n\n"
        f"Final task spec (JSON):\n{json.dumps(spec, ensure_ascii=False)}\n\n"
        "Write TWO markdown documents:\n"
        "1. INSTRUCTION.md — the worker agents' task brief: what kernel to write "
        "(operation, dtype/precision strategy, hardware target), what the ABI/"
        "reference is (and that correctness is judged against it), what counts as "
        "done, and explicit anti-goals (e.g. reimplementing the reference in the "
        "reference's own precision instead of the requested one does NOT count). "
        "Be concrete and terse; the agents also get the eval-service usage docs, "
        "so do not explain bench tooling.\n"
        "2. EVALUATION.md — the judge's rubric: given the submitted kernel SOURCE "
        "plus the hard results (correct=?, speedup vs reference baseline), state "
        "the checks that decide PASS or FAIL. Include source-level checks that "
        "hard metrics cannot see (e.g. does the kernel actually use the requested "
        "precision/instructions internally, not just pass the tolerance check).\n\n"
        "Reply with exactly this format:\n"
        "===INSTRUCTION.md===\n<content>\n===EVALUATION.md===\n<content>\n"
    )
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions",
           "--model", agent_default_model(AGENT_CLAUDE)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"ok": False, "error": f"doc generation failed: {exc}"}
    text = (proc.stdout or "").strip()
    m = re.search(r"===INSTRUCTION\.md===\s*(.*?)\s*===EVALUATION\.md===\s*(.*)", text, re.DOTALL)
    if not m:
        return {"ok": False, "error": "doc generation returned unexpected format",
                "stdout": text[-800:]}
    try:
        if not ipath.is_file():
            ipath.write_text(m.group(1).strip() + "\n", encoding="utf-8")
        if not epath.is_file():
            epath.write_text(m.group(2).strip() + "\n", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "generated": True, "instruction": str(ipath), "evaluation": str(epath)}


_JUDGE_FALLBACK_RUBRIC = (
    "No EVALUATION.md was provided. Judge on: (1) does the kernel plausibly "
    "implement the task named by the run/task slug (including any precision/"
    "hardware requirement implied by its name), rather than trivially wrapping "
    "or re-implementing the reference; (2) are the hard results acceptable "
    "(correct=True and a credible latency)."
)


def _judge_kernel_candidate(
    rubric: str, metrics: dict[str, Any], source: str
) -> dict[str, Any]:
    """One source-level judge call for one hard-correct candidate."""
    prompt = (
        "You are the judge for a GPU-kernel optimization run. Decide PASS or "
        "FAIL for the submitted kernel below, using the rubric plus the hard "
        "results. The hard results are ground truth for correctness/speed; your "
        "job is the source-level judgment the metrics cannot see. Inspect the "
        "actual launch path, not merely helper classes or comments.\n\n"
        f"RUBRIC:\n{rubric}\n\n"
        f"HARD RESULTS (from the eval service):\n{json.dumps(metrics, ensure_ascii=False)}\n\n"
        f"FULL KERNEL SOURCE:\n```\n{source[:180000]}\n```\n\n"
        "Reply with ONLY a fenced ```json block: "
        '{"verdict": "pass"|"fail", "score": 0-100, "reasoning": "<3-6 concise sentences>"}'
    )
    cmd = [
        "claude", "-p", prompt, "--dangerously-skip-permissions",
        "--model", agent_default_model(AGENT_CLAUDE),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"state": "error", "error": f"judge failed: {exc}"}
    text = (proc.stdout or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(
        r"(\{.*\})", text, re.DOTALL
    )
    if not m:
        return {"state": "error", "error": "judge returned unexpected output", "raw": text[-500:]}
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {"state": "error", "error": "judge returned invalid JSON", "raw": text[-500:]}
    return {
        "state": "done",
        "verdict": "pass" if str(obj.get("verdict", "")).lower() == "pass" else "fail",
        "score": obj.get("score"),
        "reasoning": str(obj.get("reasoning", ""))[:2000],
    }


def _export_judged_kernel(
    root: Path,
    slug: str,
    run_uid: str,
    job_id: str,
    speedup: Any,
    source: str,
    plugin: str,
) -> str:
    """Archive the Judge-approved source task-locally and promote to worktree.

    Worker run directories intentionally retain experiments and probes; only a
    source-level PASS is promoted into the user's worktree.
    """
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", plugin or "kernel").strip("_")
    worktree = task_worktree_path(root, slug)
    dest = worktree / f"{stem}_candidate.py" if worktree is not None else None
    header = (
        "# Judge-approved kernel candidate\n"
        f"# run_record: {run_uid}\n"
        f"# evaluator_job: {job_id}\n"
        f"# speedup_vs_reference: {speedup}\n"
        "# NOTE: this file uses the evaluator prepare(inputs)->launch ABI;\n"
        "# adapt the integration wrapper separately before production use.\n\n"
    )
    try:
        winner_dir = _kernel_winners_dir(root, slug) / job_id
        winner_dir.mkdir(parents=True, exist_ok=True)
        (winner_dir / "kernel.py").write_text(
            header + source.rstrip() + "\n", encoding="utf-8"
        )
        (winner_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "run_record": run_uid,
                    "job_id": job_id,
                    "plugin": plugin,
                    "speedup": speedup,
                    "promoted_to": str(dest) if dest is not None else "",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if dest is not None:
            dest.write_text(header + source.rstrip() + "\n", encoding="utf-8")
    except OSError:
        return ""
    return str(dest or (winner_dir / "kernel.py"))


def _ensure_judged_kernel_export(root: Path, rec: dict[str, Any]) -> dict[str, Any]:
    """Repair/export an older PASS verdict when its source service is reachable.

    This lets a completed run export automatically after a temporary remote
    evaluator outage, without paying for another LLM judge call.
    """
    judge = rec.get("judge") or {}
    if judge.get("verdict") != "pass" or judge.get("export_path"):
        return rec
    job_id = str(judge.get("job_id") or "")
    slug = str(rec.get("slug") or "")
    if not job_id or not slug:
        return rec
    ok, source_data = _run_kernel_helper(
        root,
        ["kernel-source", "--job-id", job_id],
        timeout=30,
        cluster=_kernel_record_cluster(rec),
    )
    source = str((source_data or {}).get("source") or "")
    if not ok or not source:
        return rec
    export_path = _export_judged_kernel(
        root,
        slug,
        str(rec.get("id") or ""),
        job_id,
        judge.get("speedup"),
        source,
        str((rec.get("config") or {}).get("plugin") or rec.get("plugin") or ""),
    )
    if export_path:
        judge = dict(judge)
        judge["export_path"] = export_path
        rec["judge"] = judge
        _kernel_write_record(root, rec)
    return rec


def _maybe_export_judged_kernel_async(root: Path, rec: dict[str, Any]) -> dict[str, Any]:
    judge = rec.get("judge") or {}
    if judge.get("verdict") != "pass" or judge.get("export_path"):
        return rec
    last_attempt = float(judge.get("export_attempt_at") or 0)
    if time.time() - last_attempt < 60:
        return rec
    judge = dict(judge)
    judge["export_attempt_at"] = time.time()
    rec["judge"] = judge
    _kernel_write_record(root, rec)
    threading.Thread(
        target=_ensure_judged_kernel_export,
        args=(root, dict(rec)),
        daemon=True,
    ).start()
    return rec


def _judge_kernel_run(root: Path, run_uid: str) -> None:
    """Judge the run's best kernel: EVALUATION.md rubric + kernel source + hard
    results -> PASS/FAIL verdict with reasoning, stored on the run record."""
    rec = _kernel_read_record(root, run_uid) or {}
    rid = rec.get("run_id")
    slug = rec.get("slug") or rec.get("task_slug") or ""

    def _store(judge: dict[str, Any]) -> None:
        cur = _kernel_read_record(root, run_uid) or {"id": run_uid}
        judge["judged_at"] = time.time()
        cur["judge"] = judge
        _kernel_write_record(root, cur)
        if judge.get("state") == "done" and slug:
            plan_path = task_root(root, str(slug)) / KERNEL_WIKI
            marker = f"<!-- kernel-judge:{run_uid}:{judge.get('job_id', '')} -->"
            try:
                existing = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else "# Plan\n"
                blocks: list[str] = []
                if marker not in existing:
                    verdict = str(judge.get("verdict") or "unknown").upper()
                    blocks.append(
                        f"\n\n{marker}\n### Evaluator judge — {verdict}\n"
                        f"- Score: `{judge.get('score', '?')}/100`\n"
                        f"- Speedup: `{judge.get('speedup', '?')}×`\n"
                        + (
                            f"- Exported winner: `{judge.get('export_path')}`\n"
                            if judge.get("export_path")
                            else ""
                        )
                        + f"- Review: {judge.get('reasoning', '')}\n"
                    )
                for candidate in judge.get("candidate_reviews") or []:
                    candidate_id = str(candidate.get("job_id") or "")
                    candidate_marker = f"<!-- kernel-candidate-judge:{candidate_id} -->"
                    if not candidate_id or candidate_marker in existing:
                        continue
                    verdict = str(candidate.get("verdict") or candidate.get("state") or "unknown").upper()
                    blocks.append(
                        f"\n\n{candidate_marker}\n"
                        f"#### Candidate `{candidate_id}` — {verdict}\n"
                        f"- Speedup: `{candidate.get('speedup', '?')}×`\n"
                        f"- Judge score: `{candidate.get('score', '?')}/100`\n"
                        f"- Finding: {candidate.get('reasoning') or candidate.get('error') or 'No details.'}\n"
                    )
                if blocks:
                    plan_path.write_text(existing.rstrip() + "".join(blocks), encoding="utf-8")
            except OSError:
                pass

    if not rid:
        _store({"state": "error", "error": "run not started"})
        return
    rubric = _JUDGE_FALLBACK_RUBRIC
    if slug:
        ep = _kernel_doc_path(root, slug, "EVALUATION.md")
        if ep.is_file():
            rubric = ep.read_text(encoding="utf-8", errors="replace")[:12000]

    # The numerically fastest library entry can be a diagnostic probe that
    # skipped required work yet happened to pass tolerance. Judge candidates
    # in speed order and select the fastest source-level PASS, not raw rank #1.
    ok, status = _run_kernel_helper(
        root, ["status", "--run-id", rid], timeout=30,
        cluster=_kernel_record_cluster(rec),
    )
    archive = list((status or {}).get("archive") or []) if ok else []
    archive.sort(key=lambda item: float(item.get("speedup") or 0), reverse=True)
    if not archive:
        ok, best = _run_kernel_helper(
            root, ["best-kernel", "--run-id", rid], timeout=30,
            cluster=_kernel_record_cluster(rec),
        )
        if ok and best.get("job_id"):
            archive = [best]
    if not archive:
        _store({"state": "error", "error": "no kernel available to judge"})
        return

    reviews: list[dict[str, Any]] = []
    for candidate in archive[:10]:
        job_id = str(candidate.get("job_id") or "")
        ok, source_data = _run_kernel_helper(
            root, ["kernel-source", "--job-id", job_id], timeout=30,
            cluster=_kernel_record_cluster(rec),
        )
        source = str((source_data or {}).get("source") or "")
        if not ok or not source:
            reviews.append({
                "job_id": job_id,
                "speedup": candidate.get("speedup"),
                "state": "error",
                "error": (source_data or {}).get("error", "source unavailable"),
            })
            continue
        metrics = {
            "correct": True,  # only correct kernels enter the library
            "speedup_vs_reference": candidate.get("speedup"),
            "kernel_us": candidate.get("kernel_us"),
            "baseline_us": candidate.get("baseline_us"),
            "agent_index": candidate.get("agent_index"),
            "task_slug": rec.get("task_slug"),
            "total_submissions": len(rec.get("submissions_seen") or []) or None,
        }
        review = _judge_kernel_candidate(rubric, metrics, source)
        review.update({"job_id": job_id, "speedup": candidate.get("speedup")})
        reviews.append(review)
        if review.get("verdict") == "pass":
            final_review = dict(review)
            final_review["candidate_reviews"] = [dict(item) for item in reviews]
            final_review["export_path"] = _export_judged_kernel(
                root,
                str(slug),
                run_uid,
                job_id,
                candidate.get("speedup"),
                source,
                str((rec.get("config") or {}).get("plugin") or rec.get("plugin") or ""),
            )
            _store(final_review)
            return

    _store({
        "state": "done",
        "verdict": "fail",
        "score": max(
            (int(r.get("score") or 0) for r in reviews if r.get("state") == "done"),
            default=0,
        ),
        "reasoning": (
            f"No source-level PASS among the top {len(reviews)} correct kernels. "
            + " | ".join(
                f"{r.get('job_id', '')[:8]} ({float(r.get('speedup') or 0):.2f}×): "
                f"{r.get('reasoning') or r.get('error') or 'failed review'}"
                for r in reviews[:3]
            )
        )[:2000],
        "job_id": reviews[0].get("job_id") if reviews else None,
        "speedup": reviews[0].get("speedup") if reviews else None,
        "candidate_reviews": reviews,
    })


def _kernel_judge_async(root: Path, run_uid: str) -> None:
    rec = _kernel_read_record(root, run_uid) or {"id": run_uid}
    rec["judge"] = {"state": "judging", "started_at": time.time()}
    _kernel_write_record(root, rec)
    threading.Thread(
        target=_judge_kernel_run, args=(root, run_uid), daemon=True
    ).start()


def _kernel_propose_shape(root: Path, cfg: dict[str, Any]) -> Any:
    """Have the host ``claude`` CLI choose a representative benchmark shape for
    the kernel op, so the shape is agent-decided rather than a human input.

    Returns the shape (a dict) or ``None`` on any failure, in which case the
    caller omits ``--shape`` and the kernel helper falls back to the plugin's
    default template.
    """
    plugin = str(cfg.get("plugin", "")).strip()
    target = str(cfg.get("target", "")).strip()
    model = str(cfg.get("model", "")).strip()
    if not plugin:
        return None
    # Show the agent the plugin's expected shape keys (if known) so it returns a
    # shape the evaluator can actually use; a freshly-resolved plugin has none,
    # and the agent infers the keys from the operation instead.
    tpl = None
    try:
        ok, data = _run_kernel_helper(root, ["plugins"], timeout=30)
        if ok:
            tpl = (data.get("shape_templates") or {}).get(plugin)
    except Exception:  # noqa: BLE001
        tpl = None
    if tpl is not None:
        keys_hint = (
            "The shape is a JSON object with EXACTLY these keys (example values "
            "shown — keep the keys, pick realistic representative values for a "
            f"meaningful benchmark):\n{json.dumps(tpl)}"
        )
    else:
        keys_hint = (
            "Infer the correct shape keys for this operation yourself (e.g. "
            "batch, heads, seq_len, head_dim, m/n/k, page_size, dtype as "
            "appropriate) and pick realistic, representative values for a "
            "meaningful benchmark."
        )
    prompt = (
        "You are choosing ONE representative benchmark shape for a GPU kernel "
        f'optimization run. Operation/plugin: "{plugin}". Target backend: '
        f'"{target or "unspecified"}".\n\n{keys_hint}\n\n'
        "Reply with ONLY a single fenced ```json code block containing the shape "
        "object, and no other prose."
    )
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
    # Only forward a Claude model; codex/gpt models aren't valid for `claude`.
    if model.startswith("claude-"):
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, OSError):
        return None
    text = (proc.stdout or "").strip()
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(
        r"(\{.*\})", text, re.DOTALL
    )
    if not m:
        return None
    try:
        shape = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return shape if isinstance(shape, dict) and shape else None


def _launch_kernel_run(root: Path, run_uid: str, cfg: dict[str, Any]) -> None:
    """Background worker: run the helper's launch and update the run record."""
    # Shape is no longer a human input. Use an explicit override when supplied,
    # otherwise let an agent propose a representative shape at launch. If that
    # also fails, omit --shape so the kernel helper falls back to the plugin's
    # default template.
    if cfg.get("shape"):
        cfg["shape_source"] = "override"
    else:
        proposed = _kernel_propose_shape(root, cfg)
        if proposed:
            cfg["shape"] = proposed
            cfg["shape_source"] = "agent"
        else:
            cfg["shape_source"] = "template"
    # Persist the resolved shape early so the UI reflects the agent's choice
    # while the (slow) build + launch runs.
    early = _kernel_read_record(root, run_uid) or {"id": run_uid}
    early["config"] = cfg
    _kernel_write_record(root, early)
    args = [
        "launch",
        "--plugin", str(cfg["plugin"]),
        "--target", str(cfg["target"]),
        "--model", str(cfg["model"]),
        "--n-agents", str(cfg.get("n_agents", 1)),
        "--starter-mode", str(cfg.get("starter_mode", "none")),
    ]
    if cfg.get("shape"):
        args += ["--shape", _shape_to_str(cfg["shape"])]
    if cfg.get("target_speedup") is not None:
        args += ["--target-speedup", str(cfg["target_speedup"])]
    if cfg.get("auto_terminate"):
        args += ["--auto-terminate", "--poll-interval", str(cfg.get("poll_interval", 60))]
    if cfg.get("build"):
        args += ["--build"]
    if cfg.get("build_mode"):
        args += ["--build-mode"]
    # Ship the task's INSTRUCTION.md (from the interview) to every agent.
    rec0 = _kernel_read_record(root, run_uid) or {}
    slug0 = str(rec0.get("slug") or "").strip()
    if slug0:
        contract_path = Path(str(rec0.get("contract_file") or ""))
        if not contract_path.is_file():
            contract_files = sorted(_kernel_contract_dir(root, slug0).glob("*.py"))
            contract_path = contract_files[0] if contract_files else Path()
        if contract_path.is_file():
            args += ["--contract-file", str(contract_path)]
        ipath = _kernel_doc_path(root, slug0, "INSTRUCTION.md")
        if ipath.is_file():
            args += ["--instructions-file", str(ipath)]
        wpath = task_root(root, slug0) / KERNEL_WIKI
        if wpath.is_file():
            args += ["--wiki-file", str(wpath)]
        epath = _kernel_doc_path(root, slug0, "EVALUATION.md")
        if epath.is_file():
            args += ["--evaluation-file", str(epath)]
    ok, data = _run_kernel_launch_streaming(
        root, run_uid, args, timeout=2400, cluster=str(cfg.get("cluster") or "")
    )
    rec = _kernel_read_record(root, run_uid) or {"id": run_uid}
    # Persist the resolved shape + how it was chosen so the UI can show it.
    rec["config"] = cfg
    if ok:
        rec.update({
            "state": "running",
            "run_id": data.get("run_id"),
            "task_slug": data.get("task_slug"),
            "containers": data.get("containers", []),
            "plugin": cfg.get("plugin"),
            "verified": cfg.get("plugin") not in _kernel_unverified_set(root),
            "launched_at": time.time(),
        })
    else:
        rec.update({
            "state": "error",
            "error": data.get("error", "launch failed"),
            "error_detail": {
                k: data[k] for k in ("stderr", "stdout", "stdout_tail", "service") if k in data
            },
        })
    _kernel_write_record(root, rec)


# --- Kernel Lab: verified state + interview-driven prepare ---

def _kernel_unverified_path(root: Path) -> Path:
    return root / ".RUD" / "kernel-plugins-unverified.json"


def _kernel_unverified_set(root: Path) -> set[str]:
    f = _kernel_unverified_path(root)
    if not f.is_file():
        return set()
    try:
        return set(json.loads(f.read_text()))
    except (json.JSONDecodeError, OSError):
        return set()


def _kernel_set_unverified(root: Path, name: str, unverified: bool) -> None:
    s = _kernel_unverified_set(root)
    if unverified:
        s.add(name)
    else:
        s.discard(name)
    f = _kernel_unverified_path(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(s)))
    tmp.replace(f)


def _resolve_plugin_for(
    root: Path,
    source: str,
    timeout: int = 2400,
    intent: str = "",
    out_dir: Path | None = None,
) -> tuple[str | None, bool, str]:
    """Run resolve_plugin (in-project script or pip module); return
    (plugin_name, created, output_tail)."""
    base, err = _kernel_helper_cmd("resolve_plugin.py")
    if base is None:
        return None, False, err
    cmd = [*base, "--source", source]
    if intent.strip():
        cmd += ["--intent", intent.strip()]
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd += ["--out-dir", str(out_dir)]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, False, "resolve_plugin timed out"
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    # The resolver may emphasize the name in Markdown (`**name**`). Capture
    # only plugin-name characters so formatting never leaks into the registry
    # key stored on the prepared record.
    m = re.search(r"RESULT:\s*(CREATE|REUSE)\s+([A-Za-z0-9_.-]+)", out)
    if not m:
        return None, False, out[-1500:]
    return m.group(2), (m.group(1) == "CREATE"), out[-1500:]


def _prepare_kernel_run(root: Path, prep_uid: str, spec: dict[str, Any]) -> None:
    """Background: resolve the plugin for the interview spec, mark a newly created
    plugin unverified, and leave a 'prepared' record the UI can launch from."""
    rec = _kernel_read_record(root, prep_uid) or {"id": prep_uid}
    source = str(spec.get("source", "")).strip()
    if not source:
        rec.update({"state": "error", "error": "interview spec has no source kernel"})
        _kernel_write_record(root, rec)
        return
    rec["state"] = "resolving"
    _kernel_write_record(root, rec)
    # Resolution must match the user's TASK, not just the literal source file
    # (e.g. "nvfp4 version of this fp8 kernel" -> the nvfp4 plugin).
    intent_bits = []
    if spec.get("dtype"):
        intent_bits.append(f"desired precision/variant: {spec['dtype']}")
    if spec.get("target"):
        intent_bits.append(f"target backend: {spec['target']}")
    slug = str(rec.get("slug") or "").strip()
    contract_dir = _kernel_contract_dir(root, slug) if slug else None
    plugin, created, out = _resolve_plugin_for(
        root,
        source,
        intent="; ".join(intent_bits),
        out_dir=contract_dir,
    )
    if plugin is None:
        rec.update({"state": "error", "error": "plugin resolution failed", "error_detail": out})
        _kernel_write_record(root, rec)
        return
    if created:
        _kernel_set_unverified(root, plugin, True)
    rec.update({
        "state": "documenting",
        "kind": "prepare",
        "plugin": plugin,
        "plugin_created": created,
        "verified": plugin not in _kernel_unverified_set(root),
        "needs_build": created,
        "resolve_output": out,
    })
    if contract_dir is not None:
        contract_files = sorted(contract_dir.glob("*.py"))
        if contract_files:
            rec["contract_file"] = str(
                contract_dir / "plugin.py"
                if (contract_dir / "plugin.py").is_file()
                else contract_files[0]
            )
    _kernel_write_record(root, rec)
    # Turn the interview into the task docs: INSTRUCTION.md for the worker
    # agents (shipped into their workdirs at launch) and EVALUATION.md for the
    # judge. Best-effort; the files stay editable in the task dir.
    if slug:
        # REUSE still gets an explicit task-local contract wrapper so task
        # ownership is visible and no generated contract lives in Loom.
        if contract_dir is not None:
            _ensure_task_contract_wrapper(root, slug, plugin)
        if contract_dir is not None:
            contract_files = sorted(contract_dir.glob("*.py"))
            if contract_files:
                rec["contract_file"] = str(
                    contract_dir / "plugin.py"
                    if (contract_dir / "plugin.py").is_file()
                    else contract_files[0]
                )
                _kernel_write_record(root, rec)
        try:
            iv = read_kernel_interview(root, slug)
            docs = _generate_kernel_docs(root, slug, spec, (iv or {}).get("messages"))
            rec["docs"] = docs
            if not docs.get("ok"):
                rec.update({
                    "state": "error",
                    "error": "task document generation failed",
                    "error_detail": docs,
                })
                _kernel_write_record(root, rec)
                return
            _seed_kernel_wiki(root, slug, spec, plugin)
        except Exception as exc:  # noqa: BLE001
            rec.update({
                "state": "error",
                "error": "task document generation failed",
                "error_detail": str(exc),
            })
            _kernel_write_record(root, rec)
            print(f"[web] kernel doc generation failed slug={slug}: {exc}", flush=True)
            return
    rec.update({"state": "prepared", "prepared_at": time.time()})
    _kernel_write_record(root, rec)


_KERNEL_INTERVIEW_SYS = """You are running a short technical interview inside "Kernel Lab" to collect everything needed to (a) define a kernel eval plugin for a GPU kernel and (b) launch an optimization run for it. Ask ONE focused question at a time and be concise. If the user gives a GitHub raw URL or a source link, use your tools to read it and INFER as much as possible (dims, dtype, operation) — only ask what you cannot infer.

Collect: source (a GitHub raw URL, a kernel name, or a clear description of the operation); desired implementation precision/variant (e.g. nvfp4 even when the correctness reference is fp8); target architecture (SM100 -> the `sm100` external cluster profile and cutedsl for nvfp4; default profile -> cuda/cutedsl with bf16/fp8); run params (target speedup [optional], number of agents, starter mode: none/generic/best-similar/preset; only use preset when there is a real local preset directory).

Do NOT ask the user for the operation shape/dims. Infer a single representative shape yourself from the source/operation (operation-specific; for attention: heads, head_dim or latent+rope, page_size, KV length, query length Sq, batch, dtype) and include it in the spec — the evaluator benchmarks this shape and the user can override it later if needed.

When AND ONLY WHEN you have everything, reply with ONLY a fenced ```json code block (no other prose), shaped like:
{"done": true, "spec": {"source": "<url-or-name>", "plugin": "mla.decode_nvfp4", "cluster": "sm100", "target": "cutedsl", "shape": {"batch_size": 4, "num_heads": 128}, "dtype": "nvfp4", "model": "claude-fable-5", "n_agents": 3, "starter_mode": "none", "target_speedup": 1.0}}
Otherwise reply with your next question as plain text only."""


def _normalize_kernel_interview_spec(raw: Any) -> dict[str, Any]:
    spec = dict(raw) if isinstance(raw, dict) else {}
    shape = dict(spec.get("shape") or {})
    aliases = {"sq": "seq_len_q", "kv_len": "max_sequence_kv"}
    for old, new in aliases.items():
        if old in shape and new not in shape:
            shape[new] = shape.pop(old)
    if shape:
        spec["shape"] = shape

    dtype = str(spec.get("dtype") or "").strip().lower()
    if dtype == "nvfp4":
        spec.setdefault("plugin", "mla.decode_nvfp4")
        spec.setdefault("cluster", "sm100")
        spec.setdefault("target", "cutedsl")
        if spec.get("target_speedup") is None:
            spec["target_speedup"] = 1.0

    model = str(spec.get("model") or "").strip()
    if not model or model in {
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    }:
        spec["model"] = agent_default_model(AGENT_CLAUDE)

    starter = str(spec.get("starter_mode") or "none").strip().lower()
    if starter == "scratch":
        starter = "none"
    source = str(spec.get("source") or "")
    if starter == "preset" and source.startswith(("http://", "https://")):
        # A URL is context in INSTRUCTION.md, not a mountable preset directory.
        starter = "none"
    spec["starter_mode"] = starter
    return spec


def _kernel_interview_turn(messages: list[dict[str, Any]], model: str = "") -> dict[str, Any]:
    """One interview turn via the logged-in host `claude` CLI. Returns either the
    next question ({done:false, assistant}) or a final spec ({done:true, spec})."""
    convo = "\n".join(
        f"{str(m.get('role', 'user')).capitalize()}: {m.get('content', '')}" for m in messages
    )
    prompt = (
        f"{_KERNEL_INTERVIEW_SYS}\n\nConversation so far:\n{convo}\n\n"
        "Produce your next turn (a single question, or the final json spec)."
    )
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "interview turn timed out"}
    text = (proc.stdout or "").strip()
    if not text:
        return {"ok": False, "error": "empty response from claude", "stderr": (proc.stderr or "")[-500:]}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(
        r"(\{\s*\"done\"\s*:\s*true.*\})", text, re.DOTALL
    )
    if m:
        try:
            obj = json.loads(m.group(1))
            if obj.get("done"):
                return {
                    "ok": True,
                    "done": True,
                    "spec": _normalize_kernel_interview_spec(obj.get("spec", obj)),
                }
        except json.JSONDecodeError:
            pass
    return {"ok": True, "done": False, "assistant": text}


_REVIEW_DEFAULT_RULES = """- Correctness: logic bugs, edge cases, wrong APIs, off-by-one, error handling.
- Security: NO hardcoded secrets/tokens/keys; no injection; safe file/subprocess use.
- Hygiene: no leftover debug prints, commented-out code, stray TODOs, dead code.
- Tests: meaningful changes should add/keep tests; flag "claims tested" with no test.
- Consistency: matches the surrounding code style and the project's skills."""


def _run_worktree_review(
    wt: Path, rules: str, skills: str, model: str = ""
) -> dict[str, Any]:
    """Bugbot-style review: run the logged-in host ``claude -p`` over a
    worktree's diff against plain-English rules (falling back to the task's
    skills). Returns ``{ok, review}`` markdown."""
    diff = worktree_diff(wt)
    files = diff.get("files", [])
    if not files:
        return {"ok": True, "review": "✅ No changes to review in this worktree.", "files": 0}
    parts: list[str] = []
    total = 0
    for f in files:
        patch = f.get("patch") or ""
        if not patch:
            continue
        parts.append(patch)
        total += len(patch)
        if total > 60000:
            parts.append("\n... (diff truncated for review) ...\n")
            break
    diff_text = "\n".join(parts).strip() or "(no textual diff)"
    rules_block = (rules or "").strip() or (skills or "").strip() or "(use general best practices)"
    prompt = (
        "You are a strict senior code reviewer (think Bugbot). Review the DIFF "
        "for this change. Only flag real problems. For each finding, output a "
        "markdown bullet exactly like:\n"
        "  - `path:line` - **[severity]** what's wrong -> concrete fix\n"
        "Always cover: correctness/bugs, security (secrets, injection), leftover "
        "debug/TODO/dead code, missing or weak tests, and any RULES violations. "
        "If everything looks good, reply with exactly: `✅ No issues found.` "
        "Keep it concise.\n\n"
        f"RULES (plain-English, from the user / task skills):\n{rules_block}\n\n"
        f"DEFAULT CHECKLIST:\n{_REVIEW_DEFAULT_RULES}\n\n"
        f"DIFF:\n{diff_text}"
    )
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "review timed out"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    text = (proc.stdout or "").strip()
    if not text:
        return {
            "ok": False,
            "error": "empty response from claude",
            "stderr": (proc.stderr or "")[-500:],
        }
    return {"ok": True, "review": text, "files": len(files)}


# --- Claude prompt builder --------------------------------------------------


def _build_ar_prompt(
    project_root: Path,
    slug: str,
    meta: Any,
    task_dir: Path,
    skills: str,
) -> str:
    """Pane prompt for an AR task, chosen by the role recorded in ar.json.

    A paper task in the middle of the loop gets that round's author prompt, so
    pressing the pane's prompt button resends exactly what the driver would -
    useful after restarting a pane mid-round.
    """
    state = ar.read_ar_state(project_root, slug)
    if not state:
        # A legacy `aris` task, or one whose ar.json has not been written yet.
        state = ar.new_studio_state()
    if ar.is_paper(state):
        paper_dir = ar.paper_root(project_root, slug)
        stage = str(state.get("stage") or ar.STAGE_DRAFT)
        n = ar.current_round(state)
        if stage == ar.STAGE_LOOP and n >= 1:
            review_path = ((ar.round_record(state, n - 1) or {}).get("review") or {}).get("path", "")
            review_text = _ar_read_text(Path(review_path)) if review_path else ""
            return ar.author_round_prompt(
                task_dir, paper_dir, state, n, review_text=review_text
            )
        return ar.author_draft_prompt(task_dir, paper_dir, state)

    base = ar.studio_prompt(task_dir, state, meta.general_goal)
    if skills.strip():
        base += f"\nDomain skills selected for this task:\n---\n{skills}\n---\n"
    return base


def _build_claude_prompt(
    project_root: Path,
    slug: str,
    default_skills: Path | None = None,
) -> str:
    meta = read_meta(project_root, slug)
    if not meta:
        return ""
    td = task_root(project_root, slug)
    wt = task_worktree_path(project_root, slug)
    wt_line = f"Worktree (branch {meta.branch or '(unset)'}): {wt}" if wt else "Worktree: (none)"
    # meta.skills_path may name several ;-joined skills files - inject them all.
    skills = load_skills_text(meta.skills_path, default_skills)
    state_doc = KERNEL_WIKI if meta.kind == "kernel" else PLAN
    plan_path = td / state_doc
    if ar.is_ar_kind(meta.kind):
        return _build_ar_prompt(project_root, slug, meta, td, skills)
    return f"""You are running Loom's {agent_label(meta.agent)} pane for this task.

You start in this task's work directory (your git worktree is a subdirectory here - cd into it to touch code):
{td / "work"}

General goal:
{meta.general_goal}

{wt_line}

Default skills from:
{meta.skills_path or "(bundled default)"}

Default skills:
---
{skills or "(none)"}
---

RUD workflow:
1. Start from the General goal above and run a short deep-interview. Ask
   one high-leverage question at a time about scope, constraints,
   acceptance, tests, risks, non-goals, and available worktrees.
2. When the interview has enough information, write or overwrite
   {plan_path} with a concise executable plan:
   - Goal
   - Context / Decisions from the interview
   - Constraints / non-goals
   - Acceptance criteria
   - Next steps as a checkbox list
   - Progress Log / Result section
   Do not leave interview notes only in chat; the result of the interview
   must be captured DIRECTLY in {plan_path}.
3. After {state_doc} is solid, tell the user it is ready to run. The user can
   click RUD's "Run /goal" button (or type /goal) to execute {state_doc}.
4. While executing and when finished, keep writing useful progress,
   blockers, decisions, and final results back into {plan_path}. Remove
   obsolete/noisy details, but preserve unrelated prior sections.

Behavioural constraints:
- {state_doc} is the ONLY task-state file. Do not create INTERVIEW.md,
  TODO.md, PROGRESS.md, NOTES.md, or any other scattered status files in
  the task directory or the repo.
- Project-scoped scratch lives in the project's NOTES.md at .RUD/NOTES.md
  (handled by the user via the web UI), not inside the worktree.

Begin by reading {plan_path}, then either ask the first interview
question or, if {state_doc} is already detailed enough, acknowledge that it is
ready and wait for the user to run ``/goal``.
"""


def _task_pane_cwd(project_root: Path, slug: str, meta=None) -> Path:
    """Directory the agent pane launches in - and where Claude Code stores the
    session transcript (``~/.claude/projects/<encoded-cwd>/``).

    All tasks launch in the task's ``work/`` dir: a stable base that holds every
    git worktree (the agent cd's into the relevant one to run git / code), so
    the session-transcript location stays consistent no matter how many
    worktrees a task has. Falls back to the primary worktree / task dir only if
    ``work/`` can't be created.
    """
    td = task_root(project_root, slug)
    wd = td / "work"
    try:
        wd.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if wd.is_dir():
        return wd
    wt = task_worktree_path(project_root, slug)
    return wt if wt is not None else td


# --- Claude tmux registry ---------------------------------------------------


class ClaudeRegistry:
    """Manage tmux + agent CLI panes per (project, task).

    A pane's lifecycle:
    1. ``start`` opens a tmux session and runs the selected agent in the task
       worktree; exiting the agent returns the pane to a login shell.
    2. A background watcher records the new CLI session ID so the UI can
       offer Resume.
    3. ``stop`` kills the tmux session but leaves the session UUIDs in
       metadata so they remain resumable from the CLI.
    4. ``resume`` re-launches the agent with ``--resume <uuid>`` in a tmux
       pane.  Useful when the original tmux was killed but the session
       transcript on disk is still good.
    """

    @staticmethod
    def _launch_agent_in_pane(target: str, cwd: Path, argv: list[str]) -> tuple[bool, str]:
        """Run the agent in the pane, returning to a login shell when it exits."""
        env = tmux_subprocess_env()
        executable = shutil.which(argv[0], path=env.get("PATH"))
        if not executable:
            return False, f"{argv[0]} not on PATH"
        direct_argv = [executable, *argv[1:]]
        login_shell = (env.get("SHELL") or "/bin/bash").strip()
        if not Path(login_shell).is_absolute():
            login_shell = shutil.which(login_shell, path=env.get("PATH")) or "/bin/bash"
        pane_command = (
            f"{shlex.join(direct_argv)}; agent_status=$?; "
            "stty sane 2>/dev/null || true; "
            "printf '\\nAgent exited (%s). Returned to shell.\\n' \"$agent_status\"; "
            f"exec {shlex.quote(login_shell)} -l"
        )
        try:
            keep = subprocess.run(
                ["tmux", "set-option", "-w", "-t", target, "remain-on-exit", "on"],
                capture_output=True,
                text=True,
                env=env,
                timeout=5,
            )
            if keep.returncode != 0:
                return False, (keep.stderr or keep.stdout or "could not configure tmux pane").strip()
            launched = subprocess.run(
                [
                    "tmux",
                    "respawn-pane",
                    "-k",
                    "-t",
                    target,
                    "-c",
                    str(cwd),
                    "-e",
                    f"PATH={env.get('PATH', '')}",
                    pane_command,
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=8,
            )
        except FileNotFoundError:
            return False, "tmux not on PATH"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if launched.returncode != 0:
            return False, (launched.stderr or launched.stdout or "could not launch agent").strip()
        return True, ""

    def start(
        self,
        project_root: Path,
        project_id: str,
        slug: str,
        *,
        resume_session_id: str = "",
        default_skills: Path | None = None,
    ) -> dict[str, Any]:
        meta = read_meta(project_root, slug)
        if not meta:
            return {"ok": False, "error": "Task not found"}
        td = task_root(project_root, slug)
        if not td.is_dir():
            return {"ok": False, "error": "Task directory missing"}

        # Run the agent inside the worktree when we have one - that's where
        # the user will eventually want /goal (or codex's equivalent) to act.
        cwd = _task_pane_cwd(project_root, slug, meta)

        agent = normalize_agent(meta.agent)
        selected_model = meta.interview_model or agent_default_model(agent)
        if agent == AGENT_CURSOR and selected_model == CURSOR_DEFAULT_MODEL:
            configured, config_error = ensure_cursor_default_model_config()
            if not configured:
                return {
                    "ok": False,
                    "error": f"Could not configure Cursor 1M Max default: {config_error}",
                }

        def watch_cursor_ready() -> None:
            if agent == AGENT_CURSOR:
                threading.Thread(
                    target=self._wait_for_claude_ready,
                    args=(target, 45.0),
                    daemon=True,
                ).start()

        session_name = self._live_or_default_session(
            project_id, slug, agent, meta.tmux_interview_target or ""
        )
        target = f"{session_name}:0.0"
        existing_ids = {
            sid
            for p in list_session_files(cwd, agent)
            if (sid := session_id_from_path(p, agent))
        }
        if self._tmux_session_exists(session_name):
            pane_command = self._pane_current_command(target)
            pane_dead = self._pane_is_dead(target)
            if resume_session_id:
                if not pane_dead and not self._pane_is_idle_shell(pane_command):
                    return {
                        "ok": False,
                        "error": (
                            "The tmux pane is still running a command. Stop it before "
                            "resuming another session."
                        ),
                        "target": target,
                        "session": session_name,
                        "pane_command": pane_command,
                    }
                agent_cmd = build_agent_command(
                    agent,
                    model=selected_model,
                    resume_session_id=resume_session_id,
                )
                ok, error = self._launch_agent_in_pane(target, cwd, agent_cmd)
                if not ok:
                    return {"ok": False, "error": error, "target": target}
                watch_cursor_ready()
                update_meta(project_root, slug, tmux_interview_target=target)
                add_claude_session(project_root, slug, resume_session_id)
                threading.Thread(
                    target=self._watch_for_session_id,
                    args=(project_root, slug, cwd, agent, existing_ids),
                    daemon=True,
                ).start()
                return {
                    "ok": True,
                    "target": target,
                    "session": session_name,
                    "cwd": str(cwd),
                    "agent": agent,
                    "resumed_session_id": resume_session_id,
                    "already_running": False,
                    "reused_tmux": True,
                    "prompt_pending": False,
                    "pane_command": pane_command,
                }
            if pane_dead or self._pane_is_idle_shell(pane_command):
                # Reuse old shell-backed sessions and new retained dead panes
                # by replacing the pane process directly with the agent.
                agent_cmd = build_agent_command(
                    agent,
                    model=selected_model,
                )
                ok, error = self._launch_agent_in_pane(target, cwd, agent_cmd)
                if not ok:
                    return {"ok": False, "error": error, "target": target}
                watch_cursor_ready()
                threading.Thread(
                    target=self._watch_for_session_id,
                    args=(project_root, slug, cwd, agent, existing_ids),
                    daemon=True,
                ).start()
                update_meta(project_root, slug, tmux_interview_target=target)
                return {
                    "ok": True,
                    "target": target,
                    "session": session_name,
                    "cwd": str(cwd),
                    "agent": agent,
                    "already_running": False,
                    "reused_tmux": True,
                    "prompt_pending": True,
                    "pane_command": pane_command,
                }
            watch_cursor_ready()
            update_meta(project_root, slug, tmux_interview_target=target)
            return {
                "ok": True,
                "target": target,
                "session": session_name,
                "cwd": str(cwd),
                "agent": agent,
                "already_running": True,
            }

        try:
            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    session_name,
                    "-x",
                    "240",
                    "-y",
                    "64",
                    "-c",
                    str(cwd),
                ],
                capture_output=True,
                text=True,
                env=tmux_subprocess_env(),
                check=True,
                timeout=8,
            )
        except FileNotFoundError:
            return {"ok": False, "error": "tmux not on PATH"}
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": str(e)}

        agent_cmd = build_agent_command(
            agent,
            model=selected_model,
            resume_session_id=resume_session_id,
        )
        ok, error = self._launch_agent_in_pane(target, cwd, agent_cmd)
        if not ok:
            self._kill_tmux_session(session_name)
            return {"ok": False, "error": error}
        watch_cursor_ready()

        update_meta(project_root, slug, tmux_interview_target=target)
        if resume_session_id:
            add_claude_session(project_root, slug, resume_session_id)
        threading.Thread(
            target=self._watch_for_session_id,
            args=(project_root, slug, cwd, agent, existing_ids),
            daemon=True,
        ).start()
        return {
            "ok": True,
            "target": target,
            "session": session_name,
            "cwd": str(cwd),
            "agent": agent,
            "resumed_session_id": resume_session_id or None,
            "already_running": False,
            "prompt_pending": not bool(resume_session_id),
        }

    def paste_prompt(
        self,
        project_root: Path,
        project_id: str,
        slug: str,
        *,
        default_skills: Path | None = None,
    ) -> dict[str, Any]:
        """Paste the task's deep-interview prompt into the running agent pane."""
        meta = read_meta(project_root, slug)
        if not meta:
            return {"ok": False, "error": "Task not found"}
        agent = normalize_agent(meta.agent)
        session_name = self._live_or_default_session(
            project_id, slug, agent, meta.tmux_interview_target or ""
        )
        if not self._tmux_session_exists(session_name):
            return {"ok": False, "error": "Start the agent pane first"}
        target = (meta.tmux_interview_target or "").strip() or f"{session_name}:0.0"
        # If the recorded target points at a dead session (while a live pane
        # exists under another name), paste into the live one instead.
        if not self._tmux_session_exists(_session_name_from_tmux_target(target)):
            target = f"{session_name}:0.0"
        if self._pane_is_dead(target):
            return {"ok": False, "error": "Agent has exited; start the pane again", "target": target}
        if agent == AGENT_CURSOR:
            self._wait_for_claude_ready(target, timeout=15.0)
        update_meta(project_root, slug, tmux_interview_target=target)
        return self._paste_prompt_to_target(project_root, slug, target, default_skills=default_skills)

    def stop(self, project_root: Path, project_id: str, slug: str) -> dict[str, Any]:
        meta = read_meta(project_root, slug)
        agent = normalize_agent(meta.agent) if meta else AGENT_CURSOR
        meta_target = (meta.tmux_interview_target or "") if meta else ""
        session_name = self._live_or_default_session(project_id, slug, agent, meta_target)
        stopped, msg = self._kill_tmux_session(session_name)
        # Clean up every other variant for this task: the other agent's session
        # (if the user flipped agents), the old "interview" pane name, and the
        # legacy "claudeloop-" brand from before the rename.
        for alias in _session_name_aliases(project_id, slug):
            if alias != session_name:
                self._kill_tmux_session(alias)
        update_meta(project_root, slug, tmux_interview_target="")
        return {
            "ok": True,
            "tmux_stopped": stopped,
            "tmux_message": msg,
            "tmux_session": session_name,
        }

    # --- helpers ---

    def _tmux_session_exists(self, session_name: str) -> bool:
        try:
            r = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True,
                text=True,
                env=tmux_subprocess_env(),
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0

    def _live_or_default_session(
        self, project_id: str, slug: str, agent: str = AGENT_CURSOR, meta_target: str = ""
    ) -> str:
        """Session name to operate on: an already-running pane for this task
        (current ``loom-`` or legacy ``claudeloop-`` brand), else the live
        session recorded in task meta (its name embeds the project id from
        creation time, and the registry can re-issue ids - e.g. after the
        claudeloop->loom rename - so it may differ from today's derived name),
        otherwise the new ``loom-`` name for a fresh start."""
        primary = _safe_claude_session_name(project_id, slug, agent)
        if self._tmux_session_exists(primary):
            return primary
        legacy = _legacy_claude_session_name(project_id, slug, agent)
        if legacy != primary and self._tmux_session_exists(legacy):
            return legacy
        recorded = _session_name_from_tmux_target(meta_target)
        if recorded and recorded not in (primary, legacy) and self._tmux_session_exists(recorded):
            return recorded
        return primary

    def _pane_current_command(self, target: str) -> str:
        try:
            r = subprocess.run(
                ["tmux", "display-message", "-p", "-t", target, "#{pane_current_command}"],
                capture_output=True,
                text=True,
                env=tmux_subprocess_env(),
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if r.returncode != 0:
            return ""
        return (r.stdout or "").strip()

    def _pane_is_dead(self, target: str) -> bool:
        try:
            r = subprocess.run(
                ["tmux", "display-message", "-p", "-t", target, "#{pane_dead}"],
                capture_output=True,
                text=True,
                env=tmux_subprocess_env(),
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0 and (r.stdout or "").strip() == "1"

    @staticmethod
    def _pane_is_idle_shell(command: str) -> bool:
        cmd = Path((command or "").strip()).name.lower()
        return cmd in {"", "bash", "dash", "fish", "sh", "tmux", "zsh"}

    def _pane_has_agent_process(self, target: str, agent: str) -> bool:
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "-t", target, "#{pane_pid}"],
                capture_output=True,
                text=True,
                env=tmux_subprocess_env(),
                timeout=5,
            )
            pane_pid = int((result.stdout or "").strip()) if result.returncode == 0 else 0
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        expected = {
            AGENT_CURSOR: {"agent", "cursor-agent"},
            AGENT_CLAUDE: {"claude"},
            AGENT_CODEX: {"codex"},
        }.get(normalize_agent(agent), {normalize_agent(agent)})
        pending = [pane_pid] if pane_pid > 0 else []
        seen: set[int] = set()
        while pending and len(seen) < 256:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            try:
                raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
                argv = [
                    part.decode("utf-8", errors="replace")
                    for part in raw.split(b"\0")
                    if part
                ]
                executable = Path(argv[0]).name.lower() if argv else ""
                if executable in expected:
                    return True
                children_path = (
                    Path("/proc") / str(pid) / "task" / str(pid) / "children"
                )
                if children_path.is_file():
                    pending.extend(
                        int(child)
                        for child in children_path.read_text().split()
                        if child.isdigit()
                    )
            except OSError:
                continue
        return False

    def session_status(
        self, project_id: str, slug: str, agent: str = AGENT_CURSOR, meta_target: str = ""
    ) -> dict[str, Any]:
        session_name = self._live_or_default_session(project_id, slug, agent, meta_target)
        target = f"{session_name}:0.0"
        tmux_alive = self._tmux_session_exists(session_name)
        pane_command = self._pane_current_command(target) if tmux_alive else ""
        pane_dead = self._pane_is_dead(target) if tmux_alive else False
        agent_process = (
            self._pane_has_agent_process(target, agent)
            if tmux_alive and not pane_dead and self._pane_is_idle_shell(pane_command)
            else False
        )
        return {
            "session": session_name,
            "target": target,
            "tmux_alive": tmux_alive,
            "pane_command": pane_command,
            "pane_dead": pane_dead,
            "agent_running": (
                tmux_alive
                and not pane_dead
                and (
                    not self._pane_is_idle_shell(pane_command)
                    or agent_process
                )
            ),
            "agent": normalize_agent(agent),
        }

    def _kill_tmux_session(self, session_name: str) -> tuple[bool, str]:
        try:
            r = subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
                text=True,
                env=tmux_subprocess_env(),
                timeout=8,
            )
        except FileNotFoundError:
            return False, "tmux not on PATH"
        except subprocess.TimeoutExpired:
            return False, "tmux kill timed out"
        if r.returncode == 0:
            return True, "tmux session killed"
        return False, (r.stderr or r.stdout or "tmux session not found").strip()

    def wait_until_ready(self, target: str, timeout: float = 15.0) -> None:
        """Block until the agent CLI in *target* is ready to receive a prompt."""
        self._wait_for_claude_ready(target, timeout=timeout)

    def _wait_for_claude_ready(self, target: str, timeout: float = 45.0) -> None:
        deadline = time.time() + timeout
        markers = ("\u276f", "\u256d", "tip:", "tips:", "/help", "cursor agent")
        while time.time() < deadline:
            ok, text = capture_pane(target, 80)
            lower = text.lower() if ok else ""
            # Cursor Agent asks once per new workspace. Loom creates isolated
            # task workdirs, so accept this prompt automatically; otherwise
            # the subsequent deep-interview paste lands on the trust screen.
            if "trust this workspace" in lower:
                # Enter activates the preselected "Trust" row without leaking
                # the shortcut letter `a` into the first chat prompt.
                send_pane_key(target, "Enter")
                time.sleep(2)
                continue
            if ok and any(m in lower for m in markers):
                time.sleep(2)
                return
            time.sleep(2)

    def _watch_for_session_id(
        self,
        project_root: Path,
        slug: str,
        cwd: Path,
        agent: str,
        existing_ids: set[str],
    ) -> None:
        """Poll the agent's session dir for a freshly-written session file."""
        deadline = time.time() + 90.0
        while time.time() < deadline:
            for p in list_session_files(cwd, agent):
                sid = session_id_from_path(p, agent)
                if sid and sid not in existing_ids:
                    add_claude_session(project_root, slug, sid)
                    return
            time.sleep(2)

    def _paste_prompt_and_watch_session(
        self,
        project_root: Path,
        slug: str,
        target: str,
        cwd: Path,
        agent: str,
        existing_ids: set[str],
        default_skills: Path | None = None,
    ) -> None:
        # Give the CLI a short chance to paint its input prompt, but do not
        # wait 90s: if the readiness heuristic misses a newer Claude/Codex UI
        # the paste should still happen quickly.
        time.sleep(2)
        self._wait_for_claude_ready(target, timeout=12.0)
        result = self._paste_prompt_to_target(project_root, slug, target, default_skills=default_skills)
        if not result.get("ok"):
            print(
                f"[web] paste prompt failed slug={slug}: {result.get('error', 'unknown error')}",
                flush=True,
            )
        self._watch_for_session_id(project_root, slug, cwd, agent, existing_ids)

    def _paste_prompt_to_target(
        self,
        project_root: Path,
        slug: str,
        target: str,
        *,
        default_skills: Path | None = None,
    ) -> dict[str, Any]:
        prompt = _build_claude_prompt(project_root, slug, default_skills=default_skills)
        if not prompt:
            return {"ok": False, "error": "empty prompt", "target": target}
        ok, err = send_pane_text(target, prompt, submit=True)
        if ok:
            return {
                "ok": True,
                "target": target,
                "prompt_chars": len(prompt),
                "has_skills": "Default skills:\n---\n(none)" not in prompt,
            }
        return {"ok": False, "error": err or "paste failed", "target": target}


# --- Per-task run monitor ---------------------------------------------------

_MONITOR_POLL_SECONDS = 4.0
_MONITOR_CAPTURE_LINES = 160
# After a stop is reported, ignore further stops for this long - a guard
# against the working indicator flickering off for a single poll mid-turn.
_MONITOR_FIRE_COOLDOWN = 10.0
# Only treat the agent as *really* stopped once the "working" indicator has been
# gone for this many consecutive polls (~12s). This filters the brief flickers
# and short mid-turn pauses that otherwise caused spurious "stopped" pings - we
# only notify OpenClaw when the agent has genuinely finished and is waiting for
# input (i.e. actually needs your attention).
_MONITOR_STOP_CONFIRM_POLLS = 3

# Interactive agent CLIs (Claude Code / Codex) show an interrupt hint while
# actively working. When it disappears, the agent has stopped and is waiting
# for input - that running -> stopped edge is what the monitor fires on.
_AGENT_WORKING_RE = re.compile(
    r"(?:esc\s+to\s+interrupt|ctrl\s*\+\s*c\s+to\s+stop)",
    re.IGNORECASE,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _TaskMonitor:
    """Background poller that watches whether the task's agent pane is working.

    Edge-triggered on the *running -> stopped* transition: when the agent was
    actively working and then stops (waiting for input), it emits an OpenClaw
    event. If the pane is already idle when monitoring is switched on, nothing
    fires until the agent runs and then stops again.
    """

    def __init__(
        self,
        manager: "TaskMonitorManager",
        project_root: Path,
        project_id: str,
        slug: str,
        pattern: str = "",
    ) -> None:
        self.manager = manager
        self.project_root = project_root
        self.project_id = project_id
        self.slug = slug
        self.pattern = pattern  # retained for API/JSON compat; not used to match
        self._stop = threading.Event()
        self._was_working = False
        self._idle_polls = 0
        self._initialized = False
        self._last_fire_ts = 0.0
        self.last_fired = ""
        self.last_match = ""
        self.thread = threading.Thread(
            target=self._loop, name=f"loom-monitor-{slug}", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_alive(self) -> bool:
        return self.thread.is_alive() and not self._stop.is_set()

    def _current_target(self) -> str:
        meta = read_meta(self.project_root, self.slug)
        if meta is None:
            return ""
        return (getattr(meta, "tmux_interview_target", "") or "").strip()

    def _loop(self) -> None:
        if self._stop.wait(_MONITOR_POLL_SECONDS):
            return
        while not self._stop.is_set():
            try:
                target = self._current_target()
                if target:
                    ok, text = capture_pane(target, _MONITOR_CAPTURE_LINES)
                    if ok:
                        working = bool(_AGENT_WORKING_RE.search(text or ""))
                        if not self._initialized:
                            # Baseline only - never fire on the first read, so
                            # enabling on an already-idle pane stays silent.
                            self._was_working = working
                            self._idle_polls = 0 if working else 1
                            self._initialized = True
                        elif working:
                            self._was_working = True
                            self._idle_polls = 0
                        else:
                            # Not working: only count it as a real stop once the
                            # indicator has stayed gone for several consecutive
                            # polls, so a one-off flicker or short mid-turn pause
                            # doesn't fire a spurious notification.
                            self._idle_polls += 1
                            if self._was_working and self._idle_polls >= _MONITOR_STOP_CONFIRM_POLLS:
                                self._was_working = False
                                self._fire(text or "")
            except Exception as exc:  # noqa: BLE001
                print(f"[monitor] {self.slug} loop error: {exc}", flush=True)
            if self._stop.wait(_MONITOR_POLL_SECONDS):
                break

    @staticmethod
    def _tail_snippet(text: str) -> str:
        lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
        # Carry a generous chunk of the final output so OpenClaw can actually
        # summarize what the agent just did, not just the last couple of lines.
        return "\n".join(lines[-60:]).strip()[-5000:]

    def _fire(self, pane_text: str) -> None:
        now = time.time()
        if now - self._last_fire_ts < _MONITOR_FIRE_COOLDOWN:
            return
        self._last_fire_ts = now
        self.last_fired = _iso_now()
        self.last_match = "stopped"
        snippet = self._tail_snippet(pane_text)
        print(f"[monitor] {self.slug} agent stopped -> openclaw", flush=True)
        try:
            self.manager.openclaw.emit(
                "agent-stopped",
                instruction=(
                    f"Loom: the agent in task {self.slug} just stopped and is "
                    f"waiting for input. Its recent terminal output is in "
                    f"data.tail below — summarize for me what it just did / "
                    f"finished, then I can reply to this message to continue it."
                ),
                project_root=self.project_root,
                task_slug=self.slug,
                data={"event": "agent-stopped", "tail": snippet},
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[monitor] {self.slug} emit error: {exc}", flush=True)
        try:
            write_task_monitor(
                self.project_root,
                self.slug,
                enabled=True,
                pattern=self.pattern,
                last_fired=self.last_fired,
                last_match=self.last_match,
            )
        except Exception:  # noqa: BLE001
            pass


class TaskMonitorManager:
    """Owns per-task monitor threads keyed by ``(project_id, slug)``."""

    def __init__(self, openclaw_client: OpenClawClient) -> None:
        self.openclaw = openclaw_client
        self._monitors: dict[tuple[str, str], _TaskMonitor] = {}
        self._lock = threading.Lock()

    def enable(
        self,
        project_root: Path,
        project_id: str,
        slug: str,
        pattern: str,
    ) -> dict[str, Any]:
        pattern = (pattern or "").strip() or DEFAULT_MONITOR_PATTERN
        key = (project_id, slug)
        with self._lock:
            existing = self._monitors.pop(key, None)
            if existing is not None:
                existing.stop()
            mon = _TaskMonitor(self, project_root, project_id, slug, pattern)
            self._monitors[key] = mon
        mon.start()
        cur = read_task_monitor(project_root, slug)
        write_task_monitor(project_root, slug, enabled=True, pattern=pattern)
        return {
            "enabled": True,
            "running": True,
            "pattern": pattern,
            "default_pattern": DEFAULT_MONITOR_PATTERN,
            "last_fired": mon.last_fired or cur.get("last_fired", ""),
            "last_match": mon.last_match or cur.get("last_match", ""),
        }

    def disable(self, project_root: Path, project_id: str, slug: str) -> dict[str, Any]:
        key = (project_id, slug)
        with self._lock:
            mon = self._monitors.pop(key, None)
        if mon is not None:
            mon.stop()
        cur = read_task_monitor(project_root, slug)
        write_task_monitor(
            project_root,
            slug,
            enabled=False,
            pattern=cur.get("pattern", ""),
        )
        return self.status(project_root, project_id, slug)

    def status(self, project_root: Path, project_id: str, slug: str) -> dict[str, Any]:
        key = (project_id, slug)
        with self._lock:
            mon = self._monitors.get(key)
        cfg = read_task_monitor(project_root, slug)
        # Lazily resume a persisted-on monitor that isn't running yet (e.g.
        # after a server restart) so the toggle survives restarts.
        if (mon is None or not mon.is_alive()) and cfg.get("enabled"):
            return self.enable(project_root, project_id, slug, cfg.get("pattern", ""))
        running = bool(mon and mon.is_alive())
        return {
            "enabled": running,
            "running": running,
            "pattern": (mon.pattern if mon else cfg.get("pattern", "")) or DEFAULT_MONITOR_PATTERN,
            "default_pattern": DEFAULT_MONITOR_PATTERN,
            "last_fired": (mon.last_fired if (mon and mon.last_fired) else cfg.get("last_fired", "")),
            "last_match": (mon.last_match if (mon and mon.last_match) else cfg.get("last_match", "")),
        }

    def resume_enabled(self, projects: list[tuple[str, Path]]) -> int:
        """Start monitors for every task whose monitor.json has enabled=true.

        Called once at startup so the per-task Notify toggle survives a server
        restart without the user re-opening each task. *projects* is a list of
        ``(project_id, project_root)`` pairs.
        """
        started = 0
        for project_id, root in projects:
            try:
                metas = list_tasks(root)
            except Exception:  # noqa: BLE001
                continue
            for meta in metas:
                try:
                    cfg = read_task_monitor(root, meta.slug)
                    if cfg.get("enabled"):
                        self.enable(root, project_id, meta.slug, cfg.get("pattern", ""))
                        started += 1
                except Exception:  # noqa: BLE001
                    continue
        return started


# --- AR paper loop ----------------------------------------------------------

_AR_POLL_SECONDS = 5.0


def _ar_run_async(fn, *args: Any) -> None:
    """Run a long AR step off the request thread; it reports via ar.json."""
    threading.Thread(target=fn, args=args, daemon=True).start()


def _ar_headless_model(meta: Any) -> str:
    """Claude model for headless Studio idea generation.

    Idea generation still goes through ``claude -p``. Paper reviews use the
    fixed Cursor PDF reviewer panel defined in ``ar_task.py``.
    """
    if meta is not None and normalize_agent(getattr(meta, "agent", "")) == AGENT_CLAUDE:
        model = str(getattr(meta, "interview_model", "") or "").strip()
        if model:
            return model
    return agent_default_model(AGENT_CLAUDE)


def _ar_merge_ideas(
    state: dict[str, Any], fresh: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Replace the proposed ideas with a new batch, keeping spawned ones.

    An idea that already has a child task is a commitment the user made, so a
    regenerate must not drop it or renumber it out from under the child.
    """
    kept = [
        i
        for i in (state.get("ideas") or [])
        if isinstance(i, dict) and i.get("status") == ar.IDEA_STATUS_SPAWNED
    ]
    taken = {str(i.get("id")) for i in kept}
    out = list(kept)
    for idea in fresh:
        base = idea["id"]
        candidate = base
        n = 2
        while candidate in taken:
            candidate = f"{base}-{n}"
            n += 1
        idea["id"] = candidate
        taken.add(candidate)
        out.append(idea)
    return out


def _ar_logger(root: Path, slug: str, job: str, *, reset: bool = True):
    """Append-only progress log for one AR job, tailed by the panel."""
    path = ar.job_log_path(root, slug, job)
    if reset:
        ar.reset_job_log(path)
    return lambda line: ar.append_job_log(path, line)


def _ar_mine_job(root: Path, slug: str, limit: int, venue_only: bool) -> None:
    state = ar.read_ar_state(root, slug)
    log = _ar_logger(root, slug, ar.JOB_PAPERS)
    log(
        f"querying arXiv for {ar.direction_label(state)} "
        f"(limit {limit}{', venue-tagged only' if venue_only else ''})"
    )
    res = ar.mine_papers(
        str(state.get("direction") or ""),
        str(state.get("custom_direction") or ""),
        limit=limit,
        venue_only=venue_only,
    )
    if res.get("ok"):
        log(f"query: {res.get('query', '')}")
        for paper in (res.get("papers") or [])[:10]:
            venue = f" [{paper['venue']}]" if paper.get("venue") else ""
            log(f"  {paper.get('published', '')}{venue} {paper.get('title', '')[:90]}")
        log(f"kept {len(res.get('papers') or [])} paper(s)")
    else:
        log(f"failed: {res.get('error')}")
    if res.get("ok"):
        ar.update_ar_state(
            root,
            slug,
            papers=res.get("papers") or [],
            papers_status="done",
            papers_error="",
            papers_query=res.get("query", ""),
            papers_updated_at=_iso_now(),
        )
        print(f"[ar] {slug}: mined {len(res.get('papers') or [])} paper(s)", flush=True)
    else:
        ar.update_ar_state(
            root, slug, papers_status="error", papers_error=str(res.get("error") or "")
        )
        print(f"[ar] {slug}: mining failed - {res.get('error')}", flush=True)


def _ar_ideas_job(root: Path, slug: str, count: int, model: str) -> None:
    state = ar.read_ar_state(root, slug)
    log = _ar_logger(root, slug, ar.JOB_IDEAS)
    res = ar.propose_ideas(
        state,
        ar.ar_skill_text(ar.SKILL_STUDIO),
        count=count,
        model=model,
        on_line=log,
    )
    if not res.get("ok"):
        log(f"failed: {res.get('error')}")
    if res.get("ok"):
        ar.update_ar_state(
            root,
            slug,
            ideas=_ar_merge_ideas(state, res.get("ideas") or []),
            ideas_status="done",
            ideas_error="",
            ideas_updated_at=_iso_now(),
        )
        print(f"[ar] {slug}: proposed {len(res.get('ideas') or [])} idea(s)", flush=True)
    else:
        ar.update_ar_state(
            root, slug, ideas_status="error", ideas_error=str(res.get("error") or "")
        )
        print(f"[ar] {slug}: idea generation failed - {res.get('error')}", flush=True)


def _ar_review_job(root: Path, slug: str) -> None:
    """One out-of-band review, triggered from the panel rather than the loop."""
    state = ar.read_ar_state(root, slug)
    paper_dir = ar.paper_root(root, slug)
    n = ar.current_round(state)
    log = _ar_logger(root, slug, ar.JOB_REVIEW)
    build = ar.build_pdf(paper_dir)
    log(
        "PDF built"
        if build.get("ok")
        else f"PDF build failed: {build.get('error')}"
    )
    res = ar.run_reviewer(
        paper_dir,
        ar.ar_skill_text(ar.SKILL_REVIEWER),
        venue=str(state.get("venue") or ar.DEFAULT_VENUE),
        round_n=max(1, n),
        build=build,
        models=ar.CURSOR_REVIEWER_MODELS,
        on_line=log,
    )
    if not res.get("ok"):
        log(f"failed: {res.get('error')}")
        readiness = res.get("readiness")
        if isinstance(readiness, dict):
            report_path = ar.round_dir(root, slug, n) / "readiness.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                report_path.write_text(
                    ar.review_readiness_markdown(readiness), encoding="utf-8"
                )
                readiness["report_path"] = str(report_path)
            except OSError:
                pass
            state = ar.read_ar_state(root, slug)
            rec = ar.ensure_round(state, n)
            rec["readiness"] = readiness
            state["review_status"] = "error"
            state["review_error"] = str(res.get("error") or "")
            ar.write_ar_state(root, slug, state)
        else:
            ar.update_ar_state(
                root,
                slug,
                review_status="error",
                review_error=str(res.get("error") or ""),
            )
        return
    path = ar.review_note_path(root, slug, n)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(str(res.get("review") or ""), encoding="utf-8")
    except OSError as exc:
        ar.update_ar_state(root, slug, review_status="error", review_error=str(exc))
        return
    state = ar.read_ar_state(root, slug)
    rec = ar.ensure_round(state, n)
    rec["review"] = {
        "created_at": _iso_now(),
        "model": ar.CURSOR_REVIEWER_PANEL,
        "models": res.get("models") or list(ar.CURSOR_REVIEWER_MODELS),
        "path": str(path),
        "scores": res.get("scores") or {},
        "headline": res.get("headline") or "",
        "input_pdf": res.get("input_pdf") or str(paper_dir / "main.pdf"),
        "reviewers": [
            {
                key: item.get(key)
                for key in ("model", "scores", "headline", "duration_seconds")
            }
            for item in (res.get("reviewers") or [])
        ],
    }
    state["review_status"] = "done"
    state["review_error"] = ""
    ar.write_ar_state(root, slug, state)


def _ar_spawn_children(
    root: Path,
    parent_slug: str,
    state: dict[str, Any],
    idea_ids: list[str],
    code_root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn selected idea cards into paper tasks, one task per idea."""
    parent = read_meta(root, parent_slug)
    venue = str(state.get("venue") or ar.DEFAULT_VENUE)
    spawned: list[dict[str, Any]] = []
    errors: list[str] = []

    for idea_id in idea_ids:
        idea = ar.find_idea(state, idea_id)
        if idea is None:
            errors.append(f"unknown idea {idea_id!r}")
            continue
        if idea.get("status") == ar.IDEA_STATUS_SPAWNED and idea.get("child_slug"):
            continue
        try:
            child = create_task(
                root,
                idea["title"],
                ar.idea_summary(idea),
                skills_path=(parent.skills_path if parent else ""),
                interview_model=(
                    parent.interview_model if parent else agent_default_model(AGENT_CURSOR)
                ),
                agent=(parent.agent if parent else AGENT_CURSOR),
                kind=ar.KIND_AR,
                auto_worktree=False,
            )
            prepare_task_worktree_from(root, child.slug, code_root)
            paper_dir = ar.paper_root(root, child.slug)
            seeded, msg = ar.seed_paper_skeleton(paper_dir, venue, idea)
            if not seeded:
                errors.append(f"{child.slug}: {msg}")
            paper_state = ar.new_paper_state(
                parent_slug=parent_slug,
                idea=idea,
                venue=venue,
                direction=str(state.get("direction") or ""),
                custom_direction=str(state.get("custom_direction") or ""),
                max_rounds=state.get("max_rounds", ar.DEFAULT_MAX_ROUNDS),
                author_model=(parent.interview_model if parent else ""),
                reviewer_model=ar.CURSOR_REVIEWER_PANEL,
                reviewer_models=ar.CURSOR_REVIEWER_MODELS,
            )
            paper_state["paper_dir"] = str(paper_dir)
            ar.write_ar_state(root, child.slug, paper_state)
            idea["status"] = ar.IDEA_STATUS_SPAWNED
            idea["child_slug"] = child.slug
            spawned.append(
                {"idea_id": idea_id, "slug": child.slug, "title": child.title}
            )
            print(f"[ar] {parent_slug}: spawned paper task {child.slug}", flush=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{idea_id}: {exc}")

    ar.write_ar_state(root, parent_slug, state)
    return spawned, errors


class _ARLoopDriver:
    """Drives one AR paper task through draft -> rounds -> final review.

    Phase 1 (the author) runs in the task's tmux pane, because writing a paper
    and running its experiments is interactive work that benefits from the full
    agent. Phase 2 (the reviewer) runs headlessly with a different model, so the
    review is genuinely a second opinion rather than the author grading itself.

    The handoff between the two is a file: the author writes
    ``rounds/round-NN/author.md`` as the last act of its turn, and this driver
    polls for it. Watching a file rather than pane text means a round survives a
    server restart, a killed pane, or an agent that stops talking mid-turn -
    the state on disk is always the truth.
    """

    def __init__(
        self,
        manager: "ARLoopManager",
        project_root: Path,
        project_id: str,
        slug: str,
    ) -> None:
        self.manager = manager
        self.project_root = project_root
        self.project_id = project_id
        self.slug = slug
        self.last_error = ""
        self.last_action = ""
        self._stop = threading.Event()
        self.thread = threading.Thread(
            target=self._loop, name=f"loom-ar-{slug}", daemon=True
        )

    # --- lifecycle ---

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_alive(self) -> bool:
        return self.thread.is_alive() and not self._stop.is_set()

    # --- helpers ---

    def _state(self) -> dict[str, Any]:
        return ar.read_ar_state(self.project_root, self.slug)

    def _save(self, state: dict[str, Any]) -> None:
        ar.write_ar_state(self.project_root, self.slug, state)

    def _note(self, action: str) -> None:
        self.last_action = action
        print(f"[ar] {self.slug}: {action}", flush=True)

    def _paper_dir(self) -> Path:
        return ar.paper_root(self.project_root, self.slug)

    def _paste(self, prompt: str) -> tuple[bool, str]:
        """Send a phase-1 prompt to the task's agent pane, starting it if needed.

        Spawning one paper task per idea would be pointless if each then had to
        be launched by hand, so the loop owns the pane's lifecycle: it starts
        one when there isn't one and lets the next tick do the paste, once the
        agent CLI has finished painting its prompt.
        """
        meta = read_meta(self.project_root, self.slug)
        if meta is None:
            return False, "task not found"
        target = (meta.tmux_interview_target or "").strip()
        if not target:
            started = self.manager.ensure_pane(
                self.project_root, self.project_id, self.slug
            )
            if not started.get("ok"):
                return False, f"could not start the agent pane: {started.get('error')}"
            self._note("started the agent pane")
            return False, "starting the agent pane…"
        self.manager.wait_until_ready(target)
        return send_pane_text(target, prompt, submit=True)

    def _emit(self, event: str, instruction: str, data: dict[str, Any]) -> None:
        try:
            self.manager.openclaw.emit(
                event,
                instruction=instruction,
                project_root=self.project_root,
                task_slug=self.slug,
                data=data,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ar] {self.slug} emit error: {exc}", flush=True)

    def _build(self) -> dict[str, Any]:
        paper_dir = self._paper_dir()
        build = ar.build_pdf(paper_dir)
        state = self._state()
        state["paper_dir"] = str(paper_dir)
        if build.get("ok"):
            state["pdf_path"] = str(build.get("pdf") or "")
            state["pdf_built_at"] = _iso_now()
            state["pdf_error"] = "" if build.get("clean") else "compiled with LaTeX errors"
        else:
            state["pdf_error"] = str(build.get("error") or "build failed")
        self._save(state)
        return build

    # --- stages ---

    def _tick_draft(self, state: dict[str, Any]) -> None:
        note = ar.author_note_path(self.project_root, self.slug, 0)
        if note.is_file():
            build = self._build()
            state = self._state()
            rec = ar.ensure_round(state, 0)
            rec["author"] = {
                "ended_at": _iso_now(),
                "note": str(note),
                "summary": _ar_read_head(note),
            }
            state["stage"] = ar.STAGE_AWAIT_DRAFT_REVIEW
            state["loop_running"] = False
            self._save(state)
            self._note("draft ready - waiting for the human draft gate")
            self._emit(
                "ar-draft-ready",
                (
                    f"Loom AR task {self.slug} finished its first draft and is "
                    "waiting for your review at the draft gate. Approve it in the "
                    "AR panel to open the author/reviewer loop."
                ),
                {
                    "event": "ar-draft-ready",
                    "pdf": state.get("pdf_path", ""),
                    "build_ok": bool(build.get("ok")),
                    "summary": rec["author"]["summary"],
                },
            )
            self.stop()
            return

        if state.get("draft_prompt_sent_at"):
            return
        paper_dir = self._paper_dir()
        if not (paper_dir / "main.tex").is_file():
            ok, msg = ar.seed_paper_skeleton(
                paper_dir, str(state.get("venue") or ar.DEFAULT_VENUE), state.get("idea")
            )
            if not ok:
                self.last_error = msg
                return
        note.parent.mkdir(parents=True, exist_ok=True)
        prompt = ar.author_draft_prompt(
            task_root(self.project_root, self.slug), paper_dir, state
        )
        ok, err = self._paste(prompt)
        if not ok:
            self.last_error = err
            return
        self.last_error = ""
        state["draft_prompt_sent_at"] = _iso_now()
        self._save(state)
        self._note("draft prompt sent to the agent pane")

    def _tick_loop(self, state: dict[str, Any]) -> None:
        n = ar.current_round(state)
        rec = ar.round_record(state, n) if n else None

        # A round is "open" until its review lands; anything else means we are
        # between rounds and should start the next one.
        if rec is None or rec.get("review"):
            self._start_round(state, n + 1)
            return

        readiness = rec.get("readiness")
        if isinstance(readiness, dict) and not readiness.get("ready"):
            # A failed completion note is archived. Wait for the author to
            # write a new one after receiving the deterministic failure list.
            note = ar.author_note_path(self.project_root, self.slug, n)
            if note.is_file():
                self._close_round(state, n, note)
            elif not readiness.get("repair_prompt_sent_at"):
                self._send_readiness_prompt(state, n)
            return

        # The author's note is the authoritative end-of-round signal, so check
        # it before the prompt bookkeeping: a round driven by hand, or one whose
        # prompt failed to paste and was sent another way, still closes.
        note = ar.author_note_path(self.project_root, self.slug, n)
        if note.is_file():
            self._close_round(state, n, note)
            return

        if not rec.get("prompt_sent_at"):
            self._send_round_prompt(state, n)

    def _start_round(self, state: dict[str, Any], n: int) -> None:
        if n > ar.max_rounds(state):
            state["stage"] = ar.STAGE_AWAIT_FINAL_REVIEW
            state["loop_running"] = False
            self._save(state)
            self._note(f"finished {n - 1} round(s) - waiting for the final human gate")
            review = ar.latest_review(state) or {}
            self._emit(
                "ar-loop-complete",
                (
                    f"Loom AR task {self.slug} finished all "
                    f"{ar.max_rounds(state)} author/reviewer rounds and is waiting "
                    "for your final review. Approve to deliver the paper, or send "
                    "it back for more rounds."
                ),
                {
                    "event": "ar-loop-complete",
                    "rounds": ar.max_rounds(state),
                    "last_review": review.get("headline", ""),
                    "pdf": state.get("pdf_path", ""),
                },
            )
            self.stop()
            return
        ar.ensure_round(state, n)
        state["round"] = n
        self._save(state)
        self._send_round_prompt(self._state(), n)

    def _send_round_prompt(self, state: dict[str, Any], n: int) -> None:
        previous = ar.round_record(state, n - 1) or {}
        review = previous.get("review") if isinstance(previous.get("review"), dict) else {}
        review_text = ""
        review_path = str((review or {}).get("path") or "")
        if review_path:
            try:
                review_text = Path(review_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                review_text = ""
        gate = ar.last_gate(state, ar.GATE_DRAFT) or {}
        final_gate = ar.last_gate(state, ar.GATE_FINAL) or {}
        note = str(final_gate.get("note") or "") if final_gate.get("decision") == "reject" else str(gate.get("note") or "")

        ar.round_dir(self.project_root, self.slug, n).mkdir(parents=True, exist_ok=True)
        prompt = ar.author_round_prompt(
            task_root(self.project_root, self.slug),
            self._paper_dir(),
            state,
            n,
            review_text=review_text,
            gate_note=note,
        )
        ok, err = self._paste(prompt)
        if not ok:
            self.last_error = err
            return
        self.last_error = ""
        state = self._state()
        rec = ar.ensure_round(state, n)
        rec["prompt_sent_at"] = _iso_now()
        state["round"] = n
        self._save(state)
        self._note(f"round {n} prompt sent to the agent pane")

    def _send_readiness_prompt(self, state: dict[str, Any], n: int) -> None:
        rec = ar.round_record(state, n) or {}
        readiness = (
            rec.get("readiness")
            if isinstance(rec.get("readiness"), dict)
            else {}
        )
        report_value = str(readiness.get("report_path") or "")
        prompt = ar.author_readiness_repair_prompt(
            task_root(self.project_root, self.slug),
            self._paper_dir(),
            state,
            n,
            readiness,
            report_path=Path(report_value) if report_value else None,
        )
        ok, err = self._paste(prompt)
        if not ok:
            self.last_error = err
            return
        self.last_error = ""
        state = self._state()
        rec = ar.ensure_round(state, n)
        latest = dict(rec.get("readiness") or {})
        latest["repair_prompt_sent_at"] = _iso_now()
        rec["readiness"] = latest
        self._save(state)
        self._note(f"round {n} readiness failures returned to the author")

    def _close_round(self, state: dict[str, Any], n: int, note: Path) -> None:
        self._note(f"round {n} author finished - checking submission readiness")
        build = self._build()

        state = self._state()
        rec = ar.ensure_round(state, n)
        readiness = ar.review_readiness(
            self._paper_dir(),
            venue=str(state.get("venue") or ar.DEFAULT_VENUE),
            build=build,
        )
        attempts = rec.setdefault("readiness_attempts", [])
        attempt_n = len(attempts) + 1
        report_path = (
            ar.round_dir(self.project_root, self.slug, n)
            / (
                "readiness.md"
                if readiness.get("ready")
                else f"readiness-attempt-{attempt_n:02d}.md"
            )
        )
        try:
            report_path.write_text(
                ar.review_readiness_markdown(readiness), encoding="utf-8"
            )
        except OSError as exc:
            self.last_error = f"could not write readiness report: {exc}"
            rec["review_error"] = self.last_error
            self._save(state)
            self.stop()
            return
        readiness["report_path"] = str(report_path)

        if not readiness.get("ready"):
            attempt_note = (
                ar.round_dir(self.project_root, self.slug, n)
                / f"author-attempt-{attempt_n:02d}.md"
            )
            summary = _ar_read_head(note)
            attempts.append(
                {
                    "attempt": attempt_n,
                    "ended_at": _iso_now(),
                    "note": str(attempt_note),
                    "summary": summary,
                    "report": str(report_path),
                    "failed": readiness.get("failed") or [],
                }
            )
            rec["readiness"] = readiness
            rec.pop("author", None)
            rec.pop("review_error", None)
            self._save(state)
            # Persist the blocked state before consuming author.md. If Loom
            # dies between these operations, restart sees the failed gate and
            # safely rechecks the still-present note instead of wedging.
            try:
                note.replace(attempt_note)
            except OSError as exc:
                self.last_error = f"could not archive blocked author note: {exc}"
                state = self._state()
                rec = ar.ensure_round(state, n)
                rec["review_error"] = self.last_error
                self._save(state)
                self.stop()
                return
            self._note(
                f"round {n} review blocked by {len(readiness.get('failed') or [])} "
                "readiness check(s)"
            )
            self._send_readiness_prompt(self._state(), n)
            return

        rec["author"] = {
            "ended_at": _iso_now(),
            "note": str(note),
            "summary": _ar_read_head(note),
        }
        rec["readiness"] = readiness
        rec.pop("review_error", None)
        self._save(state)
        self._note(f"round {n} readiness passed - starting reviewer panel")

        result = ar.run_reviewer(
            self._paper_dir(),
            ar.ar_skill_text(ar.SKILL_REVIEWER),
            venue=str(state.get("venue") or ar.DEFAULT_VENUE),
            round_n=n,
            build=build,
            readiness=readiness,
            models=ar.CURSOR_REVIEWER_MODELS,
            on_line=_ar_logger(self.project_root, self.slug, ar.JOB_REVIEW),
        )
        state = self._state()
        rec = ar.ensure_round(state, n)
        if not result.get("ok"):
            self.last_error = str(result.get("error") or "review failed")
            rec["review_error"] = self.last_error
            self._save(state)
            self._note(f"round {n} review failed: {self.last_error}")
            self.stop()
            return

        review_path = ar.review_note_path(self.project_root, self.slug, n)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            review_path.write_text(str(result.get("review") or ""), encoding="utf-8")
        except OSError as exc:
            self.last_error = f"could not write review: {exc}"
            self._save(state)
            return

        rec["review"] = {
            "created_at": _iso_now(),
            "model": ar.CURSOR_REVIEWER_PANEL,
            "models": result.get("models") or list(ar.CURSOR_REVIEWER_MODELS),
            "path": str(review_path),
            "scores": result.get("scores") or {},
            "headline": result.get("headline") or "",
            "input_pdf": result.get("input_pdf") or str(self._paper_dir() / "main.pdf"),
            "reviewers": [
                {
                    key: item.get(key)
                    for key in ("model", "scores", "headline", "duration_seconds")
                }
                for item in (result.get("reviewers") or [])
            ],
        }
        rec.pop("review_error", None)
        self._save(state)
        self._note(f"round {n} reviewed - {rec['review']['headline']}")
        self._emit(
            "ar-round-reviewed",
            (
                f"Loom AR task {self.slug} finished round {n} of "
                f"{ar.max_rounds(state)}: {rec['review']['headline']}."
            ),
            {
                "event": "ar-round-reviewed",
                "round": n,
                "scores": rec["review"]["scores"],
                "headline": rec["review"]["headline"],
            },
        )

    # --- main loop ---

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                state = self._state()
                if not ar.is_paper(state):
                    self.last_error = "not an AR paper task"
                    break
                stage = str(state.get("stage") or ar.STAGE_DRAFT)
                if stage == ar.STAGE_DRAFT:
                    self._tick_draft(state)
                elif stage == ar.STAGE_LOOP:
                    self._tick_loop(state)
                else:
                    # Waiting on a human, or delivered: nothing to drive.
                    break
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                print(f"[ar] {self.slug} loop error: {exc}", flush=True)
            if self._stop.wait(_AR_POLL_SECONDS):
                break
        state = self._state()
        if state.get("loop_running"):
            state["loop_running"] = False
            self._save(state)
        self.manager.forget(self.project_id, self.slug, self)


def _ar_read_text(path: Path, limit: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _ar_read_head(path: Path, lines: int = 40) -> str:
    text = _ar_read_text(path)
    return "\n".join(text.splitlines()[:lines]).strip()


class ARLoopManager:
    """Owns per-task AR driver threads keyed by ``(project_id, slug)``."""

    def __init__(
        self,
        openclaw_client: OpenClawClient,
        claude_registry: "ClaudeRegistry | None" = None,
        default_skills: Path | None = None,
    ) -> None:
        self.openclaw = openclaw_client
        self.registry = claude_registry
        self.default_skills = default_skills
        self._drivers: dict[tuple[str, str], _ARLoopDriver] = {}
        self._lock = threading.Lock()

    def ensure_pane(
        self, project_root: Path, project_id: str, slug: str
    ) -> dict[str, Any]:
        if self.registry is None:
            return {"ok": False, "error": "no agent registry - press Start Agent"}
        return self.registry.start(
            project_root, project_id, slug, default_skills=self.default_skills
        )

    def wait_until_ready(self, target: str, timeout: float = 12.0) -> None:
        if self.registry is not None:
            self.registry.wait_until_ready(target, timeout=timeout)

    def start(self, project_root: Path, project_id: str, slug: str) -> dict[str, Any]:
        state = ar.read_ar_state(project_root, slug)
        if not ar.is_paper(state):
            return {"ok": False, "error": "not an AR paper task"}
        stage = str(state.get("stage") or ar.STAGE_DRAFT)
        if stage in (ar.STAGE_AWAIT_DRAFT_REVIEW, ar.STAGE_AWAIT_FINAL_REVIEW):
            return {"ok": False, "error": f"waiting for you: {ar.STAGE_LABELS[stage]}"}
        if stage == ar.STAGE_DELIVERED:
            return {"ok": False, "error": "this paper has already been delivered"}
        key = (project_id, slug)
        with self._lock:
            existing = self._drivers.get(key)
            if existing is not None and existing.is_alive():
                return {"ok": True, "running": True, "note": "already running"}
            driver = _ARLoopDriver(self, project_root, project_id, slug)
            self._drivers[key] = driver
        ar.update_ar_state(project_root, slug, loop_running=True)
        driver.start()
        return {"ok": True, "running": True}

    def stop(self, project_root: Path, project_id: str, slug: str) -> dict[str, Any]:
        with self._lock:
            driver = self._drivers.pop((project_id, slug), None)
        if driver is not None:
            driver.stop()
        ar.update_ar_state(project_root, slug, loop_running=False)
        return {"ok": True, "running": False}

    def forget(self, project_id: str, slug: str, driver: "_ARLoopDriver") -> None:
        with self._lock:
            if self._drivers.get((project_id, slug)) is driver:
                self._drivers.pop((project_id, slug), None)

    def status(self, project_id: str, slug: str) -> dict[str, Any]:
        with self._lock:
            driver = self._drivers.get((project_id, slug))
        if driver is None:
            return {"running": False, "last_error": "", "last_action": ""}
        return {
            "running": driver.is_alive(),
            "last_error": driver.last_error,
            "last_action": driver.last_action,
        }

    @staticmethod
    def sweep_stale_jobs(projects: list[tuple[str, Path]]) -> int:
        """Clear AR jobs left ``running`` by a server that went away.

        Mining, idea generation and out-of-band reviews run in threads that do
        not survive a restart, and each endpoint refuses to start a second job
        while its status says running - so without this sweep a restart in the
        middle of one would wedge that task's button forever.
        """
        cleared = 0
        for _project_id, root in projects:
            try:
                metas = list_tasks(root)
            except Exception:  # noqa: BLE001
                continue
            for meta in metas:
                if not ar.is_ar_kind(meta.kind):
                    continue
                try:
                    state = ar.read_ar_state(root, meta.slug)
                except Exception:  # noqa: BLE001
                    continue
                changes: dict[str, Any] = {}
                for job in ("papers", "ideas", "review"):
                    if str(state.get(f"{job}_status") or "") == "running":
                        changes[f"{job}_status"] = "error"
                        changes[f"{job}_error"] = (
                            "interrupted by a Loom restart - run it again"
                        )
                if changes:
                    ar.update_ar_state(root, meta.slug, **changes)
                    cleared += 1
        return cleared

    def resume_running(self, projects: list[tuple[str, Path]]) -> int:
        """Restart drivers for papers whose ar.json says the loop was running.

        Round state lives on disk, so a resumed driver picks up exactly where
        the old one left off rather than restarting the round.
        """
        started = 0
        for project_id, root in projects:
            try:
                metas = list_tasks(root)
            except Exception:  # noqa: BLE001
                continue
            for meta in metas:
                if not ar.is_ar_kind(meta.kind):
                    continue
                try:
                    state = ar.read_ar_state(root, meta.slug)
                    if ar.is_paper(state) and state.get("loop_running"):
                        if self.start(root, project_id, meta.slug).get("ok"):
                            started += 1
                except Exception:  # noqa: BLE001
                    continue
        return started


# --- HTTP handler factory ---------------------------------------------------


class _TerminalStreamRegistry:
    """Route browser terminal input back through its own tmux attach PTY."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._masters: dict[str, int] = {}

    def register(self, master: int) -> str:
        stream_id = uuid.uuid4().hex
        with self._lock:
            self._masters[stream_id] = master
        return stream_id

    def unregister(self, stream_id: str, master: int) -> None:
        with self._lock:
            if self._masters.get(stream_id) == master:
                self._masters.pop(stream_id, None)

    def write(self, stream_id: str, text: str) -> tuple[bool, str]:
        if not re.fullmatch(r"[0-9a-f]{32}", stream_id):
            return False, "invalid terminal stream"
        data = text.encode("utf-8", errors="surrogatepass")
        if len(data) > 64 * 1024:
            return False, "terminal input too large"
        with self._lock:
            master = self._masters.get(stream_id)
            if master is None:
                return False, "terminal stream is not active"
            try:
                view = memoryview(data)
                while view:
                    written = os.write(master, view)
                    if written <= 0:
                        return False, "terminal stream closed"
                    view = view[written:]
            except OSError as exc:
                self._masters.pop(stream_id, None)
                return False, str(exc)
        return True, ""


def make_handler(
    project_registry: WebProjectRegistry,
    launch_root: Path,
    default_skills: Path,
    claude_registry: ClaudeRegistry,
    openclaw_client: OpenClawClient,
    auth_token: str = "",
    *,
    multi_project_workspace: bool = False,
    monitor_manager: "TaskMonitorManager | None" = None,
    ar_manager: "ARLoopManager | None" = None,
) -> type[BaseHTTPRequestHandler]:
    static_root = web_static_dir().resolve()
    required_token = auth_token.strip()
    pr = project_registry
    launch_root_resolved = launch_root.resolve()
    multi_ws = multi_project_workspace
    monitor_manager = monitor_manager or TaskMonitorManager(openclaw_client)
    ar_manager = ar_manager or ARLoopManager(
        openclaw_client, claude_registry, default_skills
    )
    terminal_streams = _TerminalStreamRegistry()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[web] {self.address_string()} - {fmt % args}", flush=True)

        def _send(self, status: int, body: bytes, headers: list[tuple[str, str]]) -> None:
            self.send_response(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        @staticmethod
        def _kill_pty(proc, master) -> None:
            """Detach the tmux attach client + close its PTY (terminal stream)."""
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                os.close(master)
            except Exception:
                pass

        def _resolve_scope(self, parsed) -> tuple[Path | None, str | None]:
            qs = parse_qs(parsed.query or "")
            qpid = (qs.get("project") or [""])[0].strip()
            hp = (self.headers.get("X-Loom-Project") or "").strip()
            pid = qpid or hp or pr.default_project_id
            if not pid:
                return None, None
            pth = pr.get_path(pid)
            if pth is None:
                return None, None
            return pth, pid

        def _bad_project(self) -> None:
            st, b, h = _json_bytes(
                {"error": "unknown or invalid project; pass ?project=<id> or header X-Loom-Project"},
                400,
            )
            self._send(st, b, h)

        # --- AR helpers ---

        def _ar_payload(self, root: Path, project_id: str, slug: str) -> dict[str, Any]:
            """Everything the AR panel renders for one task."""
            state = ar.read_ar_state(root, slug)
            paper_dir = ar.paper_root(root, slug)
            pdf = paper_dir / "main.pdf"
            payload: dict[str, Any] = {
                "ok": True,
                "slug": slug,
                "state": state,
                "catalog": ar.catalog(),
                "direction_label": ar.direction_label(state) if state else "",
                "paper_dir": str(paper_dir),
                "pdf_available": pdf.is_file(),
                "loop": ar_manager.status(project_id, slug),
                "logs": {
                    job: ar.read_job_log(ar.job_log_path(root, slug, job))
                    for job in (ar.JOB_PAPERS, ar.JOB_IDEAS, ar.JOB_REVIEW)
                },
            }
            if ar.is_paper(state):
                payload["stage_label"] = ar.progress_summary(state)
                payload["latest_review"] = ar.latest_review(state) or {}
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

            Mining and idea generation call a model and can run for minutes, so
            they hand off to a thread and report progress through ar.json; the
            panel polls GET /ar the same way it polls everything else.
            """
            if action == "mine":
                state, err = self._ar_require_state(root, slug, ar.ROLE_STUDIO)
                if state is None:
                    return {"ok": False, "error": err}, 400
                if str(state.get("papers_status")) == "running":
                    return {"ok": True, "status": "running"}, 202
                limit = max(5, min(100, int(body.get("limit", 40) or 40)))
                venue_only = bool(body.get("venue_only"))
                ar.update_ar_state(root, slug, papers_status="running", papers_error="")
                _ar_run_async(_ar_mine_job, root, slug, limit, venue_only)
                return {"ok": True, "status": "running"}, 202

            if action == "ideas":
                state, err = self._ar_require_state(root, slug, ar.ROLE_STUDIO)
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
                    return self._ar_payload(root, project_id, slug), 200
                if str(state.get("ideas_status")) == "running":
                    return {"ok": True, "status": "running"}, 202
                count = max(1, min(12, int(body.get("count", 6) or 6)))
                meta = read_meta(root, slug)
                model = str(body.get("model", "")).strip() or _ar_headless_model(meta)
                ar.update_ar_state(root, slug, ideas_status="running", ideas_error="")
                _ar_run_async(_ar_ideas_job, root, slug, count, model)
                return {"ok": True, "status": "running"}, 202

            if action == "spawn":
                state, err = self._ar_require_state(root, slug, ar.ROLE_STUDIO)
                if state is None:
                    return {"ok": False, "error": err}, 400
                raw_ids = body.get("idea_ids")
                idea_ids = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
                if not idea_ids:
                    return {"ok": False, "error": "select at least one idea"}, 400
                code_root = pr.get_code_root(project_id) or root
                spawned, errors = _ar_spawn_children(
                    root, slug, state, idea_ids, code_root
                )
                payload = self._ar_payload(root, project_id, slug)
                payload["spawned"] = spawned
                payload["errors"] = errors
                return payload, 200

            if action in ("draft", "loop/start"):
                state, err = self._ar_require_state(root, slug, ar.ROLE_PAPER)
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
                res = ar_manager.start(root, project_id, slug)
                if not res.get("ok"):
                    return res, 409
                payload = self._ar_payload(root, project_id, slug)
                payload["started"] = True
                return payload, 200

            if action == "loop/stop":
                ar_manager.stop(root, project_id, slug)
                return self._ar_payload(root, project_id, slug), 200

            if action == "gate":
                state, err = self._ar_require_state(root, slug, ar.ROLE_PAPER)
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
                ar.write_ar_state(root, slug, state)
                if str(state.get("stage")) == ar.STAGE_LOOP:
                    ar_manager.start(root, project_id, slug)
                return self._ar_payload(root, project_id, slug), 200

            if action == "review":
                state, err = self._ar_require_state(root, slug, ar.ROLE_PAPER)
                if state is None:
                    return {"ok": False, "error": err}, 400
                if str(state.get("review_status")) == "running":
                    return {"ok": True, "status": "running"}, 202
                ar.update_ar_state(root, slug, review_status="running", review_error="")
                _ar_run_async(_ar_review_job, root, slug)
                return {"ok": True, "status": "running"}, 202

            if action == "submission":
                state, err = self._ar_require_state(root, slug, ar.ROLE_PAPER)
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
                out = self._ar_payload(root, project_id, slug)
                out["submission"] = payload
                return out, 200

            if action == "build":
                state, err = self._ar_require_state(root, slug, ar.ROLE_PAPER)
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
                payload = self._ar_payload(root, project_id, slug)
                payload["build"] = {
                    k: build.get(k)
                    for k in ("ok", "clean", "bytes", "error", "missing_packages")
                }
                payload["latex_errors"] = ar.latex_errors(str(build.get("log") or ""))
                return payload, 200

            return {"ok": False, "error": f"unknown AR action {action!r}"}, 404

        def _is_authorized(self) -> bool:
            if not required_token:
                return True
            raw = self.headers.get("Authorization", "").strip()
            if raw.lower().startswith("bearer "):
                token = raw[7:].strip()
                return hmac.compare_digest(token, required_token)
            if raw.lower().startswith("basic "):
                encoded = raw[6:].strip()
                try:
                    decoded = base64.b64decode(encoded).decode("utf-8")
                except (binascii.Error, ValueError, UnicodeDecodeError):
                    return False
                _, _, password = decoded.partition(":")
                return hmac.compare_digest(password, required_token)
            return False

        def _require_auth(self) -> bool:
            if self._is_authorized():
                return True
            body = b"authentication required\n"
            self.send_response(401)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("WWW-Authenticate", 'Basic realm="Loom"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return False

        def _claude_session_summary(self, project_id: str, slug: str, meta) -> dict[str, Any]:
            agent = normalize_agent(meta.agent)
            root = pr.get_path(project_id)
            # A session can live under the current pane cwd (work/) OR under any
            # worktree where a pane was historically launched. Scan them all so
            # Resume finds every session this task ever spawned.
            candidates: list[Path] = []
            for c in (
                _task_pane_cwd(root, slug, meta),
                *list_task_worktrees(root, slug),
                task_root(root, slug),
            ):
                if c and c not in candidates:
                    candidates.append(c)
            files_by_id: dict[str, dict[str, Any]] = {}
            for cwd in candidates:
                for p in list_session_files(cwd, agent):
                    sid = session_id_from_path(p, agent)
                    if not sid:
                        continue
                    try:
                        stat = p.stat()
                    except OSError:
                        continue
                    prev = files_by_id.get(sid)
                    if prev is None or stat.st_mtime >= prev.get("mtime", 0.0):
                        files_by_id[sid] = {
                            "id": sid,
                            "path": str(p),
                            "mtime": stat.st_mtime,
                            "size": stat.st_size,
                        }
            # Preserve task-meta order (history of who-was-spawned-when)
            # but enrich with on-disk info.
            ordered = []
            seen: set[str] = set()
            for sid in meta.claude_session_ids:
                if sid in files_by_id:
                    ordered.append(files_by_id[sid])
                else:
                    ordered.append({"id": sid, "path": "", "mtime": 0.0, "size": 0})
                seen.add(sid)
            for sid, info in files_by_id.items():
                if sid not in seen:
                    ordered.append(info)
            ordered.sort(key=lambda x: x.get("mtime", 0.0), reverse=True)
            live = claude_registry.session_status(
                project_id, slug, agent, meta.tmux_interview_target or ""
            )
            return {
                "agent": agent,
                "agent_label": agent_label(agent),
                "tracked": [sid for sid in meta.claude_session_ids],
                "sessions": ordered,
                "tmux_alive": live["tmux_alive"],
                "pane_command": live["pane_command"],
                "agent_running": live["agent_running"],
                "tmux_session": live["session"],
                "tmux_target": meta.tmux_interview_target or "",
                "claude_cwd": str(cwd),
            }

        # ===== GET =====

        def do_GET(self) -> None:  # noqa: N802
            if not self._require_auth():
                return
            parsed = urlparse(self.path)
            path = parsed.path

            if path in ("/", "/index.html"):
                idx = static_root / "index.html"
                if not idx.is_file():
                    st, b, h = _text_bytes("missing index.html", 500)
                    self._send(st, b, h)
                    return
                st, b, h = _text_bytes(
                    idx.read_text(encoding="utf-8"),
                    content_type="text/html; charset=utf-8",
                )
                # Never let the browser reuse a stale index.html - it
                # references the versioned app.css/app.js, so the entry
                # document must always be fresh.
                h.append(("Cache-Control", "no-store, must-revalidate"))
                self._send(st, b, h)
                return

            if path.startswith("/static/"):
                sp = _safe_static_path(static_root, path)
                if sp is None:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                mime = (
                    _STATIC_MIME.get(sp.suffix)
                    or mimetypes.guess_type(str(sp))[0]
                    or "application/octet-stream"
                )
                st, b, h = _text_bytes(sp.read_bytes(), content_type=mime)
                # Assets are cache-busted via ?v=... in index.html; still tell
                # the browser to revalidate so edits show up without a hard refresh.
                h.append(("Cache-Control", "no-cache"))
                self._send(st, b, h)
                return

            if path == "/api/project":
                root, pid = self._resolve_scope(parsed)
                if root is None or pid is None:
                    self._bad_project()
                    return
                sk = default_skills.resolve()
                st, b, h = _json_bytes(
                    {
                        "projectRoot": str(root),
                        "projectId": pid,
                        "codeRootPattern": pr.get_code_root_pattern(pid),
                        "codeRootPath": str(pr.get_code_root(pid) or root),
                        "skillsPath": str(sk),
                        "skillsBundledRelative": "loom/skills/charlie_skills.md",
                        "skillsOptions": _available_skill_options(sk, root),
                        "modelDefaults": {
                            agent: agent_default_model(agent)
                            for agent in sorted(SUPPORTED_AGENTS)
                        },
                        "modelOptions": {
                            agent: list(agent_model_options(agent))
                            for agent in sorted(SUPPORTED_AGENTS)
                        },
                    }
                )
                self._send(st, b, h)
                return

            if path == "/api/projects":
                if multi_ws:
                    pr.prune_redundant_parent_projects(launch_root_resolved)
                cur_id = (parse_qs(parsed.query or "").get("project") or [""])[0].strip()
                hdr = (self.headers.get("X-Loom-Project") or "").strip()
                resolved = cur_id or hdr or pr.default_project_id
                cur_path = pr.get_path(resolved) if resolved else None
                current = resolved if (resolved and cur_path) else ""
                st, b, h = _json_bytes(
                    {
                        "projects": pr.list_projects(),
                        "defaultProjectId": pr.default_project_id,
                        "currentProjectId": current,
                        "launchRoot": str(launch_root_resolved),
                        "launchRootChildren": _launch_root_child_dirs(launch_root_resolved),
                        "multiProjectWorkspace": multi_ws,
                    }
                )
                self._send(st, b, h)
                return

            if path == "/api/notes":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                st, b, h = _json_bytes({"content": read_project_notes(root)})
                self._send(st, b, h)
                return

            if path == "/api/tmux/sessions":
                qs = parse_qs(parsed.query or "")
                proj = (qs.get("project") or [""])[0].strip()
                all_sessions = list_tmux_sessions()
                if proj:
                    p_root = pr.get_path(proj)
                    sessions = _filter_tmux_sessions_for_project(all_sessions, proj, p_root)
                else:
                    sessions = all_sessions
                st, b, h = _json_bytes({"tmux": tmux_available(), "sessions": sessions})
                self._send(st, b, h)
                return

            if path == "/api/tmux/panes":
                qs = parse_qs(parsed.query or "")
                sess = (qs.get("session") or [""])[0].strip()
                if not sess:
                    st, b, h = _json_bytes({"error": "session required"}, 400)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes({"panes": list_tmux_panes(sess)})
                self._send(st, b, h)
                return

            if path == "/api/tmux/capture":
                qs = parse_qs(parsed.query or "")
                target = (qs.get("target") or [""])[0].strip()
                lines = int((qs.get("lines") or ["80"])[0] or 80)
                if not validate_tmux_target(target):
                    st, b, h = _json_bytes({"ok": False, "error": "invalid target", "text": ""}, 400)
                    self._send(st, b, h)
                    return
                ok, text = capture_pane(target, lines)
                st, b, h = _json_bytes({"ok": ok, "text": text if ok else "", "error": "" if ok else text})
                self._send(st, b, h)
                return

            if path == "/api/tmux/stream":
                import select as _select

                qs = parse_qs(parsed.query or "")
                target = (qs.get("target") or [""])[0].strip()
                try:
                    cols = int((qs.get("cols") or ["80"])[0] or 80)
                    rows = int((qs.get("rows") or ["24"])[0] or 24)
                except ValueError:
                    cols, rows = 80, 24
                if not validate_tmux_target(target):
                    st, b, h = _json_bytes({"ok": False, "error": "invalid target"}, 400)
                    self._send(st, b, h)
                    return
                proc, master = open_pane_attach(target, cols, rows)
                if proc is None or master is None:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "could not attach to pane"}, 502
                    )
                    self._send(st, b, h)
                    return
                stream_id = terminal_streams.register(master)
                self.close_connection = True
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Accel-Buffering", "no")
                    self.send_header("X-Loom-Terminal-Stream", stream_id)
                    self.send_header("Connection", "close")
                    self.end_headers()
                except OSError:
                    terminal_streams.unregister(stream_id, master)
                    self._kill_pty(proc, master)
                    return
                conn = self.connection
                try:
                    while True:
                        if proc.poll() is not None:
                            try:
                                while True:
                                    data = os.read(master, 65536)
                                    if not data:
                                        break
                                    self.wfile.write(data)
                            except OSError:
                                pass
                            break
                        r, _, _ = _select.select([master, conn], [], [], 30)
                        if conn in r:
                            try:
                                probe = conn.recv(4096)
                            except OSError:
                                probe = b""
                            if not probe:
                                break  # client closed the stream
                        if master in r:
                            try:
                                data = os.read(master, 65536)
                            except OSError:
                                break
                            if not data:
                                break
                            self.wfile.write(data)
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    terminal_streams.unregister(stream_id, master)
                    self._kill_pty(proc, master)
                return

            if path == "/api/tasks":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                st, b, h = _json_bytes({"tasks": [m.to_dict() for m in list_tasks(root)]})
                self._send(st, b, h)
                return

            m_ki = re.match(r"^/api/tasks/([^/]+)/kernel-interview$", path)
            if m_ki:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m_ki.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(read_kernel_interview(root, slug))
                self._send(st, b, h)
                return

            if path == "/api/ar/catalog":
                st, b, h = _json_bytes(ar.catalog())
                self._send(st, b, h)
                return

            if path == "/api/asset":
                # Figures referenced by a rendered markdown document. `task`
                # scopes the lookup to one task directory; without it the base
                # is the project's .RUD/ root, which is where NOTES.md lives.
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                qs = parse_qs(parsed.query or "")
                rel = (qs.get("path") or [""])[0]
                slug = (qs.get("task") or [""])[0].strip()
                if slug and not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                base = task_root(root, slug) if slug else rud_root(root)
                found = read_markdown_asset(base, rel)
                if found is None:
                    st, b, h = _json_bytes({"error": "asset not found"}, 404)
                    self._send(st, b, h)
                    return
                data, ctype = found
                self._send(
                    200,
                    data,
                    [
                        ("Content-Type", ctype),
                        ("Content-Length", str(len(data))),
                        # An SVG rendered in <img> can't run scripts, but one
                        # opened directly at this URL would inherit the app's
                        # origin, so neuter it either way.
                        ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"),
                        ("X-Content-Type-Options", "nosniff"),
                        # Figures get regenerated in place; revalidate so the
                        # preview never shows a stale one.
                        ("Cache-Control", "no-cache"),
                    ],
                )
                return

            m_ar_pdf = re.match(r"^/api/tasks/([^/]+)/ar/pdf$", path)
            if m_ar_pdf:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m_ar_pdf.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                pdf, err = self._ar_resolve_pdf(root, slug)
                if pdf is None:
                    st, b, h = _json_bytes({"ok": False, "error": err}, 404)
                    self._send(st, b, h)
                    return
                try:
                    body = pdf.read_bytes()
                except OSError as exc:
                    st, b, h = _json_bytes({"ok": False, "error": str(exc)}, 500)
                    self._send(st, b, h)
                    return
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
                return

            m_ar_review = re.match(r"^/api/tasks/([^/]+)/ar/review/(\d+)$", path)
            if m_ar_review:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m_ar_review.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                n = int(m_ar_review.group(2))
                path_n = ar.review_note_path(root, slug, n)
                if not path_n.is_file():
                    st, b, h = _json_bytes(
                        {"ok": False, "error": f"no review for round {n}"}, 404
                    )
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(
                    {"ok": True, "round": n, "review": _ar_read_text(path_n)}
                )
                self._send(st, b, h)
                return

            m_ar = re.match(r"^/api/tasks/([^/]+)/ar$", path)
            if m_ar:
                root, pid = self._resolve_scope(parsed)
                if root is None or pid is None:
                    self._bad_project()
                    return
                slug = m_ar.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(self._ar_payload(root, pid, slug))
                self._send(st, b, h)
                return

            if path == "/api/kernel/plugins":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                ok, data = _run_kernel_helper(root, ["plugins"], timeout=30)
                if ok:
                    task_slug = (parse_qs(parsed.query or "").get("task") or [""])[0].strip()
                    if task_slug and _SLUG_RE.match(task_slug):
                        task_plugins = _task_contract_plugins(root, task_slug)
                        data["plugins"] = list(dict.fromkeys([
                            *task_plugins,
                            *(data.get("plugins") or []),
                        ]))
                    data["unverified"] = sorted(_kernel_unverified_set(root))
                    data["clusters"] = [""] + sorted(_kernel_cluster_profiles())
                st, b, h = _json_bytes(data, 200 if ok else 502)
                self._send(st, b, h)
                return

            if path == "/api/kernel/service":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                qs_cluster = (parse_qs(parsed.query or "").get("cluster") or [""])[0].strip()
                if qs_cluster and qs_cluster not in _kernel_cluster_profiles():
                    qs_cluster = ""
                ok, data = _kernel_service_status_cached(root, qs_cluster)
                if isinstance(data, dict):
                    data["cluster"] = qs_cluster
                st, b, h = _json_bytes(data, 200 if ok else 502)
                self._send(st, b, h)
                return

            if path == "/api/kernel/runs":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                task = (parse_qs(parsed.query or "").get("task") or [""])[0].strip()
                st, b, h = _json_bytes({"runs": _kernel_list_records(root, task or None)})
                self._send(st, b, h)
                return

            m_klog = re.match(r"^/api/kernel/runs/([^/]+)/log$", path)
            if m_klog:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid = m_klog.group(1)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                lp = _kernel_run_log_path(root, run_uid)
                text = ""
                if lp.is_file():
                    try:
                        # tail (~24KB) so a long build log stays cheap to poll
                        text = lp.read_bytes()[-24000:].decode("utf-8", "replace")
                    except OSError:
                        text = ""
                st, b, h = _json_bytes({"log": text})
                self._send(st, b, h)
                return

            m_kalog = re.match(r"^/api/kernel/runs/([^/]+)/agents/([0-9]+)/log$", path)
            if m_kalog:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid, agent_idx = m_kalog.group(1), m_kalog.group(2)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid)
                rid = (rec or {}).get("run_id")
                if not rid:
                    st, b, h = _json_bytes({"ok": False, "error": "run not started yet"})
                    self._send(st, b, h)
                    return
                ok, data = _run_kernel_helper(
                    root,
                    ["agent-log", "--run-id", rid, "--agent", agent_idx, "--tail", "300"],
                    timeout=40,
                    cluster=_kernel_record_cluster(rec),
                )
                if ok and (data or {}).get("log"):
                    local_path = _kernel_mirror_agent_log(
                        root, rec or {}, agent_idx, str(data["log"])
                    )
                    if local_path:
                        data["local_path"] = local_path
                elif not ok and rec is not None:
                    local_log = _kernel_task_agent_dir(
                        root, str(rec.get("slug") or ""), run_uid, agent_idx
                    ) / "agent.log"
                    if local_log.is_file():
                        data = {
                            "ok": True,
                            "agent": agent_idx,
                            "log": local_log.read_text(encoding="utf-8", errors="replace"),
                            "local_path": str(local_log),
                            "source": "task-local mirror",
                        }
                        ok = True
                st, b, h = _json_bytes(data, 200 if ok else 200)  # soft-fail: UI shows data.error
                self._send(st, b, h)
                return

            m_kleader = re.match(r"^/api/kernel/runs/([^/]+)/leaderboard$", path)
            if m_kleader:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid = m_kleader.group(1)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid)
                if rec is None:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                rid = rec.get("run_id")
                if not rid:
                    st, b, h = _json_bytes({"ok": False, "error": "run not started yet"})
                    self._send(st, b, h)
                    return
                ok, status = _run_kernel_helper(
                    root, ["status", "--run-id", rid], timeout=30,
                    cluster=_kernel_record_cluster(rec),
                )
                if ok:
                    _kernel_merge_submissions(root, rec, status)
                st, b, h = _json_bytes(
                    status if ok else {"ok": False, "error": (status or {}).get("error", "status failed")},
                    200 if ok else 502,
                )
                self._send(st, b, h)
                return

            m_kbest = re.match(r"^/api/kernel/runs/([^/]+)/best-kernel$", path)
            if m_kbest:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid = m_kbest.group(1)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid)
                rid = (rec or {}).get("run_id")
                if not rid:
                    st, b, h = _json_bytes({"ok": False, "error": "run not started yet"})
                    self._send(st, b, h)
                    return
                ok, data = _run_kernel_helper(
                    root, ["best-kernel", "--run-id", rid], timeout=30,
                    cluster=_kernel_record_cluster(rec),
                )
                st, b, h = _json_bytes(data, 200 if ok else 502)
                self._send(st, b, h)
                return

            m_ksrc = re.match(r"^/api/kernel/runs/([^/]+)/kernel/([^/]+)$", path)
            if m_ksrc:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid, job_id = m_ksrc.group(1), m_ksrc.group(2)
                if not _KERNEL_ID_RE.match(job_id):
                    st, b, h = _json_bytes({"error": "invalid job id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid) if _KERNEL_ID_RE.match(run_uid) else None
                local_matches: list[Path] = []
                if rec is not None and rec.get("slug"):
                    local_matches = list(
                        (_kernel_task_run_dir(root, str(rec["slug"]), run_uid) / "agents").glob(
                            f"*/attempts/*-{job_id}.*"
                        )
                    )
                if local_matches:
                    source = local_matches[0].read_text(encoding="utf-8", errors="replace")
                    st, b, h = _json_bytes({
                        "ok": True,
                        "job_id": job_id,
                        "source": source,
                        "local_path": str(local_matches[0]),
                    })
                    self._send(st, b, h)
                    return
                ok, data = _run_kernel_helper(
                    root, ["kernel-source", "--job-id", job_id], timeout=30,
                    cluster=_kernel_record_cluster(rec),
                )
                st, b, h = _json_bytes(data, 200 if ok else 502)
                self._send(st, b, h)
                return

            m_krun = re.match(r"^/api/kernel/runs/([^/]+)$", path)
            if m_krun:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid = m_krun.group(1)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid)
                if rec is None:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                if rec.get("run_id") and rec.get("state") == "running":
                    ok, status = _run_kernel_helper(
                        root, ["status", "--run-id", rec["run_id"]], timeout=30,
                        cluster=_kernel_record_cluster(rec),
                    )
                    if ok:
                        _kernel_merge_submissions(root, rec, status)
                        rec["status"] = status
                        # The auto-terminate watcher finishes runs out-of-band
                        # (kills agents, postprocesses the winner) and nothing
                        # told this record - detect "all agents gone" and flip
                        # the state so the UI doesn't show a zombie "running".
                        age = time.time() - (rec.get("launched_at") or rec.get("created_at") or 0)
                        if (
                            status.get("agents_known")
                            and not status.get("agents_running")
                            and age > 180
                        ):
                            done = bool(status.get("best") or status.get("improvements"))
                            rec["state"] = "finished" if done else "stopped"
                            rec["finished_at"] = time.time()
                            _kernel_write_record(root, rec)
                            # Judge the winning kernel against EVALUATION.md
                            # (hard results + source review) once, on finish.
                            if done and not rec.get("judge"):
                                _kernel_judge_async(root, run_uid)
                                rec = _kernel_read_record(root, run_uid) or rec
                rec = _maybe_export_judged_kernel_async(root, rec)
                st, b, h = _json_bytes(rec)
                self._send(st, b, h)
                return

            m_wt_cand = re.match(r"^/api/tasks/([^/]+)/worktree-candidates$", path)
            if m_wt_cand:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_wt_cand.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                candidates = _project_worktree_candidates(pr, root, project_id)
                # Annotate each candidate with the destination path + a
                # flag the UI uses to disable rows that are already wired
                # in.  "Already created" means the dest dir is a registered
                # git worktree (so picking again would be a no-op).
                dest_parent = task_root(root, slug) / "work"
                existing_paths = {str(p) for p in list_task_worktrees(root, slug)}
                for c in candidates:
                    dest = dest_parent / Path(c["path"]).name
                    c["destination"] = str(dest)
                    c["already_created"] = str(dest.resolve()) in existing_paths
                st, b, h = _json_bytes(
                    {
                        "projectRoot": str(root),
                        "candidates": candidates,
                        "worktrees": list(meta.worktrees),
                    }
                )
                self._send(st, b, h)
                return

            m_diff = re.match(r"^/api/tasks/([^/]+)/diff$", path)
            if m_diff:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m_diff.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                meta = detect_and_persist_worktree(root, slug) or meta
                worktrees = task_worktree_diffs(root, slug)
                st, b, h = _json_bytes(
                    {
                        "slug": slug,
                        "worktrees": worktrees,
                    }
                )
                self._send(st, b, h)
                return

            m_mon_get = re.match(r"^/api/tasks/([^/]+)/monitor$", path)
            if m_mon_get:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_mon_get.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                if not read_meta(root, slug):
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(monitor_manager.status(root, project_id, slug))
                self._send(st, b, h)
                return

            m_conversation = re.match(r"^/api/tasks/([^/]+)/conversation$", path)
            if m_conversation:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_conversation.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                meta = detect_and_persist_worktree(root, slug) or meta
                summary = self._claude_session_summary(project_id, slug, meta)
                qs = parse_qs(parsed.query or "")
                requested_id = (qs.get("session") or [""])[0].strip()
                try:
                    limit = int((qs.get("limit") or ["160"])[0] or 160)
                except ValueError:
                    limit = 160
                limit = max(20, min(500, limit))
                selected_session: dict[str, Any] | None = None
                transcript_path: Path | None = None
                for candidate in summary.get("sessions") or []:
                    if requested_id and candidate.get("id") != requested_id:
                        continue
                    candidate_path = _conversation_transcript_path(
                        candidate, str(summary.get("agent") or "")
                    )
                    if candidate_path is not None:
                        selected_session = candidate
                        transcript_path = candidate_path
                        break

                active = bool(summary.get("agent_running"))
                working = False
                terminal_question: dict[str, Any] | None = None
                target = str(summary.get("tmux_target") or "").strip()
                if active and validate_tmux_target(target):
                    capture_ok, capture_text = capture_pane(target, 100)
                    if capture_ok:
                        working = bool(_AGENT_WORKING_RE.search(capture_text or ""))
                        terminal_question = _conversation_terminal_question(capture_text)

                if selected_session is None or transcript_path is None:
                    terminal_message = (
                        {
                            "id": f"terminal-question:{terminal_question['id']}",
                            "kind": "question",
                            "created_at": None,
                            "question": terminal_question,
                        }
                        if terminal_question is not None
                        else None
                    )
                    st, b, h = _json_bytes(
                        {
                            "ok": True,
                            "available": terminal_message is not None,
                            "agent": summary.get("agent"),
                            "online": active,
                            "working": working,
                            "session_id": requested_id or None,
                            "updated_at": int(time.time() * 1000)
                            if terminal_message is not None
                            else None,
                            "messages": [terminal_message] if terminal_message is not None else [],
                            "total": 1 if terminal_message is not None else 0,
                            "has_more": False,
                        }
                    )
                    self._send(st, b, h)
                    return

                all_messages = _parse_conversation_transcript(
                    transcript_path, str(summary.get("agent") or "")
                )
                visible_messages: list[dict[str, Any]] = []
                terminal_appended = False
                for original in all_messages[-limit:]:
                    message = dict(original)
                    if message.get("kind") == "tool":
                        tool = dict(message.get("tool") or {})
                        if not active and tool.get("status") == "running":
                            tool["status"] = "canceled"
                        message["tool"] = tool
                    elif message.get("kind") == "question":
                        question = dict(message.get("question") or {})
                        if not active and question.get("status") == "pending":
                            question["status"] = "canceled"
                        message["question"] = question
                    visible_messages.append(message)
                if terminal_question is not None and not any(
                    message.get("kind") == "question"
                    and (message.get("question") or {}).get("status") == "pending"
                    for message in all_messages
                ):
                    visible_messages.append(
                        {
                            "id": f"terminal-question:{terminal_question['id']}",
                            "kind": "question",
                            "created_at": None,
                            "question": terminal_question,
                        }
                    )
                    terminal_appended = True
                try:
                    transcript_stat = transcript_path.stat()
                    updated_at = int(transcript_stat.st_mtime * 1000)
                except OSError:
                    updated_at = None
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "available": True,
                        "agent": summary.get("agent"),
                        "online": active,
                        "working": working,
                        "session_id": selected_session.get("id"),
                        "updated_at": int(time.time() * 1000)
                        if terminal_appended
                        else updated_at,
                        "messages": visible_messages,
                        "total": len(all_messages) + (1 if terminal_appended else 0),
                        "has_more": len(all_messages) > min(limit, len(all_messages)),
                    }
                )
                self._send(st, b, h)
                return

            m_sessions = re.match(r"^/api/tasks/([^/]+)/claude-sessions$", path)
            if m_sessions:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_sessions.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                # Same back-fill so the live Claude info card always sees
                # the disk truth.
                meta = detect_and_persist_worktree(root, slug) or meta
                st, b, h = _json_bytes(self._claude_session_summary(project_id, slug, meta))
                self._send(st, b, h)
                return

            m = re.match(r"^/api/tasks/([^/]+)$", path)
            if m:
                root, project_id = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                # Back-fill worktree_path / branch on tasks that pre-date the
                # auto-worktree feature, or tasks where the user manually
                # added a worktree under work/ later on.
                meta = detect_and_persist_worktree(root, slug) or meta
                # The expensive bits are git-status-per-worktree and the
                # Claude session enrichment (tmux subprocess + filesystem
                # scan). Fan both out so they overlap with the synchronous
                # markdown reads below - on a typical task this brings the
                # endpoint from ~600-1500ms down to ~150-400ms.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    statuses_fut = pool.submit(list_task_worktree_statuses, root, slug)
                    summary_fut = (
                        pool.submit(self._claude_session_summary, project_id, slug, meta)
                        if project_id
                        else None
                    )
                    # Surface every top-level *.md file in the task directory.
                    # Normal tasks use PLAN.md; kernel tasks deliberately use
                    # WIKI.md as the shared worker/evaluator knowledge base.
                    md_names = list_task_markdown_files(root, slug)
                    templates: dict[str, str] = {}
                    for md_name in md_names:
                        content = read_task_markdown_file(root, slug, md_name)
                        if content is not None:
                            templates[md_name] = content
                    primary_md = KERNEL_WIKI if meta.kind == "kernel" else PLAN
                    if primary_md not in templates:
                        templates[primary_md] = read_template(root, slug, primary_md) or ""
                        if primary_md not in md_names:
                            md_names = [primary_md, *md_names]
                    elif primary_md in md_names:
                        md_names = [primary_md, *(name for name in md_names if name != primary_md)]
                    statuses = statuses_fut.result()
                    summary = summary_fut.result() if summary_fut is not None else None
                st, b, h = _json_bytes(
                    {
                        "meta": meta.to_dict(),
                        "task_root": str(task_root(root, slug)),
                        "plan_path": str(task_root(root, slug) / primary_md),
                        "templates": templates,
                        "task_markdown_files": md_names,
                        "claude": summary or {},
                        "worktree_statuses": statuses,
                        # Tasks carry absolute skill paths, so one moved or
                        # renamed checkout leaves them pointing at nothing.
                        # The prompt silently falls back to the default; tell
                        # the UI so it can stop presenting a dead file as the
                        # task's skill.
                        "skills_missing": [
                            str(p)
                            for p in split_skills_paths(meta.skills_path or "")
                            if not p.is_file()
                        ],
                    }
                )
                self._send(st, b, h)
                return

            st, b, h = _json_bytes({"error": "not found"}, 404)
            self._send(st, b, h)

        # ===== POST =====

        def do_POST(self) -> None:  # noqa: N802
            if not self._require_auth():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            body = _read_json(self)

            if path == "/api/kernel/runs":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                plugin = str(body.get("plugin", "")).strip()
                target = str(body.get("target", "")).strip()
                model = str(body.get("model", "")).strip()
                slug = str(body.get("slug", "")).strip()
                # Shape is optional: an explicit override when given, otherwise an
                # agent proposes one at launch (see _launch_kernel_run).
                shape = body.get("shape")
                if not plugin or not target or not model:
                    st, b, h = _json_bytes(
                        {"error": "plugin, target and model are required"}, 400
                    )
                    self._send(st, b, h)
                    return
                cluster = str(body.get("cluster", "") or "").strip()
                if cluster and cluster not in _kernel_cluster_profiles():
                    st, b, h = _json_bytes(
                        {"error": f"unknown cluster profile: {cluster}"}, 400
                    )
                    self._send(st, b, h)
                    return
                raw_run_mode = str(body.get("run_mode", "") or "").strip()
                run_mode = "optimize" if raw_run_mode == "optimize" else "scratch"
                starter_mode = (
                    "best-similar"
                    if raw_run_mode and run_mode == "optimize"
                    else (
                        "none"
                        if raw_run_mode
                        else str(body.get("starter_mode", "none") or "none")
                    )
                )
                run_uid = uuid.uuid4().hex[:12]
                cfg = {
                    "plugin": plugin,
                    "target": target,
                    "model": model,
                    "cluster": cluster,
                    "run_mode": run_mode,
                    "shape": shape if shape else None,
                    "n_agents": int(body.get("n_agents", 1) or 1),
                    "starter_mode": starter_mode,
                    "target_speedup": body.get("target_speedup"),
                    "auto_terminate": bool(body.get("auto_terminate", False)),
                    "poll_interval": int(body.get("poll_interval", 60) or 60),
                    "build": bool(body.get("build", False)),
                    "build_mode": bool(body.get("build_mode", False)),
                }
                if cfg["build_mode"]:
                    # correctness-first: stop at the first correct kernel; ignore speed
                    cfg["auto_terminate"] = True
                    if cfg["target_speedup"] is None:
                        cfg["target_speedup"] = 0
                rec = {
                    "id": run_uid,
                    "state": "launching",
                    "config": cfg,
                    "run_id": None,
                    "slug": slug or None,
                    "task_slug": slug or None,
                    "containers": [],
                    "created_at": time.time(),
                }
                _kernel_write_record(root, rec)
                _initialize_kernel_run_artifacts(root, rec)
                threading.Thread(
                    target=_launch_kernel_run, args=(root, run_uid, cfg), daemon=True
                ).start()
                st, b, h = _json_bytes({"ok": True, "id": run_uid, "state": "launching"}, 202)
                self._send(st, b, h)
                return

            m_kjudge = re.match(r"^/api/kernel/runs/([^/]+)/judge$", path)
            if m_kjudge:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid = m_kjudge.group(1)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid)
                if rec is None:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                judge_state = rec.get("judge") or {}
                judge_age = time.time() - float(judge_state.get("started_at") or 0)
                if judge_state.get("state") == "judging" and judge_age < 600:
                    st, b, h = _json_bytes({"ok": True, "state": "judging"}, 202)
                    self._send(st, b, h)
                    return
                _kernel_judge_async(root, run_uid)
                st, b, h = _json_bytes({"ok": True, "state": "judging"}, 202)
                self._send(st, b, h)
                return

            m_kstop = re.match(r"^/api/kernel/runs/([^/]+)/stop$", path)
            if m_kstop:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid = m_kstop.group(1)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid)
                if rec is None:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                result: dict[str, Any] = {"ok": True}
                if rec.get("run_id"):
                    _ok, result = _run_kernel_helper(
                        root, ["stop", "--run-id", rec["run_id"]], timeout=600,
                        cluster=_kernel_record_cluster(rec),
                    )
                rec["state"] = "stopped"
                _kernel_write_record(root, rec)
                st, b, h = _json_bytes({"ok": True, "stop": result, "run": rec})
                self._send(st, b, h)
                return

            if path == "/api/kernel/interview":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                msgs = body.get("messages", [])
                if not isinstance(msgs, list):
                    st, b, h = _json_bytes({"error": "messages must be a list"}, 400)
                    self._send(st, b, h)
                    return
                result = _kernel_interview_turn(msgs, str(body.get("model", "")))
                st, b, h = _json_bytes(result, 200 if result.get("ok") else 502)
                self._send(st, b, h)
                return

            m_ar_post = re.match(r"^/api/tasks/([^/]+)/ar/([a-z/-]+)$", path)
            if m_ar_post:
                root, pid = self._resolve_scope(parsed)
                if root is None or pid is None:
                    self._bad_project()
                    return
                slug = m_ar_post.group(1)
                action = m_ar_post.group(2)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                result, status = self._ar_action(root, pid, slug, action, body)
                st, b, h = _json_bytes(result, status)
                self._send(st, b, h)
                return

            if path == "/api/kernel/prepare":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                spec = body.get("spec") or {}
                if not isinstance(spec, dict):
                    st, b, h = _json_bytes({"error": "spec must be an object"}, 400)
                    self._send(st, b, h)
                    return
                slug = str(body.get("slug", "")).strip()
                prep_uid = uuid.uuid4().hex[:12]
                rec = {"id": prep_uid, "state": "resolving", "kind": "prepare",
                       "spec": spec, "slug": slug or None, "task_slug": slug or None,
                       "created_at": time.time()}
                _kernel_write_record(root, rec)
                threading.Thread(
                    target=_prepare_kernel_run, args=(root, prep_uid, spec), daemon=True
                ).start()
                st, b, h = _json_bytes({"ok": True, "id": prep_uid, "state": "resolving"}, 202)
                self._send(st, b, h)
                return

            if path == "/api/kernel/plugins/verify":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                name = str(body.get("name", "")).strip()
                if not name:
                    st, b, h = _json_bytes({"error": "name required"}, 400)
                    self._send(st, b, h)
                    return
                _kernel_set_unverified(root, name, False)
                st, b, h = _json_bytes({"ok": True, "name": name, "verified": True})
                self._send(st, b, h)
                return

            if path == "/api/tasks/reorder":
                root, _project_id = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                raw_slugs = body.get("slugs", [])
                if not isinstance(raw_slugs, list):
                    st, b, h = _json_bytes({"error": "slugs must be a list"}, 400)
                    self._send(st, b, h)
                    return
                ok_order, err_order = reorder_tasks(root, [str(x) for x in raw_slugs])
                if not ok_order:
                    st, b, h = _json_bytes({"error": err_order}, 400)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes({"ok": True, "tasks": [m.to_dict() for m in list_tasks(root)]})
                self._send(st, b, h)
                return

            if path == "/api/tasks":
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                title = str(body.get("title", "")).strip()
                general_goal = str(body.get("general_goal", "")).strip()
                kind = {"kernel": "kernel", "ar": ar.KIND_AR, "aris": ar.KIND_AR}.get(
                    str(body.get("kind", "")).strip().lower(), "agent"
                )
                ar_state: dict[str, Any] | None = None
                if kind == ar.KIND_AR:
                    ar_state = ar.new_studio_state(
                        direction=str(body.get("ar_direction", "")),
                        custom_direction=str(body.get("ar_custom_direction", "")),
                        venue=str(body.get("ar_venue", "")),
                        mode=str(body.get("ar_mode", "")),
                        seed_idea=str(body.get("ar_seed_idea", "")),
                        max_rounds=body.get("ar_max_rounds", ar.DEFAULT_MAX_ROUNDS),
                    )
                    # AR asks for the paper's content, not a goal to interview
                    # about, so derive the stored goal from the AR fields.
                    general_goal = general_goal or ar.default_general_goal(ar_state)
                if not title or not general_goal:
                    st, b, h = _json_bytes({"error": "title and general_goal required"}, 400)
                    self._send(st, b, h)
                    return
                # skills_path may be one path, a ;-joined string, or a list of
                # paths (multiple skills used together).
                raw_sp = body.get("skills_path")
                if isinstance(raw_sp, list):
                    raw_sp = SKILLS_PATH_SEP.join(str(x) for x in raw_sp)
                requested = [
                    p.resolve() for p in split_skills_paths(str(raw_sp or ""))
                    if p.is_file()
                ]
                if not requested:
                    requested = [
                        default_skills.resolve() if default_skills.is_file()
                        else bundled_skills_path().resolve()
                    ]
                skills_path = join_skills_paths(requested)
                raw_agent = str(body.get("agent", AGENT_CURSOR)).strip().lower()
                if raw_agent and raw_agent not in SUPPORTED_AGENTS:
                    st, b, h = _json_bytes(
                        {"error": f"agent must be one of {sorted(SUPPORTED_AGENTS)}"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                meta = create_task(
                    root,
                    title,
                    general_goal,
                    skills_path=skills_path,
                    interview_model=(
                        str(body.get("interview_model", "")).strip()
                        or agent_default_model(raw_agent or AGENT_CURSOR)
                    ),
                    agent=raw_agent or AGENT_CURSOR,
                    kind=kind,
                    auto_worktree=False,
                )
                if ar_state is not None:
                    ar.write_ar_state(root, meta.slug, ar_state)
                code_root = pr.get_code_root(project_id) or root
                wt, _branch, auto_msg = prepare_task_worktree_from(
                    root, meta.slug, code_root
                )
                meta = read_meta(root, meta.slug) or meta
                cands = _project_worktree_candidates(pr, root, project_id)
                hint = ""
                if not meta.worktree_path:
                    if not cands:
                        hint = (
                            f" (configured code root {code_root} is not a git repo)"
                        )
                    else:
                        hint = (
                            f" (auto-skip: {auto_msg}; {len(cands)} candidate(s) "
                            f"available - pick one via the Agent tab)"
                        )
                print(
                    f"[web] created task slug={meta.slug} dir={task_root(root, meta.slug)} "
                    f"worktree={meta.worktree_path or '(none)'} "
                    f"branch={meta.branch or '(none)'}{hint}",
                    flush=True,
                )
                openclaw_client.emit(
                    "task-created",
                    instruction=f"Loom task created: {meta.slug}",
                    project_root=root,
                    task_slug=meta.slug,
                    data={
                        "title": meta.title,
                        "taskDir": str(task_root(root, meta.slug)),
                        "projectId": project_id,
                        "worktree": meta.worktree_path or "",
                        "branch": meta.branch or "",
                    },
                )
                st, b, h = _json_bytes({"meta": meta.to_dict()}, 201)
                self._send(st, b, h)
                return

            if path == "/api/tmux/stream-input":
                stream_id = str(body.get("stream_id", "")).strip()
                text = body.get("text", "")
                if not isinstance(text, str):
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "text must be string"}, 400
                    )
                    self._send(st, b, h)
                    return
                ok, msg = terminal_streams.write(stream_id, text)
                st, b, h = (
                    _json_bytes({"ok": True})
                    if ok
                    else _json_bytes({"ok": False, "error": msg}, 409)
                )
                self._send(st, b, h)
                return

            if path == "/api/tmux/send-text":
                target = str(body.get("target", "")).strip()
                text = body.get("text", "")
                submit = bool(body.get("submit", False))
                if not isinstance(text, str):
                    st, b, h = _json_bytes({"ok": False, "error": "text must be string"}, 400)
                    self._send(st, b, h)
                    return
                ok, msg = send_pane_text(target, text, submit=submit)
                st, b, h = (
                    _json_bytes({"ok": True})
                    if ok
                    else _json_bytes({"ok": False, "error": msg}, 400)
                )
                self._send(st, b, h)
                return

            if path == "/api/tmux/send-key":
                target = str(body.get("target", "")).strip()
                key = str(body.get("key", "")).strip()
                ok, msg = send_pane_key(target, key)
                st, b, h = (
                    _json_bytes({"ok": True})
                    if ok
                    else _json_bytes({"ok": False, "error": msg}, 400)
                )
                self._send(st, b, h)
                return

            if path == "/api/tmux/send-literal":
                target = str(body.get("target", "")).strip()
                text = body.get("text", "")
                if not isinstance(text, str):
                    st, b, h = _json_bytes({"ok": False, "error": "text must be string"}, 400)
                    self._send(st, b, h)
                    return
                ok, msg = send_pane_literal(target, text)
                st, b, h = (
                    _json_bytes({"ok": True})
                    if ok
                    else _json_bytes({"ok": False, "error": msg}, 400)
                )
                self._send(st, b, h)
                return

            if path == "/api/tmux/scroll":
                target = str(body.get("target", "")).strip()
                direction = str(body.get("dir", "up")).strip()
                try:
                    lines = int(body.get("lines", 3))
                except (TypeError, ValueError):
                    lines = 3
                if not validate_tmux_target(target):
                    st, b, h = _json_bytes({"ok": False, "error": "invalid target"}, 400)
                    self._send(st, b, h)
                    return
                ok, msg = scroll_pane(target, direction, lines)
                st, b, h = (
                    _json_bytes({"ok": True})
                    if ok
                    else _json_bytes({"ok": False, "error": msg}, 400)
                )
                self._send(st, b, h)
                return

            if path == "/api/projects/reorder":
                raw_ids = body.get("ids", [])
                if not isinstance(raw_ids, list):
                    st, b, h = _json_bytes({"error": "ids must be a list"}, 400)
                    self._send(st, b, h)
                    return
                ok_order, err_order = pr.reorder([str(x) for x in raw_ids])
                if not ok_order:
                    st, b, h = _json_bytes({"error": err_order}, 400)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "projects": pr.list_projects(),
                        "defaultProjectId": pr.default_project_id,
                    }
                )
                self._send(st, b, h)
                return

            if path == "/api/projects":
                raw_path = str(body.get("path", "")).strip()
                mode = str(body.get("mode", "existing")).strip().lower()
                repo_url = str(body.get("repo_url", "")).strip()
                code_root_pattern = str(body.get("code_root_pattern", ".") or ".").strip()
                if not raw_path:
                    st, b, h = _json_bytes({"error": "path required"}, 400)
                    self._send(st, b, h)
                    return
                if mode in ("empty", "clone"):
                    # These create files on disk, so confine them to the launch
                    # directory tree (the modal promises nothing is written
                    # outside it). Registering an *existing* folder is unrestricted.
                    try:
                        dest = Path(raw_path).expanduser().resolve()
                    except OSError:
                        st, b, h = _json_bytes({"error": "invalid path"}, 400)
                        self._send(st, b, h)
                        return
                    if not _path_within(dest, launch_root_resolved):
                        st, b, h = _json_bytes(
                            {"error": f"new folders must be inside {launch_root_resolved}"}, 400
                        )
                        self._send(st, b, h)
                        return
                    if mode == "empty":
                        try:
                            dest.mkdir(parents=True, exist_ok=True)
                        except OSError as exc:
                            st, b, h = _json_bytes({"error": f"could not create folder: {exc}"}, 400)
                            self._send(st, b, h)
                            return
                    else:  # clone
                        if not repo_url:
                            st, b, h = _json_bytes({"error": "repo URL is required to clone"}, 400)
                            self._send(st, b, h)
                            return
                        ok_clone, msg_clone = _git_clone(repo_url, dest)
                        if not ok_clone:
                            st, b, h = _json_bytes({"error": msg_clone or "git clone failed"}, 400)
                            self._send(st, b, h)
                            return
                    raw_path = str(dest)
                try:
                    normalized_code_root = pr._normalize_code_root_pattern(code_root_pattern)
                except ValueError as exc:
                    st, b, h = _json_bytes({"error": str(exc)}, 400)
                    self._send(st, b, h)
                    return
                candidate_code_root = (Path(raw_path).expanduser().resolve() / normalized_code_root)
                if not candidate_code_root.is_dir():
                    st, b, h = _json_bytes(
                        {"error": f"code root directory does not exist: {candidate_code_root}"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                new_id, err = pr.add_by_path(raw_path, normalized_code_root)
                if err or not new_id:
                    st, b, h = _json_bytes({"error": err or "failed"}, 400)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(
                    {"id": new_id, "defaultProjectId": pr.default_project_id, "projects": pr.list_projects()},
                    201,
                )
                self._send(st, b, h)
                return

            m_code_root = re.match(r"^/api/projects/([^/]+)/code-root$", path)
            if m_code_root:
                pid_code = m_code_root.group(1)
                ok_code, err_code = pr.set_code_root_pattern(
                    pid_code, str(body.get("pattern", "."))
                )
                if not ok_code:
                    status = 404 if err_code == "project not found" else 400
                    st, b, h = _json_bytes({"error": err_code}, status)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes({
                    "ok": True,
                    "pattern": pr.get_code_root_pattern(pid_code),
                    "path": str(pr.get_code_root(pid_code) or ""),
                    "projects": pr.list_projects(),
                })
                self._send(st, b, h)
                return

            m_move = re.match(r"^/api/projects/([^/]+)/move$", path)
            if m_move:
                pid_move = m_move.group(1)
                direction = str(body.get("direction", "")).strip().lower()
                ok_move, err_move = pr.move(pid_move, direction)
                if not ok_move:
                    status = 404 if err_move == "project not found" else 400
                    st, b, h = _json_bytes({"error": err_move}, status)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "projects": pr.list_projects(),
                        "defaultProjectId": pr.default_project_id,
                    }
                )
                self._send(st, b, h)
                return

            m_activate = re.match(r"^/api/projects/([^/]+)/activate$", path)
            if m_activate:
                pid_act = m_activate.group(1)
                if not pr.set_default(pid_act):
                    st, b, h = _json_bytes({"error": "project not found"}, 404)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes({"ok": True, "defaultProjectId": pid_act})
                self._send(st, b, h)
                return

            # Claude pane lifecycle - the same two route prefixes were
            # called /interview/{start,stop} before the rename, accept both.
            m_start = re.match(r"^/api/tasks/([^/]+)/(?:claude|interview)/start$", path)
            if m_start:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_start.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                result = claude_registry.start(root, project_id, slug, default_skills=default_skills)
                print(
                    f"[web] start claude slug={slug} ok={bool(result.get('ok'))} "
                    f"session={result.get('session', '')} target={result.get('target', '')}",
                    flush=True,
                )
                openclaw_client.emit(
                    "claude-start",
                    instruction=f"Loom Claude pane started for task {slug}",
                    project_root=root,
                    task_slug=slug,
                    data=result,
                )
                st, b, h = (
                    _json_bytes(result)
                    if result.get("ok")
                    else _json_bytes(result, 400)
                )
                self._send(st, b, h)
                return

            m_paste = re.match(r"^/api/tasks/([^/]+)/(?:claude|interview)/paste-prompt$", path)
            if m_paste:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_paste.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                result = claude_registry.paste_prompt(
                    root,
                    project_id,
                    slug,
                    default_skills=default_skills,
                )
                st, b, h = (
                    _json_bytes(result)
                    if result.get("ok")
                    else _json_bytes(result, 400)
                )
                self._send(st, b, h)
                return

            m_stop = re.match(r"^/api/tasks/([^/]+)/(?:claude|interview)/stop$", path)
            if m_stop:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_stop.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                if not read_meta(root, slug):
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                result = claude_registry.stop(root, project_id, slug)
                openclaw_client.emit(
                    "claude-stop",
                    instruction=f"Loom Claude pane stopped for task {slug}",
                    project_root=root,
                    task_slug=slug,
                    data=result,
                )
                st, b, h = _json_bytes(result)
                self._send(st, b, h)
                return

            m_mon_post = re.match(r"^/api/tasks/([^/]+)/monitor$", path)
            if m_mon_post:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_mon_post.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                if not read_meta(root, slug):
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                pattern = str(body.get("pattern", "")).strip()
                if pattern:
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        st, b, h = _json_bytes({"error": f"invalid regex: {exc}"}, 400)
                        self._send(st, b, h)
                        return
                result = monitor_manager.enable(root, project_id, slug, pattern)
                print(
                    f"[web] monitor enabled slug={slug} pattern={result.get('pattern', '')!r}",
                    flush=True,
                )
                st, b, h = _json_bytes(result)
                self._send(st, b, h)
                return

            m_conversation_answer = re.match(
                r"^/api/tasks/([^/]+)/conversation/answer$", path
            )
            if m_conversation_answer:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_conversation_answer.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                target = (meta.tmux_interview_target or "").strip()
                if not validate_tmux_target(target):
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "no active agent pane for this task"},
                        409,
                    )
                    self._send(st, b, h)
                    return
                capture_ok, capture_text = capture_pane(target, 100)
                question = (
                    _conversation_terminal_question(capture_text)
                    if capture_ok
                    else None
                )
                question_id = str(body.get("question_id") or "").strip()
                selected_ids = body.get("selected_ids")
                custom_text = body.get("custom_text", "")
                if (
                    question is None
                    or not question_id
                    or question.get("id") != question_id
                ):
                    st, b, h = _json_bytes(
                        {
                            "ok": False,
                            "error": "the active terminal question has changed",
                        },
                        409,
                    )
                    self._send(st, b, h)
                    return
                if not isinstance(selected_ids, list) or not all(
                    isinstance(item, str) for item in selected_ids
                ):
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "selected_ids must be a string list"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                if not isinstance(custom_text, str) or len(custom_text) > 12000:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "custom_text must be at most 12000 characters"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                prompt = (question.get("questions") or [{}])[0]
                options_by_id = {
                    str(option.get("id")): option
                    for option in (prompt.get("options") or [])
                    if isinstance(option, dict)
                }
                other_selected = any(
                    option_id in options_by_id
                    and re.match(
                        r"^other\b",
                        str(options_by_id[option_id].get("label") or "").strip(),
                        re.IGNORECASE,
                    )
                    for option_id in selected_ids
                )
                if other_selected and not custom_text.strip():
                    st, b, h = _json_bytes(
                        {
                            "ok": False,
                            "error": "type a custom answer before submitting Other",
                        },
                        400,
                    )
                    self._send(st, b, h)
                    return
                if other_selected and len(selected_ids) != 1:
                    st, b, h = _json_bytes(
                        {
                            "ok": False,
                            "error": "Other cannot be combined with another option",
                        },
                        400,
                    )
                    self._send(st, b, h)
                    return
                keys = _conversation_terminal_answer_keys(
                    question,
                    selected_ids,
                    submit=not other_selected,
                )
                if not keys and not other_selected:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "select at least one valid option"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                for key in keys:
                    # Ink-based agent menus can drop Enter while processing the
                    # preceding cursor/checkbox render. Keep navigation snappy,
                    # but give selection and submit events time to settle.
                    if key == "Enter":
                        time.sleep(0.3)
                    ok, error = send_pane_key(target, key)
                    if not ok:
                        st, b, h = _json_bytes(
                            {"ok": False, "error": error or "could not answer question"},
                            400,
                        )
                        self._send(st, b, h)
                        return
                    time.sleep(0.14 if key == "Space" else 0.08)
                if other_selected:
                    # Selecting Other changes the menu into an inline text field.
                    # Typing must happen before Enter; an empty Enter is ignored.
                    time.sleep(0.3)
                    staged_ok, staged_text = capture_pane(target, 100)
                    staged_question = (
                        _conversation_terminal_question(staged_text)
                        if staged_ok
                        else None
                    )
                    staged_options = (
                        (staged_question.get("questions") or [{}])[0].get("options")
                        if staged_question is not None
                        else []
                    ) or []
                    other_ready = any(
                        str(option.get("id")) in selected_ids
                        and bool(option.get("selected"))
                        for option in staged_options
                        if re.match(
                            r"^other\b",
                            str(option.get("label") or "").strip(),
                            re.IGNORECASE,
                        )
                    )
                    if not other_ready:
                        st, b, h = _json_bytes(
                            {
                                "ok": False,
                                "error": "could not activate the Other text field",
                            },
                            409,
                        )
                        self._send(st, b, h)
                        return
                    ok, error = send_pane_text(
                        target,
                        custom_text.strip(),
                        submit=True,
                    )
                    if not ok:
                        st, b, h = _json_bytes(
                            {"ok": False, "error": error or "could not send custom answer"},
                            400,
                        )
                        self._send(st, b, h)
                        return
                    time.sleep(0.5)
                else:
                    time.sleep(0.25)
                after_ok, after_text = capture_pane(target, 100)
                after_question = (
                    _conversation_terminal_question(after_text) if after_ok else None
                )
                still_pending = bool(
                    after_question is not None
                    and after_question.get("id") == question.get("id")
                )
                print(
                    f"[web] conversation answer slug={slug} options={selected_ids!r} "
                    f"custom_chars={len(custom_text.strip())} pending={still_pending}",
                    flush=True,
                )
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "target": target,
                        "pending": still_pending,
                    }
                )
                self._send(st, b, h)
                return

            m_force_send = re.match(
                r"^/api/tasks/([^/]+)/claude/force-send$", path
            )
            if m_force_send:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_force_send.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                if normalize_agent(meta.agent) != AGENT_CURSOR:
                    st, b, h = _json_bytes(
                        {"error": "force send is supported only for Cursor Agent"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                live = claude_registry.session_status(
                    project_id,
                    slug,
                    meta.agent,
                    meta.tmux_interview_target or "",
                )
                target = (meta.tmux_interview_target or live.get("target") or "").strip()
                if not live.get("agent_running") or not validate_tmux_target(target):
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "no active Cursor Agent pane"},
                        409,
                    )
                    self._send(st, b, h)
                    return
                before_ok, before_text = capture_pane(target, 35)
                before_working = bool(
                    before_ok and _AGENT_WORKING_RE.search(before_text or "")
                )
                ok, error = send_pane_key(target, "Enter")
                if not ok:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": error or "force send failed"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                time.sleep(0.35)
                after_ok, after_text = capture_pane(target, 35)
                after_working = bool(
                    after_ok and _AGENT_WORKING_RE.search(after_text or "")
                )
                print(
                    f"[web] force-send slug={slug} before_working={before_working} "
                    f"after_working={after_working}",
                    flush=True,
                )
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "target": target,
                        "working": after_working,
                    }
                )
                self._send(st, b, h)
                return

            m_send = re.match(r"^/api/tasks/([^/]+)/claude/send$", path)
            if m_send:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_send.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                target = (meta.tmux_interview_target or "").strip()
                if not target:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": "no active Claude pane for this task"}, 409
                    )
                    self._send(st, b, h)
                    return
                text = body.get("text", "")
                if not isinstance(text, str) or not text:
                    st, b, h = _json_bytes({"ok": False, "error": "text required"}, 400)
                    self._send(st, b, h)
                    return
                submit = bool(body.get("submit", True))
                ok, msg = send_pane_text(target, text, submit=submit)
                print(
                    f"[web] inbound claude/send slug={slug} ok={ok} chars={len(text)}",
                    flush=True,
                )
                st, b, h = (
                    _json_bytes({"ok": True, "target": target})
                    if ok
                    else _json_bytes({"ok": False, "error": msg}, 400)
                )
                self._send(st, b, h)
                return

            m_wt_create = re.match(r"^/api/tasks/([^/]+)/worktree$", path)
            if m_wt_create:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_wt_create.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                if not read_meta(root, slug):
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                raw_src = str(body.get("source_repo", "")).strip()
                if not raw_src:
                    st, b, h = _json_bytes({"error": "source_repo required"}, 400)
                    self._send(st, b, h)
                    return
                # Whitelist against the project's candidate list so a
                # poisoned request can't make us run `git worktree add`
                # against an arbitrary path on disk.
                allowed = {
                    str(Path(c["path"]).resolve())
                    for c in _project_worktree_candidates(pr, root, project_id)
                }
                try:
                    src_resolved = str(Path(raw_src).expanduser().resolve())
                except OSError as exc:
                    st, b, h = _json_bytes({"error": f"invalid path: {exc}"}, 400)
                    self._send(st, b, h)
                    return
                if src_resolved not in allowed:
                    st, b, h = _json_bytes(
                        {
                            "error": "source_repo is not in the project's candidate list",
                            "allowed": sorted(allowed),
                        },
                        400,
                    )
                    self._send(st, b, h)
                    return
                wt, branch, msg = prepare_task_worktree_from(
                    root, slug, Path(src_resolved)
                )
                print(
                    f"[web] manual worktree slug={slug} src={src_resolved} "
                    f"ok={wt is not None} msg={msg}",
                    flush=True,
                )
                if wt is None:
                    st, b, h = _json_bytes(
                        {"ok": False, "error": msg, "branch": branch}, 400
                    )
                    self._send(st, b, h)
                    return
                # Append (or refresh) the worktree list from disk.  Don't
                # call update_meta directly so order / branches stay in
                # sync across the existing entries.
                updated = detect_and_persist_worktree(root, slug) or read_meta(root, slug)
                openclaw_client.emit(
                    "worktree-created",
                    instruction=f"Loom worktree created for task {slug}",
                    project_root=root,
                    task_slug=slug,
                    data={"source_repo": src_resolved, "worktree": str(wt), "branch": branch},
                )
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "worktree_path": str(wt),
                        "branch": branch,
                        "message": msg,
                        "meta": updated.to_dict() if updated else None,
                    }
                )
                self._send(st, b, h)
                return

            m_wt_push = re.match(r"^/api/tasks/([^/]+)/worktree/push$", path)
            if m_wt_push:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_wt_push.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                raw_path = str(body.get("path", "")).strip()
                if not raw_path:
                    st, b, h = _json_bytes({"error": "path required"}, 400)
                    self._send(st, b, h)
                    return
                try:
                    wt = Path(raw_path).expanduser().resolve()
                except OSError as exc:
                    st, b, h = _json_bytes({"error": f"invalid path: {exc}"}, 400)
                    self._send(st, b, h)
                    return
                if str(wt) not in meta.worktrees:
                    st, b, h = _json_bytes(
                        {"error": "worktree is not registered with this task"},
                        400,
                    )
                    self._send(st, b, h)
                    return
                result = push_worktree_branch(wt)
                # Refresh status snapshot so the UI can update ahead/behind.
                result["status"] = worktree_status(wt)
                print(
                    f"[web] push worktree slug={slug} path={wt} "
                    f"ok={result.get('ok')} branch={result.get('branch')}",
                    flush=True,
                )
                st, b, h = _json_bytes(result, 200 if result.get("ok") else 400)
                self._send(st, b, h)
                return

            m_wt_merge = re.match(r"^/api/tasks/([^/]+)/worktree/merge$", path)
            if m_wt_merge:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_wt_merge.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                raw_path = str(body.get("path", "")).strip()
                if not raw_path:
                    st, b, h = _json_bytes({"error": "path required"}, 400)
                    self._send(st, b, h)
                    return
                try:
                    wt = Path(raw_path).expanduser().resolve()
                except OSError as exc:
                    st, b, h = _json_bytes({"error": f"invalid path: {exc}"}, 400)
                    self._send(st, b, h)
                    return
                if str(wt) not in meta.worktrees:
                    st, b, h = _json_bytes(
                        {"error": "worktree is not registered with this task"}, 400
                    )
                    self._send(st, b, h)
                    return
                result = merge_worktree_to_base(wt)
                print(
                    f"[web] merge worktree slug={slug} path={wt} "
                    f"ok={result.get('ok')} {result.get('branch')}->{result.get('base')}",
                    flush=True,
                )
                st, b, h = _json_bytes(result, 200 if result.get("ok") else 400)
                self._send(st, b, h)
                return

            m_review = re.match(r"^/api/tasks/([^/]+)/review$", path)
            if m_review:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_review.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                raw_path = str(body.get("path", "")).strip()
                if not raw_path:
                    st, b, h = _json_bytes({"error": "path required"}, 400)
                    self._send(st, b, h)
                    return
                try:
                    wt = Path(raw_path).expanduser().resolve()
                except OSError as exc:
                    st, b, h = _json_bytes({"error": f"invalid path: {exc}"}, 400)
                    self._send(st, b, h)
                    return
                if str(wt) not in meta.worktrees:
                    st, b, h = _json_bytes(
                        {"error": "worktree is not registered with this task"}, 400
                    )
                    self._send(st, b, h)
                    return
                skills_text = load_skills_text(
                    meta.skills_path, default_skills, limit_total=8000
                )
                result = _run_worktree_review(
                    wt,
                    str(body.get("rules", "")),
                    skills_text,
                    model=meta.interview_model or "",
                )
                print(
                    f"[web] review worktree slug={slug} path={wt} ok={result.get('ok')}",
                    flush=True,
                )
                st, b, h = _json_bytes(result, 200 if result.get("ok") else 502)
                self._send(st, b, h)
                return

            m_wt_push_all = re.match(r"^/api/tasks/([^/]+)/worktrees/push-all$", path)
            if m_wt_push_all:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_wt_push_all.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                results: list[dict[str, Any]] = []
                for p_str in meta.worktrees:
                    wt = Path(p_str)
                    row = push_worktree_branch(wt)
                    row["path"] = p_str
                    row["status"] = worktree_status(wt)
                    results.append(row)
                ok_all = bool(results) and all(r.get("ok") for r in results)
                print(
                    f"[web] push-all slug={slug} ok={sum(1 for r in results if r.get('ok'))}/{len(results)}",
                    flush=True,
                )
                openclaw_client.emit(
                    "worktrees-pushed",
                    instruction=f"Loom pushed worktree branches for task {slug}",
                    project_root=root,
                    task_slug=slug,
                    data={"results": results},
                )
                st, b, h = _json_bytes(
                    {"ok": ok_all, "count": len(results), "results": results}
                )
                self._send(st, b, h)
                return

            m_resume = re.match(r"^/api/tasks/([^/]+)/claude/resume$", path)
            if m_resume:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_resume.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                sid = str(body.get("session_id", "")).strip()
                if not _SESSION_ID_RE.match(sid):
                    st, b, h = _json_bytes({"error": "invalid session_id"}, 400)
                    self._send(st, b, h)
                    return
                result = claude_registry.start(root, project_id, slug, resume_session_id=sid)
                print(
                    f"[web] resume claude slug={slug} session={sid} ok={bool(result.get('ok'))} "
                    f"target={result.get('target', '')}",
                    flush=True,
                )
                openclaw_client.emit(
                    "claude-resume",
                    instruction=f"Loom Claude pane resumed for task {slug}",
                    project_root=root,
                    task_slug=slug,
                    data={**result, "session_id": sid},
                )
                st, b, h = (
                    _json_bytes(result)
                    if result.get("ok")
                    else _json_bytes(result, 400)
                )
                self._send(st, b, h)
                return

            st, b, h = _json_bytes({"error": "not found"}, 404)
            self._send(st, b, h)

        # ===== PUT =====

        def do_PUT(self) -> None:  # noqa: N802
            if not self._require_auth():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            body = _read_json(self)

            if path == "/api/notes":
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                content = body.get("content", "")
                if not isinstance(content, str):
                    st, b, h = _json_bytes({"error": "content must be string"}, 400)
                    self._send(st, b, h)
                    return
                if not write_project_notes(root, content):
                    st, b, h = _json_bytes({"error": "failed to write NOTES.md"}, 500)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes({"ok": True})
                self._send(st, b, h)
                return

            m_ki_put = re.match(r"^/api/tasks/([^/]+)/kernel-interview$", path)
            if m_ki_put:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m_ki_put.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                messages = body.get("messages", [])
                if not isinstance(messages, list):
                    st, b, h = _json_bytes({"error": "messages must be a list"}, 400)
                    self._send(st, b, h)
                    return
                spec = body.get("spec")
                if not write_kernel_interview(root, slug, messages, spec):
                    st, b, h = _json_bytes({"error": "failed to save kernel interview"}, 500)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes({"ok": True})
                self._send(st, b, h)
                return

            m_meta = re.match(r"^/api/tasks/([^/]+)/meta$", path)
            if m_meta:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m_meta.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                title = body.get("title")
                goal = body.get("general_goal")
                agent_in = body.get("agent")
                skills_in = body.get("skills_path")
                model_in = body.get("interview_model")
                if (
                    title is None
                    and goal is None
                    and agent_in is None
                    and skills_in is None
                    and model_in is None
                ):
                    st, b, h = _json_bytes(
                        {
                            "error": "supply title and/or general_goal and/or "
                            "agent and/or skills_path and/or interview_model"
                        },
                        400,
                    )
                    self._send(st, b, h)
                    return
                if agent_in is not None:
                    raw = str(agent_in).strip().lower()
                    if raw not in SUPPORTED_AGENTS:
                        st, b, h = _json_bytes(
                            {"error": f"agent must be one of {sorted(SUPPORTED_AGENTS)}"},
                            400,
                        )
                        self._send(st, b, h)
                        return
                    update_meta(
                        root,
                        slug,
                        agent=raw,
                        # A model from the other CLI is generally invalid
                        # (claude-* for Codex or gpt-* for Claude). Switching
                        # agent resets to that CLI's configured default unless
                        # the request explicitly supplies a model below.
                        interview_model=(
                            agent_default_model(raw) if model_in is None else None
                        ),
                    )
                if skills_in is not None:
                    if isinstance(skills_in, list):
                        skills_in = SKILLS_PATH_SEP.join(str(x) for x in skills_in)
                    try:
                        cands = [
                            p.resolve() for p in split_skills_paths(str(skills_in))
                        ]
                    except OSError as exc:
                        st, b, h = _json_bytes({"error": f"invalid skills_path: {exc}"}, 400)
                        self._send(st, b, h)
                        return
                    bad = [
                        str(c) for c in cands
                        if not c.is_file() or c.suffix.lower() != ".md"
                    ]
                    if not cands or bad:
                        st, b, h = _json_bytes(
                            {"error": "every skills_path entry must be an existing markdown file",
                             "invalid": bad},
                            400,
                        )
                        self._send(st, b, h)
                        return
                    update_meta(root, slug, skills_path=join_skills_paths(cands))
                if model_in is not None:
                    model = str(model_in).strip()
                    if not model:
                        current = read_meta(root, slug)
                        model = agent_default_model(
                            current.agent if current is not None else AGENT_CURSOR
                        )
                    update_meta(root, slug, interview_model=model)
                updated = rename_task_meta(
                    root,
                    slug,
                    title=str(title) if title is not None else None,
                    general_goal=str(goal) if goal is not None else None,
                ) or read_meta(root, slug)
                if updated is None:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes({"ok": True, "meta": updated.to_dict()})
                self._send(st, b, h)
                return

            m = re.match(r"^/api/tasks/([^/]+)/template$", path)
            if not m:
                st, b, h = _json_bytes({"error": "not found"}, 404)
                self._send(st, b, h)
                return
            root, _pid = self._resolve_scope(parsed)
            if root is None:
                self._bad_project()
                return
            slug = m.group(1)
            if not _SLUG_RE.match(slug):
                st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                self._send(st, b, h)
                return
            name = str(body.get("name", ""))
            content = body.get("content", "")
            if not isinstance(content, str):
                st, b, h = _json_bytes({"error": "content must be string"}, 400)
                self._send(st, b, h)
                return
            if not write_template(root, slug, name, content):
                st, b, h = _json_bytes({"error": "invalid template"}, 400)
                self._send(st, b, h)
                return
            st, b, h = _json_bytes({"ok": True})
            self._send(st, b, h)

        # ===== DELETE =====

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._require_auth():
                return
            parsed = urlparse(self.path)
            path = parsed.path

            m_krun_del = re.match(r"^/api/kernel/runs/([^/]+)$", path)
            if m_krun_del:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                run_uid = m_krun_del.group(1)
                if not _KERNEL_ID_RE.match(run_uid):
                    st, b, h = _json_bytes({"error": "invalid run id"}, 400)
                    self._send(st, b, h)
                    return
                rec = _kernel_read_record(root, run_uid)
                if rec is None:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                # A live run must be stopped before its record can be deleted, so
                # we never orphan running agent containers.
                if rec.get("state") in ("launching", "running", "resolving"):
                    st, b, h = _json_bytes(
                        {"error": "stop the run before deleting it"}, 409
                    )
                    self._send(st, b, h)
                    return
                _kernel_delete_record(root, run_uid)
                st, b, h = _json_bytes({"ok": True, "id": run_uid})
                self._send(st, b, h)
                return

            m_mon_del = re.match(r"^/api/tasks/([^/]+)/monitor$", path)
            if m_mon_del:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_mon_del.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                if not read_meta(root, slug):
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                result = monitor_manager.disable(root, project_id, slug)
                print(f"[web] monitor disabled slug={slug}", flush=True)
                st, b, h = _json_bytes(result)
                self._send(st, b, h)
                return

            m_wt_del = re.match(r"^/api/tasks/([^/]+)/worktree$", path)
            if m_wt_del:
                root, project_id = self._resolve_scope(parsed)
                if root is None or project_id is None:
                    self._bad_project()
                    return
                slug = m_wt_del.group(1)
                if not _SLUG_RE.match(slug):
                    st, b, h = _json_bytes({"error": "invalid slug"}, 400)
                    self._send(st, b, h)
                    return
                meta = read_meta(root, slug)
                if not meta:
                    st, b, h = _json_bytes({"error": "not found"}, 404)
                    self._send(st, b, h)
                    return
                qs = parse_qs(parsed.query or "")
                raw_path = (qs.get("path") or [""])[0].strip()
                if not raw_path:
                    st, b, h = _json_bytes({"error": "path query param required"}, 400)
                    self._send(st, b, h)
                    return
                try:
                    wt_target = Path(raw_path).expanduser().resolve()
                except OSError as exc:
                    st, b, h = _json_bytes({"error": f"invalid path: {exc}"}, 400)
                    self._send(st, b, h)
                    return
                ok_rm, msg_rm = remove_task_worktree(root, slug, wt_target)
                print(
                    f"[web] remove worktree slug={slug} path={wt_target} "
                    f"ok={ok_rm} msg={msg_rm}",
                    flush=True,
                )
                if not ok_rm:
                    st, b, h = _json_bytes({"ok": False, "error": msg_rm}, 400)
                    self._send(st, b, h)
                    return
                openclaw_client.emit(
                    "worktree-removed",
                    instruction=f"Loom worktree removed for task {slug}",
                    project_root=root,
                    task_slug=slug,
                    data={"worktree": str(wt_target)},
                )
                updated = read_meta(root, slug)
                st, b, h = _json_bytes(
                    {
                        "ok": True,
                        "message": msg_rm,
                        "meta": updated.to_dict() if updated else None,
                    }
                )
                self._send(st, b, h)
                return

            m_task_del = re.match(r"^/api/tasks/([^/]+)$", path)
            if m_task_del:
                root, _pid = self._resolve_scope(parsed)
                if root is None:
                    self._bad_project()
                    return
                slug = m_task_del.group(1)
                if read_meta(root, slug) is None:
                    st, b, h = _json_bytes({"error": "task not found"}, 404)
                    self._send(st, b, h)
                    return
                kernel_cleanup = _kernel_delete_task_records(root, slug)
                ok_task, err_task = delete_task(root, slug)
                if not ok_task:
                    status = 404 if err_task == "task not found" else 400
                    st, b, h = _json_bytes({"error": err_task}, status)
                    self._send(st, b, h)
                    return
                st, b, h = _json_bytes(
                    {"ok": True, "slug": slug, "kernel_cleanup": kernel_cleanup}
                )
                self._send(st, b, h)
                return

            m_del = re.match(r"^/api/projects/([^/]+)$", path)
            if not m_del:
                st, b, h = _json_bytes({"error": "not found"}, 404)
                self._send(st, b, h)
                return
            pid_del = m_del.group(1)
            ok_del, err_msg = pr.remove(pid_del)
            if not ok_del:
                st, b, h = _json_bytes({"error": err_msg}, 400)
                self._send(st, b, h)
                return
            st, b, h = _json_bytes(
                {
                    "ok": True,
                    "projects": pr.list_projects(),
                    "defaultProjectId": pr.default_project_id,
                }
            )
            self._send(st, b, h)

    return Handler


# --- Bootstrap --------------------------------------------------------------


def serve(
    host: str,
    port: int,
    project_root: Path,
    default_skills: Path,
    openclaw_config: OpenClawConfig | None = None,
    auth_token: str = "",
    *,
    multi_project_workspace: bool = False,
) -> None:
    project_root = project_root.resolve()
    os.environ["LOOM_PROJECT_ROOT"] = str(project_root)
    web_project_registry = WebProjectRegistry()
    if multi_project_workspace:
        web_project_registry.prune_redundant_parent_projects(project_root)
    claude_registry = ClaudeRegistry()
    openclaw_client = OpenClawClient(openclaw_config)
    monitor_manager = TaskMonitorManager(openclaw_client)
    # A launch/prepare runs in a background thread that does NOT survive a server
    # restart, leaving its run record stuck at "launching"/"resolving" forever.
    # On startup, no launch can be in flight, so sweep any such records to error.
    _sweep_roots = {project_root}
    try:
        for _p in web_project_registry.list_projects():
            _pp = _p.get("path")
            if _pp:
                _sweep_roots.add(Path(_pp))
    except Exception:  # noqa: BLE001
        pass
    _swept = _sweep_stale_kernel_runs(list(_sweep_roots))
    if _swept:
        print(f"  Swept {_swept} stale kernel run(s) (launching/resolving -> error)", flush=True)
    # Resume per-task run monitors that were left enabled, so the Notify toggle
    # survives a server restart without re-opening each task.
    _monitor_projects: list[tuple[str, Path]] = []
    try:
        for _p in web_project_registry.list_projects():
            _pid, _pp = _p.get("id"), _p.get("path")
            if _pid and _pp:
                _monitor_projects.append((str(_pid), Path(_pp)))
    except Exception:  # noqa: BLE001
        pass
    _resumed = monitor_manager.resume_enabled(_monitor_projects)
    if _resumed:
        print(f"  Resumed {_resumed} enabled run-monitor(s)", flush=True)
    sk = default_skills if default_skills.is_file() else bundled_skills_path().resolve()
    ar_manager = ARLoopManager(openclaw_client, claude_registry, sk)
    _ar_swept = ar_manager.sweep_stale_jobs(_monitor_projects)
    if _ar_swept:
        print(f"  Cleared {_ar_swept} interrupted AR job(s) (mine/ideas/review)", flush=True)
    _ar_resumed = ar_manager.resume_running(_monitor_projects)
    if _ar_resumed:
        print(f"  Resumed {_ar_resumed} running AR paper loop(s)", flush=True)
    handler = make_handler(
        web_project_registry,
        project_root,
        sk,
        claude_registry,
        openclaw_client,
        auth_token,
        multi_project_workspace=multi_project_workspace,
        monitor_manager=monitor_manager,
        ar_manager=ar_manager,
    )
    server = ThreadingHTTPServer((host, port), handler)
    rud_root = project_root / ".RUD"
    print("", flush=True)
    print("Loom", flush=True)
    print(f"  URL:              http://{host}:{port}/", flush=True)
    print(
        f"  Server cwd:       {project_root}  (--project / launch directory; not auto-registered)"
        f"{'  [multi-project workspace: --projects]' if multi_project_workspace else ''}",
        flush=True,
    )
    print(f"  Project registry: {web_project_registry.persist_path}", flush=True)
    print(f"  Task root:        {rud_root}", flush=True)
    print(f"  Project notes:    {rud_root}/NOTES.md", flush=True)
    print(f"  Static assets:    {web_static_dir().resolve()}", flush=True)
    print(f"  Default skills:   {sk}", flush=True)
    print("  Tabs:             Claude, PLAN.md (per task) + Notes button (per project)", flush=True)
    print(f"  Auth:             {'enabled' if auth_token.strip() else 'disabled'}", flush=True)
    print(f"  OpenClaw:         {openclaw_status(openclaw_client.config)}", flush=True)
    print("", flush=True)
    openclaw_client.emit(
        "web-start",
        instruction=f"Loom web started for project {project_root}",
        project_root=project_root,
        data={"url": f"http://{host}:{port}/", "taskRoot": str(rud_root)},
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
