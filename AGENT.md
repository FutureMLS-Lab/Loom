# AGENT.md — deploy Loom with an agent

This file is written for a coding agent (Claude Code, Codex, Cursor Agent).
Human: open your agent on the target machine and say **"follow AGENT.md and
deploy Loom"**. Agent: execute the steps top to bottom; every step says how to
verify itself. Stop and ask the human only where a step is marked **ASK**.

What exists when you are done:

- `loom web` running under tmux (or systemd), bound to `127.0.0.1:8765`,
  protected by an auth token;
- a way for the human to reach it — SSH tunnel, Tailscale, Cloudflare Tunnel,
  or a real domain with HTTPS (their choice, step 5);
- the Factory at `/factory`, and connection details ready for the
  [loom-desktop](https://github.com/FutureMLS-Lab/loom-desktop) and
  [loom-app](https://github.com/FutureMLS-Lab/loom-app) clients.

---

## 1. Prerequisites

Loom needs **Python 3.10+**, **git**, **tmux**, and **pipx**.

Debian / Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv pipx git tmux curl
pipx ensurepath
```

macOS (Homebrew):

```bash
brew install python git tmux pipx
pipx ensurepath
```

Verify: `python3 --version` (≥ 3.10), `git --version`, `tmux -V`.
Open a fresh shell if `pipx ensurepath` changed `PATH`.

**Planning to use the Research Factory (AR papers)?** The paper pipeline
compiles LaTeX on every round; without it, papers fail at their first PDF
build. Install it now (~1 GB) or skip until needed:

```bash
sudo apt-get install -y latexmk texlive-latex-extra   # Debian/Ubuntu
brew install --cask mactex-no-gui                     # macOS
```

Also set expectations with the human — **ASK**: paper authors run their
experiments on this machine unless they are given a cluster. On a laptop-class
host the Factory still writes papers; the experiments behind them are only as
big as the box.

## 2. Install Loom

```bash
pipx install git+https://github.com/FutureMLS-Lab/Loom.git
loom --version
loom doctor
```

`loom doctor` names anything still missing and how to fix it — at this
point it fails exactly one check, "agent CLI", which step 3 installs
next. To upgrade later: `pipx reinstall loom-console`.

## 3. Log in to an agent CLI — ASK

Loom drives at least one of these CLIs; each needs a one-time browser login
that only the human can complete. Install whichever they use:

```bash
curl -fsSL https://claude.ai/install.sh | bash        # Claude Code → claude
curl -fsSL https://chatgpt.com/codex/install.sh | sh  # Codex       → codex
curl https://cursor.com/install -fsS | bash           # Cursor      → agent
```

Then hand the login to the human (`claude` / `codex login --device-auth` /
`NO_OPEN_BROWSER=1 agent login` print a URL to open). Do not continue until
one CLI is authenticated.

## 4. Start the server

Generate a token, keep it out of git and shell history where you can, and
start Loom in tmux:

```bash
TOKEN=$(openssl rand -hex 24)
mkdir -p ~/projects        # or wherever the human keeps their repos
tmux new-session -d -s loom \
  "LOOM_WEB_AUTH_TOKEN=$TOKEN loom web --projects --project ~/projects"
```

- `--projects` treats the directory as a container of many repos; use plain
  `--project /path/to/one/repo` for a single project.
- The token can also be passed as `--auth-token`; the env var keeps it off
  the process command line.

Verify from the same machine:

```bash
curl -s -u ":$TOKEN" http://127.0.0.1:8765/api/projects | head -c 200
```

JSON back = the server is up. Show the human the token — it is the password
for every way of reaching Loom below.

## 5. Let the human reach it — ASK

Loom binds `127.0.0.1` on purpose: behind it sit live terminals that execute
code. **Never** put it on `0.0.0.0` without TLS in front and the auth token
on. Ask the human which of these fits, then set it up:

**a. SSH tunnel — zero exposure, no extra software.** Nothing to install on
the server. The human runs on their laptop:

```bash
ssh -N -L 8765:127.0.0.1:8765 user@SERVER
# then opens http://127.0.0.1:8765
```

**b. Tailscale — private network, best default for personal use.**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up          # human approves the login URL
tailscale ip -4            # → http://100.x.y.z:8765 from any of their devices
```

**c. Cloudflare Tunnel — public HTTPS URL without opening any port.**
Quick ephemeral URL:

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

For a stable address, create a named tunnel on their own domain
(`cloudflared tunnel create loom` + a `CNAME`; follow Cloudflare's guide).
The auth token still gates every request — the URL alone is not access.

**d. Real public IP + domain — for a team server.**

1. Give the machine a static public IP (AWS: allocate + associate an
   Elastic IP; GCP: reserve a static external IP) — the ephemeral IP most
   VMs boot with changes on stop/start.
2. Open **only 80 and 443** in the cloud firewall / security group. Do not
   open 8765.
3. Point a DNS `A` record at that IP.
4. Put [Caddy](https://caddyserver.com) in front — automatic HTTPS in two
   lines of `/etc/caddy/Caddyfile`:

   ```
   loom.example.com {
       reverse_proxy 127.0.0.1:8765
   }
   ```

5. `sudo systemctl reload caddy`, then verify
   `curl -s -u ":$TOKEN" https://loom.example.com/api/projects`.

## 6. Keep it running (optional but recommended)

For a server that should survive reboots, replace the tmux session with a
systemd unit. Put the token in a root-only env file:

```bash
sudo mkdir -p /etc/loom
printf 'LOOM_WEB_AUTH_TOKEN=%s\n' "$TOKEN" | sudo tee /etc/loom/web.env >/dev/null
sudo chmod 0600 /etc/loom/web.env
```

`/etc/systemd/system/loom-web.service` (adjust `User` and the project path):

```ini
[Unit]
Description=Loom web console
After=network-online.target

[Service]
User=YOUR_USER
EnvironmentFile=/etc/loom/web.env
# Absolute paths: in a system unit %h would be root's home, not YOUR_USER's.
ExecStart=/home/YOUR_USER/.local/bin/loom web --projects --project /home/YOUR_USER/projects
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now loom-web
```

Note: agent panes live in tmux and survive a Loom restart; the server picks
them back up when it returns.

## 7. Connect the clients

Both clients speak to the same server and token from step 4/5:

- **[loom-desktop](https://github.com/FutureMLS-Lab/loom-desktop)** — macOS
  dock and console: live task pills, inline chat, terminal and diffs.
- **[loom-app](https://github.com/FutureMLS-Lab/loom-app)** — an Expo
  mobile and web client.

Give each the base URL (`https://loom.example.com`, the Tailscale IP, or the
tunnel URL) and the token.

## 8. Final checklist

```bash
loom doctor                                            # everything green
curl -s -u ":$TOKEN" <BASE_URL>/api/projects           # JSON, not 401
```

Then have the human open `<BASE_URL>` (Loom) and `<BASE_URL>/factory`
(Research Factory), create a task, and watch the agent pane start.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: loom` | new shell, or `pipx ensurepath` then re-login |
| port 8765 busy | another Loom is running: `ss -tlnp \| grep 8765`, stop it or pass `--port` |
| 401 from curl | token mismatch — username is empty, the token is the *password* (`-u ":$TOKEN"`) |
| pane never starts | the agent CLI is not logged in — rerun step 3 |
| anything else | `loom doctor`, then the server log (tmux pane, or `journalctl -u loom-web`) |
