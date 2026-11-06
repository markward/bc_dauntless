"""A projectile the shields partly stop reaches the hull with its splash radius shrunk by the leaked fraction.

Measured on stbc.exe (CombatTap H rows: the shield step then the hull step of the same hit, 7 duels incl. the
human run bc_human_1): every projectile hit's hull radius was R x post_shield / damage (63/63; a quantum 0.14
that leaked 66.69 of 900 landed with 0.0104), while beams keep their radius (800/801). Dauntless swept the full
sphere, so a mostly-stopped torpedo still damaged every subsystem near the impact (dn_human_1: the Sovereign's
shield generator, never touched in the original, was disabled at 400 s and the shields went down with it).
"""
import pytest

import App
from engine.appc.combat import apply_hit
from engine.appc.math import TGPoint3

from tests.unit.test_apply_hit_splash import _FakeHull, _FakeShip, _FakeSub


class _Payload:
    def GetDamageRadiusFactor(self):
        return 0.6


class _Shields:
    """Every facing stops all but `leak` of a hit."""
    def __init__(self, leak):
        self.leak = leak

    def HasShields(self): return 1
    def IsOn(self): return 1
    def IsDisabled(self): return 0
    def IsDestroyed(self): return 0
    def GetCurrentShields(self, face): return 1.0e6

    def ApplyDamage(self, face, dmg):
        return dmg * self.leak


class _ShieldedShip(_FakeShip):
    def __init__(self, shields, **kw):
        super().__init__(**kw)
        self._shields = shields

    def GetShields(self):
        return self._shields

    def GetCloakingSubsystem(self):
        return None


@pytest.fixture
def restore_event_manager():
    orig = App.g_kEventManager.AddEvent
    yield
    App.g_kEventManager.AddEvent = orig


def _hit(leak, weapon_type):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    near = _FakeSub("Near", TGPoint3(0.5, 0, 0), radius=0.1)    # 0.5 from the impact: inside 0.6 + 0.1 only
    ship = _ShieldedShip(_Shields(leak), hull=hull, subsystems=[hull, near])
    apply_hit(ship, damage=900.0, hit_point=TGPoint3(0.0, 0.0, 0.0), source=None,
              weapon_type=weapon_type, payload_template=_Payload())
    return dict(ship.damage_log)


def test_a_mostly_stopped_torpedo_shrinks_its_sphere(restore_event_manager):
    got = _hit(0.1, "torpedo")                                    # 90 of 900 leaks: R 0.6 -> 0.06
    assert got["Hull"] == pytest.approx(90.0)
    assert "Near" not in got


def test_a_torpedo_that_passes_unhindered_keeps_its_sphere(restore_event_manager):
    got = _hit(1.0, "torpedo")
    assert got["Near"] == pytest.approx(900.0)


def test_a_phaser_keeps_its_radius_whatever_the_shields_stop(restore_event_manager):
    got = _hit(0.1, "phaser")
    assert got["Near"] == pytest.approx(90.0)
