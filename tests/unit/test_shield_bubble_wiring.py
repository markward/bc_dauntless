"""The bubble entry point reaches the two things the player sees.

Companion to test_shield_bubble_entry.py, which covers the geometry itself.
This file covers the wiring:

  * the drawn phaser beam stops at the bubble while a facing is live, and at
    the hull once it is not, and
  * the shield splash is anchored at the bubble entry point rather than at the
    hull impact.

Facing SELECTION is deliberately NOT covered — it still reads the hull point.
Moving it is a gameplay change and lands separately.
"""
import math

import pytest

from engine.appc import combat, hit_feedback
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem

SQRT3 = math.sqrt(3.0)
HALF = (232.0, 322.0, 70.0)


def _target(at=(0.0, 0.0, 0.0), shields_up=True):
    s = ShipClass_Create("Target")
    s._hull = HullSubsystem("Hull")
    s._hull.SetMaxCondition(100000.0)
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 100000.0)
    if not shields_up:
        ss.TurnOff()
    s.SetShieldSubsystem(ss)
    s.SetTranslateXYZ(*at)
    s._shield_hull_box = ((0.0, 0.0, 0.0), HALF)
    s._radius = 400.0
    return s


# ── shields_block: the shared "would a facing stop this" predicate ──────────

def test_shields_block_true_for_a_live_generator():
    assert combat.shields_block(_target()) is True


def test_shields_block_false_when_powered_down():
    assert combat.shields_block(_target(shields_up=False)) is False


def test_shields_block_false_when_generator_destroyed():
    ship = _target()
    ship.GetShields().SetCondition(0.0)
    assert combat.shields_block(ship) is False


def test_shields_block_false_for_an_unshielded_hull():
    """Asteroids and debris still carry a ShieldSubsystem so SDK code can chain
    GetShields() without null-guarding, but every face declares MaxShields 0.
    They must not read as shielded — otherwise, now that the generator defaults
    on, the beam would stop at a bubble the rock does not have."""
    rock = ShipClass_Create("Asteroid")
    assert rock.GetShields() is not None, "premise: ShipClass always has one"
    assert rock.GetShields().HasShields() == 0
    assert combat.shields_block(rock) is False


def test_shields_block_false_when_the_slot_is_empty():
    ship = _target()
    ship.SetShieldSubsystem(None)
    assert combat.shields_block(ship) is False


# ── the splash is anchored on the bubble ───────────────────────────────────

class _Recorder:
    """Captures the point handed to host_io.shield_hit."""
    def __init__(self):
        self.points = []

    def __call__(self, iid, point, rgba, intensity, radius=0.0):
        self.points.append(point)


def _capture_shield_hits(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(hit_feedback.host_io, "shield_hit", rec)
    return rec


def test_splash_is_anchored_at_the_bubble_not_the_hull(monkeypatch):
    rec = _capture_shield_hits(monkeypatch)
    ship = _target()
    hull_point = TGPoint3(0.0, HALF[1], 0.0)               # nose, on the hull
    bubble_point = TGPoint3(0.0, HALF[1] * SQRT3, 0.0)     # nose, on the bubble

    combat.apply_hit(ship, 100.0, hull_point, source=None,
                     ship_instances={ship: 1}, weapon_type="phaser",
                     shield_point=bubble_point)

    assert len(rec.points) == 1
    assert rec.points[0] == pytest.approx(
        (bubble_point.x, bubble_point.y, bubble_point.z))


def test_splash_falls_back_to_the_hull_point_when_no_bubble_point(monkeypatch):
    """Collisions, splash damage and any caller without a ray pass nothing —
    behaviour must be exactly what it was."""
    rec = _capture_shield_hits(monkeypatch)
    ship = _target()
    hull_point = TGPoint3(0.0, HALF[1], 0.0)

    combat.apply_hit(ship, 100.0, hull_point, source=None,
                     ship_instances={ship: 1}, weapon_type="phaser")

    assert len(rec.points) == 1
    assert rec.points[0] == pytest.approx(
        (hull_point.x, hull_point.y, hull_point.z))


def test_damage_still_lands_on_the_hull_point_not_the_bubble_point():
    """The bubble point is a VFX anchor only. Subsystem splash attribution
    must keep using the hull impact."""
    ship = _target()
    ship.GetShields().TurnOff()          # let the damage through to the hull
    before = ship.GetHull().GetCondition()
    combat.apply_hit(ship, 250.0, TGPoint3(0.0, HALF[1], 0.0), source=None,
                     shield_point=TGPoint3(0.0, HALF[1] * SQRT3, 0.0))
    assert ship.GetHull().GetCondition() == before - 250.0


# ── the drawn beam stops at the bubble ─────────────────────────────────────

def test_beam_stops_at_the_bubble_while_shields_hold():
    from engine import host_loop
    ship = _target()
    emitter = TGPoint3(0.0, 6000.0, 0.0)
    aim = TGPoint3(0.0, -1.0, 0.0)

    end = host_loop._beam_endpoint(
        target=ship, emitter_pos=emitter, aim_unit=aim,
        raw_length=6000.0, ship_instances=None,
        fallback=TGPoint3(0.0, 0.0, 0.0))

    assert end.y == pytest.approx(HALF[1] * SQRT3, abs=1.0)


def test_beam_reaches_past_the_bubble_once_shields_are_down():
    from engine import host_loop
    ship = _target(shields_up=False)
    emitter = TGPoint3(0.0, 6000.0, 0.0)
    aim = TGPoint3(0.0, -1.0, 0.0)
    fallback = TGPoint3(0.0, 0.0, 0.0)

    end = host_loop._beam_endpoint(
        target=ship, emitter_pos=emitter, aim_unit=aim,
        raw_length=6000.0, ship_instances=None, fallback=fallback)

    # No renderer instance headless, so it degrades to the caller's fallback —
    # the point is that it does NOT stop at the bubble.
    assert end.y < HALF[1] * SQRT3 - 1.0
