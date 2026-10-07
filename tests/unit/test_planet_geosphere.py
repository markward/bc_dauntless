"""Planet geosphere opt-in (spec docs/superpowers/specs/2026-10-06-planet-geosphere-design.md §4.5)."""
from types import SimpleNamespace

from engine import host_loop, planet_geosphere


class _Renderer:
    def __init__(self):
        self.calls = []

    def load_model(self, path, search, texture_replacements=None, decals=None,
                   scale=1.0, geosphere=False):
        self.calls.append((path, geosphere))
        return 100 + len(self.calls)

    def model_aabb(self, handle):
        return (0.0, 0.0, 0.0), (90.0, 90.0, 90.0)


def _cache():
    return SimpleNamespace(nif_to_handle={}, nif_to_extent={}, nif_to_sphere_radius={})


def test_toggle_defaults_on():
    assert planet_geosphere.enabled() is True


def test_load_planet_model_requests_geosphere_when_enabled():
    r = _Renderer()
    host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=None)
    assert r.calls == [("/x/IcePlanet.NIF", True)]


def test_load_planet_model_requests_plain_when_disabled():
    planet_geosphere.set_enabled(False)
    r = _Renderer()
    host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=None)
    assert r.calls == [("/x/IcePlanet.NIF", False)]


def test_planet_model_cache_key_separates_geosphere():
    r, cache = _Renderer(), _cache()
    on = host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=cache)
    planet_geosphere.set_enabled(False)
    off = host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=cache)
    assert on[0] != off[0]
    planet_geosphere.set_enabled(True)
    again = host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=cache)
    assert again[0] == on[0]
    assert len(r.calls) == 2
