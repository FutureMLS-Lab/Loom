from __future__ import annotations

from pathlib import Path

from loom.agent_watchdog import (
    acknowledge_progress,
    arm_watchdog,
    idle_decision,
    read_watchdog_state,
    record_action,
)


def plan_for(
    text: str = "Run the next accepted experiment",
    *,
    milestone_id: str = "next-experiment",
    revision: str = "1",
) -> str:
    return (
        "# Plan\n"
        f"<!-- loom:plan-revision={revision} -->\n"
        "## Active milestone\n"
        f"- [ ] [{milestone_id}] {text}\n"
        "## Future to do\n"
        "- [ ] Later backlog item\n"
    )


def make_task(tmp_path: Path, plan: str | None = None) -> Path:
    task = tmp_path / ".RUD" / "long-run"
    task.mkdir(parents=True)
    (task / "PLAN.md").write_text(plan or plan_for(), encoding="utf-8")
    return task


def enable(
    monkeypatch, *, limit: int = 6, idle: int = 30, ack: int = 20
) -> None:
    monkeypatch.setenv("LOOM_AGENT_WATCHDOG_MAX_NUDGES", str(limit))
    monkeypatch.setenv("LOOM_AGENT_WATCHDOG_IDLE_SECONDS", str(idle))
    monkeypatch.setenv("LOOM_AGENT_WATCHDOG_ACK_SECONDS", str(ack))


def make_ready(task: Path, *, pane: str = "idle") -> dict:
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text=pane, now=20)
    return idle_decision(task, target="loom-x:0.0", pane_text=pane, now=50)


def test_watchdog_is_opt_in(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LOOM_AGENT_WATCHDOG_MAX_NUDGES", raising=False)
    task = make_task(tmp_path)

    arm_watchdog(task, target="loom-x:0.0", now=10)

    assert read_watchdog_state(task) == {}
    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=100
    ) == {"action": "none", "reason": "disabled"}


def test_send_counts_only_after_working_acknowledgement(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    ready = make_ready(task)

    assert ready["action"] == "nudge"
    assert "[next-experiment]" in ready["prompt"]
    state = record_action(task, action="nudge", ok=True, now=50)

    assert state["armed"] is False
    assert state["awaiting_progress"] is True
    assert state.get("nudge_epochs", []) == []
    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=60
    ) == {"action": "none", "reason": "awaiting working acknowledgement"}

    event = acknowledge_progress(task, target="loom-x:0.0", now=61)

    assert event == {"action": "nudge", "answer": "", "attempts": 1}
    assert read_watchdog_state(task)["nudge_epochs"] == [61.0]


def test_work_resets_a_partial_idle_grace_period(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text="idle", now=20)

    arm_watchdog(task, target="loom-x:0.0", now=30)

    assert read_watchdog_state(task)["idle_since_epoch"] == 0.0
    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=31
    ) == {"action": "none", "reason": "idle grace period"}


def test_legacy_plan_without_active_contract_never_arms(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, "# Plan\n- [ ] Run an old W2 item\n")

    arm_watchdog(task, target="loom-x:0.0", now=10)

    state = read_watchdog_state(task)
    assert state["armed"] is False
    assert "plan-revision" in state["blocked_reason"]


def test_plan_revision_change_while_idle_fails_closed(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text="idle", now=20)
    (task / "PLAN.md").write_text(plan_for("Run H3", revision="2"))

    decision = idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=50
    )

    assert decision["action"] == "blocked"
    assert "changed without an observed working state" in decision["reason"]


def test_recommended_choice_must_also_match_active_milestone(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, plan_for("Run the CPU preflight"))
    pane = """
Question 1 of 1
1. What should happen next?
  [ ] Wait for a human
› [ ] Run the CPU preflight (Recommended)
Enter submit · Esc to skip
"""

    decision = make_ready(task, pane=pane)

    assert decision["action"] == "answer"
    assert decision["answer"] == "Run the CPU preflight (Recommended)"
    assert decision["keys"] == ["Enter"]
    assert decision["question_id"]


def test_recommended_choice_cannot_override_active_milestone(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, plan_for("Run W2 on prepared inputs", milestone_id="w2"))
    pane = """
Question 1 of 1
1. Which benchmark should run?
› [ ] H3 (Recommended)
  [ ] W2
Enter submit · Esc to skip
"""

    decision = make_ready(task, pane=pane)

    assert decision["action"] == "blocked"
    assert "conflicts with the active milestone" in decision["reason"]


