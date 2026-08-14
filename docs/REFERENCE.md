# Loom reference

Everything the README summarizes, in full. The README stays short; this page
does not.

## The full task flow

1. **Register your project.** Top bar → **+ Add folder**, pointed at a git repo
   (or a container directory holding several repos). Registrations live in
   `~/.loom/web-projects.json`; nothing is written outside the path.
2. **Create a task.** **Create Task** asks for a **type** (Claude, Codex, Kernel
   Lab, or AR), a **title** (becomes the slug), and a **general goal**. Loom
   creates `.RUD/<slug>/` with an empty `PLAN.md`; if the project root is a git
   repo it auto-creates a worktree at `.RUD/<slug>/work/<repo>/` on branch
   `zhongzhu/<slug>`.
3. **Start the agent.** Task → **Claude** tab → **Start Claude** launches a tmux
   pane running the agent CLI in the task's `work/` worktree. The pane keeps
   running even if you close the browser.
4. **Run the deep interview.** **Start Deep Interview** pastes a prompt (your
   goal + selected skills); the agent interviews you and writes the agreed plan
   to `PLAN.md`. Answer in the terminal (real terminal: type, ↑/↓ to pick, Enter).
5. **Review the plan** in the embedded read-only viewer (defaults to `PLAN.md`).
6. **Execute it** with **Run /goal**; answer any prompts right in the terminal.
7. **Review the changes** in the **Changes** tab (uncommitted + committed diff);
   optionally **Review ⚖** for an AI review against your rules / skills.
8. **Write the result** with **Write result** to append progress to `PLAN.md`,
   then iterate (repeat 6–8).
9. **Ship it.** Loom never auto-commits — the agent commits in the worktree (or
   you do); then **Push** the worktree, or **Merge ↩** its branch back into the
   base branch from the Changes tab.
10. **(Optional) Notify.** Flip **Notify** on the Monitor row so Loom pings you
    (e.g. in Slack via OpenClaw) when the agent stops and waits for input; your
    reply is typed straight back into the pane.
11. **(Later) Resume.** Pick a past session from the **Sessions** dropdown →
    **Resume** to reopen it in a fresh tmux pane, even if the original was killed.

## Web UI reference

An agent task has two main tabs — **Claude** (or **Codex**) and **Changes** — plus
a read-only Markdown viewer (Kernel Lab tasks get their own panel). Every control:

| Where | Control | What it does |
|-------|---------|--------------|
| **Claude tab** | **Start / Stop Claude** | Launch / kill the tmux pane (agent CLI in the primary `work/` worktree). Stopping keeps sessions resumable. |
| | **Loom flow** | Three buttons — **Start Deep Interview** → **Run /goal** → **Write result** (each pastes a prompt; run any, anytime). |
| | **Terminal** | Real xterm.js on the live PTY: type, arrows, Enter, Esc, Ctrl-C, paste all go to the agent; mouse-wheel scrolls history. |
| | **中文 / compose box** | Type Chinese (input-method-safe) or long text → **Enter** sends it into the pane. |
| | **Copy / paste** | Copy: select + **Cmd/Ctrl+C** (or Ctrl+Shift+C). Paste: **Cmd/Ctrl+V** (or Ctrl+Shift+V). |
| | **Agent** | Switch Claude ⇄ Codex (while stopped). |
| | **Skills** | Which skills markdown to inject (packaged skills under the skills dir; the default prompt is always on and not listed). |
| | **Worktrees** | Dropdown of the task's worktrees + live `git status`; **Push** (selected), **×** remove, **+ Add worktree**, **Push all**. |
| | **tmux** | The live pane target + an alive/down pill. |
| | **Sessions** | Dropdown of past agent sessions (newest first) + **Resume** — reopens it in a fresh pane, even if the tmux was killed. |
| | **Monitor** | **Notify** toggle → pings you (OpenClaw/Slack) when the agent stops; your reply is typed back into the pane. |
| | **Markdown viewer** | Read-only preview of `PLAN.md` (or any top-level `*.md`), with KaTeX math. The agent writes PLAN.md; you `/goal` it in the pane. |
| **Changes tab** | **Diff** | Read-only VSCode-style diff: uncommitted (vs `HEAD`, incl. untracked) + committed (vs base, e.g. `origin/main`). |
| | **Merge ↩** | Merge the worktree's branch into the base — `git merge --no-ff`; refuses if dirty, aborts on conflicts, never pushes. |
| | **Review ⚖** | AI review (`claude -p`) of the diff vs your rules (toolbar box) or the task's skills. |
| **Top bar** | **+ Add folder** | Register a repo from the Loom launch directory. |
| | **📓 Notes** | Fullscreen editor for `<project>/.RUD/NOTES.md` (one per project). **Cmd/Ctrl+S** saves. |

