"""File-backed projects and domain helpers for the Auto Rebuttal Factory."""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

from loom import ar_task as ar


REGISTRY_VERSION = 2
STATE_VERSION = 2
STUDIO_STATE_VERSION = 1
OUTPUT_SUBDIR = "rebuttal-output"
STATE_FILE = "state.json"
MANIFEST_FILE = "source-manifest.json"
CONCERNS_FILE = "concerns.json"
CONCERN_MATRIX_FILE = "concern-matrix.md"
VALIDATION_FILE = "validation.json"
VALIDATION_MARKDOWN_FILE = "validation.md"
RESPONSES_SUBDIR = "responses"
POLICY_SOURCES_FILE = "policy-sources.json"
POLICY_FILE = "rebuttal-policy.json"
POLICY_MARKDOWN_FILE = "rebuttal-policy.md"
STRATEGY_FILE = "rebuttal-strategy.md"
AGENT_INSTRUCTIONS_FILE = "AGENT_INSTRUCTIONS.md"
AGENT_COMPLETE_FILE = "agent-complete.json"

STAGE_INTAKE = "intake"
STAGE_CONCERNS = "concerns_ready"
STAGE_RESPONSES = "responses_ready"
STAGE_VALIDATED = "validated"
STAGE_APPROVED = "approved"
STAGE_DELIVERY_AGENT = "delivery_agent_running"
STAGE_DELIVERY_VALIDATING = "delivery_validating"
STAGE_DELIVERY_BLOCKED = "delivery_blocked"
STAGE_AWAIT_DELIVERY_APPROVAL = "await_delivery_approval"
STAGE_BUNDLE_READY = "bundle_ready"

STUDIO_STAGE_POLICY_INPUT = "policy_input"
STUDIO_STAGE_POLICY_DRAFT = "policy_draft"
STUDIO_STAGE_AWAIT_POLICY_REVIEW = "await_policy_review"
STUDIO_STAGE_ACTIVE = "active"
STUDIO_STAGE_CLOSED = "closed"

JOB_POLICY = "policy_discovery"

DEFAULT_POLICY = {
    "platform": "OpenReview",
    "character_limit": 10_000,
    "internal_target": 9_500,
    "manuscript_frozen": True,
    "allow_links": False,
    "allow_attachments": False,
    "allow_global_response": False,
    "anonymous": True,
    "response_language": "English",
    "word_limit": 0,
    "rebuttal_open_at": "",
    "rebuttal_deadline": "",
    "timezone": "",
    "discussion_end": "",
    "allow_revised_pdf": False,
    "allow_new_experiments": False,
    "allow_ac_response": True,
    "reviewers_can_update_scores": True,
    "submission_instructions": "",
}

_LOCK = threading.RLock()
_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_STUDIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_REVIEW_NAME_RE = re.compile(
    r"(?i)(?:review|reviewer|rebuttal|meta[-_ ]?review|decision|comment)"
)
_PAPER_NAME_RE = re.compile(
    r"(?i)(?:^|[-_ ])(?:main|paper|submission|manuscript|camera[-_ ]?ready)(?:[-_ .]|$)"
)
_SKIP_DIRS = {
    ".git",
    ".RUD",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    OUTPUT_SUBDIR,
}
_TEXT_SUFFIXES = {
    ".tex",
    ".bib",
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".csv",
    ".yaml",
    ".yml",
    ".toml",
}
_PLACEHOLDER_RE = re.compile(r"\[\[[^\]\r\n]+\]|\b(?:TODO|TBD|FIXME|XXX)\b", re.I)
_URL_RE = re.compile(r"(?i)(?:https?://|www\.|mailto:)\S+")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_REVISED_MANUSCRIPT_RE = re.compile(
    r"(?is)\b(?:we|the authors?)\s+(?:have|already)?\s*"
    r"(?:revised|updated|changed|modified|added|removed|replaced)"
    r".{0,100}\b(?:manuscript|paper|submission|title|theorem|figure|caption)\b"
    r"|\bin (?:the|our) revised (?:manuscript|paper|submission)\b"
)
_FUTURE_MANUSCRIPT_ACTION_RE = re.compile(
    r"(?is)\bwe will\b.{0,160}"
    r"\b(?:add|revise|update|change|modify|replace|remove|clarify|include)\b"
    r".{0,160}\b(?:paper|manuscript|submission|section|title|theorem|"
    r"figure|caption|abstract|appendix)\b"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def registry_path() -> Path:
    override = os.environ.get("LOOM_REBUTTAL_REGISTRY", "").strip()
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".loom" / "rebuttal-projects.json"
    )


def rebuttal_root() -> Path:
    override = os.environ.get("LOOM_REBUTTAL_ROOT", "").strip()
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".loom" / "rebuttal-studios"
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
    data = _read_json(
        registry_path(),
        {"version": REGISTRY_VERSION, "studios": [], "projects": []},
    )
    if not isinstance(data, dict):
        return {"version": REGISTRY_VERSION, "studios": [], "projects": []}
    studios = data.get("studios")
    if not isinstance(studios, list):
        studios = []
    projects = data.get("projects")
    if not isinstance(projects, list):
        projects = []
    return {
        "version": REGISTRY_VERSION,
        "studios": studios,
        "projects": projects,
    }


def _write_registry(data: dict[str, Any]) -> None:
    _atomic_json(registry_path(), data)


def project_id_for(source_path: Path) -> str:
    return hashlib.sha256(str(source_path.resolve()).encode()).hexdigest()[:12]


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:72] or "conference"


def studio_path(studio_id: str) -> Path:
    return rebuttal_root() / studio_id / "studio.json"


def studio_artifact_path(studio_id: str, filename: str) -> Path:
    return rebuttal_root() / studio_id / filename


def _studio_record(studio_id: str) -> dict[str, Any] | None:
    if not _STUDIO_ID_RE.match(studio_id):
        return None
    for item in _registry()["studios"]:
        if isinstance(item, dict) and item.get("id") == studio_id:
            return item
    return None


def output_root(source_path: Path) -> Path:
    return source_path / OUTPUT_SUBDIR


def state_path(source_path: Path) -> Path:
    return output_root(source_path) / STATE_FILE


def _project_record(project_id: str) -> dict[str, Any] | None:
    if not _PROJECT_ID_RE.match(project_id):
        return None
    for item in _registry()["projects"]:
        if isinstance(item, dict) and item.get("id") == project_id:
            return item
    return None


def _source_for(project_id: str) -> Path | None:
    record = _project_record(project_id)
    if record is None:
        return None
    try:
        path = Path(str(record.get("source_path") or "")).expanduser().resolve()
    except OSError:
        return None
    return path if path.is_dir() else None


def append_log(state: dict[str, Any], message: str) -> None:
    logs = state.setdefault("logs", [])
    if not isinstance(logs, list):
        logs = []
        state["logs"] = logs
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    logs.append(f"[{stamp}] {message}")
    del logs[:-400]


def read_studio(studio_id: str) -> dict[str, Any]:
    if _studio_record(studio_id) is None:
        return {}
    data = _read_json(studio_path(studio_id), {})
    return data if isinstance(data, dict) else {}


def write_studio(studio_id: str, state: dict[str, Any]) -> bool:
    if _studio_record(studio_id) is None:
        return False
    payload = dict(state)
    payload["updated_at"] = _now()
    with _LOCK:
        _atomic_json(studio_path(studio_id), payload)
    return True


