# Compute resources — run every experiment on the GPU cluster

The machine your pane runs on is a **slurm login node with NO GPU** and only 32
oversubscribed CPU cores. Model inference on it takes minutes per item where an
H100 takes seconds. Running experiments locally is the single biggest cause of
slow author rounds — a round that should take under an hour stretches to 8–19
hours on local CPU.

**Rule: never run model inference or training on the login node.** Small
aggregation/plotting scripts are fine locally; anything that loads model
weights goes to the cluster.

## Slurm (preferred)

The `batch` partition has nodes with **8x NVIDIA H100 80GB** each (176 CPU
cores, ~1TB RAM per node). Queue wait is typically minutes.

Interactive / one-off:

```
srun --partition=batch --gres=gpu:1 --cpus-per-task=16 --mem=100G \
     --time=04:00:00 --job-name=<task>-<what> <command>
```

Long or parallel lanes — write a script and submit with `sbatch` (same flags,
plus `--output=logs/%x-%j.out`), one job per lane; check with
`squeue -u $USER`. Free-GPU overview: `sinfo -p batch -O NodeList,Gres,GresUsed`.

What carries over transparently: the shared filesystem. Your `work/` tree, the
HuggingFace cache (`research-factory/.cache/huggingface`), and your `.venv`s
are all on shared storage and visible from compute nodes — activate the same
venv inside the job.

## Migration guidance

- **transformers-based runners**: the same script works on a GPU node with
  `device_map="auto"` (or `.to("cuda")`). This is usually a one-line change.
- **llama.cpp / GGUF CPU servers**: on a GPU node, prefer serving the original
  HF checkpoint with transformers or vLLM inside the job; GGUF quantizations
  exist for CPU. If you must keep llama.cpp, use a CUDA build with `-ngl 999`.
- **Parity first**: before committing to GPU results, rerun one small batch
  (greedy / temperature 0) and confirm it matches your CPU outputs; note any
  numeric drift in the round summary rather than silently mixing backends.
- **Mid-experiment**: let a batch that is nearly done finish where it started;
  submit all remaining chunks to the GPU. Never mix backends within one
  reported table without saying so.
- **Record the recipe**: once a slurm invocation works for your codebase, write
  it into your notes (README or scratch notes) so every later round reuses it
  instead of rediscovering flags.

## Defensive preflight in every GPU job

Occasionally a leaked process squats a GPU outside slurm's accounting, and jobs
scheduled onto that GPU OOM at model load. Start every sbatch script with a
guard: query the assigned GPU's used memory (`nvidia-smi
--query-gpu=memory.used --format=csv,noheader`), and if it is already above
~20 GB, `scontrol requeue $SLURM_JOB_ID` and exit instead of loading the model.
This turns a night of OOM-failed jobs into a few cheap requeues.

## If slurm is full

`tscheduler` (`/data/shared/zhizhousha/workspace/loom-project/tscheduler`) can
locate free GPUs on Together's Kubernetes clusters: `scripts/radar.sh snapshot`
or `scripts/radar.sh find h100 8`. Slurm is simpler — reach for tscheduler only
when the batch partition has no capacity.
