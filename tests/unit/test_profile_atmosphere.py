import math

import pytest

from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap


def _p(*rows):
    return P.Profile(rows=[P.ProfileRow(*r) for r in rows])


def test_radial_integral_is_exact_for_piecewise_linear():
    prof = _p((0.0, 0.0), (100.0, 1.0), (200.0, 0.0))
    assert P.radial_integral(prof, 0.0, 200.0) == pytest.approx(100.0)
    assert P.radial_integral(prof, 50.0, 150.0) == pytest.approx(75.0)
    assert P.radial_integral(prof, 150.0, 50.0) == pytest.approx(75.0)   # order-free


def test_radial_integral_persists_the_last_row():
    prof = _p((0.0, 0.0), (100.0, 0.5))
    assert P.radial_integral(prof, 100.0, 300.0) == pytest.approx(100.0)


def test_radial_integral_of_none_is_zero():
    assert P.radial_integral(None, 0.0, 1e6) == 0.0


def _map(prof, anchor=1000.0):
    return SystemMap(system="S",
                     bodies=[Body("Sun", "Sun", 10.0, (0.0, 0.0, 0.0))],
                     regions=[Region("R1", (anchor, 0.0, 0.0), 50.0)],
                     profile=prof)


def test_k_sys_hits_the_veil_from_the_outermost_region():
    m = _map(_p((0.0, 1.0), (2000.0, 1.0)))
    k = P.k_sys(m, veil=0.15)
    assert math.exp(-k * P.radial_integral(m.profile, 10.0, 1000.0)) == pytest.approx(0.15)


def test_k_sys_zero_integral_is_zero():
    m = _map(_p((0.0, 0.0), (2000.0, 0.0)))
    assert P.k_sys(m) == 0.0
    assert P.k_sys(_map(None)) == 0.0


def test_star_transmittance_at_the_outermost_region_is_the_veil(monkeypatch):
    from engine.systems import frames, resolve
    m = _map(_p((0.0, 1.0), (2000.0, 1.0)))
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("system", "S"), 1000.0, 0.0, 0.0))
    monkeypatch.setattr(resolve, "map_of", lambda name: m)
    assert P.star_transmittance(object(), veil=0.15) == pytest.approx(0.15)


def test_star_transmittance_outside_a_mapped_system_is_one(monkeypatch):
    from engine.systems import frames
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    assert P.star_transmittance(object()) == 1.0
