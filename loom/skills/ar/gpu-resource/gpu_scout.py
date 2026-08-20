#!/usr/bin/env python3
"""Free-GPU scout for the AR compute cluster.

The cluster's Slurm scheduler is unreliable (queues back up for hours, chained
`sbatch --dependency` jobs wedge into ``DependencyNeverSatisfied`` and never
run). The AR authors therefore bypass Slurm and run jobs directly on compute
nodes over SSH. This scout is what tells them *which* node:gpu pairs are
actually idle: it SSHes every reachable node, reads real ``nvidia-smi`` usage,
and republishes a free-GPU inventory every ``INTERVAL`` seconds.

Outputs (written atomically):
  ``<out>/free_gpus.json``  - machine-readable inventory
  ``<out>/free_gpus.txt``   - agent-facing table (this is what authors read)

A GPU counts as free when its ``memory.used`` is below ``THRESHOLD_MIB``.

Configuration (env vars, all optional):
  GPU_SCOUT_OUT        output directory   (default /data/shared/zhizhousha/gpu-scout)
  GPU_SCOUT_INTERVAL   seconds per sweep  (default 60)
  GPU_SCOUT_THRESHOLD  free cutoff MiB    (default 2000)
  GPU_SCOUT_SSH_TIMEOUT ssh connect secs  (default 12)
  GPU_SCOUT_WORKERS    parallel probes    (default 24)
  GPU_SCOUT_NODES      comma/space list to override sinfo discovery (optional)

Run:  python gpu_scout.py            # loop forever
      python gpu_scout.py --once     # single sweep then exit (handy in tests)

The agent-facing methodology lives in ``../GPU-RESOURCES.md``; keep the inventory
path here in sync with the path documented there.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(os.environ.get("GPU_SCOUT_OUT", "/data/shared/zhizhousha/gpu-scout"))
INTERVAL = int(os.environ.get("GPU_SCOUT_INTERVAL", "60"))
THRESHOLD_MIB = int(os.environ.get("GPU_SCOUT_THRESHOLD", "2000"))
SSH_TIMEOUT = int(os.environ.get("GPU_SCOUT_SSH_TIMEOUT", "12"))
MAX_WORKERS = int(os.environ.get("GPU_SCOUT_WORKERS", "24"))

# Slurm node states we skip because the box is unreachable/unusable, not because
# it is busy - a busy ("alloc") node can still expose an idle GPU, and the whole
# point of this scout is to find those.
SKIP_STATE_PREFIXES = ("down", "drain", "drng", "fail", "maint", "boot", "unk", "pow")


def _json_path() -> Path:
    return OUT_DIR / "free_gpus.json"


def _txt_path() -> Path:
    return OUT_DIR / "free_gpus.txt"


def candidate_nodes() -> list[str]:
    """Reachable compute nodes, from $GPU_SCOUT_NODES or ``sinfo``."""
    override = os.environ.get("GPU_SCOUT_NODES", "").replace(",", " ").split()
    if override:
        return sorted(set(override))
    try:
        out = subprocess.run(
            ["sinfo", "-h", "-N", "-o", "%N|%t"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    nodes: dict[str, str] = {}
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, state = line.split("|", 1)
        name = name.strip()
        state = state.strip().lower().rstrip("*~#$+")
        if not name:
            continue
        prev = nodes.get(name)
        skip = state.startswith(SKIP_STATE_PREFIXES)
        if prev is None or (prev.startswith(SKIP_STATE_PREFIXES) and not skip):
            nodes[name] = state
    return [n for n, s in nodes.items() if not s.startswith(SKIP_STATE_PREFIXES)]


def probe(node: str) -> tuple[str, list[dict] | None]:
    """Return (node, GPU dicts) or (node, None) if the node is unreachable."""
    try:
        res = subprocess.run(
            [
                "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                "-o", f"ConnectTimeout={SSH_TIMEOUT}", node,
                "nvidia-smi --query-gpu=index,memory.used,memory.total,"
                "utilization.gpu --format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=SSH_TIMEOUT + 6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return node, None
    if res.returncode != 0:
        return node, None
    gpus: list[dict] = []
    for line in res.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            gpus.append({
                "gpu": int(parts[0]),
                "mem_used_mib": int(parts[1]),
                "mem_total_mib": int(parts[2]),
                "util": int(parts[3]),
            })
        except ValueError:
            continue
    return node, gpus


def sweep() -> dict:
    nodes = candidate_nodes()
    free: list[dict] = []
    by_node: dict[str, list[int]] = {}
    unreachable: list[str] = []
    scanned = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(probe, n): n for n in nodes}
        for fut in as_completed(futs):
            node, gpus = fut.result()
            if gpus is None:
                unreachable.append(node)
                continue
            scanned += 1
            idle = []
            for g in gpus:
                if g["mem_used_mib"] < THRESHOLD_MIB:
                    idle.append(g["gpu"])
                    free.append({
                        "node": node, "gpu": g["gpu"],
                        "mem_used_mib": g["mem_used_mib"], "util": g["util"],
                    })
            if idle:
                by_node[node] = sorted(idle)
    free.sort(key=lambda d: (d["node"], d["gpu"]))
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "threshold_mib": THRESHOLD_MIB,
        "total_free": len(free),
        "nodes_scanned": scanned,
        "nodes_with_free": len(by_node),
        "nodes_unreachable": sorted(unreachable),
        "by_node": dict(sorted(by_node.items())),
        "free_gpus": free,
    }


def publish(inv: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _json_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(inv, indent=1), encoding="utf-8")
    tmp.replace(_json_path())

    lines = [
        f"# FREE GPU INVENTORY  (updated {inv['updated']})",
        f"# free = nvidia-smi memory.used < {inv['threshold_mib']} MiB. "
        f"{inv['total_free']} free GPU(s) across {inv['nodes_with_free']} node(s).",
        "# HOW TO USE: pick a node:gpu below, then run your job directly on it, e.g.",
        "#   ssh <node> 'cd <your worktree>; CUDA_VISIBLE_DEVICES=<gpu> setsid nohup \\",
        "#     ./.venv/bin/python train.py > runs/<name>.log 2>&1 &'",
        "# Do NOT use sbatch/srun/Slurm. Re-run nvidia-smi on the node to confirm the",
        "# GPU is still idle right before you launch (someone else may have grabbed it).",
        "",
    ]
    for node, gpus in inv["by_node"].items():
        lines.append(f"{node}\tgpu {','.join(str(g) for g in gpus)}")
    if not inv["by_node"]:
        lines.append("(no free GPUs right now - wait and re-read this file)")
    lines.append("")
    lines.append(
        f"TOTAL free: {inv['total_free']} GPU(s) on {inv['nodes_with_free']} node(s)"
    )
    tmp = _txt_path().with_suffix(".txt.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(_txt_path())


def main() -> None:
    once = "--once" in sys.argv[1:]
    print(
        f"[gpu-scout] publishing to {_txt_path()} "
        f"{'once' if once else f'every {INTERVAL}s'}",
        flush=True,
    )
    while True:
        t0 = time.time()
        try:
            inv = sweep()
            publish(inv)
            print(
                f"[gpu-scout {inv['updated']}] free={inv['total_free']} "
                f"nodes_with_free={inv['nodes_with_free']} "
                f"scanned={inv['nodes_scanned']} "
                f"unreachable={len(inv['nodes_unreachable'])}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - service loop must not die
            print(f"[gpu-scout] sweep error: {exc}", flush=True)
        if once:
            return
        time.sleep(max(5, INTERVAL - int(time.time() - t0)))


if __name__ == "__main__":
    main()
