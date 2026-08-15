"""Deterministic delivery harness for approved rebuttal response packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pypdf import PdfReader

from loom import ar_task as ar
from loom import rebuttal_task as rebuttal

DELIVERY_SUBDIR = "delivery"
ATTEMPTS_SUBDIR = "attempts"
DELIVERABLES_SUBDIR = "deliverables"
DELIVERY_INSTRUCTIONS_FILE = "DELIVERY_INSTRUCTIONS.md"
DELIVERY_COMPLETE_FILE = "delivery-complete.json"
REVISION_MAP_FILE = "revision-map.json"
PREFLIGHT_FILE = "preflight.json"
PREFLIGHT_MARKDOWN_FILE = "preflight.md"
DELIVERY_MANIFEST_FILE = "manifest.json"
HANDOFF_FILE = "openreview-handoff.md"
BUNDLE_FILE = "submission-bundle.zip"

_BUILD_SUFFIXES = {
    ".aux",
    ".bbl",
    ".blg",
    ".fls",
    ".log",
    ".out",
    ".synctex.gz",
    ".fdb_latexmk",
}
_GENERATED_PDFS = {
    "main.pdf",
    "rebuttal.pdf",
    "author-response-draft.pdf",
}
_PLACEHOLDER_RE = re.compile(
    r"\[\[[^\]\r\n]+\]|\b(?:TODO|TBD|FIXME|XXX)\b|PLEASE\s+UPDATE",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"(?i)(?:https?://|www\.|mailto:)\S+")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_WACV_OPTIONS_RE = re.compile(
    r"\\usepackage\s*\[([^\]]+)\]\s*\{wacv\}",
    re.IGNORECASE,
)
_WACV_ID_RE = re.compile(r"\\def\\wacvPaperID\s*\{([^}]+)\}")
_TITLE_RE = re.compile(r"\\title\s*\{([^{}]+)\}", re.DOTALL)
_WACV_TRACKS = ("algorithms", "applications", "datasets")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _json_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def delivery_root(source: Path) -> Path:
    return rebuttal.output_root(source) / DELIVERY_SUBDIR


def _source_for(project_id: str) -> Path:
    state = rebuttal.read_state(project_id)
    source = Path(str(state.get("source_path") or "")).expanduser()
    if not state or not source.is_dir():
        raise ValueError("rebuttal project source is missing")
    return source.resolve()


def _safe_relative(root: Path, value: str, *, suffixes: tuple[str, ...]) -> Path:
    raw = Path(str(value or ""))
    if raw.is_absolute() or not raw.parts:
        raise ValueError("delivery output path must be relative to its workspace")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("delivery output path escapes its workspace") from exc
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"delivery output must use one of: {', '.join(suffixes)}")
    if not path.is_file():
        raise ValueError(f"delivery output is missing: {raw}")
    return path


def _read_text(path: Path, limit: int = 500_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _strip_tex_comments(text: str) -> str:
    return "\n".join(
        re.sub(r"(?<!\\)%.*$", "", line)
        for line in text.splitlines()
    )


def _tex_metadata(source: Path) -> dict[str, str]:
    candidates = [
        source / "latex" / "main.tex",
        source / "main.tex",
        source / "review-rebuttal" / "author-response-draft.tex",
        source / "review-rebuttal" / "rebuttal.tex",
        source / "latex" / "rebuttal.tex",
    ]
    track = ""
    paper_id = ""
    title = ""
    for path in candidates:
        if not path.is_file():
            continue
        text = _strip_tex_comments(_read_text(path))
        if not track:
            for option_text in _WACV_OPTIONS_RE.findall(text):
                lowered = {
                    part.strip().lower()
                    for part in option_text.split(",")
                }
                found = next(
                    (value for value in _WACV_TRACKS if value in lowered),
                    "",
                )
                if found:
                    track = found
                    break
        if not paper_id:
            match = _WACV_ID_RE.search(text)
            if match:
                paper_id = match.group(1).strip()
        if not title:
            match = _TITLE_RE.search(text)
            if match:
                title = " ".join(match.group(1).split())
    return {"track": track, "paper_id": paper_id, "title": title}


def normalize_delivery_policy(
    state: dict[str, Any],
    source: Path | None = None,
) -> dict[str, Any]:
    """Return the structured artifact policy used by the delivery harness."""
    policy = rebuttal.normalize_policy(
        state.get("policy") if isinstance(state.get("policy"), dict) else {}
    )
    studio = (
        rebuttal.read_studio(str(state.get("studio_id") or ""))
        if state.get("studio_id")
        else {}
    )
    conference = str(studio.get("conference") or "").strip()
    instructions = str(policy.get("submission_instructions") or "")
    wacv = conference.upper() == "WACV" or "one page" in instructions.lower()
    metadata = _tex_metadata(source) if source is not None else {}
    saved = (
        state.get("delivery_policy")
        if isinstance(state.get("delivery_policy"), dict)
        else {}
    )

    def integer(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(saved.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    paper_id = str(saved.get("paper_id") or metadata.get("paper_id") or "")
    if not paper_id and str(state.get("title") or "").strip().isdigit():
        paper_id = str(state.get("title")).strip()
    track = str(saved.get("track") or metadata.get("track") or "")
    return {
        "enabled": bool(
            saved.get(
                "enabled",
                wacv or bool(policy.get("allow_revised_pdf")),
            )
        ),
        "venue": conference or ("WACV" if wacv else ""),
        "year": str(studio.get("year") or ""),
        "platform": str(policy.get("platform") or "OpenReview"),
        "deadline": str(policy.get("rebuttal_deadline") or ""),
        "timezone": str(policy.get("timezone") or ""),
        "same_submission_revision": bool(
            saved.get("same_submission_revision", wacv)
        ),
        "paper_id": paper_id,
        "paper_title": str(saved.get("paper_title") or metadata.get("title") or ""),
        "track": track,
        "rebuttal_format": "pdf" if wacv else str(
            saved.get("rebuttal_format") or "pdf"
        ),
        "rebuttal_page_limit": integer(
            "rebuttal_page_limit",
            1,
            1,
            20,
        ),
        "rebuttal_letter_required": bool(
            saved.get("rebuttal_letter_required", wacv)
        ),
        "paper_body_page_limit": integer(
            "paper_body_page_limit",
            8 if wacv else 0,
            0,
            30,
        ),
        "revised_paper_required": bool(
            saved.get(
                "revised_paper_required",
                wacv or bool(policy.get("allow_revised_pdf")),
            )
        ),
        "paper_max_bytes": integer(
            "paper_max_bytes",
            50 * 1024 * 1024,
            1024,
            500 * 1024 * 1024,
        ),
        "supplement_max_bytes": integer(
            "supplement_max_bytes",
            200 * 1024 * 1024,
            1024,
            1024 * 1024 * 1024,
        ),
        "separate_supplement": bool(
            saved.get("separate_supplement", wacv)
        ),
        "anonymous": bool(policy.get("anonymous", True)),
        "allow_links": bool(policy.get("allow_links", False)),
        "manual_upload_only": True,
        "submission_instructions": instructions,
    }


def _snapshot_files(source: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    roots = [
        source / "latex",
        source / "review-rebuttal",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in {".git", "__pycache__", ".pytest_cache"}
            )
            base = Path(dirpath)
            for name in sorted(filenames):
                path = base / name
                if path.is_symlink() or not path.is_file():
                    continue
                suffix = "".join(path.suffixes[-2:]) if path.name.endswith(
                    ".synctex.gz"
                ) else path.suffix
                if suffix.lower() in _BUILD_SUFFIXES:
                    continue
                if name.lower() in _GENERATED_PDFS:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size > 128 * 1024 * 1024:
                    continue
                records.append(
                    {
                        "relative_path": str(path.relative_to(source)),
                        "size": size,
                        "sha256": _sha256(path),
                    }
                )
                if len(records) >= 5_000:
                    return records
    return records


def source_snapshot(source: Path) -> dict[str, Any]:
    records = _snapshot_files(source)
    return {"files": records, "digest": _json_digest(records)}


def _copy_source_tree(source: Path, workspace_source: Path) -> None:
    workspace_source.mkdir(parents=True, exist_ok=True)
    for top_name in ("latex", "review-rebuttal"):
        src_root = source / top_name
        if not src_root.is_dir():
            continue
        dst_root = workspace_source / top_name
        for dirpath, dirnames, filenames in os.walk(src_root):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in {".git", "__pycache__", ".pytest_cache"}
            )
            base = Path(dirpath)
            rel = base.relative_to(src_root)
            (dst_root / rel).mkdir(parents=True, exist_ok=True)
            for name in sorted(filenames):
                src = base / name
                if src.is_symlink() or not src.is_file():
                    continue
                suffix = "".join(src.suffixes[-2:]) if src.name.endswith(
                    ".synctex.gz"
                ) else src.suffix
                if suffix.lower() in _BUILD_SUFFIXES:
                    continue
                if name.lower() in _GENERATED_PDFS:
                    continue
                try:
                    if src.stat().st_size > 128 * 1024 * 1024:
                        continue
                    shutil.copy2(src, dst_root / rel / name)
                except OSError:
                    continue
    for name in ("latexmkrc", ".latexmkrc"):
        path = source / name
        if path.is_file() and not path.is_symlink():
            shutil.copy2(path, workspace_source / name)


def _candidate_tex_paths(workspace_source: Path) -> tuple[Path, Path]:
    rebuttal_candidates = [
        workspace_source / "review-rebuttal" / "author-response-draft.tex",
        workspace_source / "review-rebuttal" / "rebuttal.tex",
        workspace_source / "latex" / "rebuttal.tex",
    ]
    paper_candidates = [
        workspace_source / "latex" / "main.tex",
        workspace_source / "main.tex",
    ]
    rebuttal_tex = next(
        (path for path in rebuttal_candidates if path.is_file()),
        rebuttal_candidates[0],
    )
    paper_tex = next(
        (path for path in paper_candidates if path.is_file()),
        paper_candidates[0],
    )
    return rebuttal_tex, paper_tex


def _delivery_instructions(
    *,
    state: dict[str, Any],
    source: Path,
    attempt: Path,
    workspace: Path,
    run_id: str,
    input_digest: str,
    policy: dict[str, Any],
    rebuttal_tex: Path,
    paper_tex: Path,
    feedback: str,
) -> str:
    skill = (
        ar.ar_skills_dir()
        / "paper-rebuttal-delivery"
        / "SKILL.md"
    )
    response_dir = attempt / "inputs" / "responses"
    marker = attempt / DELIVERY_COMPLETE_FILE
    revision_map = attempt / REVISION_MAP_FILE
    try:
        rebuttal_relative = rebuttal_tex.relative_to(workspace)
        paper_relative = paper_tex.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("delivery workspace path is invalid") from exc
    return f"""# WACV Rebuttal Delivery Agent

