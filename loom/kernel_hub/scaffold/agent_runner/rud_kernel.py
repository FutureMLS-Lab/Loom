#!/usr/bin/env python3
"""Loom integration helper for the kernel-optimization harness.

A thin, JSON-in/JSON-out wrapper that Loom's web backend shells out to so it can
drive kernel runs without knowing the harness internals. Every subcommand prints a
single JSON object to stdout (diagnostics go to stderr) and exits 0 on success,
1 on error. Stdlib only — no third-party deps.

Subcommands:
  plugins                       list plugins/targets/shape-templates for the form
  service-status                health-check the eval service
  up [--build]                  ensure the eval service is running (docker compose up -d,
                                or the k8s Deployment on docker-less hosts)
  launch --plugin ... [opts]    ensure service up, then run_agents(.sh|_k8s.sh); return run_id + containers
  status --run-id ID            docker/k8s + eval API -> agents/submissions/leaderboard/best
  agent-log --run-id ID --agent N [--tail N]   tail one agent's container/Job log
  stop   --run-id ID            finish_run.sh (stop containers/jobs + postprocess winner)

Backends: on hosts with docker the original docker-compose + `docker run` path is
used. On docker-less hosts (e.g. shared GPU boxes) everything runs on Kubernetes:
the evaluator as a Deployment (k8s/evaluator.yaml) and each agent as a Job
(run_agents_k8s.sh).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent          # scaffold/agent_runner
SCAFFOLD_DIR = SCRIPT_DIR.parent                      # scaffold
REPO_ROOT = SCAFFOLD_DIR.parent                       # repo root (has docker-compose.yml, env.dev)
RUN_AGENTS = SCRIPT_DIR / "run_agents.sh"
RUN_AGENTS_K8S = SCRIPT_DIR / "run_agents_k8s.sh"
FINISH_RUN = SCRIPT_DIR / "finish_run.sh"

# Fallback list (used only if the live registry can't be parsed). The real
# source of truth is the service's plugin registry, parsed below.
_FALLBACK_PLUGINS = [
    "torch.linear",
    "torch.sdpa",
    "torch.fp8_gemm",
    "cuda.int4_matmul",
    "fa3.paged_decode",
    "sparse_attention.fwd",
    "aiter.moe_up_gemm",
]


def _discover_plugins():
    """Plugin names the service actually registers, parsed statically from
    kernel_evaluator/services/plugins/__init__.py (the `for _module in (...)`
    block) + each module's PLUGIN_NAME. Avoids importing heavy deps. Falls back
    to _FALLBACK_PLUGINS on any error."""
    pdir = REPO_ROOT / "kernel_evaluator" / "services" / "plugins"
    try:
        init_text = (pdir / "__init__.py").read_text()
    except OSError:
        return list(_FALLBACK_PLUGINS)
    m = re.search(r"for\s+_module\s+in\s*\(([^)]*)\)", init_text)
    if not m:
        return list(_FALLBACK_PLUGINS)
    names = []
    for mod in (x.strip() for x in m.group(1).split(",")):
        if not mod:
            continue
        try:
            mod_text = (pdir / f"{mod}.py").read_text()
        except OSError:
            continue
        nm = re.search(r'^PLUGIN_NAME\s*=\s*["\']([^"\']+)["\']', mod_text, re.MULTILINE)
        if nm:
            names.append(nm.group(1))
    return names or list(_FALLBACK_PLUGINS)


# Shape templates pre-fill the form; the user can edit the JSON freely.
PLUGINS = _discover_plugins()
TARGETS = ["cuda", "cutedsl", "triton", "hip"]
STARTER_MODES = ["none", "generic", "best-similar", "preset"]
# claude-*-4-20250514 were retired 2026-06-15; keep this list to models the
# API key can actually serve (see `curl /v1/models`). First entry pre-fills
# the Kernel Lab launch form.
SUGGESTED_MODELS = [
    "claude-fable-5",
    "claude-sonnet-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-opus-4-5-20251101",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-1-20250805",
    "gpt-5.5",
    "gpt-5.4",
]
SHAPE_TEMPLATES = {
    "torch.linear": {"m": 4096, "n": 4096, "k": 4096, "dtype": "bf16"},
    "torch.sdpa": {"batch": 1, "qo_heads": 32, "kv_heads": 32, "seq_len": 2048,
                   "head_dim": 128, "dtype": "bf16"},
    "torch.fp8_gemm": {"m": 4096, "n": 4096, "k": 4096, "dtype": "fp8_e4m3"},
    "cuda.int4_matmul": {"m": 4096, "n": 4096, "k": 4096},
    "fa3.paged_decode": {"batch": 1, "qo_heads": 32, "kv_heads": 8, "seq_len": 4096,
                         "head_dim": 128, "page_size": 16, "dtype": "bf16"},
    "sparse_attention.fwd": {"batch": 4, "total_q": 4096, "seq_len": 4096,
                             "num_heads": 32, "head_dim": 128, "dtype": "bf16"},
    "aiter.moe_up_gemm": {"m": 4096, "n": 4096, "k": 4096, "dtype": "bf16"},
    "minimax_sparse.decode_indexer": {"batch": 1, "seq_len": 4096, "num_heads": 32},
    # Keys match make_operation_contract() in mla_decode_fp8.py
    # (requires batch_size/num_heads/page_size/max_sequence_kv).
    "mla.decode_fp8": {"batch_size": 4, "num_heads": 128, "page_size": 64,
                       "max_sequence_kv": 1024, "seq_len_q": 1,
                       "latent_dim": 512, "rope_dim": 64, "dtype": "fp8"},
    # Same ABI/shape as mla.decode_fp8 (dtype stays fp8 - that's the tensor
    # ABI); the nvfp4 part is the kernel-internal quantization task.
    "mla.decode_nvfp4": {"batch_size": 4, "num_heads": 128, "page_size": 64,
                         "max_sequence_kv": 1024, "seq_len_q": 1,
                         "latent_dim": 512, "rope_dim": 64, "dtype": "fp8"},
    # rms_norm plugins use {m, n, dtype} (+ optional epsilon).
    "aiter.rms_norm": {"m": 4096, "n": 4096, "dtype": "bf16"},
    "aiter.add_rms_norm": {"m": 4096, "n": 4096, "dtype": "bf16"},
}


# --------------------------------------------------------------------------- #
# Environment / service helpers
# --------------------------------------------------------------------------- #
def _parse_env_file(path, env):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        env[key.strip()] = val.strip().strip('"').strip("'")


def load_env():
    """Build the subprocess env: env.dev defaults, then an optional cluster
    profile (LOOM_KERNEL_ENV_FILE - selects which external cluster the
    kernel stack targets), overlaid by the real os.environ."""
    env = {}
    _parse_env_file(REPO_ROOT / "env.dev", env)
    profile = (os.environ.get("LOOM_KERNEL_ENV_FILE") or "").strip()
    if profile:
        _parse_env_file(Path(profile).expanduser(), env)
    merged = {**env, **os.environ}  # real environment wins over file defaults
    return merged


def service_url(env):
    api = env.get("KERNEL_EVALUATOR_API")
    if api:
        return api.rstrip("/")
    port = env.get("KERNEL_EVALUATOR_PORT", "8000")
    return f"http://localhost:{port}"


def admin_key(env):
    return env.get("KERNEL_EVALUATOR_ADMIN_API_KEY") or env.get("KERNEL_EVALUATOR_API_KEY") or ""


# --------------------------------------------------------------------------- #
# Backend selection: docker (original) vs Kubernetes (docker-less hosts)
# --------------------------------------------------------------------------- #
def docker_available(env=None):
    return shutil.which("docker", path=(env or os.environ).get("PATH")) is not None


def kubectl_bin(env=None):
    """kubectl path; tolerates a server PATH that misses ~/.local/bin."""
    e = env or os.environ
    found = shutil.which("kubectl", path=e.get("PATH"))
    if found:
        return found
    home = e.get("HOME") or os.path.expanduser("~")
    for cand in (Path(home) / ".local" / "bin" / "kubectl", Path("/usr/local/bin/kubectl")):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def k8s_namespace(env):
    return env.get("LOOM_K8S_NAMESPACE", "charlie")


def kubectl_base(env):
    """kubectl argv prefix honouring cluster selection: LOOM_K8S_KUBECONFIG
    (path) and/or LOOM_K8S_CONTEXT (context name) pick which cluster the
    kernel stack talks to; unset means the user's default kubeconfig/context."""
    kc = kubectl_bin(env)
    if not kc:
        return None
    # Bounded API timeout so a broken tunnel/cluster degrades into a fast,
    # visible error instead of hanging the web UI's status polls.
    base = [kc, "--request-timeout=15s"]
    kubeconfig = (env.get("LOOM_K8S_KUBECONFIG") or "").strip()
    if kubeconfig:
        base += ["--kubeconfig", kubeconfig]
    context = (env.get("LOOM_K8S_CONTEXT") or "").strip()
    if context:
        base += ["--context", context]
    return base


