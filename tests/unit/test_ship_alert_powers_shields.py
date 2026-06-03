"""ShipClass.SetAlertLevel flips the shield generator on at YELLOW or RED
and off at GREEN. Mirrors stock BC: the XO menu raises shields when the
captain calls yellow/red alert and drops them on green.

Companion to test_ship_alert_powers_weapons.py — that file covers the
weapon-power half of the alert-level policy; this one covers shields.
"""
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.properties import ShieldProperty
from engine.appc.subsystems import ShieldSubsystem


def _ship_with_shields(front_max=1000.0):
    """A bare ship with a six-face shield generator seeded to max."""
    ship = ShipClass_Create("Test")
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, front_max)
    ship.SetShieldSubsystem(ss)
    return ship


def test_default_alert_leaves_shields_off():
    """A freshly-created ship is at GREEN_ALERT — shields must not be
    powered up. Mirrors stock BC: ships dock at green with shields down."""
    ship = _ship_with_shields()
    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT
    assert ship.GetShields().IsOn() == 0


def test_yellow_alert_turns_shields_on():
    ship = _ship_with_shields()
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    assert ship.GetShields().IsOn() == 1
    assert ship.GetShields().GetPowerPercentageWanted() == 1.0


def test_red_alert_turns_shields_on():
    ship = _ship_with_shields()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetShields().IsOn() == 1
    assert ship.GetShields().GetPowerPercentageWanted() == 1.0


def test_green_alert_turns_shields_off():
    ship = _ship_with_shields()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    assert ship.GetShields().IsOn() == 0
    assert ship.GetShields().GetPowerPercentageWanted() == 0.0


def test_green_to_yellow_snaps_face_charge_to_max():
    """Raising shields snaps face charge to max — Phase 1 simplification
    of BC's gradual charge-up time."""
    ship = _ship_with_shields(front_max=1000.0)
    ss = ship.GetShields()
    # Pretend the ship spawned at green with faces drained.
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetCurrentShields(f, 0.0)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert ss.GetCurrentShields(f) == ss.GetMaxShields(f)


def test_yellow_to_green_drains_face_charge_to_zero():
    """Dropping shields drains face charge — the UI should reflect that
    shields are down, not stuck at 100%."""
    ship = _ship_with_shields(front_max=1000.0)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    ss = ship.GetShields()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        assert ss.GetCurrentShields(f) == 0.0


def test_alert_change_no_op_when_shield_subsystem_missing():
    """A ship without a shield generator (debris, asteroid) must not
    crash on SetAlertLevel. ShipClass_Create allocates a default shield
    subsystem, so this uses the raw constructor to model the no-shields
    case."""
    ship = ShipClass()
    assert ship.GetShieldSubsystem() is None
    ship.SetAlertLevel(ShipClass.RED_ALERT)  # must not raise
    assert ship.GetShieldSubsystem() is None