def _validate_url_syntax(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        if label == "Call for Papers URL":
            raise ValueError(f"{label} is required")
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{label} must be an http(s) URL")
    return text


def register_studio(
    conference: str,
    year: Any,
    cfp_url: str,
    *,
    policy_url: str = "",
    title: str = "",
) -> dict[str, Any]:
    name = " ".join(str(conference or "").split()).strip()
    if not name:
        raise ValueError("conference name is required")
    try:
        year_int = int(year)
    except (TypeError, ValueError) as exc:
        raise ValueError("conference year must be a four-digit year") from exc
    if year_int < 2000 or year_int > 2100:
        raise ValueError("conference year must be between 2000 and 2100")
    cfp = _validate_url_syntax(cfp_url, "Call for Papers URL")
    policy_link = _validate_url_syntax(policy_url, "Policy URL")

    with _LOCK:
        data = _registry()
        existing = next(
            (
                item
                for item in data["studios"]
                if isinstance(item, dict)
                and str(item.get("conference") or "").casefold() == name.casefold()
                and int(item.get("year") or 0) == year_int
            ),
            None,
        )
        if existing is None:
            base_id = _slug(f"{name}-{year_int}")
            studio_id = base_id
            suffix = 2
            taken = {
                str(item.get("id") or "")
                for item in data["studios"]
                if isinstance(item, dict)
            }
            while studio_id in taken:
                studio_id = f"{base_id[:68]}-{suffix}"
                suffix += 1
            existing = {
                "id": studio_id,
                "conference": name,
                "year": year_int,
                "created_at": _now(),
            }
            data["studios"].insert(0, existing)
        studio_id = str(existing["id"])
        existing.update(
            conference=name,
            year=year_int,
            title=title.strip() or f"{name} {year_int}",
            cfp_url=cfp,
            policy_url=policy_link,
        )
        _write_registry(data)

        state = _read_json(studio_path(studio_id), {})
        if not isinstance(state, dict) or not state:
            state = {
                "version": STUDIO_STATE_VERSION,
                "id": studio_id,
                "conference": name,
                "year": year_int,
                "title": existing["title"],
                "cfp_url": cfp,
                "policy_url": policy_link,
                "stage": STUDIO_STAGE_POLICY_INPUT,
                "active_job": "",
                "error": "",
                "policy": normalize_policy(DEFAULT_POLICY),
                "policy_evidence": {},
                "strategy": {},
                "unknowns": [],
                "sources": [],
                "policy_approved_at": "",
                "cost_usd": 0.0,
                "logs": [],
                "created_at": _now(),
            }
        else:
            state.update(
                conference=name,
                year=year_int,
                title=existing["title"],
                cfp_url=cfp,
                policy_url=policy_link,
            )
        append_log(state, f"registered {name} {year_int} rebuttal studio")
        _atomic_json(studio_path(studio_id), state)
    return studio_payload(studio_id)


def read_state(project_id: str) -> dict[str, Any]:
    source = _source_for(project_id)
    if source is None:
        return {}
    data = _read_json(state_path(source), {})
    if not isinstance(data, dict):
        return {}
    data.setdefault("content_approval", {})
    data.setdefault("delivery_policy", {})
    data.setdefault("delivery", {})
    data["version"] = STATE_VERSION
    return data


def write_state(project_id: str, state: dict[str, Any]) -> bool:
    source = _source_for(project_id)
    if source is None:
        return False
    payload = dict(state)
    payload["updated_at"] = _now()
    with _LOCK:
        _atomic_json(state_path(source), payload)
    return True


def update_state(project_id: str, **changes: Any) -> dict[str, Any]:
    with _LOCK:
        state = read_state(project_id)
        state.update(changes)
        write_state(project_id, state)
        return read_state(project_id)


def invalidate_delivery(state: dict[str, Any], reason: str) -> None:
    """Invalidate derived delivery artifacts while preserving attempt history."""
    delivery = state.get("delivery")
    if not isinstance(delivery, dict) or not delivery:
        return
    invalidated = dict(delivery)
    invalidated["phase"] = "invalidated"
    invalidated["invalidated_at"] = _now()
    invalidated["invalidated_reason"] = str(reason or "delivery inputs changed")[:500]
    invalidated["final_approval"] = {}
    invalidated["bundle"] = {}
    state["delivery"] = invalidated


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _iter_material_files(source: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(
            name for name in dirnames if name not in _SKIP_DIRS
        )
        root_path = Path(root)
        for name in sorted(filenames):
            path = root_path / name
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() == ".pdf" or path.suffix.lower() in _TEXT_SUFFIXES:
                found.append(path)
            if len(found) >= 5_000:
                return found
    return found


def _manifest_entry(path: Path, source: Path, kind: str) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "path": str(path),
        "relative_path": str(path.relative_to(source)),
        "name": path.name,
        "kind": kind,
        "size": size,
        "sha256": _sha256(path) if size <= 64 * 1024 * 1024 else "",
    }


def scan_materials(source: Path) -> dict[str, Any]:
    files = _iter_material_files(source)
    pdfs = [path for path in files if path.suffix.lower() == ".pdf"]
    review_pdfs = [path for path in pdfs if _REVIEW_NAME_RE.search(path.name)]
    paper_candidates = [path for path in pdfs if path not in review_pdfs]

    def paper_score(path: Path) -> tuple[int, int, str]:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return (
            0 if _PAPER_NAME_RE.search(path.name) else 1,
            -size,
            str(path),
        )

    paper_pdf = sorted(paper_candidates, key=paper_score)[0] if paper_candidates else None
    entries: list[dict[str, Any]] = []
    for path in files:
        if path == paper_pdf:
            kind = "paper_pdf"
        elif path in review_pdfs:
            kind = "review_pdf"
        else:
            kind = "material"
        entries.append(_manifest_entry(path, source, kind))

    warnings: list[str] = []
    if paper_pdf is None:
        warnings.append(
            "No paper PDF was identified. Name it main.pdf, paper.pdf, "
            "submission.pdf, or manuscript.pdf."
        )
    if not review_pdfs:
        warnings.append(
            "No reviewer PDF was identified. Include review/reviewer/meta-review "
            "in the filename."
        )
    if len(files) >= 5_000:
        warnings.append("Material scan stopped at 5,000 supported files.")

    return {
        "scanned_at": _now(),
        "paper_pdf": str(paper_pdf) if paper_pdf else "",
        "review_pdfs": [str(path) for path in review_pdfs],
        "files": entries,
        "warnings": warnings,
        "ready": bool(paper_pdf and review_pdfs),
    }


def register_project(
    source_value: str,
    *,
    title: str = "",
    policy: dict[str, Any] | None = None,
    studio_id: str = "",
) -> dict[str, Any]:
    raw = str(source_value or "").strip()
    if not raw:
        raise ValueError("input path is required")
    source = Path(raw).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"input path is not a directory: {source}")
    out = output_root(source)
    if out.exists() and out.is_symlink():
        raise ValueError(f"{OUTPUT_SUBDIR} must not be a symlink")
    out.mkdir(parents=True, exist_ok=True)
    project_id = project_id_for(source)
    studio = read_studio(studio_id) if studio_id else {}
    if studio_id and not studio:
        raise ValueError("conference studio not found")
    if policy is None and studio:
        policy = (
            studio.get("policy")
            if isinstance(studio.get("policy"), dict)
            else None
        )

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
                "studio_id": studio_id,
                "created_at": _now(),
            }
            data["projects"].insert(0, record)
        else:
            record["title"] = title.strip() or str(record.get("title") or source.name)
            record["source_path"] = str(source)
            if studio_id:
                record["studio_id"] = studio_id
        _write_registry(data)

        existing = _read_json(state_path(source), {})
        if not isinstance(existing, dict) or not existing:
            merged_policy = dict(DEFAULT_POLICY)
            if isinstance(policy, dict):
                merged_policy.update(policy)
            existing = {
                "version": STATE_VERSION,
                "id": project_id,
                "title": record["title"],
                "studio_id": studio_id or str(record.get("studio_id") or ""),
                "source_path": str(source),
                "output_path": str(out),
                "stage": STAGE_INTAKE,
                "active_job": "",
                "error": "",
                "policy": normalize_policy(merged_policy),
                "manifest": {},
                "reviewers": [],
                "responses": {},
                "validation": {},
                "approved_at": "",
                "content_approval": {},
                "delivery_policy": {},
                "delivery": {},
                "logs": [],
                "created_at": _now(),
            }
        else:
            existing["title"] = record["title"]
            if studio_id:
                existing["studio_id"] = studio_id
            if isinstance(policy, dict):
                current_policy = dict(existing.get("policy") or DEFAULT_POLICY)
                current_policy.update(policy)
                existing["policy"] = normalize_policy(current_policy)
        manifest = scan_materials(source)
        existing["manifest"] = manifest
        append_log(
            existing,
            f"scanned package: {len(manifest['files'])} supported file(s), "
            f"{len(manifest['review_pdfs'])} review PDF(s)",
        )
        existing["stage"] = STAGE_INTAKE
        existing["error"] = ""
        existing["updated_at"] = _now()
        _atomic_json(out / MANIFEST_FILE, manifest)
        _atomic_json(state_path(source), existing)
    return project_payload(project_id)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in ("true", "yes", "allowed", "1"):
        return True
    if text in ("false", "no", "forbidden", "0"):
        return False
    return default


