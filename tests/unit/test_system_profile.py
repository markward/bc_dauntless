import math
import pytest

from engine.systems import profile as P
from engine.systems.map import Region, SystemMap, from_json, to_json


def _p(*rows):
    return P.Profile(rows=[P.ProfileRow(*r) for r in rows])


def test_none_and_empty_are_clear():
    assert P.evaluate(None, 5000.0) == P.CLEAR
    assert P.evaluate(P.Profile(rows=[]), 5000.0) == P.CLEAR


def test_each_column_interpolates_independently():
    prof = _p((0.0, 0.0, 1.0, 0.0, 0.2, 0.0), (100.0, 1.0, 0.0, 0.5, 0.2, 1.0))
    s = P.evaluate(prof, 25.0)
    assert s.nebula == pytest.approx(0.25)
    assert s.dust == pytest.approx(0.75)
    assert s.sensors == pytest.approx(0.125)
    assert s.radiation == pytest.approx(0.2)
    assert s.asteroids == pytest.approx(0.25)


def test_exact_row_hit_returns_that_row():
    prof = _p((0.0, 0.0), (50.0, 0.4), (100.0, 1.0))
    assert P.evaluate(prof, 50.0).nebula == pytest.approx(0.4)


def test_last_row_persists_outward_forever():
    prof = _p((0.0, 0.0), (100.0, 0.05, 0.2))
    s = P.evaluate(prof, 1.0e9)
    assert (s.nebula, s.dust) == (pytest.approx(0.05), pytest.approx(0.2))


def test_clump_radius_is_anchor_plus_first_sphere_from_the_star():
    r = Region(set_name="V4", anchor_gu=(0.0, 122000.0, 0.0), radius_gu=3566.8,
               nebula={"spheres": [(0.0, 1500.0, 0.0, 1500.0)]})
    assert P.clump_radius(r, (0.0, 0.0, 0.0)) == pytest.approx(123500.0)


def test_profile_round_trips_through_map_json():
    m = SystemMap(system="X", profile=P.Profile(
        rows=[P.ProfileRow(0.0, radiation=1.0), P.ProfileRow(300.0)],
        color=(0.5, 0.25, 0.75), full_concealment=0.4))
    back = from_json(to_json(m))
    assert back.profile == m.profile


def test_map_without_profile_key_loads_as_none():
    assert from_json('{"system": "X"}').profile is None


def test_sample_for_object_uses_system_position_and_star(monkeypatch):
    from engine.systems import frames, resolve
    from engine.systems.map import Body
    prof = _p((0.0, 0.0), (1000.0, 1.0))
    m = SystemMap(system="S", bodies=[Body("Sun", "Sun", 10.0, (0.0, 0.0, 0.0))],
                  profile=prof)
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("system", "S"), 300.0, 400.0, 0.0))
    monkeypatch.setattr(resolve, "map_of", lambda name: m if name == "S" else None)
    assert P.sample_for_object(object()).nebula == pytest.approx(0.5)
    assert P.locate(object()) == (prof, pytest.approx(500.0))


def test_sample_for_object_outside_a_mapped_system_is_clear(monkeypatch):
    from engine.systems import frames
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("set", object()), 1.0, 2.0, 3.0))
    assert P.sample_for_object(object()) == P.CLEAR
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    assert P.sample_for_object(object()) == P.CLEAR
