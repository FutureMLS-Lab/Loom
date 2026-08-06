"""Paths to bundled resources (skills, web static, optional Kernel Hub)."""

from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent

KERNEL_HUB_ENV = "LOOM_KERNEL_HUB_DIR"


def bundled_skills_path() -> Path:
    return _PKG / "skills" / "charlie_skills.md"


def web_static_dir() -> Path:
    return _PKG / "web_static"


def paper_templates_dir() -> Path:
    """Venue LaTeX skeletons used by AR paper tasks.

    These live inside the package (unlike the repo-root ``templates/``) because
    an installed Loom must be able to seed a paper without a source checkout.
    Style files are vendored by ``scripts/fetch_paper_styles.py``.
    """
    return _PKG / "templates" / "paper"


def kernel_hub_dir() -> Path:
    """Kernel stack used by the optional Kernel Lab task type (scaffold +
    kernel_evaluator + docker-compose). ``scaffold/agent_runner/rud_kernel.py``
    lives under here and its ``REPO_ROOT`` resolves to this directory.

    It is excluded from the published wheel because it is ~800 files of
    Dockerfiles, CUDA sources and reference docs. It is present when running
    from a source checkout, and installed users can point ``LOOM_KERNEL_HUB_DIR``
    at one.
    """
    override = os.environ.get(KERNEL_HUB_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return _PKG / "kernel_hub"


def kernel_hub_available() -> bool:
    return (kernel_hub_dir() / "scaffold" / "agent_runner").is_dir()
