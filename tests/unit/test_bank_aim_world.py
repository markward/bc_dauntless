"""Bug F regression: arc gate aim origin is the bank's mount Position,
NOT the ship's centre and NOT the strip emit point.

Prior to this fix two call sites disagreed:

  Site                                       aim_world origin
  ------------------------------------------ ---------------------
  PhaserSystem.StartFiring                   ship_pos → target
  host_loop per-tick re-check                emit_pos → target

At close range these can disagree dramatically -- a bank could pass
StartFiring then immediately fail the per-tick re-check, or its
visible beam could fire in the wrong direction because the emit
point sat past the target on the strip.

See ``docs/instrumented_experiments/hardpoint_handling_research.md``
section "Bug F" for the full investigation.
"""
import math

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.properties import PhaserProperty
from engine.appc.subsystems import (
    PhaserBank,
    _resolve_aim_world,
    _resolve_bank_aim_world,
)


class _StubTarget:
    def __init__(self, x, y, z):
        self._p = TGPoint3(x, y, z)
    def GetWorldLocation(self):
        return self._p


class _StubShip:
    def __init__(self, x, y, z):
        self._loc = TGPoint3(x, y, z)
        self._rot = TGMatrix3()  # identity
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetParentSubsystem(self): return None
    def GetParentShip(self): return self


def _galaxy_dorsal1_bank(ship_loc=(0.0, 0.0, 0.0)):
    bank = PhaserBank("DorsalPhaser1")
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetPosition(0.0, 1.27, 0.5)
    prop.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetLength(1.69)
    prop.SetArcWidthAngles(-0.872665, 0.872665)
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    bank.SetProperty(prop)
    bank._parent_ship = _StubShip(*ship_loc)
    return bank


def test_aim_origin_is_bank_position_not_ship_centre():
    """At close range, ship_pos -> target and bank.Position -> target
    point in noticeably different directions.  Confirm the helper
    uses the bank Position."""
    bank = _galaxy_dorsal1_bank(ship_loc=(0.0, 0.0, 0.0))
    target = _StubTarget(0.0, 1.27, 100.0)  # directly above the bank
    aim = _resolve_bank_aim_world(bank, target)
    # Bank Position is (0, 1.27, 0.5); target at (0, 1.27, 100) is
    # exactly +Z from the bank.  Ship-centre to target would have a
    # +Y component (ship at origin, target +Y direction = (0, 1.27/L, 100/L)).
    assert abs(aim.x) < 1e-6
    assert abs(aim.y) < 1e-6
    assert aim.z > 0.99


def test_aim_origin_for_distant_target_approaches_ship_aim():
    """At long range, bank.Position offset becomes negligible and the
    bank-aim should converge with ship-aim."""
    bank = _galaxy_dorsal1_bank()
    target = _StubTarget(-10000.0, 0.0, 0.0)  # very far port
    bank_aim = _resolve_bank_aim_world(bank, target)
    ship_aim = _resolve_aim_world(bank._parent_ship, target)
    # Within milli-radians.
    assert abs(bank_aim.x - ship_aim.x) < 1e-3
    assert abs(bank_aim.y - ship_aim.y) < 1e-3
    assert abs(bank_aim.z - ship_aim.z) < 1e-3


def test_aim_unit_length():
    bank = _galaxy_dorsal1_bank()
    target = _StubTarget(50.0, 50.0, 50.0)
    aim = _resolve_bank_aim_world(bank, target)
    norm = math.sqrt(aim.x * aim.x + aim.y * aim.y + aim.z * aim.z)
    assert abs(norm - 1.0) < 1e-6


def test_aim_fallback_when_bank_position_equals_target():
    """Degenerate case: target sits at the bank's world Position.
    Helper falls back to ship-forward direction."""
    bank = _galaxy_dorsal1_bank()
    target = _StubTarget(0.0, 1.27, 0.5)  # exactly at bank Position
    aim = _resolve_bank_aim_world(bank, target)
    # Falls back to ship body +Y.
    assert (round(aim.x, 6), round(aim.y, 6), round(aim.z, 6)) == (0.0, 1.0, 0.0)


def test_aim_falls_back_to_ship_aim_when_bank_lacks_parent():
    """A loose PhaserBank with no parent ship still returns a sensible
    aim (delegates to ship-pos logic)."""
    bank = PhaserBank("loose")
    target = _StubTarget(1.0, 0.0, 0.0)
    aim = _resolve_bank_aim_world(bank, target)
    # Without a parent ship, the bank's world Position is (0,0,0) so
    # the aim is the unit vector to target.
    assert abs(aim.x - 1.0) < 1e-6
    assert abs(aim.y) < 1e-6
    assert abs(aim.z) < 1e-6
