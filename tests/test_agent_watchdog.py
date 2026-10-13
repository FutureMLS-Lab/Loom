from __future__ import annotations

from pathlib import Path

from loom.agent_watchdog import (
    arm_watchdog,
    idle_decision,
    read_watchdog_state,
    record_action,
)


def make_task(tmp_path: Path, plan: str | None = None) -> Path:
    task = tmp_path / ".RUD" / "long-run"
    task.mkdir(parents=True)
    (task / "PLAN.md").write_text(
        plan
        or "# Plan\n\n## Future to do\n- [ ] Run the next accepted experiment\n",
        encoding="utf-8",
    )
    return task


def enable(monkeypatch, *, limit: int = 6, idle: int = 30) -> None:
    monkeypatch.setenv("LOOM_AGENT_WATCHDOG_MAX_NUDGES", str(limit))
    monkeypatch.setenv("LOOM_AGENT_WATCHDOG_IDLE_SECONDS", str(idle))


def test_watchdog_is_opt_in(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LOOM_AGENT_WATCHDOG_MAX_NUDGES", raising=False)
    task = make_task(tmp_path)

    arm_watchdog(task, target="loom-x:0.0", now=10)

    assert read_watchdog_state(task) == {}
    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=100
    ) == {"action": "none", "reason": "disabled"}


def test_idle_working_edge_sends_one_plan_nudge(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    arm_watchdog(task, target="loom-x:0.0", now=10)

    first = idle_decision(task, target="loom-x:0.0", pane_text="idle", now=20)
    ready = idle_decision(task, target="loom-x:0.0", pane_text="idle", now=50)

    assert first == {"action": "none", "reason": "idle grace period"}
    assert ready["action"] == "nudge"
    assert "Continue the accepted PLAN" in ready["prompt"]
    state = record_action(task, action="nudge", ok=True, now=50)
    assert state["armed"] is False
    assert state["nudge_epochs"] == [50.0]
    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=100
    ) == {"action": "none", "reason": "not armed"}


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


def test_plan_without_unchecked_work_never_arms(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, "# Plan\n- [x] Everything is finished\n")

    arm_watchdog(task, target="loom-x:0.0", now=10)

    assert read_watchdog_state(task) == {}


def test_unique_recommended_terminal_choice_is_encoded(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    pane = """
Question 1 of 1
1. What should happen next?
  [ ] Wait for a human
› [ ] Run the CPU preflight (Recommended)
Enter submit · Esc to skip
"""
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text=pane, now=20)

    decision = idle_decision(
        task, target="loom-x:0.0", pane_text=pane, now=50
    )

    assert decision["action"] == "answer"
    assert decision["answer"] == "Run the CPU preflight (Recommended)"
    # The terminal capture shows the recommended row already focused.
    assert decision["keys"] == ["Enter"]


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
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text=pane, now=20)

    decision = idle_decision(
        task, target="loom-x:0.0", pane_text=pane, now=50
    )

    assert decision["action"] == "blocked"
    assert decision["notify"] is True
    assert "no unique recommended or PLAN-matched" in decision["reason"]
    assert read_watchdog_state(task)["armed"] is False


def test_unique_next_plan_item_can_answer_a_menu_without_recommended(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path, "# Plan\n- [ ] Run W2 on the prepared CPU inputs\n")
    pane = """
Question 1 of 1
1. Which matrix cell should run next?
› [ ] W2
  [ ] H3
  [ ] H4
  [ ] H5
Enter submit · Esc to skip
"""
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text=pane, now=20)

    decision = idle_decision(
        task, target="loom-x:0.0", pane_text=pane, now=50
    )

    assert decision["action"] == "answer"
    assert decision["answer"] == "W2"
    assert decision["keys"] == ["Enter"]


def test_recommended_production_action_still_fails_closed(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    pane = """
Question 1 of 1
1. Should I deploy this to production?
› [ ] Deploy now (Recommended)
  [ ] Wait
Enter submit · Esc to skip
"""
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text=pane, now=20)

    decision = idle_decision(
        task, target="loom-x:0.0", pane_text=pane, now=50
    )

    assert decision["action"] == "blocked"
    assert "high-impact boundary" in decision["reason"]


def test_local_development_deploy_is_not_mistaken_for_production(
    tmp_path, monkeypatch
) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    pane = """
Question 1 of 1
1. Which reversible local step should run?
› [ ] Deploy the local test stack (Recommended)
  [ ] Wait
Enter submit · Esc to skip
"""
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text=pane, now=20)

    decision = idle_decision(
        task, target="loom-x:0.0", pane_text=pane, now=50
    )

    assert decision["action"] == "answer"
    assert decision["answer"] == "Deploy the local test stack (Recommended)"


def test_daily_quota_survives_another_working_edge(tmp_path, monkeypatch) -> None:
    enable(monkeypatch, limit=1)
    task = make_task(tmp_path)
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text="idle", now=20)
    record_action(task, action="nudge", ok=True, now=50)
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
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text="idle", now=20)
    record_action(task, action="nudge", ok=False, error="tmux unavailable", now=50)

    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=55
    ) == {"action": "none", "reason": "idle grace period"}
    assert read_watchdog_state(task).get("nudge_epochs", []) == []


def test_two_failed_sends_fail_closed(tmp_path, monkeypatch) -> None:
    enable(monkeypatch)
    task = make_task(tmp_path)
    arm_watchdog(task, target="loom-x:0.0", now=10)
    idle_decision(task, target="loom-x:0.0", pane_text="idle", now=20)
    record_action(task, action="nudge", ok=False, error="relay stalled", now=50)

    retry = idle_decision(task, target="loom-x:0.0", pane_text="idle", now=80)
    assert retry["action"] == "nudge"
    state = record_action(
        task, action="nudge", ok=False, error="relay stalled", now=80
    )

    assert state["armed"] is False
    assert state["consecutive_failures"] == 2
    assert state["blocked_reason"] == "continuation transport failed 2 times"
    assert idle_decision(
        task, target="loom-x:0.0", pane_text="idle", now=200
    ) == {"action": "none", "reason": "not armed"}
