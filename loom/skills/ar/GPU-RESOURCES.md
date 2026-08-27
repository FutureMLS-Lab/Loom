# Compute resources — run experiments on the strongest compute you can reach

Never assume the machine your pane runs on is all you have. Anything this
host can access is fair game: the local machine itself, SSH-reachable nodes,
Slurm queues, and Kubernetes clusters. Discover what is reachable, then put
every experiment on the strongest path — model inference or training on a
shared CPU box takes minutes per item where an H100 takes seconds, and a
round that should take under an hour stretches to a full day.

Small aggregation, plotting, and test suites are fine locally; anything that
loads model weights goes to the best accelerator you can reach.

## 1. Discover what you can reach (fast, read-only, do this once per task)

Run these probes and note what answers:

```bash
nvidia-smi                          # local GPUs?
nproc; free -h                      # local CPU/RAM scale
kubectl config get-contexts         # k8s clusters copied to this host
kubectl --context <ctx> get nodes   # GPU nodes? (look for gpu products/counts)
grep -i '^Host ' ~/.ssh/config      # SSH-reachable machines
sinfo -s                            # a Slurm queue?
```

Then read the host's own docs — `CLAUDE.md`, `AGENTS.md`, `RESOURCES.md` at
the home or project root usually name the paved road, the approved contexts
and namespaces, and any known-broken paths. A background GPU inventory may
also exist (e.g. a `gpu-scout` `free_gpus.txt`/`free_gpus.json`); if present,
read it instead of probing nodes one by one.

## 2. Pick the right shape for the work

- **Many runs (seeds × conditions)** → batch scheduling: Kubernetes Jobs
  (one Job per seed/condition, small `backoffLimit`, let the scheduler spread
  them across nodes) or Slurm array jobs. Do not babysit twenty interactive
  shells.
- **One interactive debug session** → `kubectl exec` into a development pod,
  or SSH to a node with a free GPU.
- **Local machine** — legitimate when it is genuinely the best available, and
  always right for aggregation, plotting, and unit tests.
- **Slurm** — a valid path where the queue is healthy. Check the host docs
  first: if they flag the queue as unreliable, do not chain
  `--dependency` jobs on it; use direct SSH or Kubernetes instead.

## 3. Batch hygiene (the pattern that works)

- Pin the environment: a fixed container image (e.g. `nvcr.io/nvidia/pytorch`)
  or a frozen venv, identical across every run in a study and across rounds.
- Record provenance per run: code commit, source digest, node, GPU type,
  GPU-hours. Reviewers ask; the appendix answers.
- Verify a GPU is actually idle right before launch (`nvidia-smi` on the
  target); inventories go stale in a minute and GPUs are shared.
- Bring results back to the worktree as soon as runs finish. The cluster is
  not storage; pods and scratch filesystems get reclaimed.
- Clean up the Jobs/pods you created once results are safely copied out.

## 4. Sharing rules (non-negotiable)

- **Cap your concurrent footprint.** On a shared cluster, keep your queued +
  running pods to a few dozen, not hundreds. If a study needs more lanes,
  spread the arms across the other reachable clusters (each `kubectl` context
  you verified in step 1) instead of monopolizing one queue — and launch in
  waves, aggregating each wave before submitting the next.
- **Delete your Jobs as soon as their results are copied out.** Hundreds of
  Completed pods are noise for every other user of the cluster.
- Default to read-only toward everything you did not create. Never kill,
  delete, or scale someone else's pods, jobs, or queues.
- Every mutating command names its scope explicitly: `--context` and
  `--namespace` for kubectl, the partition for Slurm.
- Request only what the run needs (one GPU per single-GPU run); do not
  reserve whole nodes for insurance.
- Credentials (kubeconfig, SSH keys) stay where the host keeps them — never
  copy them into the worktree, logs, or Git.