def normalize_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(DEFAULT_POLICY)
    if isinstance(raw, dict):
        data.update(raw)
    try:
        hard = int(data.get("character_limit") or 10_000)
    except (TypeError, ValueError):
        hard = 10_000
    hard = max(500, min(100_000, hard))
    try:
        target = int(data.get("internal_target") or hard - 500)
    except (TypeError, ValueError):
        target = hard - 500
    target = max(100, min(hard - 1, target))
    try:
        word_limit = int(data.get("word_limit") or 0)
    except (TypeError, ValueError):
        word_limit = 0
    word_limit = max(0, min(100_000, word_limit))
    return {
        "platform": str(data.get("platform") or "OpenReview")[:80],
        "character_limit": hard,
        "internal_target": target,
        "word_limit": word_limit,
        "manuscript_frozen": _coerce_bool(
            data.get("manuscript_frozen"),
            True,
        ),
        "allow_links": _coerce_bool(data.get("allow_links"), False),
        "allow_attachments": _coerce_bool(
            data.get("allow_attachments"),
            False,
        ),
        "allow_global_response": _coerce_bool(
            data.get("allow_global_response"),
            False,
        ),
        "anonymous": _coerce_bool(data.get("anonymous"), True),
        "response_language": str(data.get("response_language") or "English")[:40],
        "rebuttal_open_at": str(data.get("rebuttal_open_at") or "")[:120],
        "rebuttal_deadline": str(data.get("rebuttal_deadline") or "")[:120],
        "timezone": str(data.get("timezone") or "")[:80],
        "discussion_end": str(data.get("discussion_end") or "")[:120],
        "allow_revised_pdf": _coerce_bool(
            data.get("allow_revised_pdf"),
            False,
        ),
        "allow_new_experiments": _coerce_bool(
            data.get("allow_new_experiments"),
            False,
        ),
        "allow_ac_response": _coerce_bool(
            data.get("allow_ac_response"),
            True,
        ),
        "reviewers_can_update_scores": _coerce_bool(
            data.get("reviewers_can_update_scores"),
            True,
        ),
        "submission_instructions": str(
            data.get("submission_instructions") or ""
        )[:2000],
    }


def list_projects(studio_id: str = "") -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    for record in _registry()["projects"]:
        if not isinstance(record, dict):
            continue
        project_id = str(record.get("id") or "")
        state = read_state(project_id)
        if not state:
            continue
        project_studio_id = str(
            state.get("studio_id") or record.get("studio_id") or ""
        )
        if studio_id and project_studio_id != studio_id:
            continue
        manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else {}
        validation = (
            state.get("validation")
            if isinstance(state.get("validation"), dict)
            else {}
        )
        delivery = (
            state.get("delivery")
            if isinstance(state.get("delivery"), dict)
            else {}
        )
        projects.append(
            {
                "id": project_id,
                "title": state.get("title") or record.get("title"),
                "studio_id": project_studio_id,
                "source_path": state.get("source_path") or record.get("source_path"),
                "stage": state.get("stage", STAGE_INTAKE),
                "active_job": state.get("active_job", ""),
                "agent_status": state.get("agent_status", ""),
                "tmux_target": state.get("tmux_target", ""),
                "error": state.get("error", ""),
                "reviewers": len(state.get("reviewers") or []),
                "review_files": len(manifest.get("review_pdfs") or []),
                "responses": len(state.get("responses") or {}),
                "ready": bool(validation.get("ready")),
                "delivery_phase": delivery.get("phase", ""),
                "bundle_ready": state.get("stage") == STAGE_BUNDLE_READY,
                "cost_usd": float(state.get("cost_usd") or 0.0),
                "updated_at": state.get("updated_at", ""),
            }
        )
    return projects


def list_studios() -> list[dict[str, Any]]:
    studios: list[dict[str, Any]] = []
    for record in _registry()["studios"]:
        if not isinstance(record, dict):
            continue
        studio_id = str(record.get("id") or "")
        state = read_studio(studio_id)
        if not state:
            continue
        papers = list_projects(studio_id)
        studios.append(
            {
                "id": studio_id,
                "title": state.get("title") or record.get("title"),
                "conference": state.get("conference") or record.get("conference"),
                "year": state.get("year") or record.get("year"),
                "cfp_url": state.get("cfp_url") or record.get("cfp_url"),
                "stage": state.get("stage", STUDIO_STAGE_POLICY_INPUT),
                "active_job": state.get("active_job", ""),
                "error": state.get("error", ""),
                "policy_approved": bool(state.get("policy_approved_at")),
                "rebuttal_deadline": (
                    state.get("policy") or {}
                ).get("rebuttal_deadline", ""),
                "papers": len(papers),
                "paper_ready": sum(1 for paper in papers if paper.get("ready")),
                "waiting": sum(
                    1
                    for paper in papers
                    if paper.get("stage") in (STAGE_VALIDATED,)
                ),
                "cost_usd": round(
                    float(state.get("cost_usd") or 0.0)
                    + sum(float(paper.get("cost_usd") or 0.0) for paper in papers),
                    4,
                ),
                "updated_at": state.get("updated_at", ""),
            }
        )
    return studios