def test_ambiguous_terminal_choice_fails_closed(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    pane = """
Question 1 of 1
1. Which benchmark should run?
› [ ] W2
  [ ] H3
Enter submit · Esc to skip
"""

    decision = make_ready(task, pane=pane)

    assert decision["action"] == "blocked"
    assert decision["notify"] is True
    assert "no unique active-milestone-matched" in decision["reason"]
    assert read_watchdog_state(task)["armed"] is False


def test_unique_active_milestone_can_answer_without_recommended(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, plan_for("Run W2 on prepared CPU inputs", milestone_id="w2"))
    pane = """
Question 1 of 1
1. Which matrix cell should run next?
› [ ] W2
  [ ] H3
  [ ] H4
  [ ] H5
Enter submit · Esc to skip
"""

    decision = make_ready(task, pane=pane)

    assert decision["action"] == "answer"
    assert decision["answer"] == "W2"
    assert decision["keys"] == ["Enter"]


def test_milestone_matched_production_action_still_fails_closed(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, plan_for("Deploy now to production"))
    pane = """
Question 1 of 1
1. Should I deploy this to production?
› [ ] Deploy now (Recommended)
  [ ] Wait
Enter submit · Esc to skip
"""

    decision = make_ready(task, pane=pane)

    assert decision["action"] == "blocked"
    assert "high-impact boundary" in decision["reason"]


def test_local_development_deploy_is_not_mistaken_for_production(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, plan_for("Deploy the local test stack"))
    pane = """
Question 1 of 1
1. Which reversible local step should run?
› [ ] Deploy the local test stack (Recommended)
  [ ] Wait
Enter submit · Esc to skip
"""

    decision = make_ready(task, pane=pane)

    assert decision["action"] == "answer"
    assert decision["answer"] == "Deploy the local test stack (Recommended)"


def test_answered_menu_fingerprint_is_not_reused(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, plan_for("Run W2", milestone_id="w2"))
    pane = """
Question 1 of 1
1. Which cell?
› [ ] W2
  [ ] H3
Enter submit · Esc to skip
"""
    decision = make_ready(task, pane=pane)
    record_action(
        task,
        action="answer",
        answer=decision["answer"],
        question_id=decision["question_id"],
        ok=True,
        now=50,
    )
    acknowledge_progress(task, target="loom-x:0.0", now=55)
    (task / "PLAN.md").write_text(
        plan_for("Run W2", milestone_id="w2", revision="2")
    )
    arm_watchdog(task, target="loom-x:0.0", now=56)
    idle_decision(task, target="loom-x:0.0", pane_text=pane, now=60)

    repeated = idle_decision(
        task, target="loom-x:0.0", pane_text=pane, now=90
    )

    assert repeated["action"] == "blocked"
    assert repeated["reason"] == "terminal question was already answered"


def test_acknowledged_authority_cannot_be_nudged_twice(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    make_ready(task)
    record_action(task, action="nudge", ok=True, now=50)
    acknowledge_progress(task, target="loom-x:0.0", now=55)

    arm_watchdog(task, target="loom-x:0.0", now=56)

    state = read_watchdog_state(task)
    assert state["armed"] is False
    assert "already acknowledged" in state["blocked_reason"]


def test_resolved_menu_in_scrollback_is_not_answered(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, plan_for("Run W2", milestone_id="w2"))
    pane = """
Question 1 of 1
1. Which cell?
› [ ] W2
  [ ] H3
Enter submit · Esc to skip
The agent selected W2.
Tool call one finished.
Tool call two finished.
The experiment completed.
Here is the summary.
Ready for the next instruction.
"""

    decision = make_ready(task, pane=pane)

    assert decision["action"] == "nudge"


def test_daily_quota_counts_acknowledged_continuations(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch, limit=1)
    task = make_task(tmp_path)
    make_ready(task)
    record_action(task, action="nudge", ok=True, now=50)
    acknowledge_progress(task, target="loom-x:0.0", now=55)
    (task / "PLAN.md").write_text(
        plan_for("Run the following experiment", revision="2")
    )
    arm_watchdog(task, target="loom-x:0.0", now=60)
    idle_decision(task, target="loom-x:0.0", pane_text="idle", now=70)

    decision = idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=100
    )

    assert decision["action"] == "blocked"
    assert decision["reason"] == "daily continuation limit reached (1/1)"


def test_failed_send_waits_for_a_fresh_grace_period(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    make_ready(task)
    record_action(task, action="nudge", ok=False, error="tmux unavailable", now=50)

    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=55
    ) == {"action": "none", "reason": "idle grace period"}
    assert read_watchdog_state(task).get("nudge_epochs", []) == []


def test_two_failed_sends_fail_closed(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    make_ready(task)
    record_action(task, action="nudge", ok=False, error="relay stalled", now=50)

    retry = idle_decision(task, target="loom-x:0.0", pane_text="idle", now=80)
    assert retry["action"] == "nudge"
    state = record_action(
        task, action="nudge", ok=False, error="relay stalled", now=80
    )

    assert state["armed"] is False
    assert state["continuation_attempts"] == 2
    assert state["blocked_reason"] == "continuation transport failed 2 times"


def test_missing_working_ack_retries_once_then_fails_closed(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch, ack=20)
    task = make_task(tmp_path)
    make_ready(task)
    record_action(task, action="nudge", ok=True, now=50)

    retry = idle_decision(task, target="loom-x:0.0", pane_text="idle", now=70)
    assert retry["action"] == "nudge"
    assert retry["retry"] is True
    record_action(task, action="nudge", ok=True, now=70)

    blocked = idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=90
    )
    assert blocked["action"] == "blocked"
    assert blocked["reason"] == "agent did not acknowledge continuation after 2 attempts"