**Run monitor (Notify):** edge-triggers on *running → stopped* — when the agent was
working (pane shows "esc to interrupt") then stops for input, Loom sends an OpenClaw
event with the tail of the pane; your reply is typed back in and you're pinged again
on the next stop. (Enabled while the pane is idle, it stays quiet until the agent
next runs and stops.)

## Task types

| Type | What it is |
|------|------------|
| **Claude / Codex** | The standard human-driven flow above. |
| **AR** | Automated research: turns a direction into paper ideas, then drives each idea from LaTeX draft to reviewed submission. |
| **Kernel Lab** | Dedicated panel driving the Loom Kernel Hub evaluator (spec interview + build/run launcher with live log). Advanced / optional. |

### AR — automated research

An AR task is one of two roles, both stored in `.RUD/<slug>/ar.json`.

A **studio** is what you create from the modal: pick a research direction and a
target venue (ICLR, NeurIPS, ICML or COLM), then either let it mine recent arXiv
work and propose ideas, or hand it a rough idea of your own to sharpen. The
studio's steps: editable arXiv search settings (suggested from your brief) →
mine recent papers → generate idea cards → ground each idea's novelty claim as
citation edges and verify every cited arXiv id against OpenAlex → pick the
ideas worth pursuing, and Loom turns each into its own **paper** task.

Each paper walks a fixed pipeline:

1. **Draft** — the author agent fills the venue's LaTeX skeleton. The experiments
   section gets its full structure but every number stays an `\ARnum{}` marker
   and every figure an `\ARfig{}` placeholder.
2. **Your review** — a gate. Approve to open the loop, or send it back with notes.
3. **Rounds** — by default ten of them. The author agent works in the task's tmux
   pane (revising the paper, running experiments locally in the worktree) and
   signals the end of its turn by writing `rounds/round-NN/author.md`. If it
   stops without doing so, the loop nudges it back to work, and reports through
   OpenClaw after twelve consecutive fruitless nudges. Loom then compiles the
   PDF and applies a hard readiness gate: no TODO/placeholder markers, missing
   figures, unresolved citations/references, incomplete core sections, build
   errors or visible `??` may remain, and the paper must open with a page-one
   overview figure. A blocked paper goes back to the author in the same round
   with the exact failed checks. Only a complete submission runs three
   independent Cursor reviewers headlessly; each sees an isolated workspace
   containing only the compiled PDF (never the LaTeX source). All reports are
   preserved; the lowest-Rating reviewer's complete score block is the final
   verdict. If that lowest score plateaus for three rounds, the fixed panel
   stays in place and the author must make a structural change. Two more rounds
   without improvement pause the loop for a human decision.
4. **Final review** — a gate. Approve to deliver and download the PDF, or send it
   back for another batch of rounds.

Round state lives on disk, so a round survives a killed pane or a server restart
and resumes where it left off. The methodology the agents follow is in
`loom/skills/ar/` (`AR-STUDIO.md`, `AR-AUTHOR.md`, `AR-REVIEWER.md`, the figure
skills, and `paper-rebuttal/`) — edit those to change how the pipeline writes
and reviews.

