"""Durable, conservative continuation policy for ordinary agent tasks.

The activity watcher already knows when an interactive agent changes from
working to idle.  This module decides whether that idle pane may be nudged
without a human: the feature is opt-in, the task must still have explicit
unchecked work in PLAN.md, and every successful continuation is recorded in a
rolling daily quota.  Ambiguous terminal menus and high-impact actions fail
closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from loom.web_conversation import (
    _conversation_terminal_answer_keys,
    _conversation_terminal_question,
)


STATE_FILE = "agent-watchdog.json"
DEFAULT_IDLE_SECONDS = 180.0
DEFAULT_MAX_NUDGES = 0
WINDOW_SECONDS = 24 * 60 * 60
MAX_CONSECUTIVE_FAILURES = 2

CONTINUE_PROMPT = """Loom watchdog: this pane is idle, but PLAN.md still has \
unchecked work. Continue the accepted PLAN now. Resolve routine, reversible \
choices yourself with best judgment instead of asking again, and update PLAN.md \
after each milestone. Before retrying infrastructure, inspect durable state and \
existing jobs so you do not duplicate work. Stop and ask the human only if the \
next step requires a production/live change, a destructive or irreversible \
action, an external communication/submission/push, credentials or approval, or \
a materially underdetermined research fork. If the task is actually complete, \
check off the plan and give the final summary."""

_OPEN_PLAN_ITEM_RE = re.compile(r"(?m)^\s*[-*]\s+\[\s\]\s+(.+?)\s*$")
_RECOMMENDED_RE = re.compile(r"\b(?:recommended|default)\b|推荐", re.IGNORECASE)
_HIGH_IMPACT_RE = re.compile(
    r"(?:"
    r"\b(?:deploy|change|update|restart|promote)\b.{0,40}"
    r"\b(?:prod(?:uction)?|live)\b|"
    r"\b(?:prod(?:uction)?|live)\b.{0,40}"
    r"\b(?:deploy|change|update|restart|promote)\b|"
    r"\broll[ -]?out\b|\brelease\b|"
    r"\bgit\s+push\b|\bpush\s+(?:the\s+)?branch\b|\bopen\s+(?:a\s+)?pr\b|"
    r"\bpublish\b|\bsubmit\s+(?:a\s+)?(?:paper|manuscript|review|form)\b|"
    r"\bsend\s+(?:an?\s+)?(?:email|message)\b|"
    r"\bdelete\b|\bdrop\b|\bforce[- ]?push\b|\breset\s+--hard\b|"
    r"\bterminate\b|\bshutdown\b|\brevoke\b|"
    r"\bcredential(?:s)?\b|\bapi[-_ ]?key\b|\bsecret\b|\bpassword\b|"
    r"\bapproval\b|\bpermission\b|\bpurchase\b|\bbilling\b|"
    r"(?:部署|发布|变更|重启).{0,12}(?:生产|线上)|"
    r"(?:生产|线上).{0,12}(?:部署|发布|变更|重启)|"
    r"推送|提交到外部|删除|销毁|凭据|密钥|审批|权限"
    r")",
    re.IGNORECASE,
)


def _bounded_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return 0.0
    return max(minimum, min(maximum, value))


def watchdog_max_nudges() -> int:
    """Successful continuations allowed per task per rolling day; zero is off."""
    return int(
        _bounded_env(
            "LOOM_AGENT_WATCHDOG_MAX_NUDGES",
            float(DEFAULT_MAX_NUDGES),
            minimum=1.0,
            maximum=20.0,
        )
    )


def watchdog_idle_seconds() -> float:
    """How long an armed, idle pane must stay idle before action."""
    return _bounded_env(
        "LOOM_AGENT_WATCHDOG_IDLE_SECONDS",
        DEFAULT_IDLE_SECONDS,
        minimum=30.0,
        maximum=3600.0,
    )


def watchdog_enabled() -> bool:
    return watchdog_max_nudges() > 0


def _state_path(task_dir: Path) -> Path:
    return task_dir / STATE_FILE


def read_watchdog_state(task_dir: Path) -> dict[str, Any]:
    try:
        value = json.loads(_state_path(task_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_watchdog_state(task_dir: Path, state: dict[str, Any]) -> None:
    path = _state_path(task_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # Failure to persist means failure to prove the quota.  The caller
        # sees no armed state and therefore fails closed.
        return


def _plan_status(task_dir: Path) -> tuple[bool, str, str]:
    path = task_dir / "PLAN.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False, "", ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    items = [match.group(1).strip() for match in _OPEN_PLAN_ITEM_RE.finditer(text)]
    actionable_items = [item for item in items if item and not item.startswith("<!--")]
    return bool(actionable_items), digest, actionable_items[0] if actionable_items else ""


def arm_watchdog(task_dir: Path, *, target: str, now: float | None = None) -> None:
    """Persist that this pane was observed doing work and may later be nudged."""
    if not watchdog_enabled():
        return
    actionable, plan_digest, _next_item = _plan_status(task_dir)
    if not actionable:
        return
    current = time.time() if now is None else float(now)
    state = read_watchdog_state(task_dir)
    if (
        state.get("armed")
        and state.get("target") == target
        and not float(state.get("idle_since_epoch") or 0.0)
    ):
        return
    state.update(
        {
            "armed": True,
            "target": target,
            "observed_working_epoch": current,
            "idle_since_epoch": 0.0,
            "plan_sha256": plan_digest,
            "blocked_reason": "",
            "consecutive_failures": 0,
            "last_error": "",
        }
    )
    _write_watchdog_state(task_dir, state)


def _recent_nudges(state: dict[str, Any], now: float) -> list[float]:
    raw = state.get("nudge_epochs")
    if not isinstance(raw, list):
        return []
    return [
        float(value)
        for value in raw
        if isinstance(value, (int, float)) and now - float(value) < WINDOW_SECONDS
    ]


def _choice_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return tokens - {
        "a",
        "an",
        "the",
        "to",
        "for",
        "run",
        "retry",
        "continue",
        "option",
        "recommended",
        "default",
        "now",
    }


def _terminal_choice(
    text: str, plan_item: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    question = _conversation_terminal_question(text)
    if question is None:
        return None, None, ""
    prompts = question.get("questions") or []
    if len(prompts) != 1 or not isinstance(prompts[0], dict):
        return question, None, "question has multiple prompts"
    prompt = prompts[0]
    if bool(prompt.get("allow_multiple")):
        return question, None, "question permits multiple selections"
    options = prompt.get("options") or []
    recommended = [
        option
        for option in options
        if isinstance(option, dict)
        and _RECOMMENDED_RE.search(
            f"{option.get('label', '')} {option.get('description', '')}"
        )
    ]
    if len(recommended) > 1:
        return question, None, "question has multiple recommended answers"
    plan_tokens = _choice_tokens(plan_item)
    plan_matches = []
    for option in options:
        if not isinstance(option, dict):
            continue
        option_tokens = _choice_tokens(
            f"{option.get('label', '')} {option.get('description', '')}"
        )
        if option_tokens and option_tokens.issubset(plan_tokens):
            plan_matches.append(option)
    if len(plan_matches) > 1:
        return question, None, "multiple answers match the next PLAN item"
    if recommended and plan_matches and recommended[0] is not plan_matches[0]:
        return question, None, "recommended answer conflicts with the next PLAN item"
    candidate = recommended[0] if recommended else plan_matches[0] if plan_matches else None
    if candidate is None:
        return (
            question,
            None,
            "question has no unique recommended or PLAN-matched answer",
        )
    impact_text = " ".join(
        (
            str(prompt.get("prompt") or ""),
            str(candidate.get("label") or ""),
            str(candidate.get("description") or ""),
        )
    )
    if _HIGH_IMPACT_RE.search(impact_text):
        return question, None, "recommended answer crosses a high-impact boundary"
    return question, candidate, ""


def idle_decision(
    task_dir: Path,
    *,
    target: str,
    pane_text: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Return one durable action once an armed pane has been idle long enough."""
    if not watchdog_enabled():
        return {"action": "none", "reason": "disabled"}
    current = time.time() if now is None else float(now)
    state = read_watchdog_state(task_dir)
    if not state.get("armed") or state.get("target") != target:
        return {"action": "none", "reason": "not armed"}
    actionable, plan_digest, next_item = _plan_status(task_dir)
    if not actionable:
        state.update({"armed": False, "blocked_reason": "PLAN.md has no unchecked work"})
        _write_watchdog_state(task_dir, state)
        return {"action": "none", "reason": "plan complete"}
    idle_since = float(state.get("idle_since_epoch") or 0.0)
    if idle_since <= 0:
        state["idle_since_epoch"] = current
        state["plan_sha256"] = plan_digest
        _write_watchdog_state(task_dir, state)
        return {"action": "none", "reason": "idle grace period"}
    if current - idle_since < watchdog_idle_seconds():
        return {"action": "none", "reason": "idle grace period"}
    nudges = _recent_nudges(state, current)
    limit = watchdog_max_nudges()
    if len(nudges) >= limit:
        state.update(
            {
                "armed": False,
                "blocked_reason": f"daily continuation limit reached ({len(nudges)}/{limit})",
                "nudge_epochs": nudges,
            }
        )
        _write_watchdog_state(task_dir, state)
        return {
            "action": "blocked",
            "reason": state["blocked_reason"],
            "notify": True,
        }

    question, candidate, question_error = _terminal_choice(pane_text, next_item)
    if question is not None:
        if question_error:
            state.update({"armed": False, "blocked_reason": question_error})
            _write_watchdog_state(task_dir, state)
            return {
                "action": "blocked",
                "reason": question_error,
                "notify": True,
                "question": question,
            }
        if candidate is None:  # Defensive: every non-error menu has one candidate.
            return {"action": "blocked", "reason": "missing menu answer", "notify": True}
        keys = _conversation_terminal_answer_keys(
            question, [str(candidate.get("id"))], submit=True
        )
        if not keys:
            state.update(
                {
                    "armed": False,
                    "blocked_reason": "could not encode the selected answer",
                }
            )
            _write_watchdog_state(task_dir, state)
            return {
                "action": "blocked",
                "reason": state["blocked_reason"],
                "notify": True,
            }
        return {
            "action": "answer",
            "keys": keys,
            "answer": str(candidate.get("label") or ""),
            "question": question,
        }

    # A normal prompt can safely receive a binding continuation instruction.
    # Only the recent tail is screened so an old mention of deployment in a
    # long transcript does not pin an unrelated task forever.
    recent = "\n".join((pane_text or "").splitlines()[-16:])
    if _HIGH_IMPACT_RE.search(recent):
        state.update(
            {
                "armed": False,
                "blocked_reason": "idle output mentions a high-impact boundary",
            }
        )
        _write_watchdog_state(task_dir, state)
        return {
            "action": "blocked",
            "reason": state["blocked_reason"],
            "notify": True,
        }
    return {"action": "nudge", "prompt": CONTINUE_PROMPT}


