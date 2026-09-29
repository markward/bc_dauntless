# tests/unit/test_flare_veil.py
from engine import dev_mode, host_loop
from engine.systems import profile as P


class _Renderer:
    def __init__(self, volumetric_enabled):
        self._volumetric_enabled = volumetric_enabled

    def volumetric_nebulae_enabled(self):
        return self._volumetric_enabled


def test_flares_take_the_star_transmittance_under_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(P, "star_transmittance", lambda obj: 0.2)
    r = _Renderer(volumetric_enabled=True)
    out = host_loop._veil_flares(
        r, [{"source_world_pos": (1.0, 2.0, 3.0), "elements": []}], object())
    assert out[0]["brightness"] == 0.2


def test_flares_untouched_without_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    r = _Renderer(volumetric_enabled=True)
    flares = [{"source_world_pos": (1.0, 2.0, 3.0), "elements": []}]
    assert host_loop._veil_flares(r, flares, object()) == flares
    assert "brightness" not in flares[0]


def test_flares_untouched_when_volumetric_nebulae_setting_is_off(monkeypatch):
    """Same gate as the nebula pass: a developer run with the setting off
    must not dim the flare while no haze is drawn."""
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(P, "star_transmittance", lambda obj: 0.2)
    r = _Renderer(volumetric_enabled=False)
    flares = [{"source_world_pos": (1.0, 2.0, 3.0), "elements": []}]
    assert host_loop._veil_flares(r, flares, object()) == flares
    assert "brightness" not in flares[0]
