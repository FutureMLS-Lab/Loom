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
DEFAULT_ACK_SECONDS = 45.0
DEFAULT_MAX_NUDGES = 0
WINDOW_SECONDS = 24 * 60 * 60
MAX_CONTINUATION_ATTEMPTS = 2

CONTINUE_PROMPT = """Loom watchdog: this pane is idle, but PLAN.md still has \
unchecked work. Continue the accepted PLAN now. Resolve routine, reversible \
choices yourself with best judgment instead of asking again, and update PLAN.md \
after each milestone. Before retrying infrastructure, inspect durable state and \
existing jobs so you do not duplicate work. Stop and ask the human only if the \
next step requires a production/live change, a destructive or irreversible \
action, an external communication/submission/push, credentials or approval, or \
a materially underdetermined research fork. If the task is actually complete, \
check off the plan and give the final summary."""

_PLAN_REVISION_RE = re.compile(
    r"<!--\s*loom:plan-revision=([a-z0-9._-]+)\s*-->", re.IGNORECASE
)
_ACTIVE_HEADING_RE = re.compile(r"(?im)^##\s+active milestone\s*$")
_NEXT_H2_RE = re.compile(r"(?m)^##\s+")
_OPEN_PLAN_ITEM_RE = re.compile(r"(?m)^\s*[-*]\s+\[\s\]\s+(.+?)\s*$")
_MILESTONE_RE = re.compile(r"^\[([a-z0-9][a-z0-9._-]{0,63})\]\s+(.+)$", re.I)
_QUESTION_MARKER_RE = re.compile(r"\bQuestion\s+\d+\s+of\s+\d+\b", re.I)
_QUESTION_FOOTER_RE = re.compile(
    r"(?:Space\s+select|Enter\s+(?:next|submit)|Esc\s+to\s+skip)", re.I
)
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


def watchdog_ack_seconds() -> float:
    """How long a sent continuation may wait for a working acknowledgement."""
    value = _bounded_env(
        "LOOM_AGENT_WATCHDOG_ACK_SECONDS",
        DEFAULT_ACK_SECONDS,
        minimum=8.0,
        maximum=300.0,
    )
    return value if value > 0 else DEFAULT_ACK_SECONDS


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


def _plan_contract(task_dir: Path) -> tuple[dict[str, str] | None, str]:
    """Read the one explicit milestone that authorizes unattended work."""
    path = task_dir / "PLAN.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, "PLAN.md is missing"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    revisions = _PLAN_REVISION_RE.findall(text)
    if len(revisions) != 1:
        return None, "PLAN.md must declare exactly one loom:plan-revision"
    headings = list(_ACTIVE_HEADING_RE.finditer(text))
    if len(headings) != 1:
        return None, "PLAN.md must contain exactly one Active milestone section"
    section_start = headings[0].end()
    next_heading = _NEXT_H2_RE.search(text, section_start)
    section = text[section_start : next_heading.start() if next_heading else len(text)]
    items = [match.group(1).strip() for match in _OPEN_PLAN_ITEM_RE.finditer(section)]
    items = [item for item in items if item and not item.startswith("<!--")]
    if len(items) != 1:
        return None, "Active milestone must contain exactly one unchecked item"
    milestone_match = _MILESTONE_RE.match(items[0])
    if milestone_match is None:
        return None, "Active milestone item must start with a stable [milestone-id]"
    return (
        {
            "revision": revisions[0],
            "milestone_id": milestone_match.group(1),
            "text": milestone_match.group(2).strip(),
            "plan_sha256": digest,
        },
        "",
    )


