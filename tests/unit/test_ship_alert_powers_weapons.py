"""ShipClass.SetAlertLevel flips weapon groups (phasers/torpedoes/pulse)
on at RED, off at GREEN/YELLOW. The tractor is NOT toggled by alert level —
it's powered on when equipped and available at ALL alert levels (its beam is
operated by a separate manual toggle, StartFiring/StopFiring).
"""
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.properties import WeaponSystemProperty


def _add_group(ship, name, wst):
    p = WeaponSystemProperty(name)
    p.SetWeaponSystemType(wst)
    ship.GetPropertySet().AddToSet("Scene Root", p)


def _galaxy_loadout():
    ship = ShipClass_Create("Galaxy")
    _add_group(ship, "Phasers",  WeaponSystemProperty.WST_PHASER)
    _add_group(ship, "Torpedoes",WeaponSystemProperty.WST_TORPEDO)
    _add_group(ship, "Pulse",    WeaponSystemProperty.WST_PULSE)
    _add_group(ship, "Tractors", WeaponSystemProperty.WST_TRACTOR)
    ship.SetupProperties()
    return ship


def test_red_alert_turns_phasers_on():
    ship = _galaxy_loadout()
    assert ship.GetPhaserSystem().IsOn() == 0
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetPhaserSystem().IsOn() == 1
    assert ship.GetPhaserSystem().GetPowerPercentageWanted() == 1.0


def test_red_alert_turns_torpedoes_on():
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetTorpedoSystem().IsOn() == 1


def test_red_alert_turns_pulse_on():
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetPulseWeaponSystem().IsOn() == 1


def test_tractor_powered_at_all_alert_levels():
    """The tractor is equipped-on and alert level never toggles it — so the
    player can engage the beam at green, yellow or red alert."""
    ship = _galaxy_loadout()
    assert ship.GetTractorBeamSystem().IsOn() == 1   # powered on when equipped
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    assert ship.GetTractorBeamSystem().IsOn() == 1   # untouched at red
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    assert ship.GetTractorBeamSystem().IsOn() == 1   # still on at green


def test_green_alert_turns_phasers_off():
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    assert ship.GetPhaserSystem().IsOn() == 0
    assert ship.GetPhaserSystem().GetPowerPercentageWanted() == 0.0


def test_yellow_alert_keeps_weapons_off():
    """BC convention: yellow alert raises shields but weapons stay cold."""
    ship = _galaxy_loadout()
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    assert ship.GetPhaserSystem().IsOn() == 0
    assert ship.GetTorpedoSystem().IsOn() == 0
    assert ship.GetPulseWeaponSystem().IsOn() == 0


def test_alert_change_no_op_when_group_missing():
    """A ship with no torpedo system must not crash on SetAlertLevel."""
    ship = ShipClass_Create("Bare")
    _add_group(ship, "Phasers", WeaponSystemProperty.WST_PHASER)
    ship.SetupProperties()
    ship.SetAlertLevel(ShipClass.RED_ALERT)  # must not raise
    assert ship.GetPhaserSystem().IsOn() == 1
    assert ship.GetTorpedoSystem() is None
