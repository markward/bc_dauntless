"""PhaserBank.CanHit — the arc+range test ConditionInPhaserFiringArc relies on.

Without this method the SDK call resolves to a truthy _Stub and every target
reads as 'in arc', so FedAttack fires with no arc discipline at all.
"""
import math

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import PhaserProperty
from engine.appc.weapon_subsystems import PhaserBank


class _StubShip:
    """Mirrors the real ShipClass surface CanHit touches — nothing more."""
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self._loc = TGPoint3(x, y, z)
        self._rot = TGMatrix3()  # identity
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetParentSubsystem(self): return None
    def GetParentShip(self): return self


def _forward_bank(max_range=100.0):
    """Forward-facing bank, +-50 deg width, -3..+60 deg height, at ship origin."""
    bank = PhaserBank("ForwardPhaser1")
    prop = PhaserProperty("ForwardPhaser1")
    prop.SetPosition(0.0, 0.0, 0.0)
    # model-forward +Y, up +Z
    prop.SetOrientation(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetArcWidthAngles(-0.872665, 0.872665)
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    prop.SetMaxDamageDistance(max_range)
    bank.SetProperty(prop)
    bank._parent_ship = _StubShip()
    return bank


def test_target_dead_ahead_and_in_range_can_be_hit():
    bank = _forward_bank()
    assert bank.CanHit(TGPoint3(0.0, 50.0, 0.0)) == 1


def test_target_behind_cannot_be_hit():
    bank = _forward_bank()
    assert bank.CanHit(TGPoint3(0.0, -50.0, 0.0)) == 0


def test_target_beyond_max_range_cannot_be_hit():
    bank = _forward_bank(max_range=10.0)
    # Dead ahead, so in arc — rejected on range alone.
    assert bank.CanHit(TGPoint3(0.0, 50.0, 0.0)) == 0


def test_target_outside_width_arc_cannot_be_hit():
    bank = _forward_bank()
    # 80 deg off the nose in yaw: outside the +-50 deg width arc.
    ang = math.radians(80.0)
    assert bank.CanHit(TGPoint3(50.0 * math.sin(ang), 50.0 * math.cos(ang), 0.0)) == 0


def test_returns_a_real_int_not_a_truthy_stub():
    """A _Stub is truthy AND int()s to 0 — both silently wrong. Demand a real int."""
    bank = _forward_bank()
    result = bank.CanHit(TGPoint3(0.0, 50.0, 0.0))
    assert type(result) is int


def test_zero_max_range_means_unbounded_not_unreachable():
    """MaxDamageDistance defaults to 0.0 on a bank with no authored range.
    Treat 0 as 'no limit' — treating it as 'range 0' would disable every bank
    whose hardpoint omits the field."""
    bank = _forward_bank(max_range=0.0)
    assert bank.CanHit(TGPoint3(0.0, 5000.0, 0.0)) == 1
