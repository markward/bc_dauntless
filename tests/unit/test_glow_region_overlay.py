"""engine.ui.glow_region_overlay — baked glow regions → world debug cylinders."""

import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.glow_region_overlay import build_glow_region_overlay, GLOW_COLOR
from engine.ui import glow_region_overlay as gro


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
    assert build_glow_region_overlay(None) == ([], [])


def test_unbaked_subsystem_contributes_nothing():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), prop=None))
    cyls, boxes = build_glow_region_overlay(ship)
    assert cyls == []
    assert boxes == []


def test_cylinder_identity_transform():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), _cylinder_prop()))
    cyls, boxes = build_glow_region_overlay(ship)
    assert len(cyls) == 1
    assert boxes == []
    c = cyls[0]
    assert c["center"] == pytest.approx((1.0, 2.0, 3.0))
    assert c["axis"] == pytest.approx((0.0, -1.0, 0.0))
    assert c["radius"] == pytest.approx(2.0)
    assert c["length"] == pytest.approx(2.0)
    assert c["color"] == GLOW_COLOR


def test_cylinder_aft_extent_shifts_base():
    # extent (-1, 3): resolver pre-shifts the centre by aft along the axis
    # (aft dir is -Y) and the length is fore - aft.
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), _cylinder_prop(extent=(-1.0, 3.0))))
    cyls, boxes = build_glow_region_overlay(ship)
    assert len(cyls) == 1
    assert boxes == []
    c = cyls[0]
    assert c["center"] == pytest.approx((1.0, 3.0, 3.0))
    assert c["length"] == pytest.approx(4.0)


def test_cylinder_rotated_and_translated_ship():
    # +90° about Z: body (0,-1,0) -> world (1,0,0); body point (1,2,3) ->
    # world (-2,1,3); plus ship location (10,0,0).
    rot = TGMatrix3().MakeZRotation(math.pi / 2.0)
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), _cylinder_prop()),
                 rot=rot, loc=(10.0, 0.0, 0.0))
    cyls, boxes = build_glow_region_overlay(ship)
    assert len(cyls) == 1
    assert boxes == []
    c = cyls[0]
    assert c["center"] == pytest.approx((8.0, 1.0, 3.0))
    assert c["axis"] == pytest.approx((1.0, 0.0, 0.0))


def test_sphere_becomes_circumscribing_cylinder_along_body_up():
    ship = _Ship(_Pod(_Point(0.0, 0.0, 4.0), _sphere_prop(radius=1.5)))
    cyls, boxes = build_glow_region_overlay(ship)
    assert len(cyls) == 1
    assert boxes == []
    c = cyls[0]
    # base = centre - up*r along body-up (identity: +Z), length = 2r
    assert c["center"] == pytest.approx((0.0, 0.0, 2.5))
    assert c["axis"] == pytest.approx((0.0, 0.0, 1.0))
    assert c["radius"] == pytest.approx(1.5)
    assert c["length"] == pytest.approx(3.0)


def test_authored_position_overrides_hardpoint_position():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0),
                      _cylinder_prop(position=(5.0, 6.0, 7.0))))
    cyls, boxes = build_glow_region_overlay(ship)
    assert len(cyls) == 1
    assert boxes == []
    assert cyls[0]["center"] == pytest.approx((5.0, 6.0, 7.0))


class _TwoPodShip(_Ship):
    """Two mounted pods under one damage-source getter."""
    def __init__(self, pod_a, pod_b):
        super().__init__(pod_a)
        self._pod_b = pod_b
    def GetWarpEngineSubsystem(self): return self._pod_b


def test_selected_subsystem_shows_only_its_regions():
    a = _Pod(_Point(1.0, 0.0, 0.0), _cylinder_prop(), name="Port Impulse")
    b = _Pod(_Point(-1.0, 0.0, 0.0), _cylinder_prop(), name="Star Impulse")
    ship = _TwoPodShip(a, b)
    cyls, boxes = build_glow_region_overlay(ship, selected_name="Star Impulse",
                                            show_all=False)
    assert len(cyls) == 1
    assert boxes == []
    assert cyls[0]["center"] == pytest.approx((-1.0, 0.0, 0.0))


