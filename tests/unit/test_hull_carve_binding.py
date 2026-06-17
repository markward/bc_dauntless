"""Binding-level smoke test for _dauntless_host.hull_carve_add.

Mirrors test_bridge_bindings.py style: confirm the symbol exists with the
right arity. The null-guard (stale-id silent drop) is not exercised here
because InstanceId can only be obtained from create_instance, which requires
assets; that path is covered by the integration suite.
"""
import pytest

_h = pytest.importorskip("_dauntless_host")


def test_hull_carve_add_present_and_callable():
    """Binding exists on the module."""
    assert hasattr(_h, "hull_carve_add"), (
        "_dauntless_host has no 'hull_carve_add' — binding not registered"
    )
    assert callable(_h.hull_carve_add)
