"""Planet surface detail wiring (spec 2026-10-08 §7)."""
import json
import zlib

import pytest

from engine import host_loop, planet_surface
from engine.planets import atmosphere as atmo
from engine.planets import surface


class _FakeR:
    def __init__(self):
        self.surface_calls = []
        self.calls = []

    def set_instance_surface(self, iid, params):
        self.surface_calls.append((iid, params))

    def set_instance_atmosphere(self, iid, params):
        self.calls.append((iid, params))


@pytest.fixture
def fake_r():
    return _FakeR()


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    path = tmp_path / "atmospheres.json"

    def write(obj):
        path.write_text(json.dumps(obj))
        atmo.reload()
    monkeypatch.setattr(atmo, "catalogue_path", lambda: path)
    yield write
    atmo.reload()


def test_toggle_defaults_on():
    assert planet_surface.enabled() is True


def test_apply_pushes_resolved_surface(fake_r, catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    host_loop._apply_planet_surface(fake_r, "iid1", "S", "N", "data/p.nif")
    assert fake_r.surface_calls == [
        ("iid1", (1, (0.0, 0.0, 0.0), False, 0.15, 1.0, 1.0, 1.0, zlib.crc32(b"p")))]
    assert [lp.iid for lp in surface.live()] == ["iid1"]


def test_apply_pushes_none_for_no_detail(fake_r, catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "none"}}})
    host_loop._apply_planet_surface(fake_r, "iid2", "S", "N", "data/p.nif")
    assert fake_r.surface_calls == [("iid2", None)]


def test_toggle_off_pushes_none(fake_r, catalogue, monkeypatch):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    planet_surface.set_enabled(False)
    host_loop._apply_planet_surface(fake_r, "iid1", "S", "N", "data/p.nif")
    assert fake_r.surface_calls == [("iid1", None)]


def test_every_realize_path_calls_the_surface_hook(monkeypatch, fake_r, catalogue):
    """_apply_planet_atmosphere is the single function called by every one of
    the three realize paths (mission load, realize_set_objects,
    _reconcile_celestial_instances) -- proving it always reaches the surface
    hook, with the caller's `source` forwarded, proves all three do without
    re-building each path's own fixture setup here."""
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    orig = host_loop._apply_planet_surface
    calls = []

    def spy(r_, iid, set_name, obj_name, nif_path, source="set"):
        calls.append((iid, source))
        return orig(r_, iid, set_name, obj_name, nif_path, source=source)
    monkeypatch.setattr(host_loop, "_apply_planet_surface", spy)
    host_loop._apply_planet_atmosphere(fake_r, "iid1", "S", "N", "data/p.nif")
    host_loop._apply_planet_atmosphere(fake_r, "iid2", "S", "N", "data/p.nif",
                                       source="celestial")
    assert calls == [("iid1", "set"), ("iid2", "celestial")]