def test_toggle_off_and_no_selection_yields_nothing():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), _cylinder_prop()))
    cyls, boxes = build_glow_region_overlay(ship, selected_name=None,
                                            show_all=False)
    assert cyls == []
    assert boxes == []


def test_show_all_ignores_selection_filter():
    a = _Pod(_Point(1.0, 0.0, 0.0), _cylinder_prop(), name="Port Impulse")
    b = _Pod(_Point(-1.0, 0.0, 0.0), _cylinder_prop(), name="Star Impulse")
    ship = _TwoPodShip(a, b)
    cyls, boxes = build_glow_region_overlay(ship, selected_name="Star Impulse",
                                            show_all=True)
    assert len(cyls) == 2
    assert boxes == []


def test_selected_subsystem_without_regions_yields_nothing():
    ship = _Ship(_Pod(_Point(1.0, 2.0, 3.0), prop=None, name="Bare"))
    cyls, boxes = build_glow_region_overlay(ship, selected_name="Bare",
                                            show_all=False)
    assert cyls == []
    assert boxes == []


class _BoxSub:
    def __init__(self, name, prop): self._n = name; self._p = prop
    def GetName(self): return self._n
    def GetProperty(self): return self._p


class _BoxShip:
    def __init__(self, subs): self._subs = subs
    def GetWorldLocation(self):
        class P: x = 10.0; y = 0.0; z = 0.0
        return P()
    def GetWorldRotation(self): return None   # None rot => body == world
    def __iter__(self): return iter(self._subs)


def test_pending_cylinder_overrides_baked(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("sphere", (0.0, 0.0, 0.0), 0.9)])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, 0.0, 1.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.1, 0.1, 0.1)}}
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True, pending=pending)
    assert boxes == []
    assert len(cyls) == 1
    assert abs(cyls[0]["radius"] - 0.2) < 1e-9   # pending radius, not the baked 0.9 sphere
    assert abs(cyls[0]["length"] - 2.0) < 1e-9   # pending extent fore-aft


def test_pending_box_yields_a_box(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops", lambda prop, pos, name: [])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Box", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, -1.0, 0.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.5, 0.6, 0.7)}}
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True, pending=pending)
    assert cyls == []
    assert len(boxes) == 1


def test_pending_previews_even_when_filtered_out(monkeypatch):
    # Edit Light operates on the RIGHT-CLICKED row, which right-click does
    # NOT select. With the Glow Regions toggle off and a DIFFERENT pin
    # selected, the pending subsystem must still contribute its wireframe —
    # otherwise the staged edit never previews live.
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops", lambda prop, pos, name: [])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, 0.0, 1.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.1, 0.1, 0.1)}}
    cyls, boxes = gro.build_glow_region_overlay(
        ship, selected_name="Some Other Subsystem", show_all=False, pending=pending)
    assert boxes == []
    assert len(cyls) == 1   # pending subsystem previewed despite the filter


def test_non_pending_subsystem_still_filtered_when_not_selected(monkeypatch):
    # Existing behavior preserved: with no pending spec, show_all=False and a
    # different selection, the subsystem still contributes nothing.
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("sphere", (0.0, 0.0, 0.0), 0.9)])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    cyls, boxes = gro.build_glow_region_overlay(
        ship, selected_name="Some Other Subsystem", show_all=False, pending={})
    assert cyls == []
    assert boxes == []


def test_overlay_returns_cylinders_and_boxes_tuple(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("box", (0.0, 0.0, 0.0), (1.0, 2.0, 3.0))])
    ship = _BoxShip([_BoxSub("Box Pod", object())])
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True)
    assert cyls == []
    assert len(boxes) == 1
    b = boxes[0]
    # center = ship_pos + region center (None rot => identity): (10,0,0)
    assert b["center"] == (10.0, 0.0, 0.0)
    # edge vectors carry the half-extents along body axes (identity rot).
    assert b["ex"] == (1.0, 0.0, 0.0)
    assert b["ey"] == (0.0, 2.0, 0.0)
    assert b["ez"] == (0.0, 0.0, 3.0)
    assert b["color"] == gro.GLOW_COLOR
