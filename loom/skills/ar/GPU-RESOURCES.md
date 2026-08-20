# Compute resources — run every experiment on a GPU compute node

The machine your pane runs on is a **login node with NO GPU** and only ~32
oversubscribed CPU cores. Model inference on it takes minutes per item where an
H100 takes seconds. Running experiments locally is the single biggest cause of
slow author rounds — a round that should take under an hour stretches to 8–19
hours on local CPU.

**Rule: never run model inference or training on the login node.** Small
aggregation/plotting scripts are fine locally; anything that loads model
weights goes to a GPU compute node.

## Do NOT use Slurm on this cluster

Slurm here is unreliable: the queue backs up for hours and chained
`sbatch --dependency` jobs frequently wedge into `DependencyNeverSatisfied` and
never run, which hangs your round. **Do not use `sbatch`, `srun`, or any Slurm
command.** Ignore Slurm entirely and run directly on a compute node over SSH.

## Find a free GPU, then SSH to the node and run there

A background scout refreshes a free-GPU inventory every ~60 seconds:

```
/data/shared/zhizhousha/gpu-scout/free_gpus.txt     # human/agent-facing table
/data/shared/zhizhousha/gpu-scout/free_gpus.json    # same data, machine-readable
```

"Free" means `nvidia-smi` memory.used < 2000 MiB on that GPU. Each node has 8×
H100 80GB (176 CPU cores, ~1 TB RAM). Workflow every time you need a GPU:

1. **Read the inventory** (`cat /data/shared/zhizhousha/gpu-scout/free_gpus.txt`)
   and pick a `node` + `gpu` index. For N parallel lanes, pick N different
   `node:gpu` pairs.
2. **Re-verify right before launch** — the inventory can be up to a minute
   stale and GPUs are shared, so confirm the exact GPU is still idle:

   ```
   ssh <node> "nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F', ' '\$1==<gpu>{print \$2}'"
   ```

   If that prints a number ≥ ~2000, pick another `node:gpu` from the inventory.
3. **Launch on the node**, pinned to that GPU, detached, logging into your
   worktree (which is on shared storage the node can see):

   ```
   ssh <node> 'cd <abs path to your work/code>; \
     CUDA_VISIBLE_DEVICES=<gpu> setsid nohup ./.venv/bin/python train.py \
       > runs/<lane>.log 2>&1 & echo "PID $! on <node> gpu <gpu>"'
   ```
4. **Poll from your pane** by tailing the logfile (shared FS): `tail -n 40
   runs/<lane>.log`. Do **not** open a blocking wait; sleep-poll the log/output
   files and move on to other work between checks.
5. **Clean up** when a lane finishes or you abandon it: `ssh <node> "pkill -f
   <unique substring of your command>"` so you free the GPU for the next lane
   and for other people.

What carries over transparently: the **shared filesystem**. Your `work/` tree,
the HuggingFace cache (`research-factory/.cache/huggingface`), and your `.venv`s
are all on shared storage and visible from every compute node — activate the
same venv inside the SSH command.

## Migration guidance

- **transformers-based runners**: the same script works on a GPU node with
  `device_map="auto"` (or `.to("cuda")`). Usually a one-line change.
- **llama.cpp / GGUF CPU servers**: on a GPU node, prefer serving the original
  HF checkpoint with transformers or vLLM; if you must keep llama.cpp, use a
  CUDA build with `-ngl 999`.
- **Parity first**: before trusting GPU results, rerun one small batch (greedy /
  temperature 0) and confirm it matches your CPU outputs; note any numeric drift
  in the round summary rather than silently mixing backends.
- **Record the recipe**: once an SSH launch works for your codebase, write the
  exact command into your notes (README or scratch notes) so every later round
  reuses it. Keep experiments modest and convergent — get real numbers for this
  round first, widen the grid in later rounds.

## Never squat a GPU

Pin exactly one GPU per process with `CUDA_VISIBLE_DEVICES`, and kill your
process as soon as its lane is done. Do not hold GPUs idle "in reserve". The
inventory is shared with 7 sibling papers and other people — take what you use
and release it.