def record_action(
    task_dir: Path,
    *,
    action: str,
    ok: bool,
    error: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Persist a continuation, allowing one retry after a transport failure."""
    current = time.time() if now is None else float(now)
    state = read_watchdog_state(task_dir)
    if ok:
        nudges = _recent_nudges(state, current)
        nudges.append(current)
        state.update(
            {
                "armed": False,
                "idle_since_epoch": 0.0,
                "nudge_epochs": nudges,
                "last_action": action,
                "last_action_epoch": current,
                "last_error": "",
                "blocked_reason": "",
                "consecutive_failures": 0,
            }
        )
    else:
        failures = int(state.get("consecutive_failures") or 0) + 1
        blocked = failures >= MAX_CONSECUTIVE_FAILURES
        # A single transient failure gets one retry after a fresh grace period.
        # Persistent relay/tmux failure must not become an unbounded paste loop.
        state.update(
            {
                "armed": not blocked,
                "idle_since_epoch": current,
                "last_action": action,
                "last_attempt_epoch": current,
                "last_error": error or "continuation failed",
                "consecutive_failures": failures,
                "blocked_reason": (
                    f"continuation transport failed {failures} times"
                    if blocked
                    else ""
                ),
            }
        )
    _write_watchdog_state(task_dir, state)
    return state
