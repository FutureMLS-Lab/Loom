"""Environment preflight for Loom.

Loom drives external tools (tmux panes, git worktrees, agent CLIs) rather than
reimplementing them, so a missing binary shows up much later as an empty
terminal or a failed worktree. These checks surface that up front, both from
``loom doctor`` and as a hard gate before ``loom web`` binds a port.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field

from loom.paths import (
    bundled_skills_path,
    web_static_dir,
)

OK = "ok"
WARN = "warn"
FAIL = "fail"

MIN_PYTHON = (3, 10)

AGENT_BINARIES = {
    "cursor": ("agent", "cursor-agent"),
    "claude": ("claude",),
    "codex": ("codex",),
}


@dataclass
class Check:
    """One preflight result. ``required`` checks gate ``loom web``."""

    name: str
    status: str
    detail: str
    hint: str = ""
    required: bool = False


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def blocking(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL and c.required]

    @property
    def ok(self) -> bool:
        return not self.failures


def _tool_version(binary: str, *args: str) -> str:
    try:
        out = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else ""


def _check_python() -> Check:
    current = sys.version_info[:3]
    wanted = ".".join(str(p) for p in MIN_PYTHON)
    if current[:2] >= MIN_PYTHON:
        return Check("python", OK, ".".join(str(p) for p in current), required=True)
    return Check(
        "python",
        FAIL,
        ".".join(str(p) for p in current),
        hint=f"Loom needs Python {wanted}+; reinstall into a newer interpreter",
        required=True,
    )


def _check_binary(name: str, install_hint: str, *version_args: str) -> Check:
    path = shutil.which(name)
    if not path:
        return Check(name, FAIL, "not found on PATH", hint=install_hint, required=True)
    version = _tool_version(name, *version_args) if version_args else ""
    return Check(name, OK, version or path, required=True)


def _check_agents() -> Check:
    """Not ``required``: without an agent CLI you still get tasks, PLAN.md and
    diffs, you just cannot start a pane. Worth failing ``doctor`` over, not
    worth refusing to serve."""
    found: list[str] = []
    for agent, binaries in AGENT_BINARIES.items():
        if any(shutil.which(b) for b in binaries):
            found.append(agent)
    if found:
        return Check("agent CLI", OK, ", ".join(found))
    return Check(
        "agent CLI",
        FAIL,
        "no claude / codex / cursor agent binary found",
        hint="install at least one agent CLI and log in once, e.g. `claude`",
    )


def _check_latex() -> Check:
    """WARN, not FAIL: Loom itself runs without LaTeX, but the Factory's
    paper pipeline compiles with latexmk on every round - a fresh host
    without it fails at the first PDF build, long after setup."""
    path = shutil.which("latexmk")
    if path:
        return Check("latexmk", OK, path)
    return Check(
        "latexmk",
        WARN,
        "not found - AR papers cannot build their PDFs",
        hint="for the Research Factory: `apt install latexmk texlive-latex-extra` (or a full TeX Live)",
    )


def _check_assets() -> list[Check]:
    checks: list[Check] = []
    static = web_static_dir()
    if (static / "index.html").is_file():
        checks.append(Check("web assets", OK, str(static), required=True))
    else:
        checks.append(
            Check(
                "web assets",
                FAIL,
                f"missing at {static}",
                hint="the install is incomplete; reinstall Loom",
                required=True,
            )
        )
    skills = bundled_skills_path()
    if skills.is_file():
        checks.append(Check("bundled skills", OK, str(skills)))
    else:
        checks.append(
            Check(
                "bundled skills",
                WARN,
                f"missing at {skills}",
                hint="pass --skills to point at your own markdown",
            )
        )
    return checks


def _check_port(host: str, port: int) -> Check:
    label = f"port {port}"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex((host or "127.0.0.1", port)) == 0:
            return Check(
                label,
                WARN,
                f"already in use on {host}",
                hint="another Loom may be running; use --port to pick a free one",
            )
    return Check(label, OK, f"free on {host}")


def _check_auth() -> Check:
    if os.environ.get("LOOM_WEB_AUTH_TOKEN", "").strip():
        return Check("auth token", OK, "LOOM_WEB_AUTH_TOKEN is set")
    return Check(
        "auth token",
        WARN,
        "not set",
        hint="export LOOM_WEB_AUTH_TOKEN instead of passing --auth-token, which leaks into `ps` and shell history",
    )


def run_checks(host: str = "127.0.0.1", port: int = 8765) -> Report:
    """Full preflight, including the optional/informational checks."""
    report = Report()
    report.checks.append(_check_python())
    report.checks.append(_check_binary("tmux", "install tmux, e.g. `apt install tmux` or `brew install tmux`", "-V"))
    report.checks.append(_check_binary("git", "install git, e.g. `apt install git` or `brew install git`", "--version"))
    report.checks.append(_check_agents())
    report.checks.append(_check_latex())
    report.checks.extend(_check_assets())
    report.checks.append(_check_port(host, port))
    report.checks.append(_check_auth())
    return report


def required_failures() -> list[Check]:
    """Checks that must pass before ``loom web`` can usefully start."""
    checks = [
        _check_python(),
        _check_binary("tmux", "install tmux, e.g. `apt install tmux` or `brew install tmux`", "-V"),
        _check_binary("git", "install git, e.g. `apt install git` or `brew install git`", "--version"),
        _check_agents(),
        *_check_assets(),
    ]
    return [c for c in checks if c.status == FAIL and c.required]
