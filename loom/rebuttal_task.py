"""File-backed projects and domain helpers for the Auto Rebuttal Factory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

from loom import ar_task as ar


REGISTRY_VERSION = 1
STATE_VERSION = 1
OUTPUT_SUBDIR = "rebuttal-output"
STATE_FILE = "state.json"
MANIFEST_FILE = "source-manifest.json"
CONCERNS_FILE = "concerns.json"
CONCERN_MATRIX_FILE = "concern-matrix.md"
VALIDATION_FILE = "validation.json"
VALIDATION_MARKDOWN_FILE = "validation.md"
RESPONSES_SUBDIR = "responses"

STAGE_INTAKE = "intake"
STAGE_CONCERNS = "concerns_ready"
STAGE_RESPONSES = "responses_ready"
STAGE_VALIDATED = "validated"
STAGE_APPROVED = "approved"

JOB_ANALYZE = "analyze"
JOB_DRAFT = "draft"

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
}

_LOCK = threading.RLock()
_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{12}$")
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
        {"version": REGISTRY_VERSION, "projects": []},
    )
    if not isinstance(data, dict):
        return {"version": REGISTRY_VERSION, "projects": []}
    projects = data.get("projects")
    if not isinstance(projects, list):
        projects = []
    return {"version": REGISTRY_VERSION, "projects": projects}


def _write_registry(data: dict[str, Any]) -> None:
    _atomic_json(registry_path(), data)


def project_id_for(source_path: Path) -> str:
    return hashlib.sha256(str(source_path.resolve()).encode()).hexdigest()[:12]


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


def read_state(project_id: str) -> dict[str, Any]:
    source = _source_for(project_id)
    if source is None:
        return {}
    data = _read_json(state_path(source), {})
    return data if isinstance(data, dict) else {}


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

        existing = _read_json(state_path(source), {})
        if not isinstance(existing, dict) or not existing:
            merged_policy = dict(DEFAULT_POLICY)
            if isinstance(policy, dict):
                merged_policy.update(policy)
            existing = {
                "version": STATE_VERSION,
                "id": project_id,
                "title": record["title"],
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
                "logs": [],
                "created_at": _now(),
            }
        else:
            existing["title"] = record["title"]
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
    return {
        "platform": str(data.get("platform") or "OpenReview")[:80],
        "character_limit": hard,
        "internal_target": target,
        "manuscript_frozen": bool(data.get("manuscript_frozen", True)),
        "allow_links": bool(data.get("allow_links", False)),
        "allow_attachments": bool(data.get("allow_attachments", False)),
        "allow_global_response": bool(data.get("allow_global_response", False)),
        "anonymous": bool(data.get("anonymous", True)),
        "response_language": str(data.get("response_language") or "English")[:40],
    }


def list_projects() -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    for record in _registry()["projects"]:
        if not isinstance(record, dict):
            continue
        project_id = str(record.get("id") or "")
        state = read_state(project_id)
        if not state:
            continue
        manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else {}
        validation = (
            state.get("validation")
            if isinstance(state.get("validation"), dict)
            else {}
        )
        projects.append(
            {
                "id": project_id,
                "title": state.get("title") or record.get("title"),
                "source_path": state.get("source_path") or record.get("source_path"),
                "stage": state.get("stage", STAGE_INTAKE),
                "active_job": state.get("active_job", ""),
                "error": state.get("error", ""),
                "reviewers": len(state.get("reviewers") or []),
                "review_files": len(manifest.get("review_pdfs") or []),
                "responses": len(state.get("responses") or {}),
                "ready": bool(validation.get("ready")),
                "cost_usd": float(state.get("cost_usd") or 0.0),
                "updated_at": state.get("updated_at", ""),
            }
        )
    return projects


def _safe_response_id(value: str, fallback: str = "reviewer") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-._")
    return slug[:80] or fallback


def _pdf_text(path: Path, limit: int = 120_000) -> tuple[str, str]:
    try:
        reader = PdfReader(str(path))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 - document boundary
        return "", str(exc)
    return text[:limit], ""


def _read_text(path: Path, limit: int = 12_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _review_material(state: dict[str, Any]) -> tuple[str, list[str]]:
    manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else {}
    blocks: list[str] = []
    errors: list[str] = []
    for index, raw in enumerate(manifest.get("review_pdfs") or [], 1):
        path = Path(str(raw))
        text, error = _pdf_text(path, 90_000)
        if error:
            errors.append(f"{path.name}: {error}")
            continue
        if not text.strip():
            errors.append(
                f"{path.name}: no extractable review text; provide an OCR-readable PDF"
            )
            continue
        blocks.append(f"=== REVIEW DOCUMENT {index}: {path.name} ===\n{text}")
    return "\n\n".join(blocks), errors


def _paper_material(state: dict[str, Any]) -> tuple[str, list[str]]:
    manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else {}
    value = str(manifest.get("paper_pdf") or "")
    if not value:
        return "", ["paper PDF is missing"]
    text, error = _pdf_text(Path(value), 140_000)
    if error:
        return "", [error]
    if not text.strip():
        return "", ["paper PDF has no extractable text; provide an OCR-readable PDF"]
    return text, []


def _evidence_material(state: dict[str, Any], limit: int = 120_000) -> str:
    manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else {}
    files = [
        item
        for item in manifest.get("files") or []
        if isinstance(item, dict) and item.get("kind") == "material"
    ]

    def score(item: dict[str, Any]) -> tuple[int, int, str]:
        name = str(item.get("relative_path") or "").lower()
        preferred = bool(
            re.search(
                r"(claim|evidence|result|proof|theory|experiment|table|figure|"
                r"review|readme|note|manifest)",
                name,
            )
        )
        return (0 if preferred else 1, int(item.get("size") or 0), name)

    chunks: list[str] = []
    total = 0
    for item in sorted(files, key=score):
        path = Path(str(item.get("path") or ""))
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        body = _read_text(path, 12_000)
        if not body.strip():
            continue
        chunk = f"=== {item.get('relative_path')} ===\n{body}\n"
        if total + len(chunk) > limit:
            remaining = limit - total
            if remaining > 500:
                chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n".join(chunks)


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


ModelRunner = Callable[..., dict[str, Any]]


def analyze_project(
    project_id: str,
    *,
    model: str = "",
    on_line: Callable[[str], None] | None = None,
    runner: ModelRunner | None = None,
) -> dict[str, Any]:
    state = read_state(project_id)
    if not state:
        return {"ok": False, "error": "rebuttal project not found", "cost": 0.0}
    manifest = state.get("manifest") if isinstance(state.get("manifest"), dict) else {}
    if not manifest.get("ready"):
        return {
            "ok": False,
            "error": "package needs one paper PDF and at least one review PDF",
            "cost": 0.0,
        }
    paper_text, paper_errors = _paper_material(state)
    review_text, review_errors = _review_material(state)
    if paper_errors or review_errors:
        return {
            "ok": False,
            "error": "; ".join(paper_errors + review_errors),
            "cost": 0.0,
        }
    prompt = f"""You are extracting an atomic concern matrix for an academic rebuttal.

