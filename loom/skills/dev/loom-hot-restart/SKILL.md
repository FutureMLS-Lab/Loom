---
name: loom-hot-restart
description: Restarts a running Loom web service from an updated source checkout while preserving its authentication environment, disk-backed tasks, tmux agents, and existing Turbogate public URL. Use when the user asks to hot-update, hot-reload, restart, or deploy Loom without changing its domain or token.
disable-model-invocation: true
---

# Loom Hot Restart

This is a **controlled process replacement**, not in-process Python hot
loading. Expect a short local-port outage while the public tunnel process stays
alive and resumes forwarding to the new Loom process.

Linux only: the helper uses `/proc`, POSIX signals, process groups, and `fork`.

## Guarantees

When all checks pass, the helper preserves:

- `LOOM_WEB_AUTH_TOKEN` and `TOGETHER_API_KEY` byte-for-byte;
- the existing Turbogate process and public URL;
- the same port, command-line options, and project selection;
- `.RUD` task state and Git repositories on disk;
- independent tmux Agent sessions.

It verifies both the local and public `/api/projects` endpoints before
reporting success.

## Hard safety rules

1. Never print, log, pass on the command line, or write either secret.
2. Never start a second Loom before identifying the one existing process on the
   target port.
3. Never gracefully stop a Loom whose tunnel must survive: its shutdown handler
   may close Turbogate and release the domain.
4. Refuse while paper mining, idea generation, or Reviewer jobs are running.
   Those are server subprocesses and are not resumable. Author tmux rounds are
   safe and may continue.
5. Keep the existing Turbogate process. A newly launched tunnel may receive a
   different domain.
6. Run `--dry-run` first and inspect the JSON before executing.

## Quick start

From the Loom checkout:

```bash
python loom/skills/dev/loom-hot-restart/scripts/hot_restart.py \
  --port 8766 \
  --source /absolute/path/to/updated/Loom \
  --dry-run
```

Then execute:

```bash
python loom/skills/dev/loom-hot-restart/scripts/hot_restart.py \
  --port 8766 \
  --source /absolute/path/to/updated/Loom
```

To also retire an obsolete Loom instance:

```bash
python loom/skills/dev/loom-hot-restart/scripts/hot_restart.py \
  --port 8766 \
  --source /absolute/path/to/updated/Loom \
  --stop-port 8765
```

If the running Loom no longer exposes `/api/turbogate`, supply the known
existing URL explicitly:

```bash
python loom/skills/dev/loom-hot-restart/scripts/hot_restart.py \
  --port 8766 \
  --source /absolute/path/to/updated/Loom \
  --public-url https://p-example.gate.together-turbo.com
```

The helper writes the non-secret URL and process identifiers to
`<source>/.RUD/hot-restart-<port>.json` for the next restart.

## Workflow

### 1. Preflight

Run the helper with `--dry-run`. Confirm:

- exactly one Loom process owns the target port;
- the reported source checkout is the intended updated checkout;
- the tunnel PID and public URL match the current deployment;
- `active_one_shot_jobs` is empty;
- the launch command retains required flags such as `--projects` or `--skills`.

The dry-run output contains no secret values.

### 2. Execute

Run the same command without `--dry-run`.

The helper:

1. reads the old Loom environment in memory;
2. optionally stops obsolete Loom ports normally;
3. keeps a reader attached to the Turbogate stdout pipe;
4. replaces the target Loom without invoking its tunnel cleanup;
5. launches `source/.venv/bin/python -m loom web` with the old arguments and
   environment;
6. checks the local API;
7. checks the same public URL;
8. compares secret fingerprints;
9. confirms the original tunnel PID is still alive.

### 3. Validate the result

Require all of these JSON fields:

```json
{
  "ok": true,
  "local_health": "ok",
  "public_health": "ok",
  "secrets_unchanged": true
}
```

Also verify the new PID starts from the requested checkout:

```bash
readlink -f /proc/<new_pid>/cwd
ps -p <new_pid>,<tunnel_pid> -o pid,ppid,sid,lstart,args
```

### 4. Update already-running Author rounds

Server-side code, Readiness Gates, and Reviewers use the new implementation
immediately. An Author Prompt sent before the restart still contains its old
instructions.

If renamed Skills or new Author rules must apply in the current round:

1. inspect the task pane;
2. do not interrupt an Agent while it is working;
3. when idle, send a short migration note through Loom's
   `POST /api/tasks/<slug>/claude/send`;
4. tell it to continue the same round rather than restarting work.

Future round prompts are built from the updated source automatically.

## Failure handling

- If preflight reports active one-shot jobs, wait for them. Use
  `--allow-active-jobs` only when losing those calls is intentional.
- If the new local API fails, inspect `<source>/.RUD/loom-<port>.log` or the
  original terminal.
- If the public check fails but the tunnel PID is alive, restore the local Loom
  listener on the same port before touching Turbogate.
- Never kill and recreate the tunnel merely to fix the Loom process.
- Domain preservation only applies while the existing tunnel process remains
  alive. If Turbogate itself exits, this workflow cannot guarantee recovery of
  the same assigned domain.

## Helper

Execute [`scripts/hot_restart.py`](scripts/hot_restart.py); do not copy its
secret-handling or process-control steps into ad-hoc shell commands.
