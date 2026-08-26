"""Tiny helpers shared by web.py and its split-off feature modules."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from loom.rud_task import AGENT_CURSOR, SUPPORTED_AGENTS, list_tasks, normalize_agent

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,80}$")


def _path_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _sanitize_session_name(raw: str, fallback: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.@-]+", "-", raw).strip("-")
    return safe[:90] or fallback


def _session_name_from_tmux_target(target: str) -> str:
    """``session:0.0`` -> ``session`` (we never put ``:`` in session names)."""
    t = (target or "").strip()
    if ":" in t:
        return t.split(":", 1)[0].strip()
    return t


def _tmux_id_fragment(project_id: str) -> str:
    frag = re.sub(r"[^A-Za-z0-9]+", "", (project_id or "x"))[:8]
    return frag or "proj"


# Current brand prefix for new tmux session names. "claudeloop" is the legacy
# prefix from before the rename and is still recognized for reuse/cleanup so
# panes started by older builds keep working.
_SESSION_BRAND = "loom"
_SESSION_BRANDS = ("loom", "claudeloop")

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


# (structured agent conversations live in loom/web_conversation.py)

_REVIEW_DEFAULT_RULES = """- Correctness: logic bugs, edge cases, wrong APIs, off-by-one, error handling.
- Security: NO hardcoded secrets/tokens/keys; no injection; safe file/subprocess use.
- Hygiene: no leftover debug prints, commented-out code, stray TODOs, dead code.
- Tests: meaningful changes should add/keep tests; flag "claims tested" with no test.
- Consistency: matches the surrounding code style and the project's skills."""

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

_TERMINAL_STREAM_SELECT_SECONDS = 10.0
