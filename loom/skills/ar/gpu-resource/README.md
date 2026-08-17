# gpu-resource — free-GPU scout for direct-to-node experiments

This cluster's Slurm scheduler is unreliable: queues back up for hours and
chained `sbatch --dependency` jobs frequently wedge into
`DependencyNeverSatisfied` and never run, which hangs AR author rounds. So AR
authors **bypass Slurm and run jobs directly on compute nodes over SSH**. The
piece that makes that safe is this scout: it continuously reports which
`node:gpu` pairs are actually idle.

The agent-facing methodology (what an author does with the inventory) lives in
`../GPU-RESOURCES.md`, which is injected into every author prompt via
`ar_task.gpu_resources_block()`. This folder holds the **operator-side daemon**
that produces the inventory that skill tells authors to read.

## What `gpu_scout.py` does

Every `INTERVAL` seconds it:

1. Lists reachable compute nodes (`sinfo`, skipping down/drain/etc.), or uses
   `$GPU_SCOUT_NODES` if set.
2. SSHes each node in parallel and reads real `nvidia-smi` usage — it does **not**
   trust Slurm's alloc/idle state, because a Slurm-"alloc" node often still has
   idle GPUs.
3. Marks every GPU with `memory.used < THRESHOLD_MIB` (default 2000) as free.
4. Atomically republishes two files:
   - `free_gpus.json` — machine-readable inventory
   - `free_gpus.txt`  — the table authors read (node → free gpu indices)

## Inventory location (the contract)

Default output dir: `/data/shared/zhizhousha/gpu-scout/`

```
/data/shared/zhizhousha/gpu-scout/free_gpus.txt
/data/shared/zhizhousha/gpu-scout/free_gpus.json
```

`../GPU-RESOURCES.md` points authors at exactly this path, so if you change
`GPU_SCOUT_OUT` you must update that skill too.

## Running it

```bash
# from the repo root, with the project venv
./.venv/bin/python loom/skills/ar/gpu-resource/gpu_scout.py          # loop forever
./.venv/bin/python loom/skills/ar/gpu-resource/gpu_scout.py --once   # one sweep
```

Run it once as a long-lived background daemon (one per operator/cluster) while
AR papers are training; the 8+ author panes all read the same published files.

## Configuration (env vars)

| var | default | meaning |
| --- | --- | --- |
| `GPU_SCOUT_OUT` | `/data/shared/zhizhousha/gpu-scout` | where to publish the inventory |
| `GPU_SCOUT_INTERVAL` | `60` | seconds between sweeps |
| `GPU_SCOUT_THRESHOLD` | `2000` | a GPU is "free" below this many MiB used |
| `GPU_SCOUT_SSH_TIMEOUT` | `12` | per-node SSH connect timeout (s) |
| `GPU_SCOUT_WORKERS` | `24` | parallel SSH probes |
| `GPU_SCOUT_NODES` | _(unset)_ | comma/space node list overriding `sinfo` |

## Requirements

- Passwordless SSH (BatchMode) from the login node to the compute nodes.
- `nvidia-smi` on each node; `sinfo` on the login node (only for discovery —
  set `GPU_SCOUT_NODES` to skip Slurm entirely).
- The shared filesystem is visible on the compute nodes, so an author writes
  outputs into its `work/` tree from the node and tails them from its pane.
