"""The carve breakup bindings still exist on the native module.

Their host_io wrappers went with the Python carve (layered damage phase 4,
Task 1); the bindings themselves, and this test, go with the native carve
(Task 2)."""
import pytest


def test_native_module_exposes_both_bindings():
    h = pytest.importorskip("_dauntless_host")
    assert callable(getattr(h, "hull_split_detached", None))
    assert callable(getattr(h, "hull_carve_capsule", None))
