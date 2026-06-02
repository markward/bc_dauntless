"""Tests for engine.dev_mode — the Python facade over the --developer flag.

The facade reads _dauntless_host.developer_mode via getattr() so it is safe
against stale .so files (returns False) and so tests can monkey-patch the
attribute without touching the C++ side.
"""
import pytest


@pytest.fixture
def reset_dev_mode():
    """Reset the developer_mode attribute and registry around each test."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    original = getattr(_dauntless_host, "developer_mode", False)
    original_registry = dict(dev_mode._dev_keybindings)
    try:
        yield
    finally:
        _dauntless_host.developer_mode = original
        dev_mode._dev_keybindings.clear()
        dev_mode._dev_keybindings.update(original_registry)


def test_is_enabled_returns_false_when_attribute_false(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = False
    assert dev_mode.is_enabled() is False


def test_is_enabled_returns_true_when_attribute_true(reset_dev_mode):
    import _dauntless_host
    import engine.dev_mode as dev_mode
    _dauntless_host.developer_mode = True
    assert dev_mode.is_enabled() is True


def test_is_enabled_returns_false_when_attribute_missing(reset_dev_mode):
    """Defensive: stale .so without the attribute returns False, not raise."""
    import _dauntless_host
    import engine.dev_mode as dev_mode
    saved = _dauntless_host.developer_mode
    del _dauntless_host.developer_mode
    try:
        assert dev_mode.is_enabled() is False
    finally:
        _dauntless_host.developer_mode = saved