Read the submitted paper and every review below. Do not draft responses yet.
Do not invent reviewer statements. Preserve each reviewer's identity label when
present; otherwise assign R1, R2, and so on.

Return one JSON object and nothing else:
{{
  "reviewers": [
    {{
      "id": "reviewer id or R1",
      "label": "display label",
      "summary": "one short paragraph",
      "positive_points": ["..."],
      "concerns": [
        {{
          "id": "R1-W1 or R1-Q1",
          "type": "weakness|question|meta",
          "verbatim": "short exact quote from the review",
          "summary": "faithful one-line restatement",
          "severity": "critical|high|medium|low",
          "response_mode": "correct|clarify|scope|dispute|future",
          "evidence_needed": "what proof/result/source is needed"
        }}
      ]
    }}
  ]
}}

Rules:
- Every weakness and question gets exactly one concern row.
- Repeated concerns from different reviewers remain separate.
- Do not weaken a concern while summarizing it.
- Do not infer that a concern is resolved.
- Scores and praise are metadata, not weaknesses.

=== SUBMITTED PAPER ===
{paper_text}

=== REVIEWS ===
{review_text}
"""
    if on_line:
        on_line("asking the model to atomize reviewer concerns")
    run = runner or ar._run_headless
    result = run(prompt, model=model, timeout=900, on_line=on_line)
    if not result.get("ok"):
        return result
    raw = _extract_json_object(str(result.get("text") or ""))
    if raw is None:
        return {
            "ok": False,
            "error": "model did not return a JSON concern object",
            "cost": result.get("cost", 0.0),
        }
    reviewers = _normalize_concerns(raw)
    if not reviewers:
        return {
            "ok": False,
            "error": "model returned no usable reviewer concerns",
            "cost": result.get("cost", 0.0),
        }
    source = _source_for(project_id)
    assert source is not None
    _atomic_json(output_root(source) / CONCERNS_FILE, {"reviewers": reviewers})
    (output_root(source) / CONCERN_MATRIX_FILE).write_text(
        concern_matrix_markdown(reviewers),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "reviewers": reviewers,
        "cost": result.get("cost", 0.0),
    }


def _strip_markdown_fence(text: str) -> str:
    value = str(text or "").strip()
    match = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)\s*```", value, re.S | re.I)
    return match.group(1).strip() if match else value


def _has_unconditional_future_manuscript_action(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        for match in _FUTURE_MANUSCRIPT_ACTION_RE.finditer(sentence):
            prefix = sentence[: match.start()].lower()
            if "if accepted," not in prefix:
                return True
    return False


def draft_project(
    project_id: str,
    *,
    model: str = "",
    on_line: Callable[[str], None] | None = None,
    runner: ModelRunner | None = None,
) -> dict[str, Any]:
    state = read_state(project_id)
    reviewers = [item for item in state.get("reviewers") or [] if isinstance(item, dict)]
    if not reviewers:
        return {"ok": False, "error": "analyze reviews first", "cost": 0.0}
    paper_text, errors = _paper_material(state)
    if errors:
        return {"ok": False, "error": "; ".join(errors), "cost": 0.0}
    evidence = _evidence_material(state)
    policy = normalize_policy(state.get("policy") if isinstance(state.get("policy"), dict) else {})
    skill = ar.ar_skill_text(ar.SKILL_REBUTTAL, limit=40_000)
    source = _source_for(project_id)
    assert source is not None
    response_dir = output_root(source) / RESPONSES_SUBDIR
    response_dir.mkdir(parents=True, exist_ok=True)
    responses: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    run = runner or ar._run_headless

    for reviewer in reviewers:
        reviewer_id = str(reviewer.get("id") or "reviewer")
        concern_ids = [
            str(item.get("id") or "")
            for item in reviewer.get("concerns") or []
            if isinstance(item, dict)
        ]
        if on_line:
            on_line(f"{reviewer_id}: drafting point-by-point response")
        prompt = f"""{skill}

