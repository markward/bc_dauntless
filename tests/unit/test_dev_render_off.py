"""DAUNTLESS_DEV_RENDER_OFF: render features switched off at boot, so a perf
A/B run needs nobody at the Developer Options menu (perf-register.md P-1)."""
import pytest

from engine import dev_render_off as dro
from engine import planet_atmosphere, planet_geosphere, planet_surface
from engine.systems import shuttle_service


class _FakeRenderer:
    """Records every setter call, by name, with its argument."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if not (name.startswith("set_") or name.endswith("_set_enabled")):
            raise AttributeError(name)
        return lambda value: self.calls.append((name, value))


@pytest.fixture(autouse=True)
def _restore_planet_flags():
    saved = (planet_geosphere.enabled(), planet_atmosphere.enabled(),
             planet_surface.enabled())
    yield
    planet_geosphere.set_enabled(saved[0])
    planet_atmosphere.set_enabled(saved[1])
    planet_surface.set_enabled(saved[2])


@pytest.fixture(autouse=True)
def _restore_shuttle_service():
    saved = shuttle_service.enabled()
    yield
    shuttle_service.set_enabled(saved)


def test_nothing_is_off_without_the_variable():
    assert dro.from_env({}, developer=True) == []


def test_nothing_is_off_without_developer_mode():
    """A dev-only switch: a stray variable must not degrade a player's game."""
    env = {dro.ENV: "rock_puffs"}
    assert dro.from_env(env, developer=False) == []


def test_names_are_read_from_a_comma_list_in_order():
    env = {dro.ENV: " rock_puffs, volumetric_nebulae ,,"}
    assert dro.from_env(env, developer=True) == ["rock_puffs",
                                                 "volumetric_nebulae"]


def test_an_unknown_name_is_refused_naming_the_known_ones():
    """A typo must not silently measure the unchanged scene as an A/B."""
    with pytest.raises(ValueError) as exc:
        dro.from_env({dro.ENV: "rock_puff"}, developer=True)
    assert "rock_puff" in str(exc.value)
    assert "rock_puffs" in str(exc.value)


@pytest.mark.parametrize("name,setter,value", [
    ("volumetric_nebulae", "set_volumetric_nebulae_enabled", False),
    ("procedural_sky", "set_procedural_sky_enabled", False),
    ("rock_fields", "far_set_enabled", False),
    ("rock_puffs", "rock_puffs_set_enabled", False),
    ("rock_specks", "rock_specks_set_enabled", False),
    ("minor_rocks", "minors_set_enabled", False),
    ("modern_lens_flare", "set_hdr_lens_flare_enabled", False),
    ("shadows", "set_shadows_enabled", False),
    ("dust", "set_dust_enabled", False),
    ("dof", "set_dof_enabled", False),
    ("running_lights", "running_lights_set_enabled", False),
    ("msaa", "set_msaa_samples", 0),
])
def test_each_renderer_feature_calls_its_setter(name, setter, value):
    r = _FakeRenderer()
    dro.apply([name], r)
    assert r.calls == [(setter, value)]


@pytest.mark.parametrize("name,module", [
    ("planet_geosphere", planet_geosphere),
    ("planet_atmosphere", planet_atmosphere),
    ("planet_surface", planet_surface),
])
def test_each_planet_feature_clears_its_flag(name, module):
    module.set_enabled(True)
    r = _FakeRenderer()
    dro.apply([name], r)
    assert module.enabled() is False
    assert r.calls == []


def test_shuttle_service_is_switched_off_with_no_renderer_call():
    """Python state, not a render pass: the Tau Ceti shuttle service, for a
    with/without cost capture (docs/engine/home-stations.md)."""
    shuttle_service.set_enabled(True)
    r = _FakeRenderer()
    dro.apply(["shuttle_service"], r)
    assert shuttle_service.enabled() is False
    assert r.calls == []


def test_applying_twice_is_harmless():
    """Applied before the mission loads (planets read their flags at
    realisation) and again after the saved settings (which would otherwise
    switch MSAA, dust and the nebulae back on)."""
    r = _FakeRenderer()
    dro.apply(["msaa", "planet_surface"], r)
    dro.apply(["msaa", "planet_surface"], r)
    assert r.calls == [("set_msaa_samples", 0)] * 2
    assert planet_surface.enabled() is False


def test_every_known_feature_is_listed_once():
    names = dro.known()
    assert len(names) == len(set(names))
    assert "rock_puffs" in names and "msaa" in names
    assert "shuttle_service" in names
