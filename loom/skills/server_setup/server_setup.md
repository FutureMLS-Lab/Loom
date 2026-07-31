# Loom Agent Server Setup

Build a cloud host from scratch, install the agent CLIs and Loom, and bring
existing projects and tasks over. Commands run in order.
**Never put a token, private key or kubeconfig in this file or in the repo.**

## 1. Launch an AWS host

The agent host is a CPU-only scheduler box — it does not train. Size it for
concurrent processes and memory, not for GPUs.

```bash
export AWS_REGION=us-west-2
aws sso login          # or: aws login --remote --region us-west-2
aws sts get-caller-identity --region $AWS_REGION
```

Resolve the official Debian 12 AMI (never hardcode an AMI id):

```bash
AMI_ID=$(aws ssm get-parameter --region $AWS_REGION \
  --name /aws/service/debian/release/12/latest/amd64 \
  --query 'Parameter.Value' --output text)
```

Upload your public key (public half only) and create a security group:

```bash
aws ec2 import-key-pair --region $AWS_REGION \
  --key-name agent-dev-$(date +%Y%m%d) \
  --public-key-material fileb://"$HOME/.ssh/id_rsa.pub"

aws ec2 create-security-group --region $AWS_REGION \
  --group-name agent-dev-$(date +%Y%m%d) \
  --description "SSH for agent dev host" --vpc-id <DEFAULT_VPC_ID>
# Open 22/tcp only. Password login is disabled host-side (section 2).
```

Launch:

```bash
aws ec2 run-instances --region $AWS_REGION \
  --image-id "$AMI_ID" --instance-type m8i.32xlarge \
  --subnet-id <PUBLIC_SUBNET_ID> --security-group-ids <SG_ID> \
  --key-name <KEY_NAME> --associate-public-ip-address --ebs-optimized \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={DeleteOnTermination=true,Encrypted=true,VolumeSize=1024,VolumeType=gp3,Iops=3000,Throughput=125}' \
  --metadata-options 'HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1' \
  --instance-initiated-shutdown-behavior stop --disable-api-termination \
  --count 1
```

- `m8i.32xlarge` = 128 vCPU / 512 GiB, enough for roughly 60 concurrent agents
  (budget ~2 vCPU + 8 GiB each).
- 1 TiB encrypted gp3, IMDSv2 required, termination protection on.
- **Cost**: about $6.77/hour of compute (~$4,900/month if left running). Stop it
  when idle with `aws ec2 stop-instances`; a stopped host still costs ~$80/month
  for the volume.
- Without an Elastic IP the public address changes across stop/start — update
  your local `~/.ssh/config` afterwards.

## 2. Harden SSH

`/etc/ssh/sshd_config.d/99-agent-dev.conf`:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
X11Forwarding no
AllowUsers admin
MaxAuthTries 3
```

```bash
sudo /usr/sbin/sshd -t && sudo systemctl reload ssh
sudo apt-get install -y fail2ban python3-systemd
printf '[sshd]\nenabled = true\nbackend = systemd\nport = ssh\nmaxretry = 5\nbantime = 1h\n' \
  | sudo tee /etc/fail2ban/jail.d/sshd.local
sudo systemctl restart fail2ban && sudo fail2ban-client status sshd
```

Debian cloud images log to journald, hence `backend = systemd`. After changing
sshd, **open a second SSH session and confirm it works** before closing the
first one.

## 3. Base tooling

```bash
sudo apt-get update && sudo apt-get install -y \
  python3 python3-venv python3-pip pipx git tmux curl wget jq ripgrep fd-find \
  fzf tree htop rsync unzip zip build-essential cmake ninja-build pkg-config \
  libssl-dev ca-certificates gnupg lsb-release fail2ban