=== END REBUTTAL SKILL ===

Draft one paste-ready response to this reviewer. Return Markdown only, without
code fences or internal notes.

Venue policy:
{json.dumps(policy, ensure_ascii=False, indent=2)}

Mandatory response rules:
- Open with specific gratitude.
- Use one heading for every concern id, preserving each id exactly.
- Under every heading: brief thanks, direct response, evidence, and action/scope.
- Maximize acceptance probability using the strongest accurate framing.
- Use only evidence supplied below; never invent results or manuscript changes.
- Character target: below {policy['internal_target']}; hard limit {policy['character_limit']}.
- Response language: {policy['response_language']}.
- Manuscript frozen: {policy['manuscript_frozen']}.
- Links allowed: {policy['allow_links']}.
- Attachments allowed: {policy['allow_attachments']}.

Reviewer record:
{json.dumps(reviewer, ensure_ascii=False, indent=2)}

Required concern ids:
{json.dumps(concern_ids, ensure_ascii=False)}

Submitted paper text:
{paper_text[:100_000]}

Available evidence and notes:
{evidence}
"""
        result = run(prompt, model=model, timeout=1_200, on_line=on_line)
        total_cost += float(result.get("cost") or 0.0)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": f"{reviewer_id}: {result.get('error')}",
                "cost": total_cost,
                "responses": responses,
            }
        body = _strip_markdown_fence(str(result.get("text") or ""))
        if len(body) < 100:
            return {
                "ok": False,
                "error": f"{reviewer_id}: model returned an empty response",
                "cost": total_cost,
                "responses": responses,
            }
        filename = f"response-{_safe_response_id(reviewer_id)}.md"
        path = response_dir / filename
        path.write_text(body.rstrip() + "\n", encoding="utf-8")
        responses[reviewer_id] = {
            "reviewer_id": reviewer_id,
            "path": str(path),
            "filename": filename,
            "characters": len(body),
            "updated_at": _now(),
        }
    return {"ok": True, "responses": responses, "cost": total_cost}


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
    if state.get("stage") in (STAGE_VALIDATED, STAGE_APPROVED):
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


def approve_project(project_id: str) -> dict[str, Any]:
    report = validate_project(project_id)
    if not report.get("ready"):
        raise ValueError("rebuttal package is not validation-ready")
    state = read_state(project_id)
    state["validation"] = report
    state["stage"] = STAGE_APPROVED
    state["approved_at"] = _now()
    append_log(state, "human approved the paste-ready rebuttal package")
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
    return {
        "ok": True,
        "project": {
            **state,
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
    return cleared
