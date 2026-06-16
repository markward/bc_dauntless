# tests/unit/test_phaser_overlay.py
"""Phaser strip/arc overlay geometry (Ship Property Viewer).
Spec: docs/superpowers/specs/2026-06-16-spv-phaser-strips-and-arcs-design.md
"""
import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import PhaserProperty
from engine.appc.weapon_subsystems import PhaserBank
from engine.ui import phaser_overlay as po


class _StubShip:
    """Identity rotation, origin position; iterable over its subsystems."""
    def __init__(self, subs):
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()  # identity
        self._subs = list(subs)
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetParentSubsystem(self): return None
    def GetParentShip(self): return self
    def __iter__(self): return iter(self._subs)


def _galaxy_dorsal1_bank(name="DorsalPhaser1"):
    """Galaxy-DorsalPhaser1-like bank (sdk/.../ships/Hardpoints/galaxy.py)."""
    bank = PhaserBank(name)
    prop = PhaserProperty(name)
    prop.SetPosition(0.0, 1.27, 0.5)
    prop.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetLength(1.69)
    prop.SetWidth(1.35)
    prop.SetArcWidthAngles(-0.872665, 0.872665)        # ±50°
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    bank.SetProperty(prop)
    return bank


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def test_strip_outer_rim_lies_on_sphere_of_radius_length():
    bank = _galaxy_dorsal1_bank()
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_strip_beams([bank], ship)
    assert beams, "expected strip beams"
    pos = (0.0, 1.27, 0.5)  # bank world Position (identity rotation)
    # Width=1.35 < Length=1.69, so an inner rim exists too. The OUTER rim
    # endpoints sit at radius=Length; assert at least those beams do.
    outer = [b for b in beams
             if abs(_dist(b["emitter"], pos) - 1.69) < 1e-5]
    assert outer, "no outer-rim beam endpoints at radius=Length"
    for b in beams:
        assert b["color"] == po.STRIP_COLOR


def test_strip_spans_arc_width_angles():
    bank = _galaxy_dorsal1_bank()
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_strip_beams([bank], ship)
    pos = (0.0, 1.27, 0.5)
    # First outer sample at yaw_lo. Identity rotation: world forward =
    # body (-1,0,0); up = (0,0,1). radial(yaw) = forward rotated about +Z by yaw.
    fwd = (-1.0, 0.0, 0.0)
    up = (0.0, 0.0, 1.0)
    expect_lo = po._add(pos, po._scale(po._rodrigues(fwd, up, -0.872665), 1.69))
    assert beams[0]["emitter"] == pytest.approx(expect_lo, abs=1e-6)


def test_inner_rim_and_caps_only_when_width_positive():
    bank = _galaxy_dorsal1_bank()
    # Mutate width to zero via property + re-bind (SetProperty re-mirrors _width).
    prop = bank.GetProperty()
    prop.SetWidth(0.0)
    bank.SetProperty(prop)   # re-mirror: bank._width now 0.0
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_strip_beams([bank], ship)
    # Only the outer rim polyline: exactly STRIP_SAMPLES segments.
    assert len(beams) == po.STRIP_SAMPLES


def test_arc_wireframe_has_four_edges_at_radius_length():
    bank = _galaxy_dorsal1_bank()
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_arc_beams(bank, ship)
    # 4 edges × ARC_SAMPLES segments each.
    assert len(beams) == 4 * po.ARC_SAMPLES
    pos = (0.0, 1.27, 0.5)
    radius = 1.69 * po.ARC_RADIUS_SCALE
    for b in beams:
        assert _dist(b["emitter"], pos) == pytest.approx(radius, abs=1e-5)
        assert _dist(b["target"], pos) == pytest.approx(radius, abs=1e-5)
        assert b["color"] == po.ARC_COLOR

    # Directional sanity: top edge (pitch_hi) is higher along world-up (+Z)
    # than the bottom edge (pitch_lo). Compare midpoint beam emitters.
    mid = po.ARC_SAMPLES // 2
    top_z = beams[mid]["emitter"][2]                      # top edge
    bot_z = beams[po.ARC_SAMPLES + mid]["emitter"][2]     # bottom edge
    assert top_z > bot_z


def test_arc_empty_when_length_zero():
    bank = _galaxy_dorsal1_bank()
    prop = bank.GetProperty()
    prop.SetLength(0.0)
    bank.SetProperty(prop)   # re-mirror: bank._length now 0.0
    assert bank.GetLength() == 0.0
    ship = _StubShip([bank])
    bank._parent_ship = ship
    assert po.build_arc_beams(bank, ship) == []


def test_phaser_banks_filters_non_phaser_subsystems():
    """phaser_banks() returns only PhaserBank instances.

    _iter_damage_subsystems (called by _iter_subsystems) enumerates subsystems
    via specific getter methods on the ship (GetPhaserSystem, GetHull, etc.),
    NOT via __iter__.  So we give the stub ship those getters:
      - GetPhaserSystem() → a PhaserSystem that holds `a` as a child bank
      - GetHull() → a _NotAPhaser object
    This mirrors the real ship wiring and lets _iter_damage_subsystems yield
    both; phaser_banks() should then filter out the hull stub.
    """
    from engine.appc.weapon_subsystems import PhaserSystem
    from engine.appc.subsystems import HullSubsystem

    a = _galaxy_dorsal1_bank("DorsalPhaser1")

    phaser_sys = PhaserSystem("PhaserSystem")
    phaser_sys.AddChildSubsystem(a)

    hull = HullSubsystem("Hull")

    class _StubShipWithGetters(_StubShip):
        def GetPhaserSystem(self): return phaser_sys
        def GetHull(self): return hull

    ship = _StubShipWithGetters([a])
    a._parent_ship = ship

    banks = po.phaser_banks(ship)
    assert banks == [a]


def _colors(beams):
    return {b["color"] for b in beams}


def test_overlay_arc_only_for_selected_bank():
    a = _galaxy_dorsal1_bank("DorsalPhaser1")
    b = _galaxy_dorsal1_bank("DorsalPhaser2")
    ship = _StubShip([a, b])
    a._parent_ship = ship
    b._parent_ship = ship
    banks = [a, b]
    # No selection → strips only (yellow), no cyan arc.
    strips_only = po.build_phaser_overlay(ship, selected_name=None, banks=banks)
    assert po.STRIP_COLOR in _colors(strips_only)
    assert po.ARC_COLOR not in _colors(strips_only)
    # Select bank b → strips + b's arc (cyan present).
    with_arc = po.build_phaser_overlay(ship, selected_name="DorsalPhaser2",
                                       banks=banks)
    assert po.ARC_COLOR in _colors(with_arc)
    # Exactly one bank's worth of arc beams (4 × ARC_SAMPLES).
    assert sum(1 for x in with_arc if x["color"] == po.ARC_COLOR) \
        == 4 * po.ARC_SAMPLES


def test_overlay_empty_for_none_ship():
    assert po.build_phaser_overlay(None, selected_name="DorsalPhaser1") == []
