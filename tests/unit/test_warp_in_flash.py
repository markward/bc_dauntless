"""Warp-in flash records (warp-in spec): WarpFlash_Create /
WarpFlash_CreateWithoutShip make game-time records; drawing is the renderer's.
"""
import sys
import types

import App
import pytest

from engine.appc import warp_in_dials, warp_in_flash
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.sets import SetClass_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import WarpEngineSubsystem


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp_in_flash.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_in_flash.reset()


def _set(name="S"):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def _rot(angle=0.7):
    m = TGMatrix3()
    m.MakeZRotation(angle)
    return m


def _fwd(rot):
    c = rot.GetCol(1)
    return (c.x, c.y, c.z)


def test_create_without_ship_records_flash():
    pSet = _set("Alpha")
    rot = _rot()
    f = App.WarpFlash_CreateWithoutShip(pSet, TGPoint3(1.0, 2.0, 3.0), rot, 2.5)
    assert f.set_name == "Alpha"
    assert f.center == pytest.approx((1.0, 2.0, 3.0))
    assert f.forward == pytest.approx(_fwd(rot))
    assert f.radius == 2.5
    assert f.age == 0.0
    assert f.lifetime == pytest.approx(1.5)
    assert warp_in_flash.active() == [f]
    assert warp_in_flash.spawned_count() == 1


def test_explicit_time_wins():
    f = App.WarpFlash_CreateWithoutShip(_set(), TGPoint3(0, 0, 0), _rot(), 1.0, 0.8)
    assert f.lifetime == pytest.approx(0.8)


def test_zero_radius_uses_fallback():
    f = App.WarpFlash_CreateWithoutShip(_set(), TGPoint3(0, 0, 0), _rot(), 0.0)
    assert f.radius == warp_in_dials.get("fallback_radius_gu")


def _ship_in(pSet, radius=3.0):
    s = ShipClass()
    s.SetRadius(radius)
    pSet.AddObjectToSet(s, "npc")
    s.SetTranslateXYZ(4.0, 5.0, 6.0)
    s.SetMatrixRotation(_rot(0.4))
    return s


def test_create_with_ship_uses_ship_pose():
    pSet = _set("Beta")
    s = _ship_in(pSet)
    f = App.WarpFlash_Create(s)
    assert f.set_name == "Beta"
    assert f.center == pytest.approx((4.0, 5.0, 6.0))
    assert f.forward == pytest.approx(_fwd(s.GetWorldRotation()))
    assert f.radius == 3.0
    assert f.lifetime == pytest.approx(1.5)


def test_create_with_ship_zero_radius_uses_fallback():
    s = _ship_in(_set(), radius=0.0)
    f = App.WarpFlash_Create(s)
    assert f.radius == warp_in_dials.get("fallback_radius_gu")


def test_create_with_ship_not_in_a_set_spawns_nothing():
    s = ShipClass()
    s.SetRadius(2.0)
    assert App.WarpFlash_Create(s) is None
    assert warp_in_flash.spawned_count() == 0


def test_flash_retires_after_lifetime():
    App.WarpFlash_CreateWithoutShip(_set(), TGPoint3(0, 0, 0), _rot(), 1.0)
    warp_in_flash.advance(1.0)
    assert len(warp_in_flash.active()) == 1
    warp_in_flash.advance(0.6)
    assert warp_in_flash.active() == []


def test_flash_does_not_age_at_zero_dt():
    f = App.WarpFlash_CreateWithoutShip(_set(), TGPoint3(0, 0, 0), _rot(), 1.0)
    warp_in_flash.advance(0.0)
    assert f.age == 0.0


def test_app_exports_are_real():
    assert App.WarpFlash_Create is warp_in_flash.WarpFlash_Create
    assert App.WarpFlash_CreateWithoutShip is warp_in_flash.WarpFlash_CreateWithoutShip


def test_gameloop_advances_flashes():
    from engine.core.loop import GameLoop
    App.WarpFlash_CreateWithoutShip(_set(), TGPoint3(0, 0, 0), _rot(), 1.0)
    loop = GameLoop()
    for _ in range(90):
        loop.tick()
    assert warp_in_flash.active() == []


def test_sdk_warp_flash_enter_set_spawns(monkeypatch):
    pSet = _set("Gamma")
    pSet.SetRegionModule("fake_warp_region_mod")
    mod = types.ModuleType("fake_warp_region_mod")
    mod.GetSet = lambda: pSet
    monkeypatch.setitem(sys.modules, "fake_warp_region_mod", mod)
    s = _ship_in(pSet, radius=2.0)
    sub = WarpEngineSubsystem("Warp Engines")
    s.SetWarpEngineSubsystem(sub)
    from Actions import EffectScriptActions
    EffectScriptActions.WarpFlashEnterSet(None, "fake_warp_region_mod", s.GetObjID())
    assert warp_in_flash.spawned_count() == 1
    f = warp_in_flash.active()[0]
    loc = sub.GetWarpExitLocation()
    assert f.center == pytest.approx((loc.x, loc.y, loc.z))
    assert f.set_name == "Gamma"
    assert f.radius == 2.0
