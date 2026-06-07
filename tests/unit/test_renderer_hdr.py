"""engine.renderer HDR wrapper forwards to the host module."""
from unittest.mock import MagicMock

import engine.renderer as renderer


def test_set_hdr_enabled_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_hdr_enabled(False)
    fake.hdr_set_enabled.assert_called_once_with(False)
