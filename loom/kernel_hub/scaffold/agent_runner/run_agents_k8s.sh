#!/usr/bin/env bash
# Kubernetes-native agent launcher (no docker, no registry).
#
# Mirrors run_agents.sh but spawns each optimization agent as a k8s Job instead
# of a docker container:
#   * code + workdir + per-agent prompt come from the shared PVC
#     (code staged at /shared/charlie/loom-kernel-hub)
#   * the agent CLI (claude/codex) reuses the caller's login by mounting the home PVC
#   * agents reach the evaluator via its in-cluster Service DNS
#   * one user API key is minted per agent (admin key -> /api-keys)
#
# Requires: kubectl on PATH, the kernel-evaluator Deployment/Service already applied
# (see k8s/evaluator.yaml), and the code staged on /shared.
#
# Usage:
#   run_agents_k8s.sh --plugin torch.linear --target cuda --model claude-sonnet-4-20250514 \
#     --n-agents 3 --starter-mode none [--run-id ID] [--max-iterations 1] [--target-speedup 1.1] \
#     [--auto-terminate --poll-interval 60] [--build-mode]
set -euo pipefail

# kubectl usually lives in ~/.local/bin, which server-spawned shells may miss.
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

# Cluster selection: LOOM_K8S_KUBECONFIG / LOOM_K8S_CONTEXT pick which cluster
# the agents run on (default: the user's default kubeconfig + current context).
KUBECTL=(kubectl --request-timeout=20s)
[[ -n "${LOOM_K8S_KUBECONFIG:-}" ]] && KUBECTL+=(--kubeconfig "$LOOM_K8S_KUBECONFIG")
[[ -n "${LOOM_K8S_CONTEXT:-}" ]] && KUBECTL+=(--context "$LOOM_K8S_CONTEXT")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- config (overridable via env) ----
NS="${LOOM_K8S_NAMESPACE:-charlie}"
EVAL_SVC="${KERNEL_EVALUATOR_API:-http://kernel-evaluator.${NS}.svc.cluster.local:8000}"
# Endpoint baked into the agent Jobs. Agents run in-cluster, so the Service DNS
# always works for them - and the launcher-side KERNEL_EVALUATOR_API may be a
# tunnel/localhost address that would be meaningless inside a remote pod.
AGENT_EVAL_API="${LOOM_K8S_AGENT_EVAL_API:-http://kernel-evaluator.${NS}.svc.cluster.local:8000}"
ADMIN_KEY="${KERNEL_EVALUATOR_ADMIN_API_KEY:-admin1234}"
CODE_DIR="${LOOM_K8S_CODE_DIR:-/shared/charlie/loom-kernel-hub}"
RUNS_DIR="${LOOM_K8S_RUNS_DIR:-/shared/charlie/loom-kernel-runs}"
SHARED_PVC="${LOOM_K8S_SHARED_PVC:-shared-data}"
# Home PVC carries the logged-in claude session. Set LOOM_K8S_HOME_PVC="" on
# clusters without it: agents then authenticate with the
# passed-through ANTHROPIC/OPENAI API key and use the workdir as HOME.
HOME_PVC="${LOOM_K8S_HOME_PVC-home-charlie-rwx}"
HOME_PATH="${LOOM_K8S_HOME_PATH:-/home/charlie}"
RUN_UID="${LOOM_K8S_RUN_UID:-1001}"   # owner of the home PVC (so claude reads ~/.claude)
RUN_GID="${LOOM_K8S_RUN_GID:-1001}"
# Debian trixie ships Python 3.13 (kernel_hub needs >=3.12); matches the original
# agent Dockerfile base. bookworm's 3.11 is too old for the bench-* client.
AGENT_IMAGE="${LOOM_K8S_AGENT_IMAGE:-node:24-trixie-slim}"
# Set LOOM_K8S_NODESEL_KEY="" to skip the nodeSelector (clusters without pool labels).
NODE_SELECTOR_KEY="${LOOM_K8S_NODESEL_KEY-node-pool}"
NODE_SELECTOR_VAL="${LOOM_K8S_NODESEL_VAL:-compute}"

