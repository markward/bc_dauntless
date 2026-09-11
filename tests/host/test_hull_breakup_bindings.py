"""The two bindings the breakup path needs exist on the native module and
degrade to no-ops through host_io when it is absent."""
import pytest

from engine import host_io


def test_host_io_split_is_empty_when_headless(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.hull_split_detached(1, 8) == []


def test_host_io_capsule_is_a_noop_when_headless(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    host_io.hull_carve_capsule(1, (0, 0, 0), (1, 0, 0), 0.6)   # must not raise


def test_native_module_exposes_both_bindings():
    h = pytest.importorskip("_dauntless_host")
    assert callable(getattr(h, "hull_split_detached", None))
    assert callable(getattr(h, "hull_carve_capsule", None))
