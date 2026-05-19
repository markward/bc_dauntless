"""Smoke test: _dauntless_host opens a hidden window and frames cleanly."""
import os


def test_module_imports():
    import _dauntless_host
    for name in ("init", "shutdown", "should_close", "frame"):
        assert hasattr(_dauntless_host, name)


def test_init_frame_shutdown_round_trip():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, "test")
        assert _dauntless_host.should_close() is False
        # Drive a few frames to verify buffer swaps + event poll work.
        for _ in range(3):
            _dauntless_host.frame()
    finally:
        _dauntless_host.shutdown()


def test_double_init_raises():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    import pytest
    _dauntless_host.init(320, 240, "a")
    try:
        with pytest.raises(RuntimeError):
            _dauntless_host.init(320, 240, "b")
    finally:
        _dauntless_host.shutdown()
