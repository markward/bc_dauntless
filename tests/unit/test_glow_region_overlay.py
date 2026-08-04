"""engine.ui.glow_region_overlay — baked glow regions → world debug cylinders."""

import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.glow_region_overlay import (
    build_glow_region_overlay, build_emitter_overlay, GLOW_COLOR,
)
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


def test_pending_not_drawn_when_a_different_element_is_selected(monkeypatch):
    # Selection-scoped overlay: a staged/saved light edit is NOT drawn just
    # because it is pending. With the Glow Regions toggle off and a DIFFERENT
    # element selected, the pending subsystem contributes nothing — its
    # wireframe only shows when ITS OWN light node is the selected element
    # (Edit Light selects that node, so the live edit still previews).
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops", lambda prop, pos, name: [])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, 0.0, 1.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.1, 0.1, 0.1)}}
    cyls, boxes = gro.build_glow_region_overlay(
        ship, selected_name="Some Other Subsystem", show_all=False, pending=pending)
    assert cyls == [] and boxes == []   # not the selected element -> hidden


def test_pending_previews_when_its_own_light_is_selected(monkeypatch):
    # The staged Edit Light spec DOES preview live when that light node is the
    # selected element: the pending spec (radius 0.2 cylinder) is drawn INSTEAD
    # of the baked sphere.
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("sphere", (0.0, 0.0, 0.0), 0.9)])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, 0.0, 1.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.1, 0.1, 0.1)}}
    cyls, boxes = gro.build_glow_region_overlay(
        ship, selected_name="Center Impulse", show_all=False, pending=pending)
    assert boxes == []
    assert len(cyls) == 1
    assert abs(cyls[0]["radius"] - 0.2) < 1e-9   # pending spec, not the baked 0.9 sphere


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


def test_pending_not_drawn_with_no_selection_and_toggle_off(monkeypatch):
    # Selection-scoped: with the Glow Regions toggle OFF and NOTHING selected,
    # a staged/saved light edit contributes nothing — a previously-edited
    # light no longer persists on screen once you select away or deselect.
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops", lambda prop, pos, name: [])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    pending = {"Center Impulse": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                                  "axis": (0.0, 0.0, 1.0), "radius": (0.2,),
                                  "extent": (0.0, 2.0), "scale": (0.1, 0.1, 0.1)}}
    cyls, boxes = gro.build_glow_region_overlay(
        ship, selected_name=None, show_all=False, pending=pending)
    assert cyls == [] and boxes == []


def test_toggle_off_no_selection_no_pending_still_yields_nothing(monkeypatch):
    # The early-return must still fire when there is truly nothing to show.
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("sphere", (0.0, 0.0, 0.0), 0.9)])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    cyls, boxes = gro.build_glow_region_overlay(
        ship, selected_name=None, show_all=False, pending=None)
    assert cyls == []
    assert boxes == []
    cyls, boxes = gro.build_glow_region_overlay(
        ship, selected_name=None, show_all=False, pending={})
    assert cyls == []
    assert boxes == []


def test_pending_none_hides_baked_region(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    # A baked cylinder that WOULD draw if not hidden.
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("cylinder", (0.0, 0.0, 0.0),
                                                  (0.0, 0.0, 1.0), 0.25, 2.0)])
    ship = _BoxShip([_BoxSub("Center Impulse", object())])
    pending = {"Center Impulse": None}          # staged removal
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True, pending=pending)
    assert cyls == [] and boxes == []           # hidden, not the baked region


def test_overlay_returns_cylinders_and_boxes_tuple(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("box", (0.0, 0.0, 0.0), (1.0, 2.0, 3.0),
                                                   (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))])
    ship = _BoxShip([_BoxSub("Box Pod", object())])
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True)
    assert cyls == []
    assert len(boxes) == 1
    b = boxes[0]
    # center = ship_pos + region center (None rot => identity): (10,0,0)
    assert b["center"] == (10.0, 0.0, 0.0)
    # edge vectors carry the half-extents along body axes (identity orientation).
    assert b["ex"] == (1.0, 0.0, 0.0)
    assert b["ey"] == (0.0, 2.0, 0.0)
    assert b["ez"] == (0.0, 0.0, 3.0)
    assert b["color"] == gro.GLOW_COLOR