You are the one-shot Delivery Agent for an already human-approved response.
Read `{skill}` completely before working.

## Hard boundaries

- Original package is read-only: `{source}`
- You may write only inside this isolated attempt: `{attempt}`
- Editable source copy: `{workspace}`
- Approved response snapshots: `{response_dir}`
- Never upload to OpenReview or any external service.
- Never claim a new experiment, proof, or paper change unless it exists in the
  editable source copy and is supported by the package.
- Do not decide that the package passed. The deterministic Loom harness will
  rebuild and validate every artifact after you stop.

## Frozen delivery policy

```json
{json.dumps(policy, indent=2, ensure_ascii=False)}
```

## Required one-shot work

1. Read every approved response snapshot and the concern matrix.
2. Inspect the original evidence and the editable manuscript copy.
3. Reconcile every statement that says a revision was completed with the
   actual manuscript source. Correct the copy or narrow the response; never
   fabricate completion.
4. Compress the approved response content into the official one-page WACV
   response source at `{rebuttal_tex}`. Preserve the strongest defensible AC
   and reviewer answers. Correct track, title, Paper ID, anonymity, and template
   are mandatory.
5. Produce the synchronized revised manuscript at `{paper_tex}`. If the source
   contains an inline supplement and policy requires a separate supplement,
   split it into a separate source or remove it from the revised-paper build.
6. You may compile locally to iterate, but Loom will discard that verdict and
   rebuild independently.
