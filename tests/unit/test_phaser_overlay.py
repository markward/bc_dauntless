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
