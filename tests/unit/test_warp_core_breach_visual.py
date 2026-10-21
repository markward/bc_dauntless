"""The warp-core breach's hull visual: three Internal damage records growing
at the core (engine/appc/warp_core_breach.py).

It replaced the old growing voxel carve (core_breach_carve). Sized as before:
R = clamp(0.25 x GetRadius(), 0.1, 1.2) GU; the records land at t = 0, 0.5
and 1.0 s with radii 0.4, 0.7 and 1.0 x R, all wear 10, kind 3 (Internal).
After the last one the part check runs (hull_breakup.after_wear).
"""
import pytest

from engine import host_io
from engine.appc import hull_breakup, warp_core_breach
from engine.appc.math import TGMatrix3, TGPoint3


class _Core:
    def __init__(self, pos=None):
        self._pos = pos or TGPoint3(0.5, 0.0, 0.0)   # body offset from centre

    def GetPosition(self):
        return self._pos


class _Ship:
    def __init__(self, loc=None, radius=2.0, core="default"):
        self._loc = loc or TGPoint3(0.0, 0.0, 0.0)
        self._radius = radius
        self._core = _Core() if core == "default" else core
        self._rot = TGMatrix3()   # identity

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot
    def GetRadius(self):         return self._radius
    def GetPowerSubsystem(self): return self._core


@pytest.fixture
def rig(monkeypatch):
    """Capture hull_damage_add and the part check in one ordered log; no
    shockwave (its own tests cover it)."""
    from engine.appc import shockwaves
    log = []
    monkeypatch.setattr(host_io, "hull_damage_add",
                        lambda *a, **k: log.append(("add",) + a))
    monkeypatch.setattr(hull_breakup, "after_wear",
                        lambda ship, iid, *a, **k: log.append(("wear", ship, iid)))
    monkeypatch.setattr(shockwaves, "spawn", lambda *a, **k: None)
    return log


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    yield
    warp_core_breach.reset()


def _adds(log):
    return [e[1:] for e in log if e[0] == "add"]


def test_core_breach_grows_three_internal_records(rig):
    ship = _Ship(loc=TGPoint3(10.0, 0.0, 0.0), radius=2.0)
    si = {ship: 7}
    warp_core_breach.arm(ship)
    warp_core_breach.advance(0.0, si)          # detonates: the t = 0 record
    assert len(_adds(rig)) == 1
    warp_core_breach.advance(0.25, si)         # 0.25 s: nothing new
    assert len(_adds(rig)) == 1
    warp_core_breach.advance(0.25, si)         # 0.5 s: the second
    assert len(_adds(rig)) == 2
    warp_core_breach.advance(0.5, si)          # 1.0 s: the third
    adds = _adds(rig)
    assert len(adds) == 3

    big_r = 0.25 * 2.0                          # inside [0.1, 1.2]
    for (iid, point, normal, radius, wear, kind), k in zip(adds, (0.4, 0.7, 1.0)):
        assert iid == 7
        assert point == pytest.approx((10.5, 0.0, 0.0)), "at the core"
        assert normal == pytest.approx((1.0, 0.0, 0.0)), "centre -> core"
        assert radius == pytest.approx(big_r * k)
        assert wear == pytest.approx(10.0)
        assert kind == 3, "an Internal record"

    warp_core_breach.advance(1.0, si)          # done: no fourth record
    assert len(_adds(rig)) == 3


def test_the_part_check_runs_once_after_the_last_record(rig):
    ship = _Ship()
    si = {ship: 4}
    warp_core_breach.arm(ship)
    warp_core_breach.advance(0.0, si)
    warp_core_breach.advance(0.5, si)
    assert [e[0] for e in rig] == ["add", "add"], "no check before the last"
    warp_core_breach.advance(0.5, si)
    warp_core_breach.advance(0.5, si)
    assert [e[0] for e in rig] == ["add", "add", "add", "wear"]
    assert rig[-1] == ("wear", ship, 4)


@pytest.mark.parametrize("ship_radius, expected_r", [
    (0.2, 0.1),     # tiny hull: floored at 0.1 GU
    (2.0, 0.5),     # 0.25 x radius
    (40.0, 1.2),    # a station: capped at 1.2 GU
])
def test_the_full_radius_is_a_clamped_quarter_of_the_ship(rig, ship_radius,
                                                           expected_r):
    ship = _Ship(radius=ship_radius)
    si = {ship: 1}
    warp_core_breach.arm(ship)
    for dt in (0.0, 0.5, 0.5):
        warp_core_breach.advance(dt, si)
    assert _adds(rig)[-1][3] == pytest.approx(expected_r)


def test_an_unrendered_ship_gets_no_records(rig):
    ship = _Ship()
    warp_core_breach.arm(ship)
    warp_core_breach.advance(0.0, {})          # no render instance
    warp_core_breach.advance(0.5, {ship: 1})   # dropped, never resumes
    warp_core_breach.advance(0.5, {ship: 1})
    assert rig == []


def test_a_ship_that_stops_rendering_mid_growth_is_dropped(rig):
    ship = _Ship()
    warp_core_breach.arm(ship)
    warp_core_breach.advance(0.0, {ship: 1})
    warp_core_breach.advance(0.5, {})          # gone
    warp_core_breach.advance(0.5, {ship: 1})
    assert len(_adds(rig)) == 1


def test_reset_drops_a_growing_breach(rig):
    ship = _Ship()
    warp_core_breach.arm(ship)
    warp_core_breach.advance(0.0, {ship: 1})
    warp_core_breach.reset()
    warp_core_breach.advance(0.5, {ship: 1})
    warp_core_breach.advance(0.5, {ship: 1})
    assert len(_adds(rig)) == 1


def test_a_core_at_the_ship_centre_faces_ship_up(rig):
    ship = _Ship(core=_Core(TGPoint3(0.0, 0.0, 0.0)))
    warp_core_breach.arm(ship)
    warp_core_breach.advance(0.0, {ship: 1})
    assert _adds(rig)[0][2] == pytest.approx((0.0, 0.0, 1.0))
