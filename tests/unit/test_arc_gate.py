"""Arc-aware firing gate.

Emitter convention: body-space Direction (forward, +Y), Right (+X).
ArcWidthAngles  = (yaw_lo, yaw_hi) — left-right around the Up axis.
ArcHeightAngles = (pitch_lo, pitch_hi) — up-down around the Right axis.

A target at body-space vector v passes when:
    yaw_lo  <= atan2(Right · v, Direction · v) <= yaw_hi    AND
    pitch_lo <= asin((Up · v) / |v|)            <= pitch_hi
"""
import math
from engine.appc.math import TGPoint3
from engine.appc.subsystems import _emitter_in_arc


class _FakeEmitter:
    """Minimal stand-in for a ShipSubsystem-derived emitter."""
    def __init__(self, direction=(0,1,0), right=(1,0,0),
                 arc_width=(-math.pi/4, math.pi/4),
                 arc_height=(-math.pi/8, math.pi/8)):
        self._direction = TGPoint3(*direction)
        self._right     = TGPoint3(*right)
        self._arc_w     = arc_width
        self._arc_h     = arc_height
    def GetDirection(self):       return self._direction
    def GetRight(self):           return self._right
    def GetArcWidthAngles(self):  return self._arc_w
    def GetArcHeightAngles(self): return self._arc_h


def test_target_dead_ahead_passes():
    emitter = _FakeEmitter()
    assert _emitter_in_arc(emitter, ship=None,
                            aim_world=TGPoint3(0.0, 1.0, 0.0)) is True


def test_target_just_inside_width_passes():
    emitter = _FakeEmitter(arc_width=(-math.pi/4, math.pi/4))
    # Yaw ~ +44° → inside.
    aim = TGPoint3(math.sin(math.radians(44)), math.cos(math.radians(44)), 0.0)
    assert _emitter_in_arc(emitter, None, aim) is True


def test_target_just_outside_width_fails():
    emitter = _FakeEmitter(arc_width=(-math.pi/4, math.pi/4))
    # Yaw ~ +46° → outside.
    aim = TGPoint3(math.sin(math.radians(46)), math.cos(math.radians(46)), 0.0)
    assert _emitter_in_arc(emitter, None, aim) is False


def test_target_above_height_fails():
    emitter = _FakeEmitter(arc_height=(-math.pi/8, math.pi/8))
    # Pitch ~ +30° → outside ±22.5°.
    aim = TGPoint3(0.0, math.cos(math.radians(30)), math.sin(math.radians(30)))
    assert _emitter_in_arc(emitter, None, aim) is False


def test_target_below_height_fails():
    emitter = _FakeEmitter(arc_height=(-math.pi/8, math.pi/8))
    aim = TGPoint3(0.0, math.cos(math.radians(30)), -math.sin(math.radians(30)))
    assert _emitter_in_arc(emitter, None, aim) is False


def test_target_behind_fails_even_with_full_arc():
    # ArcWidth = full ±π/2 (180° cone). Target directly behind: yaw=π → outside.
    emitter = _FakeEmitter(arc_width=(-math.pi/2, math.pi/2))
    aim = TGPoint3(0.0, -1.0, 0.0)
    assert _emitter_in_arc(emitter, None, aim) is False


def test_emitter_without_arc_setters_uses_90deg_cone():
    """A bare emitter (no GetArcWidthAngles) — fallback to dot > 0."""
    class _BareEmitter:
        def __init__(self):
            self._direction = TGPoint3(0.0, 1.0, 0.0)
        def GetDirection(self): return self._direction
    bare = _BareEmitter()
    assert _emitter_in_arc(bare, None, TGPoint3(0.0,  1.0, 0.0)) is True
    assert _emitter_in_arc(bare, None, TGPoint3(0.0, -1.0, 0.0)) is False


# Reversed bounds. Stock hardpoints author some arcs with the larger angle
# first -- every phaser on the Fed Starbase, the belly phasers on the
# Ambassador, Akira and Cardassian stations -- e.g. cardstarbase.py's
# VentralPhaser1.SetArcHeightAngles(1.745329, -0.087266). Read literally as
# lo <= pitch <= hi that range is empty and the bank can never fire; the
# gate reads a reversed pair as the same range in order.

def test_reversed_height_bounds_cover_the_range_between_them():
    emitter = _FakeEmitter(arc_height=(math.radians(100), math.radians(-5)))
    aim = TGPoint3(0.0, math.cos(math.radians(30)), math.sin(math.radians(30)))
    assert _emitter_in_arc(emitter, None, aim) is True


def test_reversed_height_bounds_still_reject_outside_the_range():
    emitter = _FakeEmitter(arc_height=(math.radians(100), math.radians(-5)))
    aim = TGPoint3(0.0, math.cos(math.radians(10)), -math.sin(math.radians(10)))
    assert _emitter_in_arc(emitter, None, aim) is False


def test_reversed_width_bounds_cover_the_range_between_them():
    emitter = _FakeEmitter(arc_width=(math.pi / 4, -math.pi / 4))
    aim = TGPoint3(math.sin(math.radians(30)), math.cos(math.radians(30)), 0.0)
    assert _emitter_in_arc(emitter, None, aim) is True


def test_reversed_width_bounds_still_reject_outside_the_range():
    emitter = _FakeEmitter(arc_width=(math.pi / 4, -math.pi / 4))
    aim = TGPoint3(math.sin(math.radians(60)), math.cos(math.radians(60)), 0.0)
    assert _emitter_in_arc(emitter, None, aim) is False
