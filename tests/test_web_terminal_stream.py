import os

from loom.web import _TerminalStreamRegistry


def test_terminal_stream_routes_input_to_registered_pty() -> None:
    read_fd, write_fd = os.pipe()
    registry = _TerminalStreamRegistry()
    stream_id = registry.register(write_fd)
    try:
        ok, error = registry.write(stream_id, "\x1b[?1;2c")
        assert ok is True
        assert error == ""
        assert os.read(read_fd, 8) == b"\x1b[?1;2c"

        registry.unregister(stream_id, write_fd)
        ok, error = registry.write(stream_id, "x")
        assert ok is False
        assert error == "terminal stream is not active"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_terminal_stream_rejects_invalid_id_and_large_input() -> None:
    read_fd, write_fd = os.pipe()
    registry = _TerminalStreamRegistry()
    stream_id = registry.register(write_fd)
    try:
        assert registry.write("not-a-stream", "x") == (
            False,
            "invalid terminal stream",
        )
        assert registry.write(stream_id, "x" * (64 * 1024 + 1)) == (
            False,
            "terminal input too large",
        )
    finally:
        registry.unregister(stream_id, write_fd)
        os.close(read_fd)
        os.close(write_fd)