7. Meet the layout and visual quality bar (all mandatory):
   - The paper body (all content before References) must fill every allowed
     body page completely — no half-empty final body page. The References
     heading must start on the page after the body limit. Expand with real,
     already-measured content; never pad with filler.
   - The one-page response must fill its entire page. A column that ends
     halfway is a failure.
   - Never print placeholder values such as "unmeasured", "TBD", "N/A (not
     run)" inside a results table. Report a real number or remove the row.
   - The revised paper keeps a page-one teaser/overview figure and a method
     overview figure unless the venue forbids them.
   - After the final compile, render every page and visually audit each
     figure at its printed size: no text overflowing its box, no overlapping
     labels, no clipped legends. Fix and re-render until clean. A separate
     three-model reviewer panel will re-check the rendered figures and will
     block delivery on any visual defect.
8. Write `{revision_map}` as JSON:

```json
{{
  "paper_id": "{policy.get('paper_id', '')}",
  "changes": [
    {{
      "concern_ids": ["R1-W1"],
      "section": "3.3",
      "pages": "4--5",
      "summary": "what changed",
      "status": "implemented|scoped"
    }}
  ],
  "unresolved": []
}}
```

9. As the final write, create `{marker}` exactly as:

```json
{{
  "status": "complete",
  "run_id": "{run_id}",
  "input_digest": "{input_digest}",
  "rebuttal_tex": "{rebuttal_relative}",
  "paper_tex": "{paper_relative}",
  "supplement": "",
  "revision_map": "{REVISION_MAP_FILE}",
  "summary": "short factual summary"
}}
```

Do not write the marker until all source and map files are complete.

## Previous deterministic validation feedback