def use_k8s(env):
    """Docker-less hosts drive runs through Kubernetes (run_agents_k8s.sh)."""
    return not docker_available(env) and kubectl_bin(env) is not None


def _kubectl_get(env, args, timeout=15):
    """Run `kubectl -n <ns> <args>` and return stdout ('' on any failure)."""
    base = kubectl_base(env)
    if not base:
        return ""
    try:
        proc = subprocess.run([*base, "-n", k8s_namespace(env), *args],
                              env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _url_up(url, timeout=3):
    req = urllib.request.Request(url.rstrip("/") + "/openapi.json", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_service_url(env):
    """Pick a reachable evaluator endpoint and pin it in
    env['KERNEL_EVALUATOR_API'] so every child process (launcher, watcher,
    agents) talks to the same one. Returns (url, up).

    On docker-less hosts the evaluator runs in k8s; its Service DNS usually
    does not resolve from the host, so fall back to the Service ClusterIP
    (stable, reachable from host and pods alike), then the pod IP."""
    primary = service_url(env)
    if _url_up(primary, timeout=2):
        env["KERNEL_EVALUATOR_API"] = primary
        return primary, True
    if docker_available(env):
        return primary, False
    candidates = []
    cluster_ip = _kubectl_get(
        env, ["get", "svc", "kernel-evaluator", "-o", "jsonpath={.spec.clusterIP}"])
    if cluster_ip:
        candidates.append(f"http://{cluster_ip}:8000")
    pod_ip = _kubectl_get(
        env, ["get", "pods", "-l", "app=kernel-evaluator",
              "-o", "jsonpath={.items[0].status.podIP}"])
    if pod_ip:
        candidates.append(f"http://{pod_ip}:8000")
    for url in candidates:
        if _url_up(url, timeout=2):
            env["KERNEL_EVALUATOR_API"] = url
            return url, True
    return primary, False


def api_get(env, path, timeout=10):
    """GET {service}{path} with admin key. Returns (status, json_or_none)."""
    url = service_url(env) + path
    req = urllib.request.Request(url, method="GET")
    key = admin_key(env)
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, None


def api_post(env, path, payload, timeout=30):
    url = service_url(env) + path
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    key = admin_key(env)
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = None
        return exc.code, body
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, None


def is_up(env, timeout=4):
    status, _ = api_get(env, "/openapi.json", timeout=timeout)
    return status == 200


def ensure_up_k8s(env, wait_s=900):
    """Docker-less host: the evaluator runs as a k8s Deployment
    (k8s/evaluator.yaml). (Re-)apply the manifest — idempotent — and wait for
    health. First boot pip-installs deps inside the pod, which takes minutes."""
    base = kubectl_base(env)
    if not base:
        return {"up": False, "started": False, "url": service_url(env),
                "error": "docker is not installed and kubectl was not found; "
                         "cannot start the eval service"}
    manifest = Path(env.get("LOOM_K8S_EVALUATOR_MANIFEST") or (REPO_ROOT / "k8s" / "evaluator.yaml"))
    if not manifest.is_file():
        return {"up": False, "started": False, "url": service_url(env),
                "error": f"k8s manifest not found: {manifest}"}
    ns = k8s_namespace(env)
    print(f"[rud_kernel] no docker on this host; ensuring k8s evaluator "
          f"(kubectl -n {ns} apply -f {manifest}) ...", file=sys.stderr, flush=True)
    proc = subprocess.run([*base, "-n", ns, "apply", "-f", str(manifest)], env=env,
                          stdout=sys.stderr, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        return {"up": False, "started": False, "url": service_url(env),
                "error": "kubectl apply failed (see log)"}
    print("[rud_kernel] waiting for evaluator health (first boot installs deps; "
          "can take several minutes) ...", file=sys.stderr, flush=True)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        url, up = resolve_service_url(env)
        if up:
            print(f"[rud_kernel] eval service healthy at {url}", file=sys.stderr, flush=True)
            return {"up": True, "started": True, "url": url}
        time.sleep(5)
    return {"up": False, "started": True, "url": service_url(env),
            "error": f"k8s evaluator did not become healthy within {wait_s}s"}


def ensure_up(env, build=False, wait_s=180):
    """Health-check the service; if down, bring it up (docker compose, or the
    k8s Deployment on docker-less hosts) and wait until healthy."""
    url, up = resolve_service_url(env)
    if up:
        return {"up": True, "started": False, "url": url}
    if not docker_available(env):
        return ensure_up_k8s(env)

    compose = ["docker", "compose", "up", "-d"]
    if build:
        compose.append("--build")
    # Stream the (potentially very long) docker build + bring-up to stderr so the
    # caller (RUD) can tee it into a per-run log and show progress live in the UI.
    # The final result JSON is printed to stdout by main(), keeping stdout clean.
    print(f"[rud_kernel] $ {' '.join(compose)}  (cwd={REPO_ROOT})", file=sys.stderr, flush=True)
    proc = subprocess.run(compose, cwd=str(REPO_ROOT), env=env,
                          stdout=sys.stderr, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        return {"up": False, "started": False, "url": service_url(env),
                "error": "docker compose up failed (see build log)"}

    print(f"[rud_kernel] image/containers up; waiting for service health at {service_url(env)} ...",
          file=sys.stderr, flush=True)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if is_up(env):
            print("[rud_kernel] eval service healthy.", file=sys.stderr, flush=True)
            return {"up": True, "started": True, "url": service_url(env)}
        time.sleep(3)
    return {"up": False, "started": True, "url": service_url(env),
            "error": f"service did not become healthy within {wait_s}s"}


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def cmd_plugins(args, env):
    return {
        "ok": True,
        "plugins": PLUGINS,
        "targets": TARGETS,
        "starter_modes": STARTER_MODES,
        "suggested_models": SUGGESTED_MODELS,
        "shape_templates": SHAPE_TEMPLATES,
    }


def cmd_service_status(args, env):
    up = is_up(env)
    return {"ok": True, "up": up, "url": service_url(env)}


def cmd_up(args, env):
    res = ensure_up(env, build=args.build)
    res["ok"] = res.get("up", False)
    return res


_EVAL_CONTAINER = "kernel-evaluator"


def ensure_db_migrated(env=None):
    """Idempotently apply alembic migrations inside the eval container so a fresh
    Postgres has its schema (and the seeded admin key). Streams to stderr so the
    output shows up in RUD's build/run log. Best-effort: warns on failure."""
    if not docker_available(env):
        # The k8s evaluator runs `alembic upgrade head` in its startup script
        # (see k8s/evaluator.yaml), so a healthy pod already has the schema.
        print("[rud_kernel] skipping docker DB migrate (k8s evaluator migrates at startup)",
              file=sys.stderr, flush=True)
        return
    print("[rud_kernel] ensuring DB schema (alembic upgrade head) ...", file=sys.stderr, flush=True)
    try:
        subprocess.run(
            ["docker", "exec", "-w", "/app/kernel_evaluator", _EVAL_CONTAINER,
             "/opt/venv/bin/python", "-c",
             "from kernel_evaluator.db.session import create_tables; create_tables()"],
            stdout=sys.stderr, stderr=subprocess.STDOUT, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[rud_kernel] DB migrate warning: {exc}", file=sys.stderr, flush=True)


# Task specs written by the interview/UI sometimes use different key names than
# the plugin contract (make_operation_contract) requires; map them here so a
# launch never 500s on a well-known synonym.
_SHAPE_KEY_ALIASES = {
    "mla.decode_fp8": {
        "kv_len": "max_sequence_kv",
        "sq": "seq_len_q",
    },
    "mla.decode_nvfp4": {
        "kv_len": "max_sequence_kv",
        "sq": "seq_len_q",
    },
}


def normalize_shape(plugin, shape_str):
    aliases = _SHAPE_KEY_ALIASES.get(plugin)
    if not aliases:
        return shape_str
    try:
        shape = json.loads(shape_str)
    except json.JSONDecodeError:
        return shape_str
    if not isinstance(shape, dict):
        return shape_str
    for old, new in aliases.items():
        if old in shape and new not in shape:
            shape[new] = shape.pop(old)
    return json.dumps(shape)


def _home_claude_login(env):
    home = env.get("HOME") or os.path.expanduser("~")
    return (Path(home) / ".claude" / ".credentials.json").is_file()


def cmd_launch(args, env):
    k8s = use_k8s(env)
    # Validate the model has usable credentials. k8s agent jobs mount the home
    # PVC, so a logged-in `claude` session works there without an API key.
    if args.model.startswith("claude-") and not env.get("ANTHROPIC_API_KEY"):
        if not (k8s and _home_claude_login(env)):
            return {"ok": False, "error": "ANTHROPIC_API_KEY is not set; claude agents cannot start"}
    if (args.model.startswith("gpt-") or re.match(r"^o[0-9]", args.model)) and not env.get("OPENAI_API_KEY"):
        return {"ok": False, "error": "OPENAI_API_KEY is not set; codex agents cannot start"}
    if k8s and args.starter_mode == "preset":
        return {"ok": False, "error": "starter-mode 'preset' is not supported on the k8s backend"}

    # Resolve the shape. Callers (the RUD web UI / its launch agent) normally
    # pass a chosen --shape; when none is given we fall back to the plugin's
    # default SHAPE_TEMPLATES entry so the shape is never a hard human input.
    if args.shape is None or str(args.shape).strip() == "":
        tpl = SHAPE_TEMPLATES.get(args.plugin)
        if tpl is None:
            return {
                "ok": False,
                "error": (
                    f"no --shape given and no default shape template for plugin "
                    f"'{args.plugin}'; pass --shape with a JSON shape"
                ),
            }
        shape_str = json.dumps(tpl)
    else:
        try:
            json.loads(args.shape)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"--shape must be valid JSON: {e}"}
        shape_str = args.shape
    shape_str = normalize_shape(args.plugin, shape_str)

    up = ensure_up(env, build=args.build)
    if not up.get("up"):
        return {"ok": False, "error": "eval service is not available", "service": up}

    # A fresh DB has no schema; run migrations (idempotent: alembic upgrade head
    # is a no-op once at head) so run-creation doesn't 500 on a missing table.
    ensure_db_migrated(env)
    if args.contract_file:
        contract_path = Path(args.contract_file)
        if not contract_path.is_file():
            return {"ok": False, "error": f"contract file not found: {contract_path}"}
        status, registered = api_post(
            env,
            "/evaluation/plugins/register",
            {"source_text": contract_path.read_text(encoding="utf-8")},
        )
        if status != 200:
            return {
                "ok": False,
                "error": f"task contract registration failed (status {status})",
                "service": registered,
            }
        if (registered or {}).get("plugin") != args.plugin:
            return {
                "ok": False,
                "error": "task contract plugin name does not match launch plugin",
                "service": registered,
            }

    cmd = ["bash", str(RUN_AGENTS_K8S if k8s else RUN_AGENTS),
           "--plugin", args.plugin,
           "--target", args.target,
           "--shape", shape_str,
           "--model", args.model,
           "--n-agents", str(args.n_agents),
           "--starter-mode", args.starter_mode]
    if args.instructions_file:
        if not Path(args.instructions_file).is_file():
            return {"ok": False, "error": f"instructions file not found: {args.instructions_file}"}
        cmd += ["--instructions-file", args.instructions_file]
    if args.wiki_file:
        if not Path(args.wiki_file).is_file():
            return {"ok": False, "error": f"wiki file not found: {args.wiki_file}"}
        cmd += ["--wiki-file", args.wiki_file]
    if args.evaluation_file:
        if not Path(args.evaluation_file).is_file():
            return {"ok": False, "error": f"evaluation file not found: {args.evaluation_file}"}
        cmd += ["--evaluation-file", args.evaluation_file]
    if args.target_speedup is not None:
        cmd += ["--target-speedup", str(args.target_speedup)]
    if args.auto_terminate:
        cmd += ["--auto-terminate", "--poll-interval", str(args.poll_interval)]
    if args.preset_path:
        cmd += ["--preset-path", args.preset_path]
    if args.build_mode:
        cmd += ["--build-mode"]

    # Stream run_agents.sh (incl. the agent docker build + launch) to stderr live
    # so RUD's run log scrolls, while still capturing stdout to parse the run id.
    proc = subprocess.Popen(cmd, cwd=str(SCRIPT_DIR), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out_lines = []
    if proc.stdout is not None:
        for line in proc.stdout:
            sys.stderr.write(line)
            sys.stderr.flush()
            out_lines.append(line)
    proc.wait()
    out = "".join(out_lines)
    if proc.returncode != 0:
        return {"ok": False, "error": "run_agents.sh failed",
                "stderr": out[-2000:]}

    # run_agents.sh prints:  Run: <run_id>  task: <task_slug>  agents: N  model: ...
    m = re.search(r"^Run:\s+(\S+)\s+task:\s+(\S+)\s+agents:", out, re.MULTILINE)
    if not m:
        return {"ok": False, "error": "could not parse run_id from run_agents.sh output",
                "stdout_tail": out[-2000:]}
    run_id, task_slug = m.group(1), m.group(2)
    if k8s:
        containers = [f"kernel-agent-{_k8s_run_label(run_id)[:46]}-{i}"
                      for i in range(1, args.n_agents + 1)]
    else:
        containers = [f"kernel-agent-{run_id}-{i}" for i in range(1, args.n_agents + 1)]
    return {
        "ok": True,
        "backend": "k8s" if k8s else "docker",
        "run_id": run_id,
        "task_slug": task_slug,
        "plugin": args.plugin,
        "target": args.target,
        "shape": shape_str,
        "model": args.model,
        "n_agents": args.n_agents,
        "starter_mode": args.starter_mode,
        "target_speedup": args.target_speedup,
        "auto_terminate": args.auto_terminate,
        "build_mode": args.build_mode,
        "containers": containers,
    }


def _docker_running(name_prefix):
    """Return {container_name: running_bool} for containers matching the prefix."""
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={name_prefix}",
         "--format", "{{.Names}}\t{{.State}}"],
        capture_output=True, text=True).stdout
    result = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        name, state = line.split("\t", 1)
        result[name.strip()] = state.strip() == "running"
    return result


def _k8s_run_label(run_id):
    """Same label derivation as run_agents_k8s.sh (k8s labels can't contain _)."""
    return run_id.replace("_", "-")[:50]


def _k8s_agents_running(env, run_id):
    """Return {job_name: active_bool} for this run's kernel-agent Jobs, or
    None when the kubectl query itself failed (unknown, not "none")."""
    out = _kubectl_get(
        env, ["get", "jobs", "-l", f"app=kernel-agent,run={_k8s_run_label(run_id)}",
              "-o", "json"], timeout=20)
    if not out:
        return None
    try:
        items = json.loads(out).get("items", [])
    except json.JSONDecodeError:
        return None
    result = {}
    for job in items:
        name = (job.get("metadata") or {}).get("name", "")
        if name:
            result[name] = bool((job.get("status") or {}).get("active"))
    return result


def _submission_rows(run_detail, limit=100):
    """Flatten the run's submission jobs into compact leaderboard rows, in
    submission order (the evaluator preserves insertion order). Every attempt
    is included — correct, incorrect, failed and still-evaluating."""
    rows = []
    for n, job in enumerate((run_detail or {}).get("jobs") or [], start=1):
        state = str(job.get("state") or "")
        err = job.get("compile_error") or job.get("benchmark_error") or ""
        rows.append({
            "n": n,
            "job_id": job.get("job_id"),
            "agent_index": job.get("agent_index"),
            "state": state,
            "correct": job.get("correct"),
            "speedup": job.get("speedup"),
            "candidate_us": job.get("candidate_us"),
            "baseline_us": job.get("baseline_us"),
            "error": str(err)[:200] if err else None,
        })
    return rows[-limit:]


def _agent_activity(run_detail):
    """Aggregate the run's submission jobs (from /evaluation/runs/{id}) into a
    per-agent activity map: how many submissions, their states, best result and
    the most recent error. Keys are agent indexes as strings."""
    activity = {}
    for job in (run_detail or {}).get("jobs") or []:
        idx = job.get("agent_index")
        key = str(idx) if idx is not None else "?"
        a = activity.setdefault(key, {
            "submissions": 0, "in_flight": 0, "failed": 0, "correct": 0,
            "best_speedup": None, "last_state": None, "last_error": None,
            "last_job_id": None,
        })
        a["submissions"] += 1
        state = str(job.get("state") or "")
        a["last_state"] = state
        a["last_job_id"] = job.get("job_id")
        if state == "completed":
            if job.get("correct"):
                a["correct"] += 1
                sp = job.get("speedup")
                if isinstance(sp, (int, float)) and (a["best_speedup"] is None or sp > a["best_speedup"]):
                    a["best_speedup"] = sp
            a["last_error"] = None if job.get("correct") else "completed but incorrect (outputs mismatch)"
        elif state.endswith("_failed"):
            a["failed"] += 1
            err = job.get("compile_error") or job.get("benchmark_error") or state
            a["last_error"] = str(err)[:400]
        else:
            a["in_flight"] += 1
    return activity


def cmd_status(args, env):
    run_id = args.run_id
    qs = "?run_id=" + urllib.request.quote(run_id)

    if use_k8s(env):
        agents_state = _k8s_agents_running(env, run_id)
    else:
        agents_state = _docker_running(f"kernel-agent-{run_id}-")
    # None => the container/Job query itself failed; don't let the caller
    # mistake "unknown" for "all agents exited".
    agents_known = agents_state is not None
    agents_state = agents_state or {}

    _, run_detail = api_get(env, f"/evaluation/runs/{urllib.request.quote(run_id)}")
    target_speedup = (run_detail or {}).get("target_speedup")
    activity = _agent_activity(run_detail)

    agents = []
    for name, running in sorted(agents_state.items()):
        idx = name.rsplit("-", 1)[-1]
        agents.append({"name": name, "index": idx, "running": running,
                       "activity": activity.get(idx)})
    # Agents whose container/Job is already gone (e.g. cleaned up by
    # finish_run) but that did submit kernels: keep them visible.
    seen = {a["index"] for a in agents}
    for idx in sorted(activity, key=lambda x: (len(x), x)):
        if idx not in seen:
            agents.append({"name": f"agent-{idx}", "index": idx,
                           "running": False, "activity": activity[idx]})

    best_status, best = api_get(env, "/scaffold/best" + qs)
    if best_status != 200:
        best = None

    _, agent_bests = api_get(env, "/scaffold/agent-bests" + qs)
    _, archive = api_get(env, "/scaffold/archive" + qs)

    return {
        "ok": True,
        "run_id": run_id,
        "target_speedup": target_speedup,
        "agents": agents,
        "agents_known": agents_known,
        "agents_running": sum(1 for a in agents if a["running"]),
        "total_submissions": sum(a["submissions"] for a in activity.values()),
        "submissions": _submission_rows(run_detail),
        "best": best,
        "agent_bests": (agent_bests or {}).get("agent_bests", []),
        "archive": (archive or {}).get("entries", []),
        "improvements": len((archive or {}).get("entries", [])),
    }


def cmd_agent_log(args, env):
    """Tail one agent's container/Job log (what the agent CLI printed).

    Note claude/codex run in batch (-p/exec) mode: the transcript appears when
    the session ends; while it runs the log shows bench-run + setup output."""
    run_id, idx = args.run_id, str(args.agent)
    tail = str(max(10, min(args.tail, 2000)))
    if use_k8s(env):
        base = kubectl_base(env)
        if not base:
            return {"ok": False, "error": "kubectl not found"}
        job = f"kernel-agent-{_k8s_run_label(run_id)[:46]}-{idx}"
        try:
            proc = subprocess.run(
                [*base, "-n", k8s_namespace(env), "logs", f"job/{job}", "--tail", tail],
                env=env, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": str(e)}
        if proc.returncode != 0:
            return {"ok": False, "agent": idx,
                    "error": (proc.stderr or "no log available").strip()[:300],
                    "log": ""}
        return {"ok": True, "agent": idx, "source": f"job/{job}", "log": proc.stdout}
    name = f"kernel-agent-{run_id}-{idx}"
    proc = subprocess.run(["docker", "logs", "--tail", tail, name],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return {"ok": False, "agent": idx,
                "error": (proc.stderr or "no log available").strip()[:300], "log": ""}
    # docker logs writes the container's stdout to stdout and stderr to stderr.
    return {"ok": True, "agent": idx, "source": name,
            "log": (proc.stdout or "") + (proc.stderr or "")}


def api_get_text(env, path, timeout=10):
    """GET {service}{path} with admin key. Returns (status, text)."""
    url = service_url(env) + path
    req = urllib.request.Request(url, method="GET")
    key = admin_key(env)
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, ""


def cmd_kernel_source(args, env):
    status, text = api_get_text(
        env, f"/scaffold/kernel-source/{urllib.request.quote(args.job_id)}"
    )
    if status != 200:
        return {"ok": False, "error": f"kernel source not found (status {status})",
                "job_id": args.job_id}
    return {"ok": True, "job_id": args.job_id, "source": text}


def cmd_job_source(args, env):
    status, text = api_get_text(
        env, f"/evaluation/jobs/{urllib.request.quote(args.job_id)}/source"
    )
    if status != 200:
        # Correct kernels survive job TTL in the archive.
        status, text = api_get_text(
            env, f"/scaffold/kernel-source/{urllib.request.quote(args.job_id)}"
        )
    if status != 200:
        return {
            "ok": False,
            "error": f"job source unavailable (status {status})",
            "job_id": args.job_id,
        }
    return {"ok": True, "job_id": args.job_id, "source": text}


def cmd_best_kernel(args, env):
    status, data = api_get(
        env, f"/evaluation/runs/{urllib.request.quote(args.run_id)}/best-kernel"
    )
    if status != 200 or not isinstance(data, dict):
        return {"ok": False, "error": f"no best kernel yet (status {status})",
                "run_id": args.run_id}
    data["ok"] = True
    return data


def cmd_stop(args, env):
    proc = subprocess.run(["bash", str(FINISH_RUN), args.run_id],
                          cwd=str(SCRIPT_DIR), env=env,
                          capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "run_id": args.run_id,
        "output": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-1000:] if proc.returncode != 0 else "",
    }


# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(description="Loom kernel-run helper (JSON output)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("plugins")
    sub.add_parser("service-status")

    up = sub.add_parser("up")
    up.add_argument("--build", action="store_true")

    lr = sub.add_parser("launch")
    # Task-local contracts may not be in the bundled registry until launch
    # registers them with the selected evaluator.
    lr.add_argument("--plugin", required=True)
    lr.add_argument("--target", required=True, choices=TARGETS)
    lr.add_argument(
        "--shape",
        required=False,
        default=None,
        help="benchmark shape as JSON. Optional: when omitted, the plugin's "
             "default SHAPE_TEMPLATES entry is used (the caller/agent normally "
             "supplies a chosen shape instead).",
    )
    lr.add_argument("--model", required=True)
    lr.add_argument("--n-agents", type=int, default=1, dest="n_agents")
    lr.add_argument("--starter-mode", default="none", choices=STARTER_MODES, dest="starter_mode")
    lr.add_argument("--target-speedup", type=float, default=None, dest="target_speedup")
    lr.add_argument("--auto-terminate", action="store_true", dest="auto_terminate")
    lr.add_argument("--poll-interval", type=int, default=60, dest="poll_interval")
    lr.add_argument("--preset-path", default="", dest="preset_path")
    lr.add_argument("--build", action="store_true")
    lr.add_argument("--build-mode", action="store_true", dest="build_mode")
    lr.add_argument(
        "--instructions-file",
        default="",
        dest="instructions_file",
        help="task INSTRUCTION.md handed to every agent (written into its "
             "workdir and appended to its CLAUDE.md/AGENTS.md)",
    )
    lr.add_argument("--wiki-file", "--plan-file", default="", dest="wiki_file")
    lr.add_argument("--evaluation-file", default="", dest="evaluation_file")
    lr.add_argument("--contract-file", default="", dest="contract_file")

    st = sub.add_parser("status")
    st.add_argument("--run-id", required=True, dest="run_id")

    al = sub.add_parser("agent-log")
    al.add_argument("--run-id", required=True, dest="run_id")
    al.add_argument("--agent", required=True, type=int)
    al.add_argument("--tail", type=int, default=200)

    sp = sub.add_parser("stop")
    sp.add_argument("--run-id", required=True, dest="run_id")

    ks = sub.add_parser("kernel-source")
    ks.add_argument("--job-id", required=True, dest="job_id")

    js = sub.add_parser("job-source")
    js.add_argument("--job-id", required=True, dest="job_id")

    bk = sub.add_parser("best-kernel")
    bk.add_argument("--run-id", required=True, dest="run_id")

    return p


HANDLERS = {
    "plugins": cmd_plugins,
    "service-status": cmd_service_status,
    "up": cmd_up,
    "launch": cmd_launch,
    "status": cmd_status,
    "agent-log": cmd_agent_log,
    "stop": cmd_stop,
    "kernel-source": cmd_kernel_source,
    "job-source": cmd_job_source,
    "best-kernel": cmd_best_kernel,
}


def main():
    args = build_parser().parse_args()
    env = load_env()
    # Pin KERNEL_EVALUATOR_API to a reachable endpoint (k8s-aware) so this
    # process and every child (run_agents*, wait_for_speedup, finish_run) agree.
    resolve_service_url(env)
    try:
        result = HANDLERS[args.command](args, env)
    except Exception as e:  # never leak a traceback into RUD's JSON parser
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
