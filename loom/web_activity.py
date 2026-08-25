"""Watching the panes: run monitors and the activity rings.

Carved out of web.py in the route split. _TaskMonitor pings OpenClaw
when a watched agent stops; AgentActivityWatcher powers the sidebar
rings (working / finished-unseen) for every task on the host.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import re

from loom.openclaw import OpenClawClient
from loom.rud_task import (
    DEFAULT_MONITOR_PATTERN,
    list_tasks,
    read_meta,
    read_task_monitor,
    task_root,
    write_task_monitor,
)
from loom.tmux_util import capture_pane
from loom.web_projects import WebProjectRegistry

# --- Per-task run monitor ---------------------------------------------------

_MONITOR_POLL_SECONDS = 4.0
_MONITOR_CAPTURE_LINES = 160
# After a stop is reported, ignore further stops for this long - a guard
# against the working indicator flickering off for a single poll mid-turn.
_MONITOR_FIRE_COOLDOWN = 10.0
# Only treat the agent as *really* stopped once the "working" indicator has been
# gone for this many consecutive polls (~12s). This filters the brief flickers
# and short mid-turn pauses that otherwise caused spurious "stopped" pings - we
# only notify OpenClaw when the agent has genuinely finished and is waiting for
# input (i.e. actually needs your attention).
_MONITOR_STOP_CONFIRM_POLLS = 3

# Interactive agent CLIs (Claude Code / Codex) show an interrupt hint while
# actively working. When it disappears, the agent has stopped and is waiting
# for input - that running -> stopped edge is what the monitor fires on.
_AGENT_WORKING_RE = re.compile(
    r"(?:esc\s+to\s+interrupt|ctrl\s*\+\s*c\s+to\s+stop)",
    re.IGNORECASE,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _TaskMonitor:
    """Background poller that watches whether the task's agent pane is working.

    Edge-triggered on the *running -> stopped* transition: when the agent was
    actively working and then stops (waiting for input), it emits an OpenClaw
    event. If the pane is already idle when monitoring is switched on, nothing
    fires until the agent runs and then stops again.
    """

    def __init__(
        self,
        manager: "TaskMonitorManager",
        project_root: Path,
        project_id: str,
        slug: str,
        pattern: str = "",
    ) -> None:
        self.manager = manager
        self.project_root = project_root
        self.project_id = project_id
        self.slug = slug
        self.pattern = pattern  # retained for API/JSON compat; not used to match
        self._stop = threading.Event()
        self._was_working = False
        self._idle_polls = 0
        self._initialized = False
        self._last_fire_ts = 0.0
        self.last_fired = ""
        self.last_match = ""
        self.thread = threading.Thread(
            target=self._loop, name=f"loom-monitor-{slug}", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_alive(self) -> bool:
        return self.thread.is_alive() and not self._stop.is_set()

    def _current_target(self) -> str:
        meta = read_meta(self.project_root, self.slug)
        if meta is None:
            return ""
        return (getattr(meta, "tmux_interview_target", "") or "").strip()

    def _loop(self) -> None:
        if self._stop.wait(_MONITOR_POLL_SECONDS):
            return
        while not self._stop.is_set():
            try:
                target = self._current_target()
                if target:
                    ok, text = capture_pane(target, _MONITOR_CAPTURE_LINES)
                    if ok:
                        working = bool(_AGENT_WORKING_RE.search(text or ""))
                        if not self._initialized:
                            # Baseline only - never fire on the first read, so
                            # enabling on an already-idle pane stays silent.
                            self._was_working = working
                            self._idle_polls = 0 if working else 1
                            self._initialized = True
                        elif working:
                            self._was_working = True
                            self._idle_polls = 0
                        else:
                            # Not working: only count it as a real stop once the
                            # indicator has stayed gone for several consecutive
                            # polls, so a one-off flicker or short mid-turn pause
                            # doesn't fire a spurious notification.
                            self._idle_polls += 1
                            if self._was_working and self._idle_polls >= _MONITOR_STOP_CONFIRM_POLLS:
                                self._was_working = False
                                self._fire(text or "")
            except Exception as exc:  # noqa: BLE001
                print(f"[monitor] {self.slug} loop error: {exc}", flush=True)
            if self._stop.wait(_MONITOR_POLL_SECONDS):
                break

    @staticmethod
    def _tail_snippet(text: str) -> str:
        lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
        # Carry a generous chunk of the final output so OpenClaw can actually
        # summarize what the agent just did, not just the last couple of lines.
        return "\n".join(lines[-60:]).strip()[-5000:]

    def _fire(self, pane_text: str) -> None:
        now = time.time()
        if now - self._last_fire_ts < _MONITOR_FIRE_COOLDOWN:
            return
        self._last_fire_ts = now
        self.last_fired = _iso_now()
        self.last_match = "stopped"
        snippet = self._tail_snippet(pane_text)
        print(f"[monitor] {self.slug} agent stopped -> openclaw", flush=True)
        try:
            self.manager.openclaw.emit(
                "agent-stopped",
                instruction=(
                    f"Loom: the agent in task {self.slug} just stopped and is "
                    f"waiting for input. Its recent terminal output is in "
                    f"data.tail below — summarize for me what it just did / "
                    f"finished, then I can reply to this message to continue it."
                ),
                project_root=self.project_root,
                task_slug=self.slug,
                data={"event": "agent-stopped", "tail": snippet},
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[monitor] {self.slug} emit error: {exc}", flush=True)
        try:
            write_task_monitor(
                self.project_root,
                self.slug,
                enabled=True,
                pattern=self.pattern,
                last_fired=self.last_fired,
                last_match=self.last_match,
            )
        except Exception:  # noqa: BLE001
            pass


class AgentActivityWatcher:
    """Watches every task's pane so the UI can show which ones just finished.

    Distinct from ``TaskMonitorManager``, which the user opts into per task to
    get an OpenClaw ping. This one is always on and purely visual: it answers
    "which agent stopped while I was looking elsewhere", which is the question
    a fleet of panes makes hard to answer by looking.

    Capturing a short tail from every agent pane costs ~65ms for thirty of
    them, so one poll for the whole host is cheaper than the per-task polling
    the UI would otherwise need.
    """

    POLL_SECONDS = 4.0
    RESCAN_SECONDS = 30.0
    # A short tail misses the working marker whenever the TUI floods the
    # pane with tool output for a dozen seconds - the ring then flashed a
    # false "finished" and cleared it on the next redraw. A deeper capture
    # plus a longer confirmation makes a finish mean a real stop (~32s of
    # sustained silence), at the cost of the blink arriving half a minute
    # after the agent stops.
    CAPTURE_LINES = 40
    IDLE_CONFIRM = 8

    def __init__(self, registry: WebProjectRegistry) -> None:
        self.registry = registry
        self._lock = threading.Lock()
        self._state: dict[tuple[str, str], dict[str, Any]] = {}
        self._targets: list[tuple[str, str, str]] = []
        self._targets_at = 0.0
        self._stop = threading.Event()
        self.thread = threading.Thread(
            target=self._loop, name="loom-activity", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _scan_targets(self) -> list[tuple[str, str, str]]:
        """(project_id, slug, tmux target) for every task with a pane."""
        out: list[tuple[str, str, str]] = []
        for project in self.registry.list_projects():
            pid, path = str(project.get("id") or ""), project.get("path")
            if not pid or not path:
                continue
            try:
                metas = list_tasks(Path(path))
            except Exception:  # noqa: BLE001
                continue
            for meta in metas:
                target = (getattr(meta, "tmux_interview_target", "") or "").strip()
                if target:
                    out.append((pid, meta.slug, target))
        return out

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = time.time()
                if now - self._targets_at > self.RESCAN_SECONDS:
                    self._targets = self._scan_targets()
                    self._targets_at = now
                live = set()
                for pid, slug, target in self._targets:
                    key = (pid, slug)
                    live.add(key)
                    ok, text = capture_pane(target, self.CAPTURE_LINES)
                    if not ok:
                        continue
                    working = bool(_AGENT_WORKING_RE.search(text or ""))
                    with self._lock:
                        entry = self._state.setdefault(
                            key, {"working": False, "idle_polls": 0, "finished_at": 0.0}
                        )
                        if working:
                            entry["working"] = True
                            entry["idle_polls"] = 0
                            # Working again supersedes an unread finish.
                            entry["finished_at"] = 0.0
                        else:
                            entry["idle_polls"] += 1
                            if entry["working"] and entry["idle_polls"] >= self.IDLE_CONFIRM:
                                entry["working"] = False
                                entry["finished_at"] = now
                with self._lock:
                    for key in [k for k in self._state if k not in live]:
                        # Keep an unread finish that a stop hook reported: the
                        # task may not be in the target list yet, and dropping
                        # it here would silently swallow the notification.
                        if self._state[key].get("finished_at"):
                            continue
                        self._state.pop(key, None)
            except Exception as exc:  # noqa: BLE001
                print(f"[activity] loop error: {exc}", flush=True)
            if self._stop.wait(self.POLL_SECONDS):
                break

    def snapshot(self) -> dict[str, Any]:
        """Which tasks are working, and which finished without being seen."""
        tasks: dict[str, Any] = {}
        projects: dict[str, dict[str, int]] = {}
        with self._lock:
            for (pid, slug), entry in self._state.items():
                finished = float(entry.get("finished_at") or 0)
                working = bool(entry.get("working"))
                tasks[f"{pid}/{slug}"] = {
                    "project": pid,
                    "slug": slug,
                    "working": working,
                    "finished_at": finished,
                }
                if working or finished:
                    agg = projects.setdefault(pid, {"working": 0, "finished": 0})
                    if working:
                        agg["working"] += 1
                    if finished:
                        agg["finished"] += 1
        return {"ok": True, "tasks": tasks, "projects": projects}

    def ack(self, project_id: str, slug: str) -> None:
        """Clear a task's finished flag once the user has looked at it."""
        with self._lock:
            entry = self._state.get((project_id, slug))
            if entry:
                entry["finished_at"] = 0.0

    def report_finished(self, cwd: str, task_id: str = "") -> tuple[str, str] | None:
        """Record a finish reported by the agent itself, via its stop hook.

        Prefer the task Loom stamped on the pane. Fall back to matching the
        reported directory against the task directories, for a pane started
        outside Loom; longest match wins there, since a worktree sits inside a
        task directory and the deeper path is the more specific answer.
        """
        if task_id and "/" in task_id:
            pid, _, slug = task_id.partition("/")
            if pid and slug:
                self._mark_finished(pid, slug)
                return pid, slug
        try:
            where = Path(cwd).expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        best: tuple[int, str, str] | None = None
        for project in self.registry.list_projects():
            pid, path = str(project.get("id") or ""), project.get("path")
            if not pid or not path:
                continue
            try:
                metas = list_tasks(Path(path))
            except Exception:  # noqa: BLE001
                continue
            for meta in metas:
                root = task_root(Path(path), meta.slug)
                if where == root or root in where.parents:
                    depth = len(root.parts)
                    if best is None or depth > best[0]:
                        best = (depth, pid, meta.slug)
        if best is None:
            return None
        _, pid, slug = best
        self._mark_finished(pid, slug)
        return pid, slug

    def _mark_finished(self, project_id: str, slug: str) -> None:
        with self._lock:
            entry = self._state.setdefault(
                (project_id, slug), {"working": False, "idle_polls": 0, "finished_at": 0.0}
            )
            entry["working"] = False
            # The agent said it stopped, so the poller has nothing left to
            # confirm; without this it would re-announce the same finish.
            entry["idle_polls"] = self.IDLE_CONFIRM
            entry["finished_at"] = time.time()


