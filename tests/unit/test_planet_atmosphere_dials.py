"""Atmosphere dial group (spec 2026-10-07 §7, plan deviation D4)."""
import types

import pytest

from engine.planets import atmosphere as atmo
from engine.planets import atmosphere_dials as dials


def _setup():
    pushes = []
    atmo.reload()
    atmo.record_live("a", "pinkgasplanet", "Albirea3", "Albirea 3", "x/PinkGasPlanet.nif")
    atmo.record_live("b", "pinkgasplanet", "Geble3", "Geble 3", "x/PinkGasPlanet.nif")
    atmo.record_live("c", "iceplanet", "Savoy2", "Savoy 2", "x/IcePlanet.nif")
    dials.set_target_fn(lambda: atmo.live()[0])
    dials.set_push_fn(lambda iid, a: pushes.append((iid, a)))
    return pushes


def test_current_reports_the_targets_entry():
    _setup()
    d = dials.current()
    assert d["thickness"] == 0.06 and d["density"] == 1.4
    assert d["intensity"] == pytest.approx(20.0)


def test_step_intensity_updates_and_clamps():
    pushes = _setup()
    dials.step("intensity", +1)
    assert all(a.intensity == pytest.approx(20.5) for _, a in pushes)
    assert atmo.resolve("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").intensity == pytest.approx(20.5)

    for _ in range(200):
        dials.step("intensity", +1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").intensity == pytest.approx(50.0)

    for _ in range(200):
        dials.step("intensity", -1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").intensity == pytest.approx(0.0)


def test_mie_is_the_eighth_dial():
    assert dials.DIAL_ORDER[7] == "mie"
    assert len(dials.DIAL_ORDER) == 8
    assert dials.STEPS["mie"] == pytest.approx(0.05)


def test_current_reports_mie():
    _setup()
    assert dials.current()["mie"] == pytest.approx(0.2)


def test_step_mie_updates_and_clamps():
    pushes = _setup()
    dials.step("mie", +1)
    assert all(a.mie == pytest.approx(0.25) for _, a in pushes)
    assert atmo.resolve("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").mie == pytest.approx(0.25)
    # Other fields survive a mie step (intensity included).
    assert all(a.intensity == pytest.approx(20.0) for _, a in pushes)

    for _ in range(200):
        dials.step("mie", +1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").mie == pytest.approx(4.0)

    for _ in range(200):
        dials.step("mie", -1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").mie == pytest.approx(0.0)


def test_other_dials_preserve_mie():
    pushes = _setup()
    dials.step("mie", +1)
    dials.step("density", +1)
    assert pushes[-1][1].mie == pytest.approx(0.25)


def test_step_updates_every_planet_sharing_the_key_only():
    pushes = _setup()
    dials.step("thickness", +1)
    assert sorted(i for i, _ in pushes) == ["a", "b"]
    assert all(a.thickness == pytest.approx(0.065) for _, a in pushes)
    assert atmo.resolve("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif").thickness == pytest.approx(0.065)


def test_step_clamps_to_spec_ranges():
    _setup()
    for _ in range(100):
        dials.step("thickness", -1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").thickness > 0.0
    for _ in range(100):
        dials.step("density", +1)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").density == 4.0


def test_reload_drops_overrides():
    _setup()
    dials.step("thickness", +1)
    atmo.reload()
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif").thickness == 0.06


def test_no_target_is_a_noop(capsys):
    pushes = _setup()
    dials.set_target_fn(lambda: None)
    dials.step("thickness", +1)
    assert pushes == []
    assert "no atmospheric planet nearby" in capsys.readouterr().err


def test_register_adds_the_group():
    from engine import dev_dial_groups
    dev_dial_groups.reset()
    dials.register()
    assert "atmosphere" in dev_dial_groups.groups()


# ── _nearest_live_planet (host_loop) ────────────────────────────────────────


def _loc(x, y, z):
    return types.SimpleNamespace(x=x, y=y, z=z)


class _FakePlanet:
    """A plain hashable stand-in -- types.SimpleNamespace defines __eq__ and
    is therefore unhashable, and planet_instances is keyed on the planet
    object."""

    def __init__(self, x, y, z, radius):
        self._loc = _loc(x, y, z)
        self._radius = radius

    def GetWorldLocation(self):
        return self._loc

    def GetRadius(self):
        return self._radius


def test_nearest_live_planet_picks_surface_distance_not_centre_distance(monkeypatch):
    from engine import host_loop
    from engine.appc import sensor_contacts
    from engine.systems import frames

    atmo.reload()
    atmo.record_live("near", "iceplanet", "S", "Near", "x/IcePlanet.nif")
    atmo.record_live("far", "iceplanet", "S", "Far", "x/IcePlanet.nif")

    player = types.SimpleNamespace(GetWorldLocation=lambda: _loc(0.0, 0.0, 0.0))
    # far_planet's CENTRE is closer (5 < 10) but its surface is farther
    # (5 - 0.5 = 4.5) than near_planet's (10 - 9 = 1.0) -- picking by centre
    # distance alone would wrongly choose far_planet.
    near_planet = _FakePlanet(10.0, 0.0, 0.0, 9.0)
    far_planet = _FakePlanet(5.0, 0.0, 0.0, 0.5)
    session = types.SimpleNamespace(
        planet_instances={near_planet: "near", far_planet: "far"},
        celestial_instances={}, celestial_placed={})

    monkeypatch.setattr(sensor_contacts, "current_player", lambda: player)
    monkeypatch.setattr(frames, "viewing_set", lambda: "VIEW")
    monkeypatch.setattr(frames, "containing_set", lambda obj: "VIEW")
    monkeypatch.setattr(frames, "in_view", lambda view, pSet, x, y, z: (x, y, z))

    result = host_loop._nearest_live_planet(session)
    assert result is not None and result.iid == "near"


def test_nearest_live_planet_returns_none_with_no_live_planets(monkeypatch):
    from engine import host_loop
    from engine.appc import sensor_contacts
    from engine.systems import frames

    atmo.reload()
    player = types.SimpleNamespace(GetWorldLocation=lambda: _loc(0.0, 0.0, 0.0))
    session = types.SimpleNamespace(
        planet_instances={}, celestial_instances={}, celestial_placed={})

    monkeypatch.setattr(sensor_contacts, "current_player", lambda: player)
    monkeypatch.setattr(frames, "viewing_set", lambda: "VIEW")
    monkeypatch.setattr(frames, "containing_set", lambda obj: "VIEW")
    monkeypatch.setattr(frames, "in_view", lambda view, pSet, x, y, z: (x, y, z))

    assert host_loop._nearest_live_planet(session) is None


# ── reload re-push (final-review fix 2) ─────────────────────────────────────


def test_repush_live_restores_catalogue_values_after_a_dial_override():
    """A dial override was pushed to the live planets; reload() drops it from
    the catalogue overlay, and repush_live() must push the catalogue values
    back to EVERY live planet (airless ones as None) so the renderer and the
    dials agree again."""
    pushes = _setup()
    atmo.record_live("m", "moon", "Savoy2", "Moon", "x/moon.nif")
    dials.step("thickness", +1)
    assert all(a.thickness == pytest.approx(0.065) for _, a in pushes)
    pushes.clear()

    atmo.reload()
    dials.repush_live()

    got = dict(pushes)
    assert sorted(got) == ["a", "b", "c", "m"]
    assert got["a"].thickness == 0.06 and got["b"].thickness == 0.06
    assert got["c"].thickness == 0.02
    assert got["m"] is None
    assert dials.current()["thickness"] == 0.06


# ── _nearest_live_planet skips airless entries (final-review fix 3) ─────────


def test_nearest_live_planet_skips_an_airless_moon(monkeypatch):
    from engine import host_loop
    from engine.appc import sensor_contacts
    from engine.systems import frames

    atmo.reload()
    atmo.record_live("parent", "pinkgasplanet", "S", "Parent", "x/PinkGasPlanet.nif")
    atmo.record_live("moon", "moon", "S", "Moon", "x/moon.nif")

    player = types.SimpleNamespace(GetWorldLocation=lambda: _loc(0.0, 0.0, 0.0))
    moon = _FakePlanet(3.0, 0.0, 0.0, 1.0)        # surface 2 GU away
    parent = _FakePlanet(100.0, 0.0, 0.0, 50.0)   # surface 50 GU away
    session = types.SimpleNamespace(
        planet_instances={moon: "moon", parent: "parent"},
        celestial_instances={}, celestial_placed={})

    monkeypatch.setattr(sensor_contacts, "current_player", lambda: player)
    monkeypatch.setattr(frames, "viewing_set", lambda: "VIEW")
    monkeypatch.setattr(frames, "containing_set", lambda obj: "VIEW")
    monkeypatch.setattr(frames, "in_view", lambda view, pSet, x, y, z: (x, y, z))

    result = host_loop._nearest_live_planet(session)
    assert result is not None and result.iid == "parent"
