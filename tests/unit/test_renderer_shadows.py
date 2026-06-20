"""engine.renderer shadows wrapper forwards to the host module."""
from unittest.mock import MagicMock
import engine.renderer as renderer


def test_set_shadows_enabled_forwards_true(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_shadows_enabled(True)
    fake.shadows_set_enabled.assert_called_once_with(True)


def test_set_shadows_enabled_forwards_false(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_shadows_enabled(False)
    fake.shadows_set_enabled.assert_called_once_with(False)