The venue LaTeX styles are vendored under `loom/templates/paper/<venue>/`. To
refresh them when a conference publishes a new template:

```bash
python3 scripts/fetch_paper_styles.py            # all venues
python3 scripts/fetch_paper_styles.py iclr icml  # just these
```

Building a PDF needs `latexmk` and a TeX Live install; on Debian the COLM
template additionally needs `texlive-fonts-extra`. Loom reports a missing style
file by name rather than dumping the LaTeX log.

### Kernel Lab bundle

The Kernel Hub stack (Dockerfiles, compose files, the `kernel_evaluator`
service and its CUDA reference docs) is ~800 files, so it ships in the source
tree but *not* in the installed package. It works out of the box from a git
checkout; a pipx/venv install needs to be pointed at one:

```bash
export LOOM_KERNEL_HUB_DIR=/path/to/Loom-checkout/loom/kernel_hub
```

`loom doctor` reports whether the bundle was found.

## OpenClaw integration

Loom can push events to an OpenClaw gateway. The headline use is the **run
monitor**: you get pinged (e.g. in Slack) whenever an agent stops and is
waiting for input, and your reply is sent straight back into its pane.

### Enable it

Launch Loom pointing at the **`/hooks/agent`** endpoint — message **delivery is
on by default**. (The lighter `/hooks/wake` endpoint only *wakes* the gateway
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

### What Loom sends

Loom emits lifecycle events — `task-created`, `claude-start` / `claude-stop`,
`worktree-created`, … — and, when a task's **Monitor** toggle is on, an
`agent-stopped` event each time that agent finishes a turn / waits for input,
carrying the last lines of the pane for context. AR papers additionally emit
`ar-draft-ready`, `ar-round-reviewed`, `ar-loop-complete` and
`ar-author-stalled`. The stop is detected by watching the agent's "working"
hint (`esc to interrupt`) and firing when it disappears, so it does not depend
on any particular "done" wording.

### Replying back into the pane

Your OpenClaw agent continues a task by calling Loom's inbound endpoint:

```
POST /api/tasks/<slug>/claude/send   {"text": "check the current pods", "submit": true}
```

It types the message into that task's live agent pane (auth header +
`?project=<id>` apply). The full loop is: **agent stops → OpenClaw pings you →
you reply → the reply lands in the pane → the agent continues → repeat.**

### Gateway on another host

If OpenClaw runs elsewhere, bridge the two with an SSH reverse tunnel from the
Loom machine, then point OpenClaw at `http://127.0.0.1:8765/`:

```bash
ssh -f -N -L 18789:127.0.0.1:18789 -R 8765:127.0.0.1:8765 user@gateway-host
```

The bundled `loom/skills/remote_control/` skill documents the full Loom
HTTP API for an OpenClaw agent (auth, project scoping, reading panes, sending
text, etc.).

## Storage layout

```
<project>/.RUD/
├── NOTES.md              # project-scoped scratch (📓 Notes button)
├── MEMORY.md             # lessons agents append when tasks finish
├── task-order.json
└── <slug>/
    ├── task.json         # title, goal, agent, skills, worktrees, sessions
    ├── PLAN.md           # done / results / to-do / progress log
    ├── monitor.json      # run-monitor state (only if used)
    ├── ar.json           # only for AR tasks
    ├── kernel_interview.json  # only for Kernel Lab tasks
    └── work/
        └── <repo>/...    # git worktree, branch zhongzhu/<slug>
```

```
~/.claude/projects/<encoded-cwd>/
└── <session-uuid>.jsonl  # native Claude Code session transcripts

~/.loom/
└── web-projects.json     # registered project paths
```

AR tasks live in their own always-registered project (`~/ar` by default,
`LOOM_AR_ROOT` to move it) rather than inside a code repo.

## HTTP API

Everything is plain JSON; scope with `?project=<id>` (or the
`X-Loom-Project` header). When `--auth-token` is set, send it as
`Authorization: Bearer <token>` (or HTTP basic, password = token).