def studio_payload(studio_id: str) -> dict[str, Any]:
    state = read_studio(studio_id)
    if not state:
        return {}
    policy_markdown = _read_text(
        studio_artifact_path(studio_id, POLICY_MARKDOWN_FILE),
        100_000,
    ) or _policy_markdown(state)
    strategy_markdown = _read_text(
        studio_artifact_path(studio_id, STRATEGY_FILE),
        100_000,
    ) or _strategy_markdown(
        state.get("strategy") if isinstance(state.get("strategy"), dict) else {}
    )
    return {
        "ok": True,
        "studio": {
            **state,
            "policy": normalize_policy(
                state.get("policy")
                if isinstance(state.get("policy"), dict)
                else {}
            ),
            "policy_markdown": policy_markdown,
            "strategy_markdown": strategy_markdown,
            "papers": list_projects(studio_id),
        },
    }


def save_studio_policy(
    studio_id: str,
    policy: dict[str, Any],
    *,
    strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = read_studio(studio_id)
    if not state:
        raise ValueError("conference studio not found")
    state["policy"] = normalize_policy(policy)
    if isinstance(strategy, dict):
        state["strategy"] = strategy
    state["stage"] = STUDIO_STAGE_AWAIT_POLICY_REVIEW
    state["policy_approved_at"] = ""
    append_log(state, "saved edited conference rebuttal policy")
    write_studio(studio_id, state)
    studio_dir = studio_path(studio_id).parent
    _atomic_json(
        studio_dir / POLICY_FILE,
        {
            "policy": state["policy"],
            "evidence": state.get("policy_evidence") or {},
            "unknowns": state.get("unknowns") or [],
        },
    )
    (studio_dir / POLICY_MARKDOWN_FILE).write_text(
        _policy_markdown(state),
        encoding="utf-8",
    )
    (studio_dir / STRATEGY_FILE).write_text(
        _strategy_markdown(
            state.get("strategy")
            if isinstance(state.get("strategy"), dict)
            else {}
        ),
        encoding="utf-8",
    )
    return studio_payload(studio_id)


def approve_studio_policy(studio_id: str) -> dict[str, Any]:
    state = read_studio(studio_id)
    if not state:
        raise ValueError("conference studio not found")
    if not state.get("sources"):
        raise ValueError("discover the official rebuttal policy first")
    state["policy"] = normalize_policy(
        state.get("policy") if isinstance(state.get("policy"), dict) else {}
    )
    state["stage"] = STUDIO_STAGE_ACTIVE
    state["policy_approved_at"] = _now()
    append_log(state, "human approved the conference rebuttal policy")
    write_studio(studio_id, state)
    (studio_path(studio_id).parent / POLICY_MARKDOWN_FILE).write_text(
        _policy_markdown(state),
        encoding="utf-8",
    )
    for paper in list_projects(studio_id):
        project_id = str(paper.get("id") or "")
        paper_state = read_state(project_id)
        if not paper_state:
            continue
        paper_state["policy"] = dict(state["policy"])
        paper_state["validation"] = {}
        paper_state["approved_at"] = ""
        paper_state["content_approval"] = {}
        invalidate_delivery(paper_state, "conference policy changed")
        if paper_state.get("stage") in (
            STAGE_VALIDATED,
            STAGE_APPROVED,
            STAGE_DELIVERY_AGENT,
            STAGE_DELIVERY_VALIDATING,
            STAGE_DELIVERY_BLOCKED,
            STAGE_AWAIT_DELIVERY_APPROVAL,
            STAGE_BUNDLE_READY,
        ):
            paper_state["stage"] = STAGE_RESPONSES
        append_log(
            paper_state,
            f"inherited approved policy from {state.get('title', studio_id)}",
        )
        write_state(project_id, paper_state)
    return studio_payload(studio_id)


def register_paper_for_studio(
    studio_id: str,
    source_value: str,
    *,
    title: str = "",
) -> dict[str, Any]:
    studio = read_studio(studio_id)
    if not studio:
        raise ValueError("conference studio not found")
    if studio.get("stage") != STUDIO_STAGE_ACTIVE:
        raise ValueError("approve the conference rebuttal policy before adding papers")
    return register_project(
        source_value,
        title=title,
        policy=studio.get("policy")
        if isinstance(studio.get("policy"), dict)
        else None,
        studio_id=studio_id,
    )


def _safe_response_id(value: str, fallback: str = "reviewer") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-._")
    return slug[:80] or fallback


def _read_text(path: Path, limit: int = 12_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


class _PolicyPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip = 0
        self._in_title = False
        self._href = ""
        self._anchor: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lower = tag.lower()
        if lower in ("script", "style", "noscript", "svg"):
            self._skip += 1
            return
        if self._skip:
            return
        if lower == "title":
            self._in_title = True
        if lower == "a":
            self._href = dict(attrs).get("href") or ""
            self._anchor = []
        if lower in ("p", "div", "section", "article", "li", "br", "h1", "h2", "h3"):
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if lower == "title":
            self._in_title = False
        if lower == "a" and self._href:
            self.links.append(
                (self._href, " ".join("".join(self._anchor).split()))
            )
            self._href = ""
            self._anchor = []

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
        self.text.append(data)
        if self._href:
            self._anchor.append(data)


def _public_url(value: str) -> str:
    text = _validate_url_syntax(value, "Policy source URL")
    parsed = urllib.parse.urlparse(text)
    if parsed.username or parsed.password:
        raise ValueError("policy source URL must not contain credentials")
    host = str(parsed.hostname or "").lower()
    if host in ("localhost", "localhost.localdomain"):
        raise ValueError("policy source URL must be public")
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, parsed.port or 443)
            ]
        except (OSError, ValueError) as exc:
            raise ValueError(f"could not resolve policy source host: {host}") from exc
    if not addresses or any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        for address in addresses
    ):
        raise ValueError("policy source URL must resolve only to public addresses")
    return text


def _normalise_page_text(value: str, limit: int = 120_000) -> str:
    text = re.sub(r"\r\n?|\u00a0", "\n", value)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:limit]


def _fetch_policy_page(url: str, timeout: int = 25) -> dict[str, Any]:
    safe_url = _public_url(url)
    request = urllib.request.Request(
        safe_url,
        headers={
            "User-Agent": "Loom-Rebuttal-Policy/1.0",
            "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = _public_url(response.geturl())
            content_type = str(response.headers.get("Content-Type") or "").lower()
            body = response.read(2_000_001)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return {"url": safe_url, "ok": False, "error": str(exc)}
    if len(body) > 2_000_000:
        return {"url": final_url, "ok": False, "error": "policy page exceeds 2 MB"}

    if "pdf" in content_type or final_url.lower().endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(body))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:  # noqa: BLE001 - remote document boundary
            return {"url": final_url, "ok": False, "error": f"PDF parse failed: {exc}"}
        return {
            "url": final_url,
            "ok": bool(text.strip()),
            "title": Path(urllib.parse.urlparse(final_url).path).name,
            "text": _normalise_page_text(text),
            "links": [],
            "content_type": content_type,
        }

    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type)
    if match:
        charset = match.group(1)
    text = body.decode(charset, errors="replace")
    if "html" not in content_type and "<html" not in text[:1000].lower():
        return {
            "url": final_url,
            "ok": bool(text.strip()),
            "title": final_url,
            "text": _normalise_page_text(text),
            "links": [],
            "content_type": content_type,
        }
    parser = _PolicyPageParser()
    try:
        parser.feed(text)
    except Exception as exc:  # noqa: BLE001 - malformed HTML boundary
        return {"url": final_url, "ok": False, "error": f"HTML parse failed: {exc}"}
    links = [
        {
            "url": urllib.parse.urljoin(final_url, href),
            "anchor": anchor,
        }
        for href, anchor in parser.links
        if href and not href.startswith(("#", "mailto:", "javascript:"))
    ]
    page_text = _normalise_page_text("".join(parser.text))
    return {
        "url": final_url,
        "ok": bool(page_text),
        "title": " ".join(parser.title.split())[:300],
        "text": page_text,
        "links": links[:500],
        "content_type": content_type,
    }


