"""Review Factory - the reviewer panel with a door of its own.

The three-model panel was born inside the Research Factory's rounds
(``ar_task.run_reviewer``). This module is the panel as a service: the Paper
Factory calls :func:`panel_review` every round, and standalone review
projects - a directory holding any compiled PDF - reach the same panel
through the ``/api/review`` endpoints. Deliberately thin: the panel
implementation stays in ``ar_task``, because forking it would fork the one
thing every factory must agree on - what a review is.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from loom import ar_task as ar
from loom import paper_fetch

REGISTRY_VERSION = 1
OUTPUT_SUBDIR = "review-output"
_LOCK = threading.Lock()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def registry_path() -> Path:
    override = os.environ.get("LOOM_REVIEW_REGISTRY", "").strip()
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".loom" / "review-projects.json"
    )


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _registry() -> dict[str, Any]:
    data = _read_json(registry_path(), {"version": REGISTRY_VERSION, "projects": []})
    if not isinstance(data, dict):
        return {"version": REGISTRY_VERSION, "projects": []}
    projects = data.get("projects")
    return {
        "version": REGISTRY_VERSION,
        "projects": projects if isinstance(projects, list) else [],
    }


def _write_registry(data: dict[str, Any]) -> None:
    _atomic_json(registry_path(), data)


def project_id_for(source_path: Path) -> str:
    return hashlib.sha256(str(source_path.resolve()).encode()).hexdigest()[:12]


def output_root(source_path: Path) -> Path:
    return source_path / OUTPUT_SUBDIR


def state_path(source_path: Path) -> Path:
    return output_root(source_path) / "state.json"


def _project_record(project_id: str) -> dict[str, Any] | None:
    for item in _registry()["projects"]:
        if isinstance(item, dict) and item.get("id") == project_id:
            return item
    return None


def _source_for(project_id: str) -> Path | None:
    record = _project_record(project_id)
    if not record:
        return None
    return Path(str(record.get("source_path") or "")).expanduser()


def read_state(project_id: str) -> dict[str, Any]:
    source = _source_for(project_id)
    if source is None:
        return {}
    state = _read_json(state_path(source), {})
    return state if isinstance(state, dict) else {}


def write_state(project_id: str, state: dict[str, Any]) -> bool:
    source = _source_for(project_id)
    if source is None:
        return False
    _atomic_json(state_path(source), state)
    return True


def update_state(project_id: str, **changes: Any) -> dict[str, Any]:
    with _LOCK:
        state = read_state(project_id)
        state.update(changes)
        state["updated_at"] = _now()
        write_state(project_id, state)
    return state


def find_pdf(source: Path) -> Path | None:
    """The PDF a review project is about: ``main.pdf``, else the newest one."""
    main = source / "main.pdf"
    if main.is_file():
        return main
    candidates = [
        p
        for p in source.rglob("*.pdf")
        if OUTPUT_SUBDIR not in p.parts and p.is_file()
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def register_project(
    source_value: str,
    *,
    title: str = "",
    venue: str = "",
    rubric_path: str = "",
) -> dict[str, Any]:
    """Register a directory holding a compiled PDF as a review project."""
    raw = str(source_value or "").strip()
    if not raw:
        raise ValueError("input path is required")
    source = Path(raw).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"input path is not a directory: {source}")
    if find_pdf(source) is None:
        raise ValueError(f"no PDF found under {source}")
    rubric = str(rubric_path or "").strip()
    if rubric and not Path(rubric).expanduser().is_file():
        raise ValueError(f"rubric file not found: {rubric}")
    out = output_root(source)
    if out.exists() and out.is_symlink():
        raise ValueError(f"{OUTPUT_SUBDIR} must not be a symlink")
    out.mkdir(parents=True, exist_ok=True)
    project_id = project_id_for(source)

    with _LOCK:
        data = _registry()
        record = next(
            (
                item
                for item in data["projects"]
                if isinstance(item, dict) and item.get("id") == project_id
            ),
            None,
        )
        if record is None:
            record = {
                "id": project_id,
                "source_path": str(source),
                "title": title.strip() or source.name,
                "created_at": _now(),
            }
            data["projects"].insert(0, record)
        else:
            record["title"] = title.strip() or str(record.get("title") or source.name)
            record["source_path"] = str(source)
        _write_registry(data)

        state = _read_json(state_path(source), {})
        if not isinstance(state, dict) or not state:
            state = {"version": REGISTRY_VERSION, "id": project_id}
        state.setdefault("status", "idle")
        state["venue"] = (venue or state.get("venue") or ar.DEFAULT_VENUE).strip()
        state["rubric_path"] = rubric or str(state.get("rubric_path") or "")
        state["updated_at"] = _now()
        _atomic_json(state_path(source), state)
    return record


def review_root() -> Path:
    """Managed home for fetched papers: factories/review/<venue>/<paper>/.

    Local directories register in place; only URL imports live here.
    """
    override = os.environ.get("LOOM_REVIEW_ROOT", "").strip()
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".loom" / "factories" / "review"
    )


def import_from_url(
    url: str, *, title: str = "", venue: str = ""
) -> dict[str, Any]:
    """Fetch a paper off a public URL (arXiv, OpenReview, direct PDF) and
    register the downloaded copy as a review project."""
    clean = str(url or "").strip()
    if not clean:
        raise ValueError("a paper URL is required")
    name = title.strip() or paper_fetch.probe_title(clean)
    folder = (
        paper_fetch.slugify(name)
        or hashlib.sha256(clean.encode()).hexdigest()[:12]
    )
    dest = review_root() / (venue.strip().lower() or "unsorted") / folder
    fetched = paper_fetch.fetch_paper_pdf(clean, dest / "paper.pdf")
    record = register_project(
        str(dest),
        title=name or str(fetched.get("title") or "").strip() or dest.name,
        venue=venue,
    )
    update_state(str(record["id"]), source_url=clean)
    return record


def unregister_project(project_id: str) -> bool:
    """Drop a project from the registry; its files stay on disk."""
    with _LOCK:
        data = _registry()
        before = len(data["projects"])
        data["projects"] = [
            item
            for item in data["projects"]
            if not (isinstance(item, dict) and item.get("id") == project_id)
        ]
        if len(data["projects"]) == before:
            return False
        _write_registry(data)
    return True


def list_projects() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in _registry()["projects"]:
        if not isinstance(record, dict):
            continue
        state = read_state(str(record.get("id")))
        latest = state.get("latest_review") or {}
        out.append(
            {
                **record,
                "status": str(state.get("status") or "idle"),
                "error": str(state.get("error") or ""),
                "venue": str(state.get("venue") or ar.DEFAULT_VENUE),
                "rating": (latest.get("scores") or {}).get("rating"),
                "headline": str(latest.get("headline") or ""),
                "reviewed_at": str(latest.get("created_at") or ""),
                "updated_at": str(state.get("updated_at") or ""),
            }
        )
    return out


def _rubric_text(state: dict[str, Any]) -> str:
    rubric = str(state.get("rubric_path") or "").strip()
    if rubric:
        try:
            return Path(rubric).expanduser().read_text(
                encoding="utf-8", errors="replace"
            )[:24000]
        except OSError:
            pass
    return ar.ar_skill_text(ar.SKILL_REVIEWER)


def panel_review(paper_dir: Path, *, skill_text: str = "", **kwargs: Any) -> dict[str, Any]:
    """One reviewer-panel run - the door every factory walks through.

    The Paper Factory's rounds call this with their own readiness result;
    standalone projects call it via :func:`run_project_review` with the
    structural gate bypassed (an external PDF has no LaTeX tree to check).
    """
    text = skill_text or ar.ar_skill_text(ar.SKILL_REVIEWER)
    return ar.run_reviewer(paper_dir, text, **kwargs)


def run_project_review(project_id: str, on_line: Any = None) -> dict[str, Any]:
    """Run the panel for a standalone project and persist the report."""
    source = _source_for(project_id)
    if source is None or not source.is_dir():
        return {"ok": False, "error": "unknown review project"}
    state = read_state(project_id)
    pdf = find_pdf(source)
    if pdf is None:
        return {"ok": False, "error": f"no PDF found under {source}"}

    res = panel_review(
        source,
        skill_text=_rubric_text(state),
        venue=str(state.get("venue") or ar.DEFAULT_VENUE),
        build={"ok": True, "clean": True, "pdf": str(pdf)},
        # An external PDF has no sections/ tree; structural readiness is the
        # Paper Factory's gate, not this one's.
        readiness={"ready": True, "checks": [], "skipped": "standalone review"},
        on_line=on_line,
    )
    if not res.get("ok"):
        return res

    run_dir = output_root(source) / "reviews" / _now().replace(":", "").replace("+0000", "Z")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "review.md").write_text(str(res.get("review") or ""), encoding="utf-8")
    reviewers = list(res.get("reviewers") or [])
    _atomic_json(
        run_dir / "panel.json",
        {
            "pdf": str(pdf),
            "models": res.get("models") or [],
            "deciding_model": res.get("deciding_model") or "",
            "scores": res.get("scores") or {},
            "headline": res.get("headline") or "",
            "reviewers": reviewers,
            "cost": res.get("cost", 0.0),
        },
    )
    update_state(
        project_id,
        status="done",
        error="",
        latest_review={
            "created_at": _now(),
            "path": str(run_dir),
            "pdf": str(pdf),
            "scores": res.get("scores") or {},
            "headline": res.get("headline") or "",
            "deciding_model": res.get("deciding_model") or "",
            "models": res.get("models") or [],
            "reviewers": reviewers,
        },
    )
    return res