| Method | URL | Purpose |
|--------|-----|---------|
| `GET` | `/api/project` | Active project root, skills path, skills options |
| `GET` | `/api/projects` | List registered projects, default, launch root |
| `POST` | `/api/projects` `{path}` | Register a project root |
| `POST` | `/api/projects/<id>/activate` | Set the default project |
| `POST` | `/api/projects/reorder` `{ids}` | Persist order |
| `DELETE` | `/api/projects/<id>` | Drop from registry (files untouched) |
| `GET` / `PUT` | `/api/notes` | Read / save project `NOTES.md` |
| `GET` | `/api/tasks` | All tasks for the active project |
| `POST` | `/api/tasks` `{title, general_goal, agent?, kind?}` | Create task (auto-worktree if the root is a git repo) |
| `POST` | `/api/tasks/reorder` `{slugs}` | Persist order |
| `GET` | `/api/tasks/<slug>` | Meta + PLAN.md + scanned markdown + agent summary + worktree statuses |
| `PUT` | `/api/tasks/<slug>/meta` `{title?, general_goal?, agent?, skills_path?}` | Rename / re-goal / switch agent |
| `PUT` | `/api/tasks/<slug>/template` `{name, content}` | Write PLAN.md |
| `DELETE` | `/api/tasks/<slug>` | Delete task tree (also unregisters worktrees) |
| `GET` | `/api/tasks/<slug>/diff` | **Changes tab**: per-worktree uncommitted + committed diff |
| `GET`/`POST`/`DELETE` | `/api/tasks/<slug>/monitor` | Run-monitor status / enable / disable |
| `POST` | `/api/tasks/<slug>/claude/send` `{text, submit?}` | Push a message into the pane (used by OpenClaw replies) |
| `GET` | `/api/tasks/<slug>/worktree-candidates` | Repos you could base a worktree on |
| `POST` / `DELETE` | `/api/tasks/<slug>/worktree` | Create / remove a worktree |
| `POST` | `/api/tasks/<slug>/worktree/push` `{path}` | `git push -u origin <branch>` |
| `POST` | `/api/tasks/<slug>/worktree/merge` `{path}` | Merge the worktree branch into the base branch (no push) |
| `POST` | `/api/tasks/<slug>/worktrees/push-all` | Push every task worktree branch |
| `POST` | `/api/tasks/<slug>/review` `{path, rules?}` | AI review of the worktree diff vs rules / skills |
| `POST` | `/api/tasks/<slug>/claude/start` | Launch the agent pane in the primary worktree |
| `POST` | `/api/tasks/<slug>/claude/stop` | Kill the tmux pane (on-disk sessions stay resumable) |
| `POST` | `/api/tasks/<slug>/claude/paste-prompt` | Re-paste the deep-interview prompt |
| `POST` | `/api/tasks/<slug>/claude/resume` `{session_id}` | New tmux, `--resume <id>` |
| `GET` | `/api/tasks/<slug>/claude-sessions` | Tracked session UUIDs + on-disk transcripts |
| `GET` | `/api/tmux/stream?target=…&cols=N&rows=N` | Live PTY byte stream for the xterm terminal |
| `POST` | `/api/tmux/stream-close` `{stream_id}` | A client ends its own stream (proxies can swallow the socket close) |
| `GET` | `/api/tmux/capture?target=…&lines=N` | Pane scrollback snapshot (used by the monitor) |
| `POST` | `/api/tmux/send-literal` `{target, text}` | Send raw keystrokes/bytes (used by the terminal) |
| `POST` | `/api/tmux/send-text` / `send-key` | Type text / send a named key into a pane |

AR tasks add `/api/ar/*` and `/api/tasks/<slug>/ar*` endpoints (overview,
catalog, skills, mine/ideas/link/spawn, loop control, reviews, files, PDF).
Kernel Lab adds `/api/kernel/*`. For backwards compatibility,
`/api/tasks/<slug>/interview/{start,stop,paste-prompt}` still resolves to the
agent-pane endpoints.