def _same_policy_domain(candidate: str, seed: str) -> bool:
    candidate_host = str(urllib.parse.urlparse(candidate).hostname or "").lower()
    seed_host = str(urllib.parse.urlparse(seed).hostname or "").lower()
    return (
        candidate_host == seed_host
        or candidate_host.endswith("." + seed_host)
        or seed_host.endswith("." + candidate_host)
        or candidate_host in {"openreview.net", "www.openreview.net"}
    )


def fetch_policy_sources(
    studio: dict[str, Any],
    *,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fetch = fetcher or _fetch_policy_page
    seeds = [
        str(studio.get("cfp_url") or ""),
        str(studio.get("policy_url") or ""),
    ]
    queue = [url for url in seeds if url]
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    while queue and len(sources) < 6:
        requested = queue.pop(0)
        if requested in seen:
            continue
        seen.add(requested)
        page = fetch(requested)
        page["requested_url"] = requested
        sources.append(page)
        if not page.get("ok"):
            continue
        links = page.get("links") if isinstance(page.get("links"), list) else []
        for link in links:
            if not isinstance(link, dict):
                continue
            candidate = str(link.get("url") or "")
            label = f"{link.get('anchor', '')} {candidate}"
            if not re.search(
                r"(?i)(rebuttal|author response|discussion|review|faq|"
                r"guideline|submission|important dates|call for papers|cfp)",
                label,
            ):
                continue
            if not _same_policy_domain(candidate, str(studio.get("cfp_url") or "")):
                continue
            if candidate not in seen and candidate not in queue:
                queue.append(candidate)
            if len(queue) + len(sources) >= 10:
                break
    return sources


def _policy_field(
    raw_policy: dict[str, Any],
    key: str,
    source_urls: set[str],
) -> tuple[Any, dict[str, Any]]:
    raw = raw_policy.get(key)
    if isinstance(raw, dict):
        value = raw.get("value")
        source_url = str(raw.get("source_url") or "")
        evidence = {
            "source_url": source_url if source_url in source_urls else "",
            "quote": str(raw.get("quote") or "").strip()[:2000],
            "confidence": str(raw.get("confidence") or "low").strip()[:20],
        }
        return value, evidence
    return raw, {"source_url": "", "quote": "", "confidence": "low"}


def _policy_markdown(state: dict[str, Any]) -> str:
    policy = normalize_policy(state.get("policy") or {})
    evidence = (
        state.get("policy_evidence")
        if isinstance(state.get("policy_evidence"), dict)
        else {}
    )
    labels = {
        "platform": "投稿与讨论平台",
        "character_limit": "每份回复字符上限",
        "internal_target": "内部安全字符目标",
        "word_limit": "每份回复词数上限",
        "rebuttal_open_at": "Rebuttal 开放时间",
        "rebuttal_deadline": "Rebuttal 截止时间",
        "timezone": "时区 / AoE",
        "discussion_end": "Discussion 截止时间",
        "manuscript_frozen": "Rebuttal 期间正文是否冻结",
        "allow_revised_pdf": "是否允许上传修订 PDF",
        "allow_new_experiments": "是否允许报告新实验",
        "allow_links": "是否允许外部链接",
        "allow_attachments": "是否允许附件",
        "allow_global_response": "是否支持 Global Response",
        "allow_ac_response": "是否支持 AC / Meta-review 回复",
        "anonymous": "是否必须保持匿名",
        "reviewers_can_update_scores": "Reviewer 是否可以更新评分",
        "response_language": "回复语言",
        "submission_instructions": "提交与格式说明",
    }

    def render_value(value: Any) -> str:
        if isinstance(value, bool):
            return "允许 / 是" if value else "不允许 / 否"
        if value in ("", None, 0):
            return "未确认"
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        f"# {state.get('title', 'Conference')} Rebuttal 规则",
        "",
        f"**当前状态：** `{state.get('stage', STUDIO_STAGE_POLICY_INPUT)}`",
        f"**Call for Papers：** {state.get('cfp_url', '')}",
        f"**Policy 已人工批准：** {'是' if state.get('policy_approved_at') else '否'}",
        "",
        "## 一、官方硬规则",
        "",
        "| 规则 | 当前值 | 官方原文 | 来源 | 置信度 |",
        "|---|---|---|---|---|",
    ]
    for key, value in policy.items():
        item = evidence.get(key) if isinstance(evidence.get(key), dict) else {}
        quote = str(item.get("quote") or "").replace("|", "\\|").replace("\n", " ")
        source_url = str(item.get("source_url") or "")
        confidence = str(item.get("confidence") or "")
        if not quote and not source_url:
            rendered = f"未确认（回退值：{render_value(value)}）"
            confidence = "unknown"
        else:
            rendered = render_value(value)
        source = f"[官方来源]({source_url})" if source_url else "—"
        lines.append(
            f"| {labels.get(key, key)} | {rendered} | {quote or '—'} | "
            f"{source} | {confidence or 'low'} |"
        )
    lines.extend(["", "## 二、仍需人工确认", ""])
    unknowns = state.get("unknowns") or []
    lines.extend(f"- {item}" for item in unknowns)
    if not unknowns:
        lines.append("- 暂无；仍应由作者核对官方页面原文。")
    return "\n".join(lines).rstrip() + "\n"


def _strategy_markdown(strategy: dict[str, Any]) -> str:
    lines = ["# Rebuttal 接收策略", ""]
    summary = str(strategy.get("summary") or "").strip()
    if summary:
        lines.extend(["## 一、总体策略", "", summary, ""])
    headings = {
        "response_structure": "二、逐 Reviewer 回复结构",
        "priorities": "三、优先级",
        "warnings": "四、风险与禁止事项",
    }
    for key in ("response_structure", "priorities", "warnings"):
        values = strategy.get(key)
        if not isinstance(values, list):
            continue
        lines.extend([f"## {headings[key]}", ""])
        lines.extend(f"- {str(item).strip()}" for item in values if str(item).strip())
        lines.append("")
    if len(lines) == 2:
        lines.extend(["尚未生成策略。先执行 Policy Discovery。", ""])
    return "\n".join(lines).rstrip() + "\n"


