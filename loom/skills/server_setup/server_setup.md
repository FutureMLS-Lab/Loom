# Loom Agent Server 搭建与运维

从零开一台云主机，装好 agent CLI 和 Loom，把已有项目和任务全部接进去。
命令按顺序可以直接执行。**任何 token、私钥、kubeconfig 都不要写进这个文件或仓库。**

## 1. 开一台 AWS 机器

按需选型：Agent 主机是 CPU-only 的调度机，不跑训练，瓶颈在并发进程数和内存。

```bash
export AWS_REGION=us-west-2
aws sso login          # 或 aws login --remote --region us-west-2
aws sts get-caller-identity --region $AWS_REGION
```

解析官方 Debian 12 AMI（不要写死 AMI id）：

```bash
AMI_ID=$(aws ssm get-parameter --region $AWS_REGION \
  --name /aws/service/debian/release/12/latest/amd64 \
  --query 'Parameter.Value' --output text)
```

上传本机公钥（只传公钥）并建安全组：

```bash
aws ec2 import-key-pair --region $AWS_REGION \
  --key-name agent-dev-$(date +%Y%m%d) \
  --public-key-material fileb://"$HOME/.ssh/id_rsa.pub"

aws ec2 create-security-group --region $AWS_REGION \
  --group-name agent-dev-$(date +%Y%m%d) \
  --description "SSH for agent dev host" --vpc-id <DEFAULT_VPC_ID>
# 只开 22/tcp；口令登录在主机侧关闭（见第 2 节）
```

启动实例：

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

- `m8i.32xlarge` = 128 vCPU / 512 GiB，约可并发跑 60 个 agent（每个预算 2 vCPU + 8 GiB）。
- 磁盘 1 TiB gp3 加密；IMDSv2 必须开；打开 termination protection。
- **成本**：compute 约 $6.77/hr（24×7 约 $4,900/月），不用时 `aws ec2 stop-instances`；stop 后仅 EBS 约 $80/月。
- 没有 Elastic IP 时，stop/start 后公网 IP 会变，要更新本地 `~/.ssh/config`。

## 2. SSH 加固

`/etc/ssh/sshd_config.d/99-agent-dev.conf`：

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

改 sshd 后**先另开一条 SSH 连接确认能登录**，再关掉当前会话。

## 3. 基础工具

```bash
sudo apt-get update && sudo apt-get install -y \
  python3 python3-venv python3-pip pipx git tmux curl wget jq ripgrep fd-find \
  fzf tree htop rsync unzip zip build-essential cmake ninja-build pkg-config \
  libssl-dev ca-certificates gnupg lsb-release fail2ban

pipx ensurepath && pipx install uv
export PATH="$HOME/.local/bin:$PATH"
```

GitHub CLI、Docker、kubectl、AWS CLI v2 都从官方源装；Docker 装完 `sudo usermod -aG docker $USER` 并重开一个 SSH 会话。

## 4. 装 Agent CLI 并登录

```bash
curl -fsSL https://claude.ai/install.sh | bash        # Claude Code
curl -fsSL https://chatgpt.com/codex/install.sh | sh  # Codex CLI
curl https://cursor.com/install -fsS | bash           # Cursor Agent -> agent / cursor-agent
```

SSH 上登录（都会打印一个 URL，在可信浏览器里打开）：

```bash
claude auth login
codex login --device-auth
NO_OPEN_BROWSER=1 agent login
```

验证：`claude --version && codex --version && agent --version && agent status --format json`

登录态是账号资产，不要跨组织复制 `~/.claude`、`~/.codex/auth.json`、`~/.cursor`。

## 5. 装 Loom

```bash
git clone https://github.com/FutureMLS-Lab/Loom.git "$HOME/loom"
pipx install --editable "$HOME/loom"
loom --version && loom doctor
```

`--editable` 之后升级只要 `git -C ~/loom pull`，不用重装。

## 6. 启动 Loom

一定放在 tmux 里，Loom 自己管理的 agent pane 也都是 tmux session。

```bash
tmux new-session -s loom
export LOOM_TOKEN="$(openssl rand -hex 24)"   # 存到密码管理器，不要写进文件
loom web --project /home/admin --port 8765 --auth-token "$LOOM_TOKEN" --projects
```