def arm_watchdog(task_dir: Path, *, target: str, now: float | None = None) -> None:
    """Persist that this pane was observed doing work and may later be nudged."""
    if not watchdog_enabled():
        return
    current = time.time() if now is None else float(now)
    state = read_watchdog_state(task_dir)
    contract, contract_error = _plan_contract(task_dir)
    if contract is None:
        state.update(
            {
                "armed": False,
                "awaiting_progress": False,
                "target": target,
                "blocked_reason": contract_error,
            }
        )
        _write_watchdog_state(task_dir, state)
        return
    already_acknowledged = (
        state.get("last_acknowledged_revision") == contract["revision"]
        and state.get("last_acknowledged_milestone_id")
        == contract["milestone_id"]
    )
    if already_acknowledged:
        state.update(
            {
                "armed": False,
                "target": target,
                "blocked_reason": (
                    "active milestone was already acknowledged; advance the "
                    "PLAN revision before another automatic continuation"
                ),
            }
        )
        _write_watchdog_state(task_dir, state)
        return
    if (
        state.get("armed")
        and state.get("target") == target
        and not float(state.get("idle_since_epoch") or 0.0)
        and state.get("plan_sha256") == contract["plan_sha256"]
    ):
        return
    state.update(
        {
            "armed": True,
            "target": target,
            "observed_working_epoch": current,
            "idle_since_epoch": 0.0,
            "plan_sha256": contract["plan_sha256"],
            "plan_revision": contract["revision"],
            "active_milestone_id": contract["milestone_id"],
            "active_milestone_text": contract["text"],
            "blocked_reason": "",
            "continuation_attempts": 0,
            "last_error": "",
        }
    )
    _write_watchdog_state(task_dir, state)


def acknowledge_progress(
    task_dir: Path, *, target: str, now: float | None = None
) -> dict[str, Any] | None:
    """Commit a sent continuation only after the pane is observed working."""
    current = time.time() if now is None else float(now)
    state = read_watchdog_state(task_dir)
    if not state.get("awaiting_progress") or state.get("target") != target:
        return None
    nudges = _recent_nudges(state, current)
    nudges.append(current)
    event = {
        "action": str(state.get("pending_action") or "nudge"),
        "answer": str(state.get("pending_answer") or ""),
        "attempts": int(state.get("continuation_attempts") or 1),
    }
    question_id = str(state.get("pending_question_id") or "")
    state.update(
        {
            "armed": False,
            "awaiting_progress": False,
            "idle_since_epoch": 0.0,
            "nudge_epochs": nudges,
            "continuation_attempts": 0,
            "last_action": event["action"],
            "last_action_epoch": current,
            "last_acknowledged_epoch": current,
            "last_acknowledged_revision": str(state.get("plan_revision") or ""),
            "last_acknowledged_milestone_id": str(
                state.get("active_milestone_id") or ""
            ),
            "last_error": "",
            "blocked_reason": "",
            "pending_action": "",
            "pending_answer": "",
            "pending_question_id": "",
            "ack_deadline_epoch": 0.0,
        }
    )
    if question_id:
        state["last_answered_question_id"] = question_id
    _write_watchdog_state(task_dir, state)
    return event


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


def _current_terminal_question(text: str) -> dict[str, Any] | None:
    """Parse only the bottom-most menu that is still at the live pane edge."""
    lines = (text or "").splitlines()
    markers = [index for index, line in enumerate(lines) if _QUESTION_MARKER_RE.search(line)]
    if not markers:
        return None
    live_lines = lines[markers[-1] :]
    footer_index = next(
        (
            index
            for index, line in enumerate(live_lines)
            if _QUESTION_FOOTER_RE.search(line)
        ),
        None,
    )
    if footer_index is None:
        return None
    # A resolved menu left in scrollback normally has answer/tool output below
    # it. Permit only the small model/status footer rendered by the live TUI.
    trailing = [line for line in live_lines[footer_index + 1 :] if line.strip()]
    if len(trailing) > 4:
        return None
    return _conversation_terminal_question("\n".join(live_lines))


