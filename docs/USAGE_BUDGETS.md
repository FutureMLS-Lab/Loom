# Agent usage budgets

Loom treats conversation history as a finite resource. Agent CLIs can issue
many model requests during one visible turn, and every tool call may carry the
same accumulated history again. Cached input is cheaper than uncached input,
but it is not free.

**Every limit on this page is off by default.** Loom never interrupts a
running agent and never moves a task to a fresh session on its own; it shows
how large each session has grown and leaves the decision to you. The limits
are opt-in — see [Configuration](#configuration).

## Why the limits exist

The 2026-09-24 team usage export contained 190 calls, 921.3 million tokens and
$1,444.57 of cost. `gpt-5.6-sol-max-fast` accounted for 101 calls, 671.8
million tokens and $1,034.49. About 96% of that model's tokens were cache
reads. The expensive pattern was therefore not simply “too many clicks”; it
was repeated tool turns inside very large conversations.

## Defaults

- Cursor tasks default to `grok-4.7-high-fast`, selected from the account's
  current catalogue as the cost-conscious fast iteration model. Set
  `LOOM_CURSOR_DEFAULT_MODEL` before starting Loom to override it. Available
  fast siblings are still preferred, and Claude panes keep `--effort max`.
  Explicit per-task model selections remain available in the UI.
- Every session shows its transcript size, and the web UI marks it
  **CONTEXT GROWING** at 4 MiB and offers **New session**. Cursor uses its
  canonical agent JSONL transcript; `store.db` is not counted because it also
  contains file snapshots and tool artifacts and can overstate the
  conversation by orders of magnitude.
- Fresh handoffs pass paths to the default rules, `PLAN.md`, project memory,
  selected skills and worktree instead of pasting the whole original prompt.
  AR author prompts put their invariant methodology in an identical leading
  block, so the provider can reuse a stable prefix while round-specific review
  text stays at the end.
- Automated Research defaults to four rounds, permits at most twelve, starts
  each author/repair round in a fresh context window, and stops after two
  fruitless continuation nudges.
- Automated reviewer panels keep the existing strong three-model panel. If
  the compiled PDF is byte-for-byte unchanged, Loom skips the next panel
  rather than paying three reviewers to read it again.
- A failed reviewer panel is not blindly rerun. This avoids repeating the
  successful reviewers just because one model timed out.

## Opt-in limits

- **Transcript budget** (`LOOM_SESSION_CONTEXT_BUDGET_MB`, e.g. `8`). Past the
  limit, sending from Loom's compose box or workflow buttons uses a compact
  fresh-session handoff, and resuming an over-budget historical session
  requires a second explicit confirmation. Normal handoff state belongs in
  `PLAN.md` and the worktree, not in an indefinitely resumed chat.
- **Live turn guard** (`LOOM_TURN_TOKEN_BUDGET`, e.g. `1500000`, and
  `LOOM_CONTEXT_PERCENT_BUDGET`, e.g. `50`). Loom watches the live terminal
  status while an agent is working and pauses the turn (Ctrl-C) at whichever
  limit comes first. This closes the expensive gap where one click can issue
  dozens of tool/model calls before the user gets another chance to press
  Send. Worktree changes are preserved, and the next message must rotate to a
  fresh `PLAN.md`-backed session. Rebuttal factory panes get the same guard.
- **Unattended continuation** (`LOOM_AUTO_ROTATE_BUDGET_LIMIT`, e.g. `2`).
  After the live guard pauses an ordinary Agent or Author task, Loom takes the
  compact handoff automatically, at most that many times per task in a
  rolling 24-hour window. AR paper rounds always remain paused because their
  continuation must preserve a round-specific completion-note contract.
- **Ordinary-agent watchdog** (`LOOM_AGENT_WATCHDOG_MAX_NUDGES`, e.g. `6`).
  After an ordinary `agent` pane was observed working and then remains idle,
  Loom continues it only when `PLAN.md` still contains an unchecked checklist
  item. Set `LOOM_AGENT_WATCHDOG_IDLE_SECONDS` to change the three-minute grace
  period. A single-choice terminal menu is answered only when exactly one
  non-high-impact option is explicitly marked Recommended/default or uniquely
  matches the next unchecked PLAN item. Ambiguous menus, production or
  destructive actions, external pushes/submissions, credentials and approvals
  stop for a human. Every successful continuation is stored in
  `agent-watchdog.json` and counts toward a rolling 24-hour cap. Transport
  failures get one delayed retry, then stop and require human attention.

## Configuration

Every setting below is an environment variable. To make one stick on a host,
put it in `~/.loom/env` (`KEY=VALUE` lines, `#` comments); every `loom`
command loads that file first, and a variable already set in the real
environment wins. For example, to keep GPT as the Cursor default and turn
every limit on:

```bash
LOOM_CURSOR_DEFAULT_MODEL=gpt-5.6-sol-max-fast
LOOM_SESSION_CONTEXT_BUDGET_MB=8
LOOM_TURN_TOKEN_BUDGET=1500000
LOOM_CONTEXT_PERCENT_BUDGET=50
LOOM_AUTO_ROTATE_BUDGET_LIMIT=2
LOOM_AGENT_WATCHDOG_MAX_NUDGES=6
LOOM_AGENT_WATCHDOG_IDLE_SECONDS=180
```

`LOOM_SESSION_CONTEXT_BUDGET_MB` sets the per-session hard limit (default `0`,
off). `LOOM_SESSION_CONTEXT_WARNING_MB` moves the **CONTEXT GROWING** mark
(default `4`; `0` hides it). Positive values are clamped to 0.25–64 MiB, and
the warning never exceeds the hard limit when one is set.

Set `LOOM_CLAUDE_EFFORT` to `low`, `medium`, `high`, or `max` to override the
Claude pane reasoning effort. The default is `max`.

`LOOM_TURN_TOKEN_BUDGET` is the maximum token count displayed for one active
turn and `LOOM_CONTEXT_PERCENT_BUDGET` the live context occupancy ceiling.
Both default to `0`, which leaves the guard off. The terminal reports rounded
values and Loom polls every four seconds, so these are safety cutoffs rather
than exact billing limits.

`LOOM_AUTO_ROTATE_BUDGET_LIMIT` is the maximum number of unattended
fresh-session continuations per task per rolling 24 hours (default `0`,
maximum `20`). With `0`, a paused task stays paused until you continue it.

`LOOM_AGENT_WATCHDOG_MAX_NUDGES` is the separate rolling daily cap for
continuing a live ordinary session after it becomes idle (default `0`, maximum
`20`). Auto-rotation and the watchdog solve different stalls and keep separate
quotas. `LOOM_AGENT_WATCHDOG_IDLE_SECONDS` defaults to `180` and is clamped to
30–3600 seconds. The watchdog is edge-armed: Loom must first observe the pane
working, so enabling it never sends a prompt into every task that was already
idle. The armed state is durable, so a Loom web restart cannot forget a task
that was in flight.

The transcript budget applies to messages sent through Loom's compose box and
workflow buttons. Raw keystrokes sent directly into the embedded terminal are
intentionally not intercepted; use the visible context indicator and **New
session** when operating the CLI directly.

## What “reuse” means here

The usage export already shows roughly 96% cache reads for the expensive
model. Raising that percentage alone cannot remove the bill: cached input is
still charged, and a multi-million-token history is still expensive when it
is replayed across many tool turns. The policy therefore optimizes for
**bounded reuse**: preserve a stable, cacheable instruction prefix; keep
changing state in repository files; and rotate to a compact handoff — with
**New session**, or automatically once you set a limit — before the
accumulated conversation dominates every subsequent request.
