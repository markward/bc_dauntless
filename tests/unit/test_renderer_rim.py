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


def test_set_rim_strength_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_rim_strength(7, 0.55)
    fake.set_rim_strength.assert_called_once_with(7, 0.55)


def test_rim_strength_uses_specular_coef_when_authored():
    """loadspacehelper forwards the hardpoint stats' 'SpecularCoef' via
    SetSpecularKs; the rim intensity must read it back."""
    import App
    from engine.host_loop import _rim_strength_for
    ship = App.ShipClass_Create()
    ship.SetSpecularKs(0.55)
    assert _rim_strength_for(ship) == 0.55


def test_rim_strength_defaults_when_no_specular_coef():
    import App
    from engine.host_loop import _rim_strength_for
    ship = App.ShipClass_Create()
    assert _rim_strength_for(ship) == renderer.DEFAULT_RIM_STRENGTH
