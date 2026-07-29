from types import SimpleNamespace

import loom.tmux_util as tmux_util


def test_send_pane_text_delays_submit_until_after_paste(monkeypatch) -> None:
    events: list[tuple[str, object]] = []

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(
        tmux_util,
        "_exit_copy_mode_if_active",
        lambda _target, _env: events.append(("copy-mode", None)),
    )

    def fake_run(command, **_kwargs):
        events.append(("run", command))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tmux_util.subprocess, "run", fake_run)
    monkeypatch.setattr(
        tmux_util.time,
        "sleep",
        lambda seconds: events.append(("sleep", seconds)),
    )
    monkeypatch.setattr(
        tmux_util,
        "send_pane_key",
        lambda target, key: (events.append(("key", (target, key))) or (True, "")),
    )

    ok, error = tmux_util.send_pane_text("loom-cursor-task:0.0", "hello", submit=True)

    assert ok is True
    assert error == ""
    paste_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "run" and "paste-buffer" in event[1]
    )
    assert events[paste_index + 1] == ("sleep", 0.1)
    assert events[paste_index + 2] == (
        "key",
        ("loom-cursor-task:0.0", "Enter"),
    )


def test_ensure_tmux_sync_output_appends_missing_feature(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout="xterm*:clipboard:focus\nscreen*:title\n",
            stderr="",
        )

    monkeypatch.setattr(tmux_util.subprocess, "run", fake_run)

    tmux_util._ensure_tmux_sync_output({})

    assert commands[-1] == [
        "tmux",
        "set-option",
        "-as",
        "terminal-features",
        ",xterm*:sync",
    ]


def test_ensure_tmux_sync_output_does_not_duplicate_feature(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout="xterm*:clipboard:focus\nxterm*:sync\n",
            stderr="",
        )

    monkeypatch.setattr(tmux_util.subprocess, "run", fake_run)

    tmux_util._ensure_tmux_sync_output({})

    assert len(commands) == 1