- `--project` 是启动目录；`--projects` 表示这个目录是**多个 git repo 的容器**，单个 repo 根目录则省略该参数。
- `--auth-token` 必开；用户名随意，密码就是 token。
- 想后台常驻用 `--daemon`，日志默认在 `<project>/.RUD/web.log`。
- 只监听 127.0.0.1，**不要**用 `--host 0.0.0.0` 暴露到公网。

本地访问走 SSH 隧道：

```bash
ssh -N -L 8765:127.0.0.1:8765 admin@<SERVER_IP>
# 浏览器打开 http://127.0.0.1:8765，密码填 token
```

## 7. 把项目和任务放进去

Loom 的任务就是项目目录下的 `.RUD/<slug>/`，所以迁移＝把目录搬过来。

1. **注册项目**：界面顶部 `+ Add folder`，或
   ```bash
   curl -s -u "x:$LOOM_TOKEN" -X POST http://127.0.0.1:8765/api/projects \
     -H 'content-type: application/json' \
     -d '{"path":"/home/admin/myrepo","mode":"existing","code_root_pattern":"."}'
   ```
   注册表在 `~/.loom/web-projects.json`（跟着 `$HOME` 走，换 HOME 就是另一套工作区）。

2. **搬历史任务**：把旧机器上的 `<project>/.RUD/` 整个 rsync 过来，Loom 会自动扫出来。
   ```bash
   rsync -av --exclude 'work/' old-host:/path/repo/.RUD/ /home/admin/myrepo/.RUD/
   ```
   - `.RUD/<slug>/task.json` 是任务元数据，`PLAN.md` 是正文，`task-order.json` 决定侧栏顺序。
   - `work/` 是 git worktree，**不要** rsync，到新机器上重新创建（`+ Add worktree`）。

3. **新建任务**：界面 `Create Task`，或 `POST /api/tasks`，body 里给 `title` / `general_goal` / 可选 `skills_path`、`agent`、`kind`。

4. 任务用完不要手删目录，用界面的 `Delete task`，否则 `task-order.json` 会留下孤儿条目。

## 8. 配置

- **Skills**：`~/loom/loom/skills/**.md` 会被自动扫成可选项（支持子目录，标签就是相对路径）。新增技能直接放 `.md` 文件即可，刷新页面就能选。
- **模型**：Cursor 的候选来自 `agent --list-models`（约 200 个，界面按家族分组），Claude/Codex 的候选写死在 `rud_task.py`。列表缓存 15 分钟。
- **共享凭证**：集群 kubeconfig / SSH key / VPN 统一放 `~/agent-resources/`，权限 `0700`，并用软链接接到 `~/.kube/config`、`~/.ssh/config` 等标准位置。
- **通知**：需要 agent 停下来时提醒，加 `--openclaw --openclaw-url <hooks-url> --openclaw-token <token>`。

## 9. 升级版本

```bash
# Loom（editable 安装，pull 即生效；改了 Python 需重启 web，改了前端刷新即可）
git -C ~/loom pull

# Agent CLI：重跑各自的安装脚本即可，登录态会保留
curl -fsSL https://claude.ai/install.sh | bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
curl https://cursor.com/install -fsS | bash
```

重启 Loom web **不会**杀掉 agent：pane 活在 tmux 里，重启后重新 attach 就行。

```bash
tmux attach -t loom      # Ctrl-C 停掉，再执行第 6 节的启动命令
tmux ls                  # 所有 loom-* session 就是各任务的 agent pane
```

## 10. 验收清单

```bash
nproc && free -h && df -h /
loom doctor
claude --version && codex --version && agent --version
tmux ls
curl -s -o /dev/null -w '%{http_code}\n' -u "x:$LOOM_TOKEN" http://127.0.0.1:8765/
sudo systemctl is-active ssh fail2ban docker
```

## 11. 红线

- token / 私钥 / kubeconfig 一律不进 Git、不进 PLAN.md、不进日志。
- Loom 不做鉴权以外的防护，只能绑 127.0.0.1 + SSH 隧道。
- 换公司/换账号时重建主机，只复用本文的安装步骤，不要搬旧机器的登录态和组织凭证。
