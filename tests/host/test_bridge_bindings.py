"""Smoke tests for the bridge-pass C++ bindings. These don't validate
rendering correctness — that's covered by the live visual verify in the
plan's final task — but they confirm the bindings exist with the right
shapes so a missing-attribute error in the host loop fails fast."""
import pytest


@pytest.fixture
def host_module():
    """The compiled _dauntless_host module; xfail-cleanly if the build
    is stale and the bindings haven't been refreshed."""
    pytest.importorskip("_dauntless_host")
    import _dauntless_host as h
    return h


def test_create_bridge_instance_binding_exists(host_module):
    assert hasattr(host_module, "create_bridge_instance")


def test_set_bridge_camera_binding_exists(host_module):
    assert hasattr(host_module, "set_bridge_camera")


def test_bridge_pass_set_enabled_binding_exists(host_module):
    assert hasattr(host_module, "bridge_pass_set_enabled")


def test_bridge_pass_set_enabled_accepts_bool_without_init(host_module):
    """bridge_pass_set_enabled must be safe to call before init() —
    it only mutates a global flag; no GL state is touched until frame()."""
    host_module.bridge_pass_set_enabled(False)
    host_module.bridge_pass_set_enabled(True)
    host_module.bridge_pass_set_enabled(False)  # leave disabled


def test_consume_mouse_delta_binding_exists(host_module):
    assert hasattr(host_module, "consume_mouse_delta")


def test_set_cursor_locked_binding_exists(host_module):
    assert hasattr(host_module, "set_cursor_locked")