def discover_studio_policy(
    studio_id: str,
    *,
    model: str = "",
    on_line: Callable[[str], None] | None = None,
    runner: ModelRunner | None = None,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    studio = read_studio(studio_id)
    if not studio:
        return {"ok": False, "error": "conference studio not found", "cost": 0.0}
    if on_line:
        on_line("fetching official conference policy sources")
    sources = fetch_policy_sources(studio, fetcher=fetcher)
    usable = [item for item in sources if item.get("ok") and item.get("text")]
    if not usable:
        errors = "; ".join(
            str(item.get("error") or "no readable text") for item in sources
        )
        return {
            "ok": False,
            "error": f"no official policy page could be read: {errors}",
            "sources": sources,
            "cost": 0.0,
        }
    source_urls = {str(item.get("url") or "") for item in usable}
    source_text = "\n\n".join(
        f"=== SOURCE {index}: {item.get('url')} ===\n"
        f"TITLE: {item.get('title', '')}\n{item.get('text', '')}"
        for index, item in enumerate(usable, 1)
    )[:350_000]
    prompt = f"""You extract official conference rebuttal policy and a separate
acceptance-oriented response strategy.

Conference: {studio.get('conference')} {studio.get('year')}

Use only the official source text below. Every factual policy field must contain
an exact source URL from the supplied SOURCE headers, a short supporting quote,
and confidence high/medium/low. If a rule is absent, set value to null and add
it to unknowns. Never infer a venue rule from general knowledge. Keep official
field values and quotes faithful to their source language, but write every
`strategy` sentence and every `unknowns` item in concise Simplified Chinese.

Return one JSON object and nothing else:
{{
  "official_policy": {{
    "platform": {{"value": "OpenReview|CMT|other|null", "source_url": "...", "quote": "...", "confidence": "high"}},
    "character_limit": {{"value": 10000, "source_url": "...", "quote": "...", "confidence": "high"}},
    "word_limit": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "rebuttal_open_at": {{"value": "", "source_url": "", "quote": "", "confidence": "low"}},
    "rebuttal_deadline": {{"value": "", "source_url": "", "quote": "", "confidence": "low"}},
    "timezone": {{"value": "", "source_url": "", "quote": "", "confidence": "low"}},
    "discussion_end": {{"value": "", "source_url": "", "quote": "", "confidence": "low"}},
    "manuscript_frozen": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "allow_revised_pdf": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "allow_new_experiments": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "allow_links": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "allow_attachments": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "allow_global_response": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "allow_ac_response": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "anonymous": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "reviewers_can_update_scores": {{"value": null, "source_url": "", "quote": "", "confidence": "low"}},
    "submission_instructions": {{"value": "", "source_url": "", "quote": "", "confidence": "low"}}
  }},
  "strategy": {{
    "summary": "how to maximize acceptance under these rules",
    "response_structure": ["..."],
    "priorities": ["..."],
    "warnings": ["..."]
  }},
  "unknowns": ["rules that require human confirmation"]
}}

Official sources:
{source_text}
"""
    if on_line:
        on_line(f"asking {model or 'default model'} to structure the policy")
    run = runner or ar._run_headless
    result = run(prompt, model=model, timeout=900, on_line=on_line)
    if not result.get("ok"):
        return {**result, "sources": sources}
    raw = _extract_json_object(str(result.get("text") or ""))
    if raw is None:
        return {
            "ok": False,
            "error": "model did not return a JSON policy object",
            "sources": sources,
            "cost": result.get("cost", 0.0),
        }
    raw_policy = (
        raw.get("official_policy")
        if isinstance(raw.get("official_policy"), dict)
        else {}
    )
    current = dict(studio.get("policy") or DEFAULT_POLICY)
    evidence: dict[str, Any] = {}
    for key in DEFAULT_POLICY:
        value, item = _policy_field(raw_policy, key, source_urls)
        evidence[key] = item
        if value not in (None, "", "unknown", "Unknown"):
            current[key] = value
    policy = normalize_policy(current)
    strategy = raw.get("strategy") if isinstance(raw.get("strategy"), dict) else {}
    unknowns = [
        str(item).strip()[:1000]
        for item in (raw.get("unknowns") or [])
        if str(item).strip()
    ][:50]
    studio_dir = studio_path(studio_id).parent
    _atomic_json(studio_dir / POLICY_SOURCES_FILE, {"sources": sources})
    _atomic_json(
        studio_dir / POLICY_FILE,
        {
            "policy": policy,
            "evidence": evidence,
            "unknowns": unknowns,
        },
    )
    (studio_dir / POLICY_MARKDOWN_FILE).write_text(
        _policy_markdown(
            {
                **studio,
                "policy": policy,
                "policy_evidence": evidence,
                "unknowns": unknowns,
                "stage": STUDIO_STAGE_AWAIT_POLICY_REVIEW,
            }
        ),
        encoding="utf-8",
    )
    (studio_dir / STRATEGY_FILE).write_text(
        _strategy_markdown(strategy),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "policy": policy,
        "policy_evidence": evidence,
        "strategy": strategy,
        "unknowns": unknowns,
        "sources": sources,
        "cost": result.get("cost", 0.0),
    }


def _normalize_concerns(raw: dict[str, Any]) -> list[dict[str, Any]]:
    reviewers_raw = raw.get("reviewers")
    if not isinstance(reviewers_raw, list):
        return []
    reviewers: list[dict[str, Any]] = []
    seen_reviewers: set[str] = set()
    for reviewer_index, reviewer_raw in enumerate(reviewers_raw, 1):
        if not isinstance(reviewer_raw, dict):
            continue
        reviewer_id = _safe_response_id(
            str(reviewer_raw.get("id") or reviewer_raw.get("reviewer") or ""),
            f"R{reviewer_index}",
        )
        base_id = reviewer_id
        suffix = 2
        while reviewer_id in seen_reviewers:
            reviewer_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_reviewers.add(reviewer_id)
        concerns_raw = reviewer_raw.get("concerns")
        concerns: list[dict[str, str]] = []
        if isinstance(concerns_raw, list):
            for concern_index, concern_raw in enumerate(concerns_raw, 1):
                if not isinstance(concern_raw, dict):
                    continue
                kind = str(concern_raw.get("type") or "W").strip().upper()
                prefix = "Q" if kind.startswith("Q") else ("M" if kind.startswith("M") else "W")
                concern_id = _safe_response_id(
                    str(concern_raw.get("id") or ""),
                    f"{reviewer_id}-{prefix}{concern_index}",
                )
                concerns.append(
                    {
                        "id": concern_id,
                        "type": {
                            "Q": "question",
                            "M": "meta",
                            "W": "weakness",
                        }[prefix],
                        "summary": str(concern_raw.get("summary") or "").strip()[:1000],
                        "verbatim": str(concern_raw.get("verbatim") or "").strip()[:3000],
                        "severity": str(concern_raw.get("severity") or "medium").strip()[:40],
                        "response_mode": str(
                            concern_raw.get("response_mode") or "clarify"
                        ).strip()[:40],
                        "evidence_needed": str(
                            concern_raw.get("evidence_needed") or ""
                        ).strip()[:1000],
                    }
                )
        reviewers.append(
            {
                "id": reviewer_id,
                "label": str(reviewer_raw.get("label") or reviewer_id).strip()[:160],
                "summary": str(reviewer_raw.get("summary") or "").strip()[:2000],
                "positive_points": [
                    str(value).strip()[:500]
                    for value in (reviewer_raw.get("positive_points") or [])
                    if str(value).strip()
                ][:8],
                "concerns": concerns,
            }
        )
    return [reviewer for reviewer in reviewers if reviewer["concerns"]]


def concern_matrix_markdown(reviewers: list[dict[str, Any]]) -> str:
    lines = [
        "# Rebuttal Concern Matrix",
        "",
        "| ID | Reviewer | Type | Severity | Concern | Response mode | Evidence needed |",
        "|---|---|---|---|---|---|---|",
    ]
    for reviewer in reviewers:
        for concern in reviewer.get("concerns") or []:
            values = [
                concern.get("id", ""),
                reviewer.get("label", reviewer.get("id", "")),
                concern.get("type", ""),
                concern.get("severity", ""),
                concern.get("summary", ""),
                concern.get("response_mode", ""),
                concern.get("evidence_needed", ""),
            ]
            escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
            lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines) + "\n"


