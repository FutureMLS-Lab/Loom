"""Kernel Lab machinery (legacy).

Carved out of web.py in the route split. Kernel Lab is retired - the
bundle left the tree and creation is disabled - but one pre-retirement
task still renders, so its run storage, cluster profiles, launch/judge
pipeline and doc generators live on here until the feature is buried
for good.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from loom.paths import KERNEL_HUB_ENV, kernel_hub_dir
from loom.rud_task import (
    AGENT_CLAUDE,
    PLAN,
    agent_default_model,
    read_kernel_interview,
    task_root,
    task_worktree_path,
)

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
        f"Kernel Lab helper '{script_name}' not found at {bundled}. Kernel Lab "
        f"is retired and the bundle left the tree; to run this legacy task, "
        f"check out a pre-retirement revision (before c23b149) and set "
        f"{KERNEL_HUB_ENV}=<that-checkout>/loom/kernel_hub"
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