def test_box_wireframe_tilts_with_orientation(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    # forward=+X, up=+Z -> box local Y axis points along world +X.
    monkeypatch.setattr(gro, "baked_region_ops",
        lambda prop, pos, name: [("box", (0.0, 0.0, 0.0), (1.0, 2.0, 3.0),
                                   (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))])
    ship = _BoxShip([_BoxSub("Box Pod", object())])
    _c, boxes = gro.build_glow_region_overlay(ship, show_all=True)
    b = boxes[0]
    # ey carries the hy=2 extent along the forward axis (+X here), not body +Y.
    assert b["ey"] == pytest.approx((2.0, 0.0, 0.0), abs=1e-6)


# ----------------------------------------------------------------------
# Task 9: build_emitter_overlay — selection-scoped emitter wireframe feed
# ----------------------------------------------------------------------

def _emitter_spec(kind="point", position=(1.0, 2.0, 3.0), axis=(0.0, -1.0, 0.0),
                  radius=0.5, length=4.0, color=(1.0, 0.5, 0.2)):
    return {"kind": kind, "position": position, "axis": axis, "radius": radius,
            "length": length, "color": color, "intensity": 2.0}


class _FakePanel:
    def __init__(self, selected=None, spec=None):
        self._selected_emitter = selected
        self._spec = spec

    def _effective_emitter(self, i, j):
        return self._spec


def test_emitter_overlay_nothing_selected_yields_empty_lists():
    ship = _Ship(_Pod(_Point(0.0, 0.0, 0.0)))
    spheres, cyls, cones = build_emitter_overlay(ship, _FakePanel(selected=None))
    assert spheres == [] and cyls == [] and cones == []


def test_emitter_overlay_selected_but_spec_gone_yields_empty_lists():
    # A stale selection (removed since selected) resolves to a falsy spec.
    ship = _Ship(_Pod(_Point(0.0, 0.0, 0.0)))
    spheres, cyls, cones = build_emitter_overlay(
        ship, _FakePanel(selected=(0, 0), spec=None))
    assert spheres == [] and cyls == [] and cones == []


def test_emitter_overlay_none_ship_yields_empty_lists():
    spheres, cyls, cones = build_emitter_overlay(
        None, _FakePanel(selected=(0, 0), spec=_emitter_spec()))
    assert spheres == [] and cyls == [] and cones == []


def test_emitter_overlay_point_returns_sphere_only():
    ship = _Ship(_Pod(_Point(0.0, 0.0, 0.0)))
    spec = _emitter_spec("point", position=(1.0, 2.0, 3.0), radius=0.75)
    spheres, cyls, cones = build_emitter_overlay(
        ship, _FakePanel(selected=(0, 0), spec=spec))
    assert cyls == [] and cones == []
    assert len(spheres) == 1
    s = spheres[0]
    assert s["center"] == pytest.approx((1.0, 2.0, 3.0))
    assert s["radius"] == pytest.approx(0.75)
    assert s["color"] == (1.0, 0.5, 0.2)


def test_emitter_overlay_strip_returns_cylinder_only():
    ship = _Ship(_Pod(_Point(0.0, 0.0, 0.0)))
    spec = _emitter_spec("strip")
    spheres, cyls, cones = build_emitter_overlay(
        ship, _FakePanel(selected=(0, 0), spec=spec))
    assert spheres == [] and cones == []
    assert len(cyls) == 1
    c = cyls[0]
    assert c["axis"] == pytest.approx((0.0, -1.0, 0.0))
    assert c["radius"] == pytest.approx(0.5)
    assert c["length"] == pytest.approx(4.0)


def test_emitter_overlay_cone_transforms_into_world_space():
    # Same rotated/translated ship as test_cylinder_rotated_and_translated_ship:
    # +90deg about Z, ship at (10,0,0). body(1,2,3) -> world(-2,1,3) + loc
    # = (8,1,3); body axis (0,-1,0) -> world (1,0,0).
    rot = TGMatrix3().MakeZRotation(math.pi / 2.0)
    ship = _Ship(_Pod(_Point(0.0, 0.0, 0.0)), rot=rot, loc=(10.0, 0.0, 0.0))
    spec = _emitter_spec("cone", position=(1.0, 2.0, 3.0), axis=(0.0, -1.0, 0.0),
                         radius=0.5, length=4.0)
    spheres, cyls, cones = build_emitter_overlay(
        ship, _FakePanel(selected=(0, 0), spec=spec))
    assert spheres == [] and cyls == []
    assert len(cones) == 1
    c = cones[0]
    assert c["apex"] == pytest.approx((8.0, 1.0, 3.0))
    assert c["axis"] == pytest.approx((1.0, 0.0, 0.0))
    n = math.sqrt(sum(a * a for a in c["axis"]))
    assert abs(n - 1.0) < 1e-9
    assert c["radius"] == pytest.approx(0.5)
    assert c["length"] == pytest.approx(4.0)
    assert c["color"] == pytest.approx((1.0, 0.5, 0.2))


def test_emitter_overlay_zero_axis_falls_back_to_default_no_nan():
    # A degenerate/authored zero axis must never reach DebugCone/DebugCylinder
    # (they normalize in GLM -> NaN on a zero vector); it must fall back to
    # the same default light_emitters gives an axis-less spec, (0,-1,0).
    ship = _Ship(_Pod(_Point(0.0, 0.0, 0.0)))
    spec = _emitter_spec("cone", axis=(0.0, 0.0, 0.0))
    spheres, cyls, cones = build_emitter_overlay(
        ship, _FakePanel(selected=(0, 0), spec=spec))
    assert len(cones) == 1
    ax = cones[0]["axis"]
    assert ax == pytest.approx((0.0, -1.0, 0.0))
    n = math.sqrt(sum(a * a for a in ax))
    assert abs(n - 1.0) < 1e-9
    assert not any(v != v for v in ax)   # no NaN component