N_AGENTS=1; MODEL=""; PLUGIN=""; TARGET=""; SHAPE=""; RUN_ID=""
STARTER_MODE="none"; MAX_ITERATIONS=1; TARGET_SPEEDUP=""
AUTO_TERMINATE=false; POLL_INTERVAL=60; BUILD_MODE=false
INSTRUCTIONS_FILE=""; WIKI_FILE=""; EVALUATION_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plugin)         PLUGIN="$2"; shift 2 ;;
    --target)         TARGET="$2"; shift 2 ;;
    --shape)          SHAPE="$2"; shift 2 ;;
    --model)          MODEL="$2"; shift 2 ;;
    --n-agents)       N_AGENTS="$2"; shift 2 ;;
    --run-id)         RUN_ID="$2"; shift 2 ;;
    --starter-mode)   STARTER_MODE="$2"; shift 2 ;;
    --max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
    --target-speedup) TARGET_SPEEDUP="$2"; shift 2 ;;
    --auto-terminate) AUTO_TERMINATE=true; shift ;;
    --poll-interval)  POLL_INTERVAL="$2"; shift 2 ;;
    --build-mode)     BUILD_MODE=true; shift ;;
    --instructions-file) INSTRUCTIONS_FILE="$2"; shift 2 ;;
    --wiki-file|--plan-file) WIKI_FILE="$2"; shift 2 ;;
    --evaluation-file) EVALUATION_FILE="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$PLUGIN" || -z "$TARGET" || -z "$MODEL" ]] && {
  echo "usage: $0 --plugin P --target T --model M [--n-agents N] [--shape JSON] [--run-id ID] [--starter-mode M] [--max-iterations N]" >&2
  exit 1
}
command -v kubectl >/dev/null 2>&1 || { echo "error: kubectl not on PATH" >&2; exit 1; }

if [[ "$MODEL" == claude-* ]]; then CLI="claude"; else CLI="codex"; fi
KERNEL_FILE="kernel.cu"; [[ "$TARGET" == "cutedsl" || "$TARGET" == "triton" ]] && KERNEL_FILE="kernel.py"

# Endpoint the LAUNCHER uses for its own admin calls (create run / mint keys).
# Agents always get the Service DNS (they run in normal pods with cluster DNS),
# but the launcher may run somewhere without cluster DNS (e.g. the Loom/dev pod
# uses public DNS) — in that case fall back to the evaluator pod IP.
ADMIN_EP="$EVAL_SVC"
if ! curl -sf -m 5 -o /dev/null "$ADMIN_EP/openapi.json" 2>/dev/null; then
  POD_IP=$("${KUBECTL[@]}" -n "$NS" get pods -l app=kernel-evaluator -o jsonpath='{.items[0].status.podIP}' 2>/dev/null || true)
  if [[ -n "$POD_IP" ]] && curl -sf -m 5 -o /dev/null "http://$POD_IP:8000/openapi.json" 2>/dev/null; then
    ADMIN_EP="http://$POD_IP:8000"
    echo "[launcher] Service DNS unreachable here; using evaluator pod IP $POD_IP for admin calls"
  else
    echo "error: cannot reach evaluator at $EVAL_SVC or via pod IP; is the deployment up?" >&2
    exit 1
  fi
fi

# ---- create the eval run if not supplied ----
TASK_SLUG=""
if [[ -z "$RUN_ID" ]]; then
  [[ -z "$SHAPE" ]] && { echo "error: --shape required when --run-id is not given" >&2; exit 1; }
  body="{\"plugin\":\"$PLUGIN\",\"target\":\"$TARGET\",\"shapes\":[$SHAPE]"
  [[ -n "$TARGET_SPEEDUP" ]] && body="$body,\"target_speedup\":$TARGET_SPEEDUP"
  body="$body}"
  CREATE_RESP=$(curl -s -X POST "$ADMIN_EP/evaluation/runs" \
    -H 'Content-Type: application/json' -H "X-API-Key: $ADMIN_KEY" -d "$body")
  RUN_ID=$(echo "$CREATE_RESP" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("run_id",""))
