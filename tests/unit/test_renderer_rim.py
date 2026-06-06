"""engine.renderer rim wrappers forward to the host module."""
from unittest.mock import MagicMock

import engine.renderer as renderer


def test_set_rim_enabled_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_rim_enabled(False)
    fake.rim_set_enabled.assert_called_once_with(False)


def test_set_rim_eligible_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_rim_eligible(7, True)
    fake.set_rim_eligible.assert_called_once_with(7, True)