pipx ensurepath && pipx install uv
export PATH="$HOME/.local/bin:$PATH"
```

Install GitHub CLI, Docker, kubectl and AWS CLI v2 from their official
repositories. After Docker, run `sudo usermod -aG docker $USER` and open a new
SSH session before using it without sudo.

## 4. Install and authenticate the agent CLIs

```bash
curl -fsSL https://claude.ai/install.sh | bash        # Claude Code
curl -fsSL https://chatgpt.com/codex/install.sh | sh  # Codex CLI
curl https://cursor.com/install -fsS | bash           # Cursor Agent -> agent / cursor-agent
```

Log in over SSH; each prints a URL to open in a trusted browser:

```bash
claude auth login
codex login --device-auth
NO_OPEN_BROWSER=1 agent login
```

Verify: `claude --version && codex --version && agent --version && agent status --format json`

Sessions belong to an account, not to the machine. Do not copy `~/.claude`,
`~/.codex/auth.json` or `~/.cursor` across organisations.

## 5. Install Loom

```bash
git clone https://github.com/FutureMLS-Lab/Loom.git "$HOME/loom"
pipx install --editable "$HOME/loom"
loom --version && loom doctor
```

With `--editable`, upgrading is just `git -C ~/loom pull` — no reinstall.

## 6. Start Loom

Always start it inside tmux; the agent panes Loom manages are tmux sessions too.

```bash
tmux new-session -s loom
export LOOM_TOKEN="$(openssl rand -hex 24)"   # keep it in a password manager
loom web --project /home/admin --port 8765 --auth-token "$LOOM_TOKEN" --projects
```

- `--project` is the launch directory. `--projects` says that directory is a
  **container of several git repos**; omit it when the launch directory is
  itself one repo root.
- Always set `--auth-token`. Any username works; the token is the password.
- `--daemon` runs it in the background, logging to `<project>/.RUD/web.log`.
- It binds 127.0.0.1. **Do not** expose it with `--host 0.0.0.0`.

Reach it from your laptop over an SSH tunnel:

```bash
ssh -N -L 8765:127.0.0.1:8765 admin@<SERVER_IP>
# open http://127.0.0.1:8765 and use the token as the password
```

## 7. Bring projects and tasks in

A Loom task *is* a directory: `<project>/.RUD/<slug>/`. Migrating means copying
those directories.

1. **Register a project** — `+ Add folder` in the UI, or:
   ```bash
   curl -s -u "x:$LOOM_TOKEN" -X POST http://127.0.0.1:8765/api/projects \
     -H 'content-type: application/json' \
     -d '{"path":"/home/admin/myrepo","mode":"existing","code_root_pattern":"."}'
   ```
   The registry lives at `~/.loom/web-projects.json`, so it follows `$HOME` — a
   different HOME is a completely separate workspace.

2. **Move historical tasks** — rsync the old `.RUD/` tree across and Loom picks
   them up on its own:
   ```bash
   rsync -av --exclude 'work/' old-host:/path/repo/.RUD/ /home/admin/myrepo/.RUD/
   ```
   - `.RUD/<slug>/task.json` is the metadata, `PLAN.md` is the content, and
     `task-order.json` controls sidebar order.
   - `work/` holds git worktrees — **do not** copy them. Recreate them on the
     new host with `+ Add worktree`.

3. **Create a task** — `Create Task` in the UI, or `POST /api/tasks` with
   `title` / `general_goal` plus optional `skills_path`, `agent`, `kind`.

4. Delete tasks through the UI, not with `rm`, or `task-order.json` keeps
   orphaned entries.

## 8. Configure

- **Skills**: every `.md` under `~/loom/loom/skills/` is offered in the picker,
  including subdirectories (the label is the relative path). Drop a new file in
  and reload the page.
- **Models**: the Cursor list comes from `agent --list-models` (~200 entries,
  grouped by family in the UI) and is cached for 15 minutes; the Claude and
  Codex lists are defined in `rud_task.py`.
- **Shared credentials**: keep cluster kubeconfig, SSH keys and VPN config under
  `~/agent-resources/` with mode `0700`, symlinked into the standard locations
  (`~/.kube/config`, `~/.ssh/config`).
- **Notifications**: to be pinged when an agent goes idle, add
  `--openclaw --openclaw-url <hooks-url> --openclaw-token <token>`.

## 9. Upgrade

```bash
# Loom: editable install, so a pull is enough. Python changes need a web
# restart; frontend changes only need a browser reload.
git -C ~/loom pull

# Agent CLIs: re-run the installers; login state survives.
curl -fsSL https://claude.ai/install.sh | bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
curl https://cursor.com/install -fsS | bash
```

Restarting the Loom web server does **not** kill agents — the panes live in
tmux and reattach afterwards.

```bash
tmux attach -t loom      # Ctrl-C to stop, then re-run the section 6 command
tmux ls                  # every loom-* session is one task's agent pane
```

## 10. Verification checklist

```bash
nproc && free -h && df -h /
loom doctor
claude --version && codex --version && agent --version
tmux ls
curl -s -o /dev/null -w '%{http_code}\n' -u "x:$LOOM_TOKEN" http://127.0.0.1:8765/
sudo systemctl is-active ssh fail2ban docker
```

## 11. Hard rules

- Tokens, private keys and kubeconfigs never go into Git, PLAN.md or logs.
- Loom has no protection beyond its auth token: bind 127.0.0.1 and tunnel in.
- When changing accounts or employers, rebuild the host from these steps. Do not
  carry over login state or an organisation's credentials.
