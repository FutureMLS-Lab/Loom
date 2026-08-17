# OpenClaw notifications

Loom pushes events to an OpenClaw gateway. The headline use is the **run
monitor**: you get pinged (e.g. in Slack) whenever an agent stops and waits
for input, and your reply is typed straight back into its pane.

## Enable it

Launch Loom pointing at the **`/hooks/agent`** endpoint — message delivery is
on by default. (The lighter `/hooks/wake` endpoint only *wakes* the gateway
and does **not** post a message, so use `/hooks/agent`.)

```bash
loom web --project /path/to/project \
  --openclaw \
  --openclaw-url http://127.0.0.1:18789/hooks/agent \
  --openclaw-token <gateway-token> \
  --openclaw-debug            # logs each POST + HTTP status
```

Add `--openclaw-channel <#channel>` or `--openclaw-to <user>` if your gateway
needs an explicit destination. (Full flag list: `loom/cli.py`.)

## What Loom sends

Lifecycle events — `task-created`, `claude-start` / `claude-stop`,
`worktree-created`, … — and, when a task's **Monitor** toggle is on, an
`agent-stopped` event each time that agent finishes a turn, carrying the last
lines of the pane for context. Factory papers additionally emit
`ar-draft-ready`, `ar-round-reviewed`, `ar-loop-complete` and
`ar-author-stalled`. The stop is detected by watching the agent's "working"
hint (`esc to interrupt`) and firing when it disappears, so it does not
depend on any particular "done" wording.

## Replying back into the pane

Your OpenClaw agent continues a task by calling Loom's inbound endpoint:

```
POST /api/tasks/<slug>/claude/send   {"text": "check the current pods", "submit": true}
```

It types the message into that task's live agent pane (auth header +
`?project=<id>` apply). The full loop: **agent stops → OpenClaw pings you →
you reply → the reply lands in the pane → the agent continues → repeat.**

## Gateway on another host

Bridge the two with an SSH reverse tunnel from the Loom machine, then point
OpenClaw at `http://127.0.0.1:8765/`:

```bash
ssh -f -N -L 18789:127.0.0.1:18789 -R 8765:127.0.0.1:8765 user@gateway-host
```

The bundled `loom/skills/remote_control/` skill documents the Loom HTTP API
for an OpenClaw agent (auth, project scoping, reading panes, sending text);
the full contract is [API.md](API.md).