def prepare_agent_instructions(project_id: str) -> Path:
    state = read_state(project_id)
    if not state:
        raise ValueError("rebuttal project not found")
    source = _source_for(project_id)
    if source is None:
        raise ValueError("paper source directory is missing")
    out = output_root(source)
    out.mkdir(parents=True, exist_ok=True)
    marker = out / AGENT_COMPLETE_FILE
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    policy = normalize_policy(
        state.get("policy") if isinstance(state.get("policy"), dict) else {}
    )
    studio = (
        read_studio(str(state.get("studio_id") or ""))
        if state.get("studio_id")
        else {}
    )
    policy_markdown = (
        _read_text(
            studio_artifact_path(str(state.get("studio_id")), POLICY_MARKDOWN_FILE),
            100_000,
        )
        if studio
        else ""
    )
    strategy_markdown = (
        _read_text(
            studio_artifact_path(str(state.get("studio_id")), STRATEGY_FILE),
            100_000,
        )
        if studio
        else ""
    )
    skill_path = ar.ar_skills_dir() / ar.SKILL_REBUTTAL
    review_paths = list((state.get("manifest") or {}).get("review_pdfs") or [])
    reviews_block = "\n".join(f"  - `{path}`" for path in review_paths)
    instructions = f"""# Auto Rebuttal Agent Task

You are the dedicated Rebuttal Agent for this paper. Work visibly in this tmux
pane and use tools to inspect the package. Do not modify or delete the submitted
paper, reviewer PDFs, or any source evidence. Write only under:

`{out}`

## Inputs

- Paper package: `{source}`
- Submitted PDF: `{(state.get('manifest') or {}).get('paper_pdf', '')}`
- Review PDFs:
{reviews_block}
- Rebuttal Skill: `{skill_path}`

Read the Rebuttal Skill completely before drafting.

## Approved Conference Policy

```json
{json.dumps(policy, indent=2, ensure_ascii=False)}
```

{policy_markdown}

## Acceptance Strategy

{strategy_markdown}

## Required workflow

1. Read the submitted PDF and every Review/Meta-review PDF.
2. Inspect relevant proof, experiment, result, and notes files in the package.
3. Atomize every reviewer Weakness and Question. Do not omit or soften a point.
4. Write `{out / CONCERNS_FILE}` exactly as:

```json
{{
  "reviewers": [
    {{
      "id": "R1",
      "label": "Reviewer R1",
      "summary": "...",
      "positive_points": ["..."],
      "concerns": [
        {{
          "id": "R1-W1",
          "type": "weakness",
          "verbatim": "short exact quote",
          "summary": "faithful one-line restatement",
          "severity": "critical|high|medium|low",
          "response_mode": "correct|clarify|scope|dispute|future",
          "evidence_needed": "..."
        }}
      ]
    }}
  ]
}}
```

5. Write `{out / CONCERN_MATRIX_FILE}` as a readable Markdown table.
6. For every reviewer ID, write one self-contained response to
   `{out / RESPONSES_SUBDIR}/response-<ID>.md`.
7. Start each response with specific gratitude. Answer every concern ID under
   its own heading, direct answer first, then evidence and action/scope.
8. Maximize acceptance probability using the strongest accurate framing.
9. Obey the Conference Policy exactly. Do not claim a frozen paper was changed;
   conditional future edits must use `If accepted, we will ...`.
10. Do not submit externally.

## Completion protocol

Only after all concern and response files are complete, write:

`{marker}`

with:

```json
{{"status": "complete", "reviewers": ["R1"], "summary": "..."}}
```

Make the completion marker the final file you write, then stop and wait.
"""
    path = out / AGENT_INSTRUCTIONS_FILE
    path.write_text(instructions, encoding="utf-8")
    return path


def ingest_agent_outputs(project_id: str) -> dict[str, Any]:
    state = read_state(project_id)
    source = _source_for(project_id)
    if not state or source is None:
        return {"ok": False, "error": "rebuttal project not found"}
    out = output_root(source)
    marker = _read_json(out / AGENT_COMPLETE_FILE, {})
    if not isinstance(marker, dict) or marker.get("status") != "complete":
        return {"ok": False, "error": "agent completion marker is missing or invalid"}
    raw = _read_json(out / CONCERNS_FILE, {})
    if not isinstance(raw, dict):
        return {"ok": False, "error": "agent concerns.json is missing or invalid"}
    reviewers = _normalize_concerns(raw)
    if not reviewers:
        return {"ok": False, "error": "agent produced no usable reviewer concerns"}
    (out / CONCERN_MATRIX_FILE).write_text(
        concern_matrix_markdown(reviewers),
        encoding="utf-8",
    )
    response_dir = out / RESPONSES_SUBDIR
    responses: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for reviewer in reviewers:
        reviewer_id = str(reviewer.get("id") or "")
        path = response_dir / f"response-{_safe_response_id(reviewer_id)}.md"
        body = _read_text(path, 200_000)
        if len(body.strip()) < 100:
            missing.append(reviewer_id)
            continue
        responses[reviewer_id] = {
            "reviewer_id": reviewer_id,
            "path": str(path),
            "filename": path.name,
            "characters": len(body.rstrip()),
            "updated_at": _now(),
        }
    if missing:
        return {
            "ok": False,
            "error": f"agent responses missing or empty: {', '.join(missing)}",
            "reviewers": reviewers,
            "responses": responses,
        }
    return {
        "ok": True,
        "reviewers": reviewers,
        "responses": responses,
        "summary": str(marker.get("summary") or "").strip()[:2000],
    }


ModelRunner = Callable[..., dict[str, Any]]