def _terminal_choice(
    text: str,
    milestone_text: str,
    *,
    last_answered_question_id: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    question = _current_terminal_question(text)
    if question is None:
        return None, None, ""
    if str(question.get("id") or "") == last_answered_question_id:
        return question, None, "terminal question was already answered"
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
    plan_tokens = _choice_tokens(milestone_text)
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
        return question, None, "multiple answers match the active milestone"
    if not plan_matches:
        return (
            question,
            None,
            "question has no unique active-milestone-matched answer",
        )
    candidate = plan_matches[0]
    if recommended and recommended[0] is not candidate:
        return question, None, "recommended answer conflicts with the active milestone"
    impact_text = " ".join(
        (
            str(prompt.get("prompt") or ""),
            str(candidate.get("label") or ""),
            str(candidate.get("description") or ""),
        )
    )
    if _HIGH_IMPACT_RE.search(impact_text):
        return question, None, "milestone-matched answer crosses a high-impact boundary"
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
    if state.get("target") != target:
        return {"action": "none", "reason": "not armed"}
    contract, contract_error = _plan_contract(task_dir)
    if contract is None:
        if (
            not state.get("armed")
            and not state.get("awaiting_progress")
            and state.get("blocked_reason") == contract_error
        ):
            return {"action": "none", "reason": "blocked"}
        state.update(
            {
                "armed": False,
                "awaiting_progress": False,
                "blocked_reason": contract_error,
            }
        )
        _write_watchdog_state(task_dir, state)
        return {"action": "blocked", "reason": contract_error, "notify": True}
    contract_changed = any(
        (
            state.get("plan_sha256") != contract["plan_sha256"],
            state.get("plan_revision") != contract["revision"],
            state.get("active_milestone_id") != contract["milestone_id"],
        )
    )
    if contract_changed:
        reason = "active milestone changed without an observed working state"
        if (
            not state.get("armed")
            and not state.get("awaiting_progress")
            and state.get("blocked_reason") == reason
        ):
            return {"action": "none", "reason": "blocked"}
        state.update(
            {
                "armed": False,
                "awaiting_progress": False,
                "blocked_reason": reason,
            }
        )
        _write_watchdog_state(task_dir, state)
        return {"action": "blocked", "reason": reason, "notify": True}

    retry = False
    if state.get("awaiting_progress"):
        deadline = float(state.get("ack_deadline_epoch") or 0.0)
        if current < deadline:
            return {"action": "none", "reason": "awaiting working acknowledgement"}
        attempts = int(state.get("continuation_attempts") or 0)
        if attempts >= MAX_CONTINUATION_ATTEMPTS:
            reason = f"agent did not acknowledge continuation after {attempts} attempts"
            state.update(
                {
                    "armed": False,
                    "awaiting_progress": False,
                    "blocked_reason": reason,
                }
            )
            _write_watchdog_state(task_dir, state)
            return {"action": "blocked", "reason": reason, "notify": True}
        retry = True
    else:
        if not state.get("armed"):
            return {"action": "none", "reason": "not armed"}
        idle_since = float(state.get("idle_since_epoch") or 0.0)
        if idle_since <= 0:
            state["idle_since_epoch"] = current
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

    question, candidate, question_error = _terminal_choice(
        pane_text,
        contract["text"],
        last_answered_question_id=str(
            state.get("last_answered_question_id") or ""
        ),
    )
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
            "question_id": str(question.get("id") or ""),
            "question": question,
            "retry": retry,
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
    prompt = (
        f"{CONTINUE_PROMPT}\n\n"
        f"Authorized active milestone [{contract['milestone_id']}] "
        f"(PLAN revision {contract['revision']}): {contract['text']}"
    )
    return {"action": "nudge", "prompt": prompt, "retry": retry}


def record_action(
    task_dir: Path,
    *,
    action: str,
    ok: bool,
    answer: str = "",
    question_id: str = "",
    error: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Persist a send attempt; success still requires a working acknowledgement."""
    current = time.time() if now is None else float(now)
    state = read_watchdog_state(task_dir)
    attempts = int(state.get("continuation_attempts") or 0) + 1
    if ok:
        state.update(
            {
                "armed": False,
                "awaiting_progress": True,
                "idle_since_epoch": 0.0,
                "continuation_attempts": attempts,
                "pending_action": action,
                "pending_answer": answer,
                "pending_question_id": question_id,
                "last_attempt_epoch": current,
                "ack_deadline_epoch": current + watchdog_ack_seconds(),
                "last_error": "",
                "blocked_reason": "",
            }
        )
    else:
        blocked = attempts >= MAX_CONTINUATION_ATTEMPTS
        # A single transient failure gets one retry after a fresh grace period.
        # Persistent relay/tmux failure must not become an unbounded paste loop.
        state.update(
            {
                "armed": not blocked,
                "awaiting_progress": False,
                "idle_since_epoch": current,
                "continuation_attempts": attempts,
                "pending_action": "",
                "pending_answer": "",
                "pending_question_id": "",
                "ack_deadline_epoch": 0.0,
                "last_attempt_epoch": current,
                "last_error": error or "continuation failed",
                "blocked_reason": (
                    f"continuation transport failed {attempts} times"
                    if blocked
                    else ""
                ),
            }
        )
    _write_watchdog_state(task_dir, state)
    return state