except Exception: print("")')
  TASK_SLUG=$(echo "$CREATE_RESP" | python3 -c 'import json,sys
try:
    bs = (json.load(sys.stdin).get("benchmark_shapes") or [{}])
    print(bs[0].get("task_slug", ""))
except Exception: print("")')
  [[ -z "$RUN_ID" ]] && { echo "error: run creation failed: $(echo "$CREATE_RESP" | head -c 500)" >&2; exit 1; }
fi
[[ -z "$RUN_ID" ]] && { echo "error: failed to create/resolve run" >&2; exit 1; }
RUN_LABEL=$(echo "$RUN_ID" | tr '_' '-' | cut -c1-50)
# Same "Run:" line as run_agents.sh — rud_kernel.py parses it for run_id/task_slug.
echo "Run: $RUN_ID  task: ${TASK_SLUG:-$PLUGIN}  agents: $N_AGENTS  model: $MODEL  starter: $STARTER_MODE"
echo "cli=$CLI  build_mode=$BUILD_MODE  auto_terminate=$AUTO_TERMINATE"

if [ "$BUILD_MODE" = true ]; then
  PROMPT="You are writing a GPU kernel via the eval service, in BUILD MODE (correctness first). Steps:
1. Read CLAUDE.md (note the BUILD MODE section) and any .agents/skills/*/SKILL.md (especially eval-service).
2. Run: bench-run   (shows the task + instructions; writes a starter to $KERNEL_FILE if starter-mode is set).
3. Write/improve $KERNEL_FILE to satisfy the task ABI described by bench-run.
4. Run: bench-submit $KERNEL_FILE   then   bench-poll <job_id>. Iterate on compile/correctness errors.
Stop as soon as bench-poll reports correct=True — speed does not matter. Do not fake results."
else
  PROMPT="You are optimizing a GPU kernel via the eval service. Steps:
1. Read CLAUDE.md and any .agents/skills/*/SKILL.md (especially eval-service and cuda-docs).
2. Run: bench-run   (shows the task + instructions; writes a starter to $KERNEL_FILE if starter-mode is set).
3. Write/improve $KERNEL_FILE to satisfy the task ABI described by bench-run.
4. Run: bench-submit $KERNEL_FILE   then   bench-poll <job_id>. Iterate until correct=True and speedup>1.0x.
5. Periodically run bench-best to learn from the current global best.
Work until speedup>1.0x. Do not stop early. Do not fake results."
fi

# Pass API keys through to the jobs when the caller has them; otherwise the
# agents rely on the logged-in CLI session from the mounted home PVC.
EXTRA_ENV=""
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  EXTRA_ENV+="
            - name: ANTHROPIC_API_KEY
              value: \"$ANTHROPIC_API_KEY\""
fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  EXTRA_ENV+="
            - name: OPENAI_API_KEY
              value: \"$OPENAI_API_KEY\"
            - name: CODEX_API_KEY
              value: \"$OPENAI_API_KEY\""
fi
if [[ -z "$HOME_PVC" && -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
  echo "error: no home PVC (LOOM_K8S_HOME_PVC empty) and no ANTHROPIC/OPENAI API key - agents would have no CLI auth" >&2
  exit 1
fi

# Optional scheduling / home-PVC YAML fragments (empty on clusters without them).
SCHED_YAML=""
if [[ -n "$NODE_SELECTOR_KEY" ]]; then
  SCHED_YAML="
      nodeSelector:
        $NODE_SELECTOR_KEY: $NODE_SELECTOR_VAL"
fi
HOME_VOL_YAML=""; HOME_MOUNT_YAML=""
if [[ -n "$HOME_PVC" ]]; then
  HOME_VOL_YAML="
        - name: home
          persistentVolumeClaim: { claimName: $HOME_PVC }"
  HOME_MOUNT_YAML="
            - { name: home, mountPath: $HOME_PATH }"
fi

# Task-specific INSTRUCTION.md (from the Loom interview): shipped to every
# agent workdir via base64 env, appended to its CLAUDE.md and referenced in
# the prompt, so the task brief actually reaches the worker.
INSTRUCTIONS_B64=""
if [[ -n "$INSTRUCTIONS_FILE" ]]; then
  [[ -f "$INSTRUCTIONS_FILE" ]] || { echo "error: instructions file not found: $INSTRUCTIONS_FILE" >&2; exit 1; }
  INSTRUCTIONS_B64=$(base64 -w0 "$INSTRUCTIONS_FILE")
  PROMPT="Read INSTRUCTION.md in your working directory FIRST - it is the task brief and overrides generic guidance.
$PROMPT"
fi
WIKI_B64=""
if [[ -n "$WIKI_FILE" ]]; then
  [[ -f "$WIKI_FILE" ]] || { echo "error: wiki file not found: $WIKI_FILE" >&2; exit 1; }
  WIKI_B64=$(base64 -w0 "$WIKI_FILE")
fi
EVALUATION_B64=""
if [[ -n "$EVALUATION_FILE" ]]; then
  [[ -f "$EVALUATION_FILE" ]] || { echo "error: evaluation file not found: $EVALUATION_FILE" >&2; exit 1; }
  EVALUATION_B64=$(base64 -w0 "$EVALUATION_FILE")
fi

launched=()
for i in $(seq 1 "$N_AGENTS"); do
  AGENT_KEY=$(curl -sf -X POST "$ADMIN_EP/api-keys" \
    -H 'Content-Type: application/json' -H "X-API-Key: $ADMIN_KEY" -d '{"role":"user"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')
  [[ -z "$AGENT_KEY" ]] && { echo "error: failed to mint key for agent $i" >&2; exit 1; }

  WORK="$RUNS_DIR/$RUN_ID/agent-$i"
  # The workdir lives on the cluster's shared PVC. The launcher host may not
  # mount that PVC (e.g. tunnel-reached clusters), so the pod creates it and
  # writes PROMPT.txt itself from a base64 env (avoids multi-line YAML env).
  PROMPT_B64=$(printf '%s\n' "$PROMPT" | base64 -w0)
  # 46 chars keeps the per-run suffix (uniqueness) within the 63-char name cap.
  JOB="kernel-agent-$(echo "$RUN_LABEL" | cut -c1-46)-$i"
  "${KUBECTL[@]}" -n "$NS" delete job "$JOB" --ignore-not-found >/dev/null 2>&1 || true

  "${KUBECTL[@]}" -n "$NS" apply -f - >/dev/null <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB
  labels:
    app: kernel-agent
    run: "$RUN_LABEL"
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels: { app: kernel-agent, run: "$RUN_LABEL" }
    spec:
      restartPolicy: Never$SCHED_YAML
      tolerations:
        - { key: node-group, value: nccl, effect: NoSchedule }
      volumes:
        - name: shared
          persistentVolumeClaim: { claimName: $SHARED_PVC }$HOME_VOL_YAML
      containers:
        - name: agent
          image: $AGENT_IMAGE
          workingDir: /shared
          env:
            - name: KERNEL_EVALUATOR_API
              value: "$AGENT_EVAL_API"
            - name: KERNEL_EVALUATOR_API_KEY
              value: "$AGENT_KEY"
            - name: BENCH_RUN_ID
              value: "$RUN_ID"
            - name: BENCH_AGENT_INDEX
              value: "$i"
            - name: BENCH_STARTER_MODE
              value: "$STARTER_MODE"
            - name: AGENT_PROMPT_B64
              value: "$PROMPT_B64"
            - name: AGENT_INSTRUCTIONS_B64
              value: "$INSTRUCTIONS_B64"
            - name: AGENT_WIKI_B64
              value: "$WIKI_B64"
            - name: AGENT_EVALUATION_B64
              value: "$EVALUATION_B64"
            - name: BENCH_SHARED_WIKI
              value: "$RUNS_DIR/$RUN_ID/WIKI.md"$EXTRA_ENV
          command: ["bash", "-lc"]
          args:
            - |-
              export PATH="\$PATH:/usr/local/bin"
              echo "[agent $i] apt install python…"
              apt-get update && apt-get install -y python3 python3-pip git curl passwd util-linux || echo "APT FAILED"
              echo "[agent $i] npm install claude/codex…"
              npm i -g @anthropic-ai/claude-code @openai/codex || echo "NPM FAILED (continuing)"
              echo "[agent $i] pip install client…"
              pip install --break-system-packages --no-cache-dir -e "$CODE_DIR" || echo "PIP FAILED"
              mkdir -p "$WORK" && chown -R $RUN_UID:$RUN_GID "$RUNS_DIR/$RUN_ID" 2>/dev/null || true
              echo "\$AGENT_PROMPT_B64" | base64 -d > "$WORK/PROMPT.txt"
              if [ -n "\$AGENT_INSTRUCTIONS_B64" ]; then
                echo "\$AGENT_INSTRUCTIONS_B64" | base64 -d > "$WORK/INSTRUCTION.md"
              fi
              RUN_WIKI="$RUNS_DIR/$RUN_ID/WIKI.md"
              if [ ! -f "\$RUN_WIKI" ] && [ -n "\$AGENT_WIKI_B64" ]; then
                echo "\$AGENT_WIKI_B64" | base64 -d > "\$RUN_WIKI.tmp-$i"
                mv -n "\$RUN_WIKI.tmp-$i" "\$RUN_WIKI" 2>/dev/null || rm -f "\$RUN_WIKI.tmp-$i"
              fi
              [ -f "\$RUN_WIKI" ] || printf '# Kernel Knowledge Base\n\n## CUDA / PTX field notes\n- Verify target architecture, PTX/SASS, registers, shared memory, spills, and tensor-core instructions.\n\n## Attempt Log\n' > "\$RUN_WIKI"
              ln -sfn ../WIKI.md "$WORK/WIKI.md"
              if [ -n "\$AGENT_EVALUATION_B64" ]; then
                echo "\$AGENT_EVALUATION_B64" | base64 -d > "$WORK/EVALUATION.md"
              fi
              chown -R $RUN_UID:$RUN_GID "$RUNS_DIR/$RUN_ID" 2>/dev/null || true
              # Drop to a non-root user: claude refuses --dangerously-skip-permissions
              # as root, and (when a home PVC is mounted) ~/.claude creds are owned
              # by uid $RUN_UID.
              if ! getent passwd $RUN_UID >/dev/null; then
                groupadd -o -g $RUN_GID agent 2>/dev/null || true
                useradd -o -u $RUN_UID -g $RUN_GID -d $HOME_PATH -s /bin/bash agent 2>/dev/null || true
              fi
              AGENT_USER=\$(getent passwd $RUN_UID | cut -d: -f1)
              echo "[agent $i] running as \$AGENT_USER (uid $RUN_UID)"
              runuser -u "\$AGENT_USER" -- bash -c '
                # With an API key the CLI needs no login session: isolate HOME in
                # the per-agent workdir so N concurrent agents do not race on the
                # real ~/.claude.json (mirrors the docker path HOME=/workspace).
                if [ -n "\$ANTHROPIC_API_KEY" ] || [ -n "\$CODEX_API_KEY" ]; then
                  export HOME="$WORK"
                else
                  export HOME=$HOME_PATH
                fi
                export PATH=/usr/local/bin:\$PATH
                cd "$WORK"
                cp -r "$CODE_DIR/scaffold/agent_runner/.agents" . 2>/dev/null || true
                cat "$CODE_DIR"/scaffold/instructions/common/*.md "$CODE_DIR"/scaffold/instructions/$TARGET/*.md > CLAUDE.md 2>/dev/null || true
                if [ "$BUILD_MODE" = "true" ]; then cat "$CODE_DIR/scaffold/eval/BUILD_MODE.md" >> CLAUDE.md 2>/dev/null || true; fi
                if [ -f INSTRUCTION.md ]; then { echo; echo "## Task brief (INSTRUCTION.md)"; echo; cat INSTRUCTION.md; } >> CLAUDE.md; fi
                if [ -f EVALUATION.md ]; then { echo; echo "## Evaluator rubric (EVALUATION.md)"; echo; cat EVALUATION.md; } >> CLAUDE.md; fi
                printf "\n## Shared kernel knowledge (WIKI.md)\n- WIKI.md is shared by every agent in this run. Read it before each attempt.\n- bench-poll automatically appends every compile/correctness/performance result.\n- After each result, add a concise diagnosis and next fix under that attempt.\n- Do not repeat an approach already shown to fail; build on other agents findings.\n- Before submitting, self-review against EVALUATION.md when present.\n" >> CLAUDE.md
                AGENT_PROMPT="\$(cat "$WORK/PROMPT.txt")"
                echo "[agent $i] bench-run…"; bench-run --run-id "$RUN_ID" || true
                for it in \$(seq 1 $MAX_ITERATIONS); do
                  echo "[agent $i] iteration \$it/$MAX_ITERATIONS"
                  if [ "$CLI" = "claude" ]; then
                    claude -p "\$AGENT_PROMPT" --dangerously-skip-permissions --model "$MODEL" || true
                  else
                    codex exec --dangerously-bypass-approvals-and-sandbox "\$AGENT_PROMPT" || true
                  fi
                done
              '
              echo "[agent $i] done"
          volumeMounts:
            - { name: shared, mountPath: /shared }$HOME_MOUNT_YAML
          resources:
            requests: { cpu: "1", memory: 2Gi }
            limits: { cpu: "4", memory: 8Gi }
YAML
  echo "  agent $i -> job/$JOB"
  launched+=("$JOB")
done

echo
echo "run:  $RUN_ID"
echo "jobs: ${launched[*]}"
echo "watch: kubectl -n $NS logs -f job/${launched[0]}"
echo "stop:  kubectl -n $NS delete jobs -l app=kernel-agent,run=$RUN_LABEL"

if [ "$AUTO_TERMINATE" = true ]; then
    # Host-side watcher: polls the eval API and calls finish_run.sh (which
    # kubectl-deletes the agent jobs) once the target speedup is reached.
    export KERNEL_EVALUATOR_API="$ADMIN_EP"
    export KERNEL_EVALUATOR_ADMIN_API_KEY="$ADMIN_KEY"
    # The watcher log must live somewhere the LAUNCHER host can write; RUNS_DIR
    # may be another cluster's PVC that isn't mounted here - fall back to /tmp.
    WATCH_DIR="$RUNS_DIR/$RUN_ID"
    mkdir -p "$WATCH_DIR" 2>/dev/null || { WATCH_DIR="/tmp/loom-kernel-runs/$RUN_ID"; mkdir -p "$WATCH_DIR"; }
    nohup bash "$SCRIPT_DIR/wait_for_speedup.sh" "$RUN_ID" --interval "$POLL_INTERVAL" \
        > "$WATCH_DIR/wait_for_speedup.log" 2>&1 &
    echo "Auto-terminate: enabled (poll: ${POLL_INTERVAL}s, watcher pid $!, log: $WATCH_DIR/wait_for_speedup.log)"
fi
