"""engine.renderer.spawn_test_character wrapper: forwards to the host binding
when present, no-ops (returns None) when the .so lacks it (headless/stale)."""
from unittest.mock import MagicMock

import engine.renderer as renderer


def test_spawn_test_character_without_binding_returns_none(monkeypatch):
    # A host module that does NOT expose spawn_test_character (e.g. a stale .so
    # built before this binding existed) must make the wrapper no-op to None,
    # never raise — mirrors the getattr(_h, ...) guard used by other wrappers.
    class _NoBinding:
        pass

    monkeypatch.setattr(renderer, "_h", _NoBinding())
    assert renderer.spawn_test_character("x.nif") is None


def test_spawn_test_character_forwards_to_binding(monkeypatch):
    fake = MagicMock()
    fake.spawn_test_character.return_value = "iid-sentinel"
    monkeypatch.setattr(renderer, "_h", fake)

    result = renderer.spawn_test_character("body.nif")

    # The host owns placement now; the wrapper just forwards the nif path.
    fake.spawn_test_character.assert_called_once_with("body.nif")
    assert result == "iid-sentinel"
