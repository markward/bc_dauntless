"""host_io.reload_bridge_panels: developer reload of Lottie bridge panels."""
import types

from engine import host_io


def test_reload_bridge_panels_is_a_noop_without_the_binding(monkeypatch):
    monkeypatch.setattr(host_io, "_h", types.SimpleNamespace())
    assert host_io.reload_bridge_panels() is None


def test_reload_bridge_panels_calls_the_binding(monkeypatch):
    calls = []
    monkeypatch.setattr(
        host_io, "_h", types.SimpleNamespace(reload_bridge_panels=lambda: calls.append(1)))
    host_io.reload_bridge_panels()
    assert calls == [1]
