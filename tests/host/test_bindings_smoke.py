"""Smoke test: _open_stbc_host opens a hidden window and frames cleanly."""
import os


def test_module_imports():
    import _open_stbc_host
    for name in ("init", "shutdown", "should_close", "frame"):
        assert hasattr(_open_stbc_host, name)


def test_init_frame_shutdown_round_trip():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(640, 480, "test")
        assert _open_stbc_host.should_close() is False
        # Drive a few frames to verify buffer swaps + event poll work.
        for _ in range(3):
            _open_stbc_host.frame()
    finally:
        _open_stbc_host.shutdown()


def test_double_init_raises():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    import pytest
    _open_stbc_host.init(320, 240, "a")
    try:
        with pytest.raises(RuntimeError):
            _open_stbc_host.init(320, 240, "b")
    finally:
        _open_stbc_host.shutdown()