def _has_unconditional_future_manuscript_action(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        for match in _FUTURE_MANUSCRIPT_ACTION_RE.finditer(sentence):
            prefix = sentence[: match.start()].lower()
            if "if accepted," not in prefix:
                return True
    return False


def response_body(project_id: str, reviewer_id: str) -> str:
    state = read_state(project_id)
    metadata = state.get("responses") if isinstance(state.get("responses"), dict) else {}
    item = metadata.get(reviewer_id)
    if not isinstance(item, dict):
        return ""
    path = Path(str(item.get("path") or ""))
    source = _source_for(project_id)
    if source is None:
        return ""
    try:
        path.resolve().relative_to(output_root(source).resolve())
    except (OSError, ValueError):
        return ""
    return _read_text(path, 200_000)


def save_response(project_id: str, reviewer_id: str, body: str) -> dict[str, Any]:
    state = read_state(project_id)
    responses = dict(state.get("responses") or {})
    item = responses.get(reviewer_id)
    if not isinstance(item, dict):
        raise ValueError("unknown reviewer response")
    source = _source_for(project_id)
    if source is None:
        raise ValueError("rebuttal project not found")
    path = Path(str(item.get("path") or "")).resolve()
    try:
        path.relative_to((output_root(source) / RESPONSES_SUBDIR).resolve())
    except ValueError as exc:
        raise ValueError("response path escapes project output") from exc
    text = str(body or "").rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    item = dict(item)
    item["characters"] = len(text.rstrip())
    item["updated_at"] = _now()
    responses[reviewer_id] = item
    state["responses"] = responses
    state["validation"] = {}
    invalidate_delivery(state, f"{reviewer_id} response changed")
    state["content_approval"] = {}
    if state.get("stage") in (
        STAGE_VALIDATED,
        STAGE_APPROVED,
        STAGE_DELIVERY_AGENT,
        STAGE_DELIVERY_VALIDATING,
        STAGE_DELIVERY_BLOCKED,
        STAGE_AWAIT_DELIVERY_APPROVAL,
        STAGE_BUNDLE_READY,
    ):
        state["stage"] = STAGE_RESPONSES
        state["approved_at"] = ""
    append_log(state, f"{reviewer_id}: saved edited response")
    write_state(project_id, state)
    return project_payload(project_id)


def validate_project(project_id: str) -> dict[str, Any]:
    state = read_state(project_id)
    policy = normalize_policy(state.get("policy") if isinstance(state.get("policy"), dict) else {})
    reviewers = [item for item in state.get("reviewers") or [] if isinstance(item, dict)]
    responses = state.get("responses") if isinstance(state.get("responses"), dict) else {}
    report: dict[str, Any] = {
        "checked_at": _now(),
        "ready": True,
        "files": [],
        "errors": [],
    }
    reviewer_ids = {str(item.get("id") or "") for item in reviewers}
    if reviewer_ids != set(responses):
        missing = sorted(reviewer_ids - set(responses))
        extra = sorted(set(responses) - reviewer_ids)
        if missing:
            report["errors"].append(f"missing responses: {', '.join(missing)}")
        if extra:
            report["errors"].append(f"unexpected responses: {', '.join(extra)}")

    for reviewer in reviewers:
        reviewer_id = str(reviewer.get("id") or "")
        body = response_body(project_id, reviewer_id)
        errors: list[str] = []
        if len(body.strip()) < 100:
            errors.append("response is not substantive")
        count = len(body.rstrip())
        if count > policy["character_limit"]:
            errors.append(
                f"{count:,} characters exceed hard limit "
                f"{policy['character_limit']:,}"
            )
        elif count >= policy["internal_target"]:
            errors.append(
                f"{count:,} characters meet or exceed internal target "
                f"{policy['internal_target']:,}"
            )
        for concern in reviewer.get("concerns") or []:
            concern_id = str(concern.get("id") or "")
            if concern_id and concern_id not in body:
                errors.append(f"missing concern id {concern_id}")
        if _PLACEHOLDER_RE.search(body):
            errors.append("contains unresolved placeholder")
        if not policy["allow_links"] and _URL_RE.search(body):
            errors.append("contains a forbidden URL")
        if policy["anonymous"] and _EMAIL_RE.search(body):
            errors.append("contains an email address")
        if policy["manuscript_frozen"] and _REVISED_MANUSCRIPT_RE.search(body):
            errors.append("claims the frozen manuscript was already revised")
        if policy["manuscript_frozen"] and _has_unconditional_future_manuscript_action(
            body
        ):
            errors.append(
                'future manuscript action must use "If accepted, we will ..."'
            )
        report["files"].append(
            {
                "reviewer_id": reviewer_id,
                "characters": count,
                "ok": not errors,
                "errors": errors,
            }
        )
        report["errors"].extend(f"{reviewer_id}: {error}" for error in errors)

    report["ready"] = not report["errors"] and bool(reviewers)
    source = _source_for(project_id)
    if source is not None:
        _atomic_json(output_root(source) / VALIDATION_FILE, report)
        lines = [
            "# Rebuttal Validation",
            "",
            f"**Status:** {'READY' if report['ready'] else 'BLOCKED'}",
            f"**Checked:** {report['checked_at']}",
            "",
        ]
        for item in report["files"]:
            lines.append(
                f"- [{'x' if item['ok'] else ' '}] "
                f"{item['reviewer_id']}: {item['characters']:,} characters"
            )
            lines.extend(f"  - {error}" for error in item["errors"])
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error}" for error in report["errors"])
        (output_root(source) / VALIDATION_MARKDOWN_FILE).write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )
    return report


def content_approval_snapshot(
    project_id: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a human response approval to exact policy and response bytes."""
    current = state or read_state(project_id)
    response_hashes: dict[str, str] = {}
    for reviewer_id in sorted((current.get("responses") or {}).keys()):
        body = response_body(project_id, reviewer_id)
        response_hashes[str(reviewer_id)] = hashlib.sha256(
            body.encode("utf-8")
        ).hexdigest()
    policy = normalize_policy(
        current.get("policy") if isinstance(current.get("policy"), dict) else {}
    )
    policy_hash = hashlib.sha256(
        json.dumps(policy, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    digest_payload = {
        "policy_sha256": policy_hash,
        "responses": response_hashes,
    }
    return {
        **digest_payload,
        "digest": hashlib.sha256(
            json.dumps(
                digest_payload,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }


def approve_project(project_id: str) -> dict[str, Any]:
    current = read_state(project_id)
    if current.get("stage") != STAGE_VALIDATED:
        raise ValueError("validate the response content before human approval")
    report = validate_project(project_id)
    if not report.get("ready"):
        raise ValueError("rebuttal package is not validation-ready")
    state = read_state(project_id)
    state["validation"] = report
    state["stage"] = STAGE_APPROVED
    state["approved_at"] = _now()
    state["content_approval"] = {
        **content_approval_snapshot(project_id, state),
        "approved_at": state["approved_at"],
    }
    invalidate_delivery(state, "responses were approved again")
    append_log(state, "human approved the rebuttal response content")
    write_state(project_id, state)
    return project_payload(project_id)


def project_payload(project_id: str) -> dict[str, Any]:
    state = read_state(project_id)
    if not state:
        return {}
    responses = {}
    for reviewer_id, item in (state.get("responses") or {}).items():
        if not isinstance(item, dict):
            continue
        responses[reviewer_id] = {
            **item,
            "body": response_body(project_id, reviewer_id),
        }
    studio_id = str(state.get("studio_id") or "")
    studio = read_studio(studio_id) if studio_id else {}
    return {
        "ok": True,
        "project": {
            **state,
            "studio": {
                "id": studio_id,
                "title": studio.get("title", ""),
                "conference": studio.get("conference", ""),
                "year": studio.get("year", ""),
            }
            if studio
            else {},
            "policy": normalize_policy(
                state.get("policy") if isinstance(state.get("policy"), dict) else {}
            ),
            "responses": responses,
        },
    }


def delete_project(project_id: str) -> bool:
    """Forget a project without deleting source materials or generated output."""
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


def delete_studio(studio_id: str) -> bool:
    """Forget an empty Studio while preserving policy artifacts on disk."""
    if list_projects(studio_id):
        raise ValueError("forget or move every Paper Rebuttal before deleting the Studio")
    with _LOCK:
        data = _registry()
        before = len(data["studios"])
        data["studios"] = [
            item
            for item in data["studios"]
            if not (isinstance(item, dict) and item.get("id") == studio_id)
        ]
        if len(data["studios"]) == before:
            return False
        _write_registry(data)
    return True


def sweep_interrupted_jobs() -> int:
    cleared = 0
    for item in list_projects():
        project_id = str(item.get("id") or "")
        state = read_state(project_id)
        if state.get("active_job"):
            state["error"] = (
                f"{state['active_job']} was interrupted by a Loom restart; run it again"
            )
            state["active_job"] = ""
            append_log(state, state["error"])
            write_state(project_id, state)
            cleared += 1
    for item in list_studios():
        studio_id = str(item.get("id") or "")
        state = read_studio(studio_id)
        if state.get("active_job"):
            state["error"] = (
                f"{state['active_job']} was interrupted by a Loom restart; run it again"
            )
            state["active_job"] = ""
            append_log(state, state["error"])
            write_studio(studio_id, state)
            cleared += 1
    return cleared
