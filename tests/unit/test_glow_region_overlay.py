"""engine.ui.glow_region_overlay — baked glow regions → world debug cylinders."""

import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.glow_region_overlay import build_glow_region_overlay, GLOW_COLOR


class _Point:
    def __init__(self, x, y, z):
        self._x, self._y, self._z = x, y, z
    def GetX(self): return self._x
    def GetY(self): return self._y
    def GetZ(self): return self._z


class _Pod:
    """Leaf subsystem with an optional baked glow region on its property."""
    def __init__(self, pos, prop=None, name="pod"):
        self._pos, self._prop, self._name = pos, prop, name
    def GetPosition(self): return self._pos
    def GetName(self): return self._name
    def GetProperty(self): return self._prop
    def GetNumChildSubsystems(self): return 0


class _Ship:
    """Minimal ship: one damage-source getter + world transform."""
    def __init__(self, pod, rot=None, loc=(0.0, 0.0, 0.0)):
        self._pod = pod
        self._rot = rot if rot is not None else TGMatrix3()
        self._loc = TGPoint3(*loc)
    def GetImpulseEngineSubsystem(self): return self._pod
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot


def _cylinder_prop(axis=(0.0, -1.0, 0.0), radius=2.0, extent=(0.0, 2.0),
                   position=None):
    from engine.appc.properties import EngineProperty
    p = EngineProperty("pod")
    p.SetGlowRegionShape(0, "Cylinder")
    p.SetGlowRegionAxis(0, *axis)
    p.SetGlowRegionRadius(0, radius)
    p.SetGlowRegionExtent(0, *extent)
    if position is not None:
        p.SetGlowRegionPosition(0, *position)
    return p


def _sphere_prop(radius=1.5, position=None):
    from engine.appc.properties import EngineProperty
    p = EngineProperty("pod")
    p.SetGlowRegionShape(0, "Sphere")
    p.SetGlowRegionRadius(0, radius)
    if position is not None:
        p.SetGlowRegionPosition(0, *position)
    return p


def test_none_ship_yields_nothing():
    assert build_glow_region_overlay(None) == []


def test_unbaked_subsystem_contributes_nothing():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), prop=None))
    assert build_glow_region_overlay(ship) == []


def test_cylinder_identity_transform():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), _cylinder_prop()))
    out = build_glow_region_overlay(ship)
    assert len(out) == 1
    c = out[0]
    assert c["center"] == pytest.approx((1.0, 2.0, 3.0))
    assert c["axis"] == pytest.approx((0.0, -1.0, 0.0))
    assert c["radius"] == pytest.approx(2.0)
    assert c["length"] == pytest.approx(2.0)
    assert c["color"] == GLOW_COLOR


def test_cylinder_aft_extent_shifts_base():
    # extent (-1, 3): resolver pre-shifts the centre by aft along the axis
    # (aft dir is -Y) and the length is fore - aft.
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), _cylinder_prop(extent=(-1.0, 3.0))))
    out = build_glow_region_overlay(ship)
    assert len(out) == 1
    c = out[0]
    assert c["center"] == pytest.approx((1.0, 3.0, 3.0))
    assert c["length"] == pytest.approx(4.0)


def test_cylinder_rotated_and_translated_ship():
    # +90° about Z: body (0,-1,0) -> world (1,0,0); body point (1,2,3) ->
    # world (-2,1,3); plus ship location (10,0,0).
    rot = TGMatrix3().MakeZRotation(math.pi / 2.0)
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), _cylinder_prop()),
                 rot=rot, loc=(10.0, 0.0, 0.0))
    out = build_glow_region_overlay(ship)
    assert len(out) == 1
    c = out[0]
    assert c["center"] == pytest.approx((8.0, 1.0, 3.0))
    assert c["axis"] == pytest.approx((1.0, 0.0, 0.0))


def test_sphere_becomes_circumscribing_cylinder_along_body_up():
    ship = _Ship(_Pod(_Point(0.0, 0.0, 4.0), _sphere_prop(radius=1.5)))
    out = build_glow_region_overlay(ship)
    assert len(out) == 1
    c = out[0]
    # base = centre - up*r along body-up (identity: +Z), length = 2r
    assert c["center"] == pytest.approx((0.0, 0.0, 2.5))
    assert c["axis"] == pytest.approx((0.0, 0.0, 1.0))
    assert c["radius"] == pytest.approx(1.5)
    assert c["length"] == pytest.approx(3.0)


def test_authored_position_overrides_hardpoint_position():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0),
                      _cylinder_prop(position=(5.0, 6.0, 7.0))))
    out = build_glow_region_overlay(ship)
    assert len(out) == 1
    assert out[0]["center"] == pytest.approx((5.0, 6.0, 7.0))
