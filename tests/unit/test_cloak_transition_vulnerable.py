"""Cloak-transition vulnerability window (2026-07-08 live-play fix).

While a ship is fading in or out (CLOAKING / DECLOAKING) it is briefly exposed:
its shields are DOWN so hits reach the hull — the window enemies use to attack a
(de)cloaking ship. Fully decloaked, shields block normally; and the shield CHARGE
is preserved through the transition (it is only *blocking* that is suspended), so
the ship isn't left empty (see test_cloak_combat_rules).
"""
from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem, CloakingSubsystem


def _cloak_ship(hull_max=2000.0, face_max=1000.0):
    ship = ShipClass_Create("Target")
    hull = HullSubsystem("Hull"); hull.SetMaxCondition(hull_max); ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    ship.SetAlertLevel(ShipClass.RED_ALERT)      # shields up + charged
    ship._radius = 20.0
    return ship


def test_shields_block_when_fully_decloaked():
    # Control: a normal (fully decloaked) ship's shields absorb the hit.
    ship = _cloak_ship()
    assert ship.GetShields().GetCurrentShields(0) == 1000.0
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetShields().GetCurrentShields(0) == 500.0   # absorbed
    assert ship.GetHull().GetCondition() == 2000.0           # hull untouched


def test_shields_down_while_cloaking():
    ship = _cloak_ship()
    ship.GetCloakingSubsystem().StartCloaking()               # CLOAKING (fading out)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 1500.0           # exposed -> hull took it
    assert ship.GetShields().GetCurrentShields(0) == 1000.0  # charge preserved


def test_shields_down_while_decloaking():
    ship = _cloak_ship()
    cloak = ship.GetCloakingSubsystem()
    cloak.InstantCloak()                                      # fully cloaked
    cloak.StopCloaking()                                     # DECLOAKING (fading in)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 1500.0           # exposed during decloak
    assert ship.GetShields().GetCurrentShields(0) == 1000.0  # charge preserved