{feedback or "(first attempt; no previous report)"}
"""


def prepare_delivery_attempt(
    project_id: str,
    *,
    feedback: str = "",
) -> dict[str, Any]:
    state = rebuttal.read_state(project_id)
    if not state:
        raise ValueError("rebuttal project not found")
    if state.get("stage") not in {
        rebuttal.STAGE_APPROVED,
        rebuttal.STAGE_DELIVERY_BLOCKED,
        rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL,
        rebuttal.STAGE_BUNDLE_READY,
    }:
        raise ValueError("human-approve the response content before delivery")
    current_delivery = (
        state.get("delivery")
        if isinstance(state.get("delivery"), dict)
        else {}
    )
    if current_delivery.get("agent_status") == "running":
        raise ValueError("delivery agent is already running")

    source = _source_for(project_id)
    policy = normalize_delivery_policy(state, source)
    if not policy.get("enabled"):
        raise ValueError("approved policy does not enable a revised-PDF delivery")
    approval = (
        state.get("content_approval")
        if isinstance(state.get("content_approval"), dict)
        else {}
    )
    current_approval = rebuttal.content_approval_snapshot(project_id, state)
    if not approval:
        approval = {
            **current_approval,
            "approved_at": str(state.get("approved_at") or _now()),
            "migrated": True,
        }
        state["content_approval"] = approval
    if approval.get("digest") != current_approval.get("digest"):
        raise ValueError("approved response content changed; approve it again")

    snapshot = source_snapshot(source)
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    attempt = delivery_root(source) / ATTEMPTS_SUBDIR / run_id
    workspace = attempt / "workspace"
    workspace_source = workspace / "source"
    inputs = attempt / "inputs"
    responses_out = inputs / "responses"
    responses_out.mkdir(parents=True, exist_ok=True)
    _copy_source_tree(source, workspace_source)
    for reviewer_id in sorted((state.get("responses") or {}).keys()):
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(reviewer_id)).strip("-")
        (responses_out / f"response-{safe_id or 'reviewer'}.md").write_text(
            rebuttal.response_body(project_id, str(reviewer_id)),
            encoding="utf-8",
        )
    policy_path = inputs / "delivery-policy.json"
    _atomic_json(policy_path, policy)
    _atomic_json(inputs / "content-approval.json", approval)
    _atomic_json(inputs / "source-snapshot.json", snapshot)
    concern_path = rebuttal.output_root(source) / rebuttal.CONCERN_MATRIX_FILE
    if concern_path.is_file():
        shutil.copy2(concern_path, inputs / rebuttal.CONCERN_MATRIX_FILE)

    digest_payload = {
        "content_approval": approval.get("digest"),
        "delivery_policy": policy,
        "source_digest": snapshot.get("digest"),
    }
    input_digest = _json_digest(digest_payload)
    rebuttal_tex, paper_tex = _candidate_tex_paths(workspace_source)
    instructions_path = attempt / DELIVERY_INSTRUCTIONS_FILE
    instructions_path.write_text(
        _delivery_instructions(
            state=state,
            source=source,
            attempt=attempt,
            workspace=workspace,
            run_id=run_id,
            input_digest=input_digest,
            policy=policy,
            rebuttal_tex=rebuttal_tex,
            paper_tex=paper_tex,
            feedback=feedback,
        ),
        encoding="utf-8",
    )

    attempts = list(current_delivery.get("attempts") or [])
    attempts.append(
        {
            "run_id": run_id,
            "created_at": _now(),
            "attempt_path": str(attempt),
            "input_digest": input_digest,
        }
    )
    state["delivery_policy"] = policy
    state["delivery"] = {
        "run_id": run_id,
        "phase": "prepared",
        "created_at": _now(),
        "attempt_path": str(attempt),
        "workspace_path": str(workspace),
        "instructions_path": str(instructions_path),
        "marker_path": str(attempt / DELIVERY_COMPLETE_FILE),
        "input_digest": input_digest,
        "source_digest": snapshot.get("digest"),
        "content_approval_digest": approval.get("digest"),
        "agent_status": "prepared",
        "agent_model": "",
        "tmux_target": "",
        "summary": "",
        "validation": {},
        "artifacts": {},
        "final_approval": {},
        "bundle": {},
        "attempts": attempts[-20:],
    }
    state["error"] = ""
    rebuttal.append_log(state, f"prepared delivery attempt {run_id}")
    rebuttal.write_state(project_id, state)
    return {
        "ok": True,
        "run_id": run_id,
        "attempt": attempt,
        "workspace": workspace,
        "instructions": instructions_path,
        "marker": attempt / DELIVERY_COMPLETE_FILE,
        "input_digest": input_digest,
    }


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "command": command,
            "returncode": -1,
            "output": str(exc),
        }
    output = ((result.stdout or "") + "\n" + (result.stderr or ""))[-50_000:]
    return {
        "ok": result.returncode == 0,
        "command": command,
        "returncode": result.returncode,
        "output": output,
    }


def strict_build_pdf(
    tex_path: Path,
    build_root: Path,
    output_name: str,
    *,
    timeout: int = 360,
) -> dict[str, Any]:
    """Build from source in a fresh directory and require a clean exit."""
    if not tex_path.is_file():
        return {"ok": False, "error": f"TeX source is missing: {tex_path}"}
    build_root.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    compilers: list[tuple[str, list[str]]] = []
    latexmk = shutil.which("latexmk")
    if latexmk:
        compilers.append(
            (
                "latexmk",
                [
                    latexmk,
                    "-pdf",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-file-line-error",
                    f"-outdir={build_root}",
                    tex_path.name,
                ],
            )
        )
    tectonic = shutil.which("tectonic")
    if tectonic:
        compilers.append(
            (
                "tectonic",
                [
                    tectonic,
                    "--keep-logs",
                    "--outdir",
                    str(build_root),
                    tex_path.name,
                ],
            )
        )
    pdflatex = shutil.which("pdflatex")
    if pdflatex and not latexmk:
        compilers.append(
            (
                "pdflatex",
                [
                    pdflatex,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-file-line-error",
                    f"-output-directory={build_root}",
                    tex_path.name,
                ],
            )
        )
    if not compilers:
        return {"ok": False, "error": "no LaTeX compiler is available"}

    build_env = os.environ.copy()
    tex_roots = [
        str(tex_path.parent),
        str(tex_path.parent.parent / "latex"),
    ]
    existing_texinputs = build_env.get("TEXINPUTS", "")
    if existing_texinputs:
        tex_roots.append(existing_texinputs)
    build_env["TEXINPUTS"] = os.pathsep.join(tex_roots) + os.pathsep

    for compiler, command in compilers:
        compiler_dir = build_root / compiler
        shutil.rmtree(compiler_dir, ignore_errors=True)
        compiler_dir.mkdir(parents=True, exist_ok=True)
        adjusted = [
            str(compiler_dir) if value == str(build_root) else value
            for value in command
        ]
        adjusted = [
            f"-outdir={compiler_dir}" if value == f"-outdir={build_root}" else value
            for value in adjusted
        ]
        adjusted = [
            f"-output-directory={compiler_dir}"
            if value == f"-output-directory={build_root}"
            else value
            for value in adjusted
        ]
        result = _run_command(
            adjusted,
            cwd=tex_path.parent,
            timeout=timeout,
            env=build_env,
        )
        if compiler == "pdflatex" and result.get("ok"):
            result = _run_command(
                adjusted,
                cwd=tex_path.parent,
                timeout=timeout,
                env=build_env,
            )
        result["compiler"] = compiler
        attempts.append(result)
        built = compiler_dir / f"{tex_path.stem}.pdf"
        if result.get("ok") and built.is_file() and built.stat().st_size > 0:
            output = build_root / output_name
            shutil.copy2(built, output)
            log = compiler_dir / f"{tex_path.stem}.log"
            return {
                "ok": True,
                "pdf": str(output),
                "compiler": compiler,
                "log": str(log) if log.is_file() else "",
                "attempts": attempts,
            }
    detail = "; ".join(
        f"{item.get('compiler')}: exit {item.get('returncode')}"
        for item in attempts
    )
    return {
        "ok": False,
        "error": f"strict LaTeX build failed ({detail})",
        "attempts": attempts,
    }


def _pdf_info(path: Path) -> dict[str, Any]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not read PDF: {exc}"}
    text_parts: list[str] = []
    letter = True
    links: list[str] = []
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            text_parts.append("")
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        if not (
            abs(width - 612.0) <= 8.0
            and abs(height - 792.0) <= 8.0
        ):
            letter = False
        annotations = page.get("/Annots") or []
        for ref in annotations:
            try:
                annotation = ref.get_object()
                action = annotation.get("/A") or {}
                uri = action.get("/URI")
                if uri:
                    links.append(str(uri))
            except Exception:  # noqa: BLE001, S112
                continue
    metadata = {
        str(key): str(value)
        for key, value in (reader.metadata or {}).items()
        if value is not None
    }
    return {
        "ok": True,
        "pages": len(reader.pages),
        "page_texts": text_parts,
        "letter": letter,
        "text": "\n".join(text_parts),
        "links": links,
        "metadata": metadata,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _references_start_page(page_texts: list[str]) -> int:
    """1-based page on which the References section heading appears, or 0."""
    for index, text in enumerate(page_texts, 1):
        for raw in text.splitlines():
            line = raw.strip().lower().strip("0123456789 .")
            if line == "references":
                return index
    return 0


def _tex_preflight(
    path: Path,
    policy: dict[str, Any],
    *,
    rebuttal_source: bool,
) -> list[str]:
    text = _strip_tex_comments(_read_text(path))
    errors: list[str] = []
    if _PLACEHOLDER_RE.search(text):
        errors.append(f"{path.name}: unresolved placeholder")
    if policy.get("anonymous") and _EMAIL_RE.search(text):
        errors.append(f"{path.name}: email address violates anonymity")
    if rebuttal_source:
        match = _WACV_OPTIONS_RE.search(text)
        options = {
            part.strip().lower()
            for part in (match.group(1).split(",") if match else [])
        }
        if policy.get("venue") == "WACV" and "rebuttal" not in options:
            errors.append("rebuttal source does not use WACV rebuttal mode")
        expected_track = str(policy.get("track") or "")
        if expected_track and expected_track not in options:
            errors.append(
                f"rebuttal source uses the wrong WACV track; expected {expected_track}"
            )
        expected_id = str(policy.get("paper_id") or "")
        id_match = _WACV_ID_RE.search(text)
        if expected_id and (
            not id_match or id_match.group(1).strip() != expected_id
        ):
            errors.append(f"rebuttal source must use Paper ID {expected_id}")
        expected_title = " ".join(
            str(policy.get("paper_title") or "").split()
        )
        if expected_title and expected_title not in " ".join(text.split()):
            errors.append("rebuttal source does not contain the paper title")
        if not policy.get("allow_links") and _URL_RE.search(text):
            errors.append("rebuttal source contains a forbidden external URL")
    return errors


def _log_preflight(log_path: str, label: str) -> list[str]:
    if not log_path:
        return []
    text = _read_text(Path(log_path), 1_000_000)
    errors: list[str] = []
    if re.search(r"(?i)undefined (?:references?|citations?)", text):
        errors.append(f"{label}: undefined reference or citation")
    if re.search(r"(?i)LaTeX Warning:.*multiply defined", text):
        errors.append(f"{label}: multiply-defined reference")
    if re.search(r"(?i)Overfull \\[hv]box", text):
        errors.append(f"{label}: overfull box")
    return errors


def _revision_map_preflight(path: Path, state: dict[str, Any]) -> list[str]:
    raw = _read_json(path, {})
    if not isinstance(raw, dict):
        return ["revision-map.json is missing or invalid"]
    changes = raw.get("changes")
    if not isinstance(changes, list) or not changes:
        return ["revision-map.json contains no manuscript changes"]
    covered: set[str] = set()
    for item in changes:
        if not isinstance(item, dict):
            continue
        covered.update(
            str(value)
            for value in (item.get("concern_ids") or [])
            if str(value)
        )
        if not str(item.get("summary") or "").strip():
            return ["revision-map.json has a change without a summary"]
    unresolved = raw.get("unresolved")
    if isinstance(unresolved, list):
        for item in unresolved:
            if isinstance(item, dict):
                covered.update(
                    str(value)
                    for value in (item.get("concern_ids") or [])
                    if str(value)
                )
            elif isinstance(item, str):
                covered.add(item)
    required = {
        str(concern.get("id") or "")
        for reviewer in (state.get("reviewers") or [])
        if isinstance(reviewer, dict)
        for concern in (reviewer.get("concerns") or [])
        if isinstance(concern, dict) and concern.get("id")
    }
    missing = sorted(required - covered)
    return (
        ["revision map omits concern IDs: " + ", ".join(missing)]
        if missing
        else []
    )


def _artifact_record(path: Path, name: str) -> dict[str, Any]:
    info = _pdf_info(path) if path.suffix.lower() == ".pdf" else {}
    return {
        "name": name,
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "pages": int(info.get("pages") or 0),
    }


def _preflight_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Rebuttal Delivery Preflight",
        "",
        f"**Status:** {'READY' if report.get('ready') else 'BLOCKED'}",
        f"**Checked:** {report.get('checked_at', '')}",
        "",
        "## Checks",
    ]
    for item in report.get("checks") or []:
        lines.append(
            f"- [{'x' if item.get('ok') else ' '}] "
            f"{item.get('label')}: {item.get('detail', '')}"
        )
    lines.extend(["", "## Errors"])
    errors = report.get("errors") or []
    lines.extend(f"- {error}" for error in errors)
    if not errors:
        lines.append("- None")
    return "\n".join(lines).rstrip() + "\n"


def _handoff_markdown(
    policy: dict[str, Any],
    artifacts: dict[str, Any],
) -> str:
    lines = [
        "# OpenReview Handoff",
        "",
        (
            "Loom does not upload these files. A human must use the existing "
            "revision action for the same submission."
        ),
        "",
        f"- Platform: {policy.get('platform', 'OpenReview')}",
        f"- Venue: {policy.get('venue', '')} {policy.get('year', '')}".rstrip(),
        f"- Paper ID: {policy.get('paper_id', '')}",
        (
            f"- Deadline: {policy.get('deadline', '')} "
            f"{policy.get('timezone', '')}"
        ).rstrip(),
        "- Submission action: revise the existing paper; do not create a new submission",
        "",
        "## Files",
    ]
    for key in ("revised_paper", "rebuttal", "supplement"):
        item = artifacts.get(key)
        if isinstance(item, dict):
            lines.append(
                f"- {key}: `{item.get('name')}` "
                f"(SHA-256 `{item.get('sha256')}`)"
            )
    lines.extend(
        [
            "",
            "## Human checklist",
            "",
            "- [ ] Open the existing Paper ID and choose its revision action.",
            "- [ ] Visually inspect every uploaded PDF after upload.",
            "- [ ] Confirm title, track, anonymity, and supplementary-material choice.",
            "- [ ] Re-download the uploaded files and compare them with this manifest.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def ingest_delivery_completion(project_id: str) -> dict[str, Any]:
    state = rebuttal.read_state(project_id)
    delivery = (
        state.get("delivery")
        if isinstance(state.get("delivery"), dict)
        else {}
    )
    if not state or not delivery:
        return {"ok": False, "error": "delivery attempt not found"}
    attempt = Path(str(delivery.get("attempt_path") or "")).resolve()
    workspace = Path(str(delivery.get("workspace_path") or "")).resolve()
    marker_path = attempt / DELIVERY_COMPLETE_FILE
    marker = _read_json(marker_path, {})
    if not isinstance(marker, dict) or marker.get("status") != "complete":
        return {"ok": False, "error": "delivery completion marker is missing or invalid"}
    if str(marker.get("run_id") or "") != str(delivery.get("run_id") or ""):
        return {"ok": False, "error": "stale delivery completion marker run ID"}
    if str(marker.get("input_digest") or "") != str(
        delivery.get("input_digest") or ""
    ):
        return {"ok": False, "error": "stale delivery completion marker input digest"}
    try:
        rebuttal_tex = _safe_relative(
            workspace,
            str(marker.get("rebuttal_tex") or ""),
            suffixes=(".tex",),
        )
        paper_tex = _safe_relative(
            workspace,
            str(marker.get("paper_tex") or ""),
            suffixes=(".tex",),
        )
        revision_map = _safe_relative(
            attempt,
            str(marker.get("revision_map") or REVISION_MAP_FILE),
            suffixes=(".json",),
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    policy = normalize_delivery_policy(state, _source_for(project_id))
    build_root = attempt / "build"
    shutil.rmtree(build_root, ignore_errors=True)
    rebuttal_build = strict_build_pdf(
        rebuttal_tex,
        build_root / "rebuttal",
        "rebuttal.pdf",
    )
    paper_build = strict_build_pdf(
        paper_tex,
        build_root / "paper",
        "revised-paper.pdf",
    )
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    for label, result in (
        ("rebuttal clean build", rebuttal_build),
        ("revised paper clean build", paper_build),
    ):
        ok = bool(result.get("ok"))
        checks.append(
            {
                "label": label,
                "ok": ok,
                "detail": result.get("compiler") if ok else result.get("error", ""),
            }
        )
        if not ok:
            errors.append(f"{label}: {result.get('error', 'failed')}")
    errors.extend(_tex_preflight(rebuttal_tex, policy, rebuttal_source=True))
    errors.extend(_tex_preflight(paper_tex, policy, rebuttal_source=False))
    errors.extend(_revision_map_preflight(revision_map, state))
    errors.extend(_log_preflight(str(rebuttal_build.get("log") or ""), "rebuttal"))
    errors.extend(_log_preflight(str(paper_build.get("log") or ""), "revised paper"))

    artifacts_dir = attempt / DELIVERABLES_SUBDIR
    shutil.rmtree(artifacts_dir, ignore_errors=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    if rebuttal_build.get("ok"):
        source_pdf = Path(str(rebuttal_build["pdf"]))
        target = artifacts_dir / "rebuttal.pdf"
        shutil.copy2(source_pdf, target)
        info = _pdf_info(target)
        page_limit = int(policy.get("rebuttal_page_limit") or 1)
        if int(info.get("pages") or 0) != page_limit:
            errors.append(
                f"rebuttal PDF must be exactly {page_limit} page(s); "
                f"found {info.get('pages', 0)}"
            )
        if policy.get("rebuttal_letter_required") and not info.get("letter"):
            errors.append("rebuttal PDF is not US Letter geometry")
        if policy.get("anonymous") and _EMAIL_RE.search(str(info.get("text") or "")):
            errors.append("rebuttal PDF contains an email address")
        rebuttal_author = str((info.get("metadata") or {}).get("/Author") or "")
        if (
            policy.get("anonymous")
            and rebuttal_author.strip()
            and "anonymous" not in rebuttal_author.lower()
        ):
            errors.append("rebuttal PDF metadata contains a non-anonymous author")
        if not policy.get("allow_links") and info.get("links"):
            errors.append("rebuttal PDF contains an external link annotation")
        if _PLACEHOLDER_RE.search(str(info.get("text") or "")):
            errors.append("rebuttal PDF contains an unresolved placeholder")
        artifacts["rebuttal"] = _artifact_record(target, target.name)
    if paper_build.get("ok"):
        source_pdf = Path(str(paper_build["pdf"]))
        target = artifacts_dir / "revised-paper.pdf"
        shutil.copy2(source_pdf, target)
        info = _pdf_info(target)
        if target.stat().st_size > int(policy.get("paper_max_bytes") or 0):
            errors.append("revised paper exceeds the configured file-size limit")
        if policy.get("anonymous") and _EMAIL_RE.search(str(info.get("text") or "")):
            errors.append("revised paper PDF contains an email address")
        paper_author = str((info.get("metadata") or {}).get("/Author") or "")
        if (
            policy.get("anonymous")
            and paper_author.strip()
            and "anonymous" not in paper_author.lower()
        ):
            errors.append("revised paper PDF metadata contains a non-anonymous author")
        if policy.get("separate_supplement") and re.search(
            r"(?i)\b(?:supplementary material|supplemental material)\b",
            str(info.get("text") or ""),
        ):
            errors.append(
                "revised paper still contains inline supplementary material"
            )
        body_limit = int(policy.get("paper_body_page_limit") or 0)
        if body_limit:
            pages = int(info.get("pages") or 0)
            references_page = _references_start_page(
                list(info.get("page_texts") or [])
            )
            if pages < body_limit:
                errors.append(
                    f"revised paper has only {pages} page(s); the body must "
                    f"fill all {body_limit} allowed pages"
                )
            elif references_page and references_page <= body_limit:
                errors.append(
                    f"paper body must fill all {body_limit} allowed pages; "
                    f"the References section already starts on page "
                    f"{references_page}"
                )
        artifacts["revised_paper"] = _artifact_record(target, target.name)

    supplement_value = str(marker.get("supplement") or "").strip()
    if supplement_value:
        try:
            supplement = _safe_relative(
                workspace,
                supplement_value,
                suffixes=(".pdf", ".zip"),
            )
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if supplement.stat().st_size > int(
                policy.get("supplement_max_bytes") or 0
            ):
                errors.append("supplement exceeds the configured file-size limit")
            target = artifacts_dir / f"supplement{supplement.suffix.lower()}"
            shutil.copy2(supplement, target)
            artifacts["supplement"] = _artifact_record(target, target.name)

    required = {"rebuttal"}
    if policy.get("revised_paper_required"):
        required.add("revised_paper")
    missing = sorted(required - set(artifacts))
    if missing:
        errors.append("missing required delivery artifacts: " + ", ".join(missing))

    report = {
        "checked_at": _now(),
        "run_id": delivery.get("run_id"),
        "input_digest": delivery.get("input_digest"),
        "ready": not errors,
        "checks": checks,
        "errors": errors,
        "artifacts": artifacts,
        "revision_map": str(revision_map),
        "builds": {
            "rebuttal": rebuttal_build,
            "paper": paper_build,
        },
    }
    _atomic_json(attempt / PREFLIGHT_FILE, report)
    (attempt / PREFLIGHT_MARKDOWN_FILE).write_text(
        _preflight_markdown(report),
        encoding="utf-8",
    )
    manifest = {
        "version": 1,
        "run_id": delivery.get("run_id"),
        "input_digest": delivery.get("input_digest"),
        "source_digest": delivery.get("source_digest"),
        "policy": policy,
        "artifacts": artifacts,
        "created_at": _now(),
    }
    _atomic_json(attempt / DELIVERY_MANIFEST_FILE, manifest)
    (attempt / HANDOFF_FILE).write_text(
        _handoff_markdown(policy, artifacts),
        encoding="utf-8",
    )

    state_report = {
        key: value
        for key, value in report.items()
        if key != "builds"
    }
    state = rebuttal.read_state(project_id)
    current = dict(state.get("delivery") or {})
    current.update(
        phase="awaiting_final_approval" if report["ready"] else "blocked",
        agent_status="complete",
        summary=str(marker.get("summary") or "")[:2000],
        validation=state_report,
        artifacts=artifacts,
        manifest_path=str(attempt / DELIVERY_MANIFEST_FILE),
        preflight_path=str(attempt / PREFLIGHT_MARKDOWN_FILE),
        handoff_path=str(attempt / HANDOFF_FILE),
        completed_at=_now(),
    )
    state["delivery"] = current
    state["stage"] = (
        rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL
        if report["ready"]
        else rebuttal.STAGE_DELIVERY_BLOCKED
    )
    state["error"] = "" if report["ready"] else "; ".join(errors[:5])
    rebuttal.append_log(
        state,
        "delivery preflight passed; awaiting final artifact approval"
        if report["ready"]
        else f"delivery preflight blocked by {len(errors)} issue(s)",
    )
    rebuttal.write_state(project_id, state)
    return {
        "ok": report["ready"],
        "error": "" if report["ready"] else state["error"],
        "report": report,
    }


def _deterministic_zip(path: Path, files: list[tuple[str, Path]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for arcname, source in sorted(files):
            info = zipfile.ZipInfo(arcname)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with source.open("rb") as input_handle, archive.open(
                info,
                "w",
            ) as output_handle:
                shutil.copyfileobj(
                    input_handle,
                    output_handle,
                    length=1024 * 1024,
                )


def _figure_verification_prompt(pdf_path: Path) -> str:
    return f"""You are one member of a strict three-model scientific-figure