class TaskMonitorManager:
    """Owns per-task monitor threads keyed by ``(project_id, slug)``."""

    def __init__(self, openclaw_client: OpenClawClient) -> None:
        self.openclaw = openclaw_client
        self._monitors: dict[tuple[str, str], _TaskMonitor] = {}
        self._lock = threading.Lock()

    def enable(
        self,
        project_root: Path,
        project_id: str,
        slug: str,
        pattern: str,
    ) -> dict[str, Any]:
        pattern = (pattern or "").strip() or DEFAULT_MONITOR_PATTERN
        key = (project_id, slug)
        with self._lock:
            existing = self._monitors.pop(key, None)
            if existing is not None:
                existing.stop()
            mon = _TaskMonitor(self, project_root, project_id, slug, pattern)
            self._monitors[key] = mon
        mon.start()
        cur = read_task_monitor(project_root, slug)
        write_task_monitor(project_root, slug, enabled=True, pattern=pattern)
        return {
            "enabled": True,
            "running": True,
            "pattern": pattern,
            "default_pattern": DEFAULT_MONITOR_PATTERN,
            "last_fired": mon.last_fired or cur.get("last_fired", ""),
            "last_match": mon.last_match or cur.get("last_match", ""),
        }

    def disable(self, project_root: Path, project_id: str, slug: str) -> dict[str, Any]:
        key = (project_id, slug)
        with self._lock:
            mon = self._monitors.pop(key, None)
        if mon is not None:
            mon.stop()
        cur = read_task_monitor(project_root, slug)
        write_task_monitor(
            project_root,
            slug,
            enabled=False,
            pattern=cur.get("pattern", ""),
        )
        return self.status(project_root, project_id, slug)

    def status(self, project_root: Path, project_id: str, slug: str) -> dict[str, Any]:
        key = (project_id, slug)
        with self._lock:
            mon = self._monitors.get(key)
        cfg = read_task_monitor(project_root, slug)
        # Lazily resume a persisted-on monitor that isn't running yet (e.g.
        # after a server restart) so the toggle survives restarts.
        if (mon is None or not mon.is_alive()) and cfg.get("enabled"):
            return self.enable(project_root, project_id, slug, cfg.get("pattern", ""))
        running = bool(mon and mon.is_alive())
        return {
            "enabled": running,
            "running": running,
            "pattern": (mon.pattern if mon else cfg.get("pattern", "")) or DEFAULT_MONITOR_PATTERN,
            "default_pattern": DEFAULT_MONITOR_PATTERN,
            "last_fired": (mon.last_fired if (mon and mon.last_fired) else cfg.get("last_fired", "")),
            "last_match": (mon.last_match if (mon and mon.last_match) else cfg.get("last_match", "")),
        }

    def resume_enabled(self, projects: list[tuple[str, Path]]) -> int:
        """Start monitors for every task whose monitor.json has enabled=true.

        Called once at startup so the per-task Notify toggle survives a server
        restart without the user re-opening each task. *projects* is a list of
        ``(project_id, project_root)`` pairs.
        """
        started = 0
        for project_id, root in projects:
            try:
                metas = list_tasks(root)
            except Exception:  # noqa: BLE001
                continue
            for meta in metas:
                try:
                    cfg = read_task_monitor(root, meta.slug)
                    if cfg.get("enabled"):
                        self.enable(root, project_id, meta.slug, cfg.get("pattern", ""))
                        started += 1
                except Exception:  # noqa: BLE001
                    continue
        return started


