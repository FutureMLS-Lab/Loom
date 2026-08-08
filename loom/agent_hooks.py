"""Let an agent tell Loom the moment it finishes, instead of Loom watching.

Loom can infer completion by capturing a pane and looking for the CLI's
"esc to interrupt" indicator, but that is a heuristic on someone else's UI and
it costs a poll of every pane on the host. Both the Cursor Agent CLI and Claude
Code fire a hook when a turn ends, which is exact, instant, and free - so the
hook is the primary signal and the poller stays as a fallback for agents that
have none.

The hook posts the workspace it ran in; Loom maps that back to a task, because
the hook has no idea Loom exists beyond a URL.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

HOOK_SCRIPT_NAME = "loom-agent-stop.sh"
HOOK_TOKEN_NAME = "hook-token"
# Marks the entries Loom owns, so re-installing updates them and leaves every
# other hook the user has configured untouched.
HOOK_MARKER = "loom-agent-stop"


def loom_home() -> Path:
    override = os.environ.get("LOOM_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".loom"


def hook_token_path() -> Path:
    return loom_home() / HOOK_TOKEN_NAME


def hook_token() -> str:
    """A credential for the hook alone, created once and kept 0600.

    Separate from the web auth token: a hook only needs to say "this workspace
    finished", so it gets a secret that can do only that, and the web token is
    never copied onto disk for it.
    """
    path = hook_token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    token = secrets.token_hex(24)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        return ""
    return token


def _script_body(url: str, token_path: Path) -> str:
    """The hook itself.

    One Python process does the whole job: read the event, find the workspace,
    post it. Doing it in shell would mean quoting a path through curl, and a
    path with a space in it would silently stop reporting. It never blocks the
    agent - every failure path still exits 0, and the request is capped at two
    seconds.
    """
    return f"""#!/usr/bin/env python3
# Written by Loom; safe to delete. Reports the end of an agent turn so the
# task rings in the UI the moment it happens rather than up to a poll later.
import json
import os
import sys
import urllib.request

URL = {url!r}
TOKEN_PATH = {str(token_path)!r}

try:
    event = json.load(sys.stdin)
except Exception:
    event = {{}}

# Loom stamps the task onto the pane it launched, which is the only exact
# answer: the event's workspace_roots is the repository root, shared by every
# task in that project. The path is a fallback for panes Loom did not start.
task = os.environ.get("LOOM_TASK_ID", "")
roots = event.get("workspace_roots") or []
cwd = roots[0] if roots else (event.get("cwd") or "")

try:
    with open(TOKEN_PATH, encoding="utf-8") as fh:
        token = fh.read().strip()
except OSError:
    token = ""

if (task or cwd) and token:
    body = json.dumps({{
        "task": task,
        "cwd": cwd,
        "session": event.get("session_id", ""),
    }}).encode()
    request = urllib.request.Request(
        URL,
        data=body,
        headers={{"Content-Type": "application/json", "X-Loom-Hook-Token": token}},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=2).read()
    except Exception:
        pass  # Loom being down must never hold up the agent

print("{{}}")
"""


def install_cursor_hook(url: str) -> tuple[bool, str]:
    """Add (or refresh) Loom's stop hook in the user's Cursor hooks file."""
    root = Path.home() / ".cursor"
    script = root / "hooks" / HOOK_SCRIPT_NAME
    config = root / "hooks.json"
    token = hook_token()
    if not token:
        return False, "could not create the hook token"
    try:
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(_script_body(url, hook_token_path()), encoding="utf-8")
        script.chmod(0o755)
    except OSError as exc:
        return False, f"could not write {script}: {exc}"

    data: dict[str, Any] = {"version": 1, "hooks": {}}
    if config.is_file():
        try:
            loaded = json.loads(config.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
                data.setdefault("version", 1)
                data.setdefault("hooks", {})
        except (json.JSONDecodeError, OSError):
            return False, f"{config} is not readable JSON; left it alone"

    hooks = data["hooks"]
    if not isinstance(hooks.get("stop"), list):
        hooks["stop"] = []
    # Replace only our own entry, so hooks the user added stay exactly as they
    # are - this file belongs to them, not to Loom.
    entry = {"command": f"./hooks/{HOOK_SCRIPT_NAME}", "timeout": 5}
    hooks["stop"] = [
        h for h in hooks["stop"]
        if not (isinstance(h, dict) and HOOK_MARKER in str(h.get("command", "")))
    ] + [entry]

    try:
        config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"could not write {config}: {exc}"
    return True, str(config)


def install_claude_hook(url: str) -> tuple[bool, str]:
    """The same signal from Claude Code, whose hooks live in its settings."""
    settings = Path.home() / ".claude" / "settings.json"
    script = Path.home() / ".cursor" / "hooks" / HOOK_SCRIPT_NAME
    if not script.is_file():
        return False, "cursor hook script missing"
    data: dict[str, Any] = {}
    if settings.is_file():
        try:
            loaded = json.loads(settings.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            return False, f"{settings} is not readable JSON; left it alone"

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks.get("Stop"), list):
        hooks["Stop"] = []
    entry = {"hooks": [{"type": "command", "command": str(script), "timeout": 5}]}
    hooks["Stop"] = [
        h for h in hooks["Stop"]
        if HOOK_MARKER not in json.dumps(h)
    ] + [entry]

    try:
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"could not write {settings}: {exc}"
    return True, str(settings)


def install(port: int, host: str = "127.0.0.1") -> list[str]:
    """Install the stop hook for every agent CLI that supports one.

    These are the user's own config files, so set ``LOOM_NO_AGENT_HOOKS=1`` to
    keep Loom out of them and fall back to watching panes.
    """
    if os.environ.get("LOOM_NO_AGENT_HOOKS", "").strip() not in ("", "0", "false"):
        return ["disabled by LOOM_NO_AGENT_HOOKS"]
    url = f"http://{host if host not in ('0.0.0.0', '') else '127.0.0.1'}:{port}/api/activity/finished"
    notes: list[str] = []
    ok, detail = install_cursor_hook(url)
    notes.append(f"cursor: {'installed' if ok else 'skipped'} ({detail})")
    ok, detail = install_claude_hook(url)
    notes.append(f"claude: {'installed' if ok else 'skipped'} ({detail})")
    return notes