verification panel. Review only the rendered figures in `{pdf_path}` and their
captions/context. Do not accept or reject the paper's research contribution.

Audit every main-text figure at its final paper size:

1. scientific fidelity to the caption and surrounding claims;
2. exact values, conditions, uncertainty, sample sizes, and negative findings;
3. readable labels, legends, axes, typography, and colour contrast;
4. no clipping, overlap, bad alignment, pseudo-text, misleading geometry, or
   unsupported significance;
5. consistent visual language and publication-ready WACV presentation;
6. teaser topology and arrows preserve the actual method and caveats;
7. results graphics expose rather than hide individual-run variability when
   the evidence supports it.

Use FAIL if any figure needs another redraw before submission. Minor aesthetic
preferences that do not impair correctness or readability are not blocking.

Return exactly this Markdown structure:

# Figure Verification

Figure Verdict: PASS|FAIL

## Blocking Figure Issues
- `None` for PASS, otherwise concrete figure/page/element fixes.

## Figure-by-Figure Audit
- Inspect every main-text figure separately.

## Scores
Soundness: 1-4
Presentation: 1-4
Contribution: 1-4
Rating: 1-10
Confidence: 1-5
Recommendation: accept|weak accept|borderline|weak reject|reject

PASS requires no blocking issue and Rating at least 7/10. Judge the PDF itself,
not source files or prior versions.
"""


def verify_delivery_figures(
    project_id: str,
    *,
    timeout: int = 1800,
    on_line: Any = None,
) -> dict[str, Any]:
    """Require all fixed Cursor reviewers to approve the rendered figures."""
    state = rebuttal.read_state(project_id)
    current = (
        state.get("delivery")
        if isinstance(state.get("delivery"), dict)
        else {}
    )
    paper = (current.get("artifacts") or {}).get("revised_paper")
    pdf = Path(str((paper or {}).get("path") or ""))
    if not pdf.is_file():
        return {"ok": False, "error": "revised-paper.pdf is missing"}
    catalog = ar._cursor_models()
    if not catalog.get("ok"):
        return catalog
    available = set(catalog.get("models") or [])
    missing = [
        model for model in ar.CURSOR_REVIEWER_MODELS if model not in available
    ]
    if missing:
        return {
            "ok": False,
            "error": "required figure reviewer model(s) unavailable: "
            + ", ".join(missing),
        }

    if on_line is not None:
        on_line(
            "verifying revised-paper figures with: "
            + ", ".join(ar.CURSOR_REVIEWER_MODELS)
        )
    with TemporaryDirectory(
        prefix="loom-rebuttal-figure-review-",
        ignore_cleanup_errors=True,
    ) as tmp:
        workspace = Path(tmp)
        review_pdf = workspace / "revised-paper.pdf"
        shutil.copy2(pdf, review_pdf)
        prompt = _figure_verification_prompt(review_pdf)
        by_model: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(
            max_workers=len(ar.CURSOR_REVIEWER_MODELS)
        ) as pool:
            futures = {
                pool.submit(
                    ar._run_cursor_headless,
                    prompt,
                    model,
                    workspace,
                    timeout=timeout,
                    on_line=on_line,
                ): model
                for model in ar.CURSOR_REVIEWER_MODELS
            }
            for future in as_completed(futures):
                model = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "ok": False,
                        "model": model,
                        "error": str(exc),
                    }
                text = str(result.get("review") or "")
                verdict_match = re.search(
                    r"(?im)^\s*(?:\*\*)?Figure Verdict(?:\*\*)?"
                    r"\s*[:：]\s*(?:\*\*)?(PASS|FAIL)",
                    text,
                )
                verdict = (
                    verdict_match.group(1).upper()
                    if verdict_match
                    else "FAIL"
                )
                rating = float((result.get("scores") or {}).get("rating") or 0)
                result["figure_verdict"] = verdict
                result["figure_pass"] = bool(
                    result.get("ok") and verdict == "PASS" and rating >= 7
                )
                by_model[model] = result

    reviewers = [
        by_model.get(
            model,
            {"ok": False, "model": model, "error": "review result missing"},
        )
        for model in ar.CURSOR_REVIEWER_MODELS
    ]
    all_pass = all(item.get("figure_pass") for item in reviewers)
    attempt = Path(str(current.get("attempt_path") or ""))
    review_dir = attempt / "figure-verification"
    review_dir.mkdir(parents=True, exist_ok=True)
    for item in reviewers:
        model = str(item.get("model") or "unknown")
        safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "-", model)
        (review_dir / f"{safe_model}.md").write_text(
            str(item.get("review") or f"ERROR: {item.get('error', '')}").rstrip()
            + "\n",
            encoding="utf-8",
        )
    report = {
        "checked_at": _now(),
        "all_pass": all_pass,
        "models": list(ar.CURSOR_REVIEWER_MODELS),
        "reviewers": reviewers,
        "input_pdf": str(pdf),
        "input_sha256": _sha256(pdf),
    }
    _atomic_json(review_dir / "figure-verification.json", report)
    summary_lines = [
        "# Three-Model Figure Verification",
        "",
        f"**Verdict:** {'PASS' if all_pass else 'FAIL'}",
        f"**PDF SHA-256:** `{report['input_sha256']}`",
        "",
    ]
    for item in reviewers:
        summary_lines.extend(
            [
                f"## {item.get('model')}",
                "",
                f"- Verdict: {item.get('figure_verdict', 'FAIL')}",
                f"- Rating: {(item.get('scores') or {}).get('rating', 'missing')}/10",
                f"- Complete: {'yes' if item.get('ok') else 'no'}",
                "",
            ]
        )
    (review_dir / "README.md").write_text(
        "\n".join(summary_lines).rstrip() + "\n",
        encoding="utf-8",
    )

    state = rebuttal.read_state(project_id)
    current = dict(state.get("delivery") or {})
    current["figure_verification"] = report
    current["final_approval"] = {}
    current["bundle"] = {}
    if all_pass:
        current["phase"] = "awaiting_final_approval"
        current["agent_status"] = "complete"
        state["stage"] = rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL
        state["error"] = ""
        rebuttal.append_log(
            state,
            "all three figure reviewers passed the revised paper",
        )
    else:
        current["phase"] = "figure_verification_blocked"
        current["agent_status"] = "complete"
        state["stage"] = rebuttal.STAGE_DELIVERY_BLOCKED
        failed = [
            str(item.get("model") or "unknown")
            for item in reviewers
            if not item.get("figure_pass")
        ]
        state["error"] = "figure verification failed: " + ", ".join(failed)
        rebuttal.append_log(state, state["error"])
    state["delivery"] = current
    rebuttal.write_state(project_id, state)
    return {"ok": all_pass, "report": report, "review_dir": str(review_dir)}


def approve_delivery(project_id: str) -> dict[str, Any]:
    state = rebuttal.read_state(project_id)
    if state.get("stage") != rebuttal.STAGE_AWAIT_DELIVERY_APPROVAL:
        raise ValueError("delivery artifacts are not ready for final approval")
    delivery = dict(state.get("delivery") or {})
    report = delivery.get("validation")
    if not isinstance(report, dict) or not report.get("ready"):
        raise ValueError("delivery preflight has not passed")
    artifacts_map = (
        delivery.get("artifacts")
        if isinstance(delivery.get("artifacts"), dict)
        else {}
    )
    revised = artifacts_map.get("revised_paper")
    if isinstance(revised, dict):
        verification = (
            delivery.get("figure_verification")
            if isinstance(delivery.get("figure_verification"), dict)
            else {}
        )
        if not verification.get("all_pass"):
            raise ValueError(
                "all three figure reviewers must pass before final approval"
            )
        if str(verification.get("input_sha256") or "") != str(
            revised.get("sha256") or ""
        ):
            raise ValueError(
                "figure verification is stale; re-verify the current "
                "revised paper"
            )
    approval = rebuttal.content_approval_snapshot(project_id, state)
    if approval.get("digest") != delivery.get("content_approval_digest"):
        raise ValueError("approved response content changed; rebuild delivery")
    source = _source_for(project_id)
    if source_snapshot(source).get("digest") != delivery.get("source_digest"):
        raise ValueError("paper source changed after delivery started; rebuild delivery")

    artifacts = (
        delivery.get("artifacts")
        if isinstance(delivery.get("artifacts"), dict)
        else {}
    )
    exact_hashes: dict[str, str] = {}
    files: list[tuple[str, Path]] = []
    for key, item in artifacts.items():
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        expected = str(item.get("sha256") or "")
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"delivery artifact changed after validation: {key}")
        exact_hashes[key] = expected
        files.append((str(item.get("name") or path.name), path))

    attempt = Path(str(delivery.get("attempt_path") or ""))
    for name in (
        DELIVERY_MANIFEST_FILE,
        PREFLIGHT_FILE,
        PREFLIGHT_MARKDOWN_FILE,
        HANDOFF_FILE,
    ):
        path = attempt / name
        if path.is_file():
            files.append((name, path))
    bundle = attempt / DELIVERABLES_SUBDIR / BUNDLE_FILE
    _deterministic_zip(bundle, files)
    bundle_record = _artifact_record(bundle, bundle.name)
    approved_at = _now()
    delivery["phase"] = "bundle_ready"
    delivery["final_approval"] = {
        "approved_at": approved_at,
        "artifact_sha256": exact_hashes,
        "input_digest": delivery.get("input_digest"),
    }
    delivery["bundle"] = bundle_record
    state["delivery"] = delivery
    state["stage"] = rebuttal.STAGE_BUNDLE_READY
    state["error"] = ""
    rebuttal.append_log(
        state,
        "human approved exact delivery artifact hashes; bundle is ready",
    )
    rebuttal.write_state(project_id, state)
    return rebuttal.project_payload(project_id)


def artifact_path(project_id: str, artifact: str) -> Path | None:
    state = rebuttal.read_state(project_id)
    delivery = (
        state.get("delivery")
        if isinstance(state.get("delivery"), dict)
        else {}
    )
    attempt = Path(str(delivery.get("attempt_path") or ""))
    if not attempt.is_dir():
        return None
    if artifact == "bundle":
        item = delivery.get("bundle")
    elif artifact == "preflight":
        path = Path(str(delivery.get("preflight_path") or ""))
        item = {"path": str(path)}
    elif artifact == "handoff":
        path = Path(str(delivery.get("handoff_path") or ""))
        item = {"path": str(path)}
    else:
        item = (delivery.get("artifacts") or {}).get(artifact)
    if not isinstance(item, dict):
        return None
    path = Path(str(item.get("path") or ""))
    try:
        path.resolve().relative_to(attempt.resolve())
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None
